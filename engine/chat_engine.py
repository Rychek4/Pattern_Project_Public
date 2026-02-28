"""
Pattern Project - Chat Engine

UI-agnostic message processing engine.  Owns the full lifecycle:
prompt building -> LLM call -> tool execution -> response storage.

Emits EngineEvents at every stage so UI layers (GUI, CLI, Web) can
react without duplicating pipeline logic.

Usage:
    from engine import ChatEngine

    engine = ChatEngine()
    engine.add_listener(my_callback)
    engine.process_message("Hello!")
"""

import threading
import traceback
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import config
from core.logger import log_info, log_error, log_warning
from core.temporal import get_temporal_tracker
from core.user_settings import get_user_settings
from core.round_recorder import RoundRecorder
from memory.conversation import get_conversation_manager
from llm.router import get_llm_router, TaskType
from prompt_builder import get_prompt_builder
from agency.tools import get_tool_definitions, process_with_tools

from engine.events import EngineEvent, EngineEventType


class ChatEngine:
    """UI-agnostic message processing engine.

    All entry points (process_message, process_pulse, process_reminder,
    process_telegram, process_deferred_retry) run synchronously.
    The caller is responsible for threading.
    """

    def __init__(self):
        self._conversation_mgr = get_conversation_manager()
        self._llm_router = get_llm_router()
        self._prompt_builder = get_prompt_builder()
        self._temporal_tracker = get_temporal_tracker()
        self._user_settings = get_user_settings()
        self._round_recorder = RoundRecorder()

        from llm.retry_manager import get_retry_manager
        self._retry_manager = get_retry_manager()

        self._pulse_manager = None
        self._telegram_listener = None

        # State flags (protected by lock for thread safety)
        self._lock = threading.Lock()
        self._is_processing = False
        self._cancel_requested = False
        self._is_first_message_of_session = True

        # Event listeners
        self._listeners: List[Callable[[EngineEvent], None]] = []

    # ------------------------------------------------------------------
    # Event system
    # ------------------------------------------------------------------

    def add_listener(self, callback: Callable[[EngineEvent], None]):
        """Register a callback to receive EngineEvents."""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[EngineEvent], None]):
        """Unregister a callback."""
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def _emit(self, event_type: EngineEventType, **data):
        """Emit an event to all registered listeners."""
        event = EngineEvent(event_type=event_type, data=data)
        for listener in self._listeners:
            try:
                listener(event)
            except Exception as e:
                log_error(f"Engine event listener error: {e}")

    # ------------------------------------------------------------------
    # Connection points
    # ------------------------------------------------------------------

    def connect_pulse(self, pulse_manager):
        """Connect the system pulse manager for timer control."""
        self._pulse_manager = pulse_manager

    def connect_telegram(self, telegram_listener):
        """Connect the Telegram listener for pause/resume."""
        self._telegram_listener = telegram_listener

    @property
    def is_processing(self) -> bool:
        return self._is_processing

    @property
    def is_first_message_of_session(self) -> bool:
        return self._is_first_message_of_session

    def cancel(self):
        """Request cancellation of current processing."""
        self._cancel_requested = True

    @property
    def retry_manager(self):
        """Access the retry manager (for external cancel checks)."""
        return self._retry_manager

    @property
    def round_recorder(self):
        """Access the round recorder (for prompt export)."""
        return self._round_recorder

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _pause_timers(self):
        """Pause pulse and telegram timers during processing."""
        if self._pulse_manager:
            self._pulse_manager.pause()
        if self._telegram_listener:
            self._telegram_listener.pause()

    def _resume_timers(self):
        """Resume pulse and telegram timers after processing."""
        if self._pulse_manager:
            self._pulse_manager.resume()
        if self._telegram_listener:
            self._telegram_listener.resume()

    def _build_dev_callbacks(self) -> Optional[Dict[str, Callable]]:
        """Build dev mode callbacks for process_with_tools, if dev mode is on."""
        if not config.DEV_MODE_ENABLED:
            return None

        def emit_response_pass(**kwargs):
            self._emit(EngineEventType.DEV_RESPONSE_PASS, **kwargs)

        def emit_command_executed(**kwargs):
            self._emit(EngineEventType.DEV_COMMAND_EXECUTED, **kwargs)

        return {
            "emit_response_pass": emit_response_pass,
            "emit_command_executed": emit_command_executed
        }

    def _on_pulse_interval_change(self, change_info):
        """Handle pulse interval change from AI tool call."""
        if not isinstance(change_info, dict):
            return
        pt = change_info.get("pulse_type", "")
        secs = change_info.get("interval_seconds", 0)
        if self._pulse_manager:
            if pt == "reflective":
                self._pulse_manager.set_reflective_interval(secs)
            elif pt == "action":
                self._pulse_manager.set_action_interval(secs)
        log_info(f"{pt} pulse interval changed to {secs}s", prefix="⏱️")
        self._emit(EngineEventType.PULSE_INTERVAL_CHANGED,
                   pulse_type=pt, interval_seconds=secs)

    def _inject_memories(self, user_message: dict, relevant_memories: Optional[str]):
        """Inject relevant memories into a user message (API-only, not stored)."""
        if not relevant_memories:
            return
        content = user_message.get("content")
        if isinstance(content, str):
            user_message["content"] = f"{relevant_memories}\n\n{content}"
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    block["text"] = f"{relevant_memories}\n\n{block.get('text', '')}"
                    break

    def _capture_visuals_for_message(self, text_content: str) -> dict:
        """Capture visual content and build a multimodal message if enabled.

        Captures sources configured for "auto" mode. Sources in "on_demand"
        mode are captured via tool calls instead.
        """
        if not config.VISUAL_ENABLED:
            return {"role": "user", "content": text_content}

        has_auto_visuals = (
            config.VISUAL_SCREENSHOT_MODE == "auto" or
            config.VISUAL_WEBCAM_MODE == "auto"
        )
        if not has_auto_visuals:
            return {"role": "user", "content": text_content}

        try:
            from agency.visual_capture import capture_all_visuals, build_multimodal_content

            images = capture_all_visuals()
            if not images:
                return {"role": "user", "content": text_content}

            content_array = build_multimodal_content(text_content, images)
            log_info(f"Built multimodal message with {len(images)} image(s)", prefix="👁️")
            return {"role": "user", "content": content_array}

        except Exception as e:
            log_error(f"Visual capture error, falling back to text-only: {e}")
            return {"role": "user", "content": text_content}

    @staticmethod
    def _detect_image_media_type(image_data: bytes) -> str:
        """Detect image MIME type from magic bytes.

        Args:
            image_data: Raw image bytes

        Returns:
            Detected MIME type string, defaults to "image/jpeg" if unknown
        """
        if image_data[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        if image_data[:2] == b'\xff\xd8':
            return "image/jpeg"
        if image_data[:4] == b'GIF8':
            return "image/gif"
        if image_data[:4] == b'RIFF' and image_data[8:12] == b'WEBP':
            return "image/webp"
        return "image/jpeg"

    def _build_image_message(self, text: str, image_data: bytes,
                             media_type: Optional[str] = None) -> dict:
        """Build a multimodal message from raw image bytes.

        Args:
            text: The message text
            image_data: Raw image bytes (any supported format)
            media_type: Optional MIME type hint from the client.
                        If not provided, detected from magic bytes.

        Returns:
            Message dict with multimodal content array
        """
        try:
            import base64
            from agency.visual_capture import ImageContent, build_multimodal_content

            if not media_type:
                media_type = self._detect_image_media_type(image_data)

            base64_data = base64.standard_b64encode(image_data).decode("utf-8")
            img_content = ImageContent(
                data=base64_data,
                media_type=media_type,
                source_type="clipboard"
            )
            content_array = build_multimodal_content(text, [img_content])
            log_info(f"Built multimodal message from image bytes (media_type={media_type})", prefix="📋")
            return {"role": "user", "content": content_array}

        except Exception as e:
            log_error(f"Failed to build image message: {e}")
            return {"role": "user", "content": text}

    def _build_telegram_image_message(self, text: str, image) -> dict:
        """Build a multimodal message from a Telegram photo attachment.

        Args:
            text: The message text (or caption)
            image: ImageContent object from Telegram photo processing
        """
        try:
            from agency.visual_capture import build_multimodal_content

            content_array = build_multimodal_content(text, [image])
            log_info(f"Built Telegram image message (source: {image.source_type})", prefix="📷")
            return {"role": "user", "content": content_array}

        except Exception as e:
            log_error(f"Failed to build Telegram image message: {e}")
            return {"role": "user", "content": text}

    # ------------------------------------------------------------------
    # Primary entry point: user chat message (streaming)
    # ------------------------------------------------------------------

    def process_message(self, user_input: str, image_data: Optional[bytes] = None,
                        image_media_type: Optional[str] = None):
        """Process a user chat message with streaming.

        This is the main entry point. Handles prompt building, conversation
        history, memory injection, visual message building, streaming LLM call,
        tool execution, temporal echo stripping, and response storage.

        Runs synchronously — caller should run in a thread.

        Args:
            user_input: The user's message text
            image_data: Optional raw image bytes (from clipboard paste)
            image_media_type: Optional MIME type of the image (e.g. "image/png").
                              If not provided, detected from magic bytes.
        """
        log_info("=== ChatEngine.process_message START ===", prefix="📨")
        log_info(f"Input length: {len(user_input)} chars", prefix="📨")
        log_info(f"Has image: {image_data is not None}", prefix="📨")

        self._is_processing = True
        self._cancel_requested = False
        self._emit(EngineEventType.PROCESSING_STARTED, source="user")

        try:
            # Check for cancellation early
            if self._cancel_requested:
                self._emit(EngineEventType.NOTIFICATION,
                           message="Request cancelled", level="warning")
                log_info("Cancelled early", prefix="📨")
                return

            # Build prompt
            log_info("Building prompt...", prefix="📨")
            assembled = self._prompt_builder.build(
                user_input=user_input,
                system_prompt="",
                additional_context={"is_session_start": self._is_first_message_of_session}
            )
            self._is_first_message_of_session = False
            log_info(f"Prompt built: {len(assembled.full_system_prompt)} chars system prompt", prefix="📨")

            self._emit(EngineEventType.PROMPT_ASSEMBLED,
                       blocks=[{
                           "source_name": block.source_name,
                           "priority": block.priority,
                           "content": block.content,
                           "metadata": block.metadata
                       } for block in assembled.context_blocks],
                       token_estimate=len(assembled.full_system_prompt) // 4)

            # Get conversation history BEFORE storing the new turn
            log_info("Getting conversation history...", prefix="📨")
            history = self._conversation_mgr.get_api_messages()
            log_info(f"Got {len(history)} messages in history", prefix="📨")

            # Store user message for persistence (may trigger memory extraction)
            log_info("Storing user turn (may trigger extraction)...", prefix="📨")
            self._conversation_mgr.add_turn(
                role="user",
                content=user_input,
                input_type="text"
            )
            log_info("User turn stored", prefix="📨")

            # Build user message (with visuals if applicable)
            log_info("Building user message...", prefix="📨")
            if image_data:
                user_message = self._build_image_message(user_input, image_data, image_media_type)
                log_info("Built message with image", prefix="📨")
            else:
                user_message = self._capture_visuals_for_message(user_input)
                content = user_message.get("content", "")
                if isinstance(content, list):
                    log_info(f"Built multimodal message with {len(content)} content blocks", prefix="📨")
                else:
                    log_info(f"Built text-only message ({len(content)} chars)", prefix="📨")

            # Inject relevant memories
            relevant_memories = assembled.session_context.get("relevant_memories")
            self._inject_memories(user_message, relevant_memories)
            if relevant_memories:
                self._emit(EngineEventType.MEMORIES_INJECTED)

            history.append(user_message)
            log_info(f"History now has {len(history)} messages", prefix="📨")

            # Get tools
            tools = get_tool_definitions()
            log_info(f"Got {len(tools)} tool definitions", prefix="📨")

            # Start streaming
            self._emit(EngineEventType.STREAM_START)

            # Start recording this round for prompt export
            self._round_recorder.start_round()
            self._round_recorder.record_request(
                system_prompt=assembled.full_system_prompt,
                messages=history,
                tools=tools,
                model=self._user_settings.conversation_model,
                temperature=0.7,
                thinking_enabled=True,
                is_streaming=True,
            )

            # Stream the response
            final_state = None
            for chunk, state in self._llm_router.chat_stream(
                messages=history,
                system_prompt=assembled.full_system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=0.7,
                tools=tools,
                thinking_enabled=True
            ):
                if self._cancel_requested:
                    self._emit(EngineEventType.NOTIFICATION,
                               message="Request cancelled", level="warning")
                    break

                final_state = state
                if chunk:
                    self._emit(EngineEventType.STREAM_CHUNK, text=chunk)

            # Check if streaming completed successfully
            log_info("Streaming loop exited, checking result...", prefix="📨")
            if final_state is None:
                log_error("final_state is None - streaming yielded nothing!", prefix="📨")
                self._emit(EngineEventType.PROCESSING_ERROR,
                           error="No response received", error_type=None)
                return

            if final_state.stop_reason == "error":
                error_msg = getattr(final_state, '_error_message', 'unknown error')
                error_type = getattr(final_state, '_error_type', None)
                log_error(f"Streaming ended with error ({error_type}): {error_msg}", prefix="📨")

                if error_type == "both_models_unavailable":
                    self.schedule_retry(user_input, source="user")
                    self._emit(EngineEventType.PROCESSING_ERROR,
                               error=error_msg, error_type="both_models_unavailable")
                else:
                    self._emit(EngineEventType.PROCESSING_ERROR,
                               error=error_msg, error_type=error_type)
                return

            log_info(f"Streaming completed: {len(final_state.text)} chars, stop_reason={final_state.stop_reason}", prefix="📨")

            self._emit(EngineEventType.STREAM_COMPLETE,
                       text=final_state.text,
                       tokens_in=final_state.input_tokens,
                       tokens_out=final_state.output_tokens,
                       stop_reason=final_state.stop_reason or "")

            # Emit server-side tool calls (web_search, web_fetch) via engine
            # events.  Only when there are NO client tool calls -- if there are,
            # process_with_tools() will emit TOOL_INVOKED for all tools
            # (including server tools) via ProcessEventBus, avoiding duplicates.
            if final_state.server_tool_details and not final_state.has_tool_calls():
                from agency.tools.response_helper import _build_tool_detail
                for st in final_state.server_tool_details:
                    tool_detail = _build_tool_detail(st.get("name", ""), st.get("input", {}))
                    self._emit(EngineEventType.SERVER_TOOL_INVOKED,
                               tool_name=st.get("name", ""), detail=tool_detail)

            # Record streaming response for prompt export
            self._round_recorder.record_response(
                response_text=final_state.text,
                thinking_text=final_state.thinking_text,
                tool_calls=final_state.tool_calls,
                raw_content=final_state.raw_content,
                stop_reason=final_state.stop_reason or "",
                tokens_in=final_state.input_tokens,
                tokens_out=final_state.output_tokens,
            )

            # Log thinking in dev mode
            if final_state.thinking_text and config.DEV_MODE_ENABLED:
                log_info(f"Thinking ({len(final_state.thinking_text)} chars): {final_state.thinking_text[:500]}...", prefix="🧠")

            # Get full streamed text
            streamed_text = final_state.text
            final_text = streamed_text

            # Check for tool calls and process them
            if final_state.has_tool_calls():
                from llm.router import LLMResponse, LLMProvider

                response = LLMResponse(
                    text=final_state.text,
                    success=True,
                    provider=LLMProvider.ANTHROPIC,
                    tokens_in=final_state.input_tokens,
                    tokens_out=final_state.output_tokens,
                    stop_reason=final_state.stop_reason,
                    tool_calls=final_state.tool_calls,
                    raw_content=final_state.raw_content,
                    web_searches_used=final_state.web_searches_used,
                    citations=final_state.citations,
                    server_tool_details=final_state.server_tool_details,
                    thinking_text=final_state.thinking_text
                )

                max_passes = getattr(config, 'COMMAND_MAX_PASSES', 40)

                result = process_with_tools(
                    llm_router=self._llm_router,
                    response=response,
                    history=history,
                    system_prompt=assembled.full_system_prompt,
                    max_passes=max_passes,
                    pulse_callback=self._on_pulse_interval_change,
                    tools=tools,
                    dev_mode_callbacks=self._build_dev_callbacks(),
                    thinking_enabled=True,
                    round_recorder=self._round_recorder
                )

                final_text = result.final_text

                # Clarification request
                if result.clarification_requested and result.clarification_data:
                    self._emit(EngineEventType.CLARIFICATION_REQUESTED,
                               data=result.clarification_data)

            # Strip temporal markers the LLM echoed from prompt context
            from core.temporal import strip_temporal_echoes
            final_text = strip_temporal_echoes(final_text)

            # Store response
            log_info(f"Storing assistant response ({len(final_text)} chars)", prefix="📨")
            self._conversation_mgr.add_turn(
                role="assistant",
                content=final_text,
                input_type="text"
            )

            # Emit final response
            self._emit(EngineEventType.RESPONSE_COMPLETE,
                       text=final_text, source="user", provider="anthropic")

            log_info("=== ChatEngine.process_message COMPLETE ===", prefix="📨")

        except Exception as e:
            error_msg = f"Message processing error: {str(e)}"
            tb = traceback.format_exc()
            log_error("=== ChatEngine.process_message EXCEPTION ===", prefix="📨")
            log_error(f"Exception: {error_msg}", prefix="📨")
            log_error(f"Traceback:\n{tb}", prefix="📨")
            self._emit(EngineEventType.PROCESSING_ERROR, error=str(e), error_type=None)

        finally:
            self._emit(EngineEventType.PROCESSING_COMPLETE)
            self._is_processing = False
            self._cancel_requested = False

    # ------------------------------------------------------------------
    # System pulse
    # ------------------------------------------------------------------

    def process_pulse(self, pulse_type: str):
        """Process a system pulse (reflective or action).

        Args:
            pulse_type: "reflective" or "action"
        """
        from agency.system_pulse import (
            get_action_pulse_prompt, ACTION_PULSE_STORED_MESSAGE,
            get_reflective_pulse_prompt, REFLECTIVE_PULSE_STORED_MESSAGE
        )
        from prompt_builder.sources.system_pulse import get_interval_label

        label = pulse_type.capitalize()
        log_info(f"=== ChatEngine.process_pulse({pulse_type}) START ===", prefix="⏱️")

        self._is_processing = True
        self._emit(EngineEventType.PROCESSING_STARTED, source="pulse")
        self._emit(EngineEventType.PULSE_FIRED, pulse_type=pulse_type)

        try:
            self._pause_timers()

            # Determine prompt and task type based on pulse type
            if pulse_type == "reflective":
                interval = self._pulse_manager.reflective_timer.interval if self._pulse_manager else 43200
                task_type = TaskType.PULSE_REFLECTIVE
                stored_message = REFLECTIVE_PULSE_STORED_MESSAGE
                pulse_prompt = get_reflective_pulse_prompt(get_interval_label(interval))
            else:
                interval = self._pulse_manager.action_timer.interval if self._pulse_manager else 7200
                task_type = TaskType.PULSE_ACTION
                stored_message = ACTION_PULSE_STORED_MESSAGE
                pulse_prompt = get_action_pulse_prompt(get_interval_label(interval))

            self._emit(EngineEventType.STATUS_UPDATE,
                       text=f"{label} pulse...", type="thinking")

            # Store abbreviated pulse message
            self._conversation_mgr.add_turn(
                role="system",
                content=stored_message,
                input_type="system"
            )

            # Build prompt
            assembled = self._prompt_builder.build(
                user_input=pulse_prompt,
                system_prompt="",
                additional_context={"is_pulse": True}
            )
            self._emit(EngineEventType.PROMPT_ASSEMBLED,
                       blocks=[], token_estimate=len(assembled.full_system_prompt) // 4)

            history = self._conversation_mgr.get_api_messages()
            history.append({"role": "user", "content": pulse_prompt})

            tools = get_tool_definitions(is_pulse=True)

            # Signal round start so the web process panel creates a round group
            self._emit(EngineEventType.STREAM_START)

            # LLM call (non-streaming for pulses)
            response = self._llm_router.chat(
                messages=history,
                system_prompt=assembled.full_system_prompt,
                task_type=task_type,
                temperature=0.7,
                tools=tools,
                thinking_enabled=True
            )

            log_info(f"PULSE: Router returned, success={response.success}", prefix="⏱️")

            if response.success:
                self._emit(EngineEventType.STREAM_COMPLETE,
                           text=response.text,
                           tokens_in=getattr(response, 'tokens_in', 0),
                           tokens_out=getattr(response, 'tokens_out', 0),
                           stop_reason=getattr(response, 'stop_reason', ''))

                result = process_with_tools(
                    llm_router=self._llm_router,
                    response=response,
                    history=history,
                    system_prompt=assembled.full_system_prompt,
                    max_passes=getattr(config, 'COMMAND_MAX_PASSES', 40),
                    pulse_callback=self._on_pulse_interval_change,
                    tools=tools,
                    dev_mode_callbacks=self._build_dev_callbacks(),
                    thinking_enabled=True,
                    task_type=task_type
                )

                final_text = result.final_text
                log_info(f"PULSE: Processed in {result.passes_executed} pass(es)", prefix="⏱️")

                self._conversation_mgr.add_turn(
                    role="assistant",
                    content=final_text,
                    input_type="text"
                )

                self._emit(EngineEventType.RESPONSE_COMPLETE,
                           text=final_text, source="pulse", provider=result.final_provider,
                           pulse_type=pulse_type)

                if result.clarification_requested and result.clarification_data:
                    self._emit(EngineEventType.CLARIFICATION_REQUESTED,
                               data=result.clarification_data)
            else:
                error_msg = f"{label} pulse API error: {response.error}"
                log_error(f"PULSE: API call failed - {error_msg}")
                self._emit(EngineEventType.PROCESSING_ERROR,
                           error=response.error, error_type="api_error")

        except Exception as e:
            error_msg = f"{label} pulse exception: {str(e)}"
            tb = traceback.format_exc()
            log_error(f"PULSE: Exception - {error_msg}")
            log_error(f"PULSE: Traceback:\n{tb}")
            self._emit(EngineEventType.PROCESSING_ERROR,
                       error=str(e), error_type=None)

        finally:
            log_info(f"=== ChatEngine.process_pulse({pulse_type}) completing ===", prefix="⏱️")
            if self._pulse_manager:
                self._pulse_manager.mark_pulse_complete()
            self._emit(EngineEventType.PROCESSING_COMPLETE)
            self._resume_timers()
            self._is_processing = False

    # ------------------------------------------------------------------
    # Reminder
    # ------------------------------------------------------------------

    def process_reminder(self, triggered_intentions):
        """Process a reminder pulse with triggered intentions.

        Args:
            triggered_intentions: List of Intention objects that are due
        """
        from agency.intentions import get_reminder_pulse_prompt

        log_info(f"=== ChatEngine.process_reminder() START ({len(triggered_intentions)} intentions) ===", prefix="⏰")

        self._is_processing = True
        self._emit(EngineEventType.PROCESSING_STARTED, source="reminder")

        # Build detail string for event
        reminder_detail = ""
        if triggered_intentions:
            previews = []
            for intention in triggered_intentions:
                content = getattr(intention, 'content', '')
                if content:
                    previews.append(content[:50])
            reminder_detail = "; ".join(previews) if previews else ""
        self._emit(EngineEventType.REMINDER_FIRED,
                   intentions=triggered_intentions, detail=reminder_detail)

        try:
            self._pause_timers()
            self._emit(EngineEventType.STATUS_UPDATE,
                       text="Reminder triggered...", type="thinking")

            reminder_prompt = get_reminder_pulse_prompt(triggered_intentions)
            stored_message = "[Reminder Pulse]"

            # Store abbreviated message
            self._conversation_mgr.add_turn(
                role="system",
                content=stored_message,
                input_type="system"
            )

            # Build prompt
            assembled = self._prompt_builder.build(
                user_input=reminder_prompt,
                system_prompt=""
            )

            history = self._conversation_mgr.get_api_messages()
            history.append({"role": "user", "content": reminder_prompt})

            tools = get_tool_definitions()

            # Signal round start so the web process panel creates a round group
            self._emit(EngineEventType.STREAM_START)

            # LLM call
            response = self._llm_router.chat(
                messages=history,
                system_prompt=assembled.full_system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=0.7,
                tools=tools,
                thinking_enabled=True
            )

            if response.success:
                result = process_with_tools(
                    llm_router=self._llm_router,
                    response=response,
                    history=history,
                    system_prompt=assembled.full_system_prompt,
                    max_passes=getattr(config, 'COMMAND_MAX_PASSES', 40),
                    pulse_callback=self._on_pulse_interval_change,
                    tools=tools,
                    dev_mode_callbacks=self._build_dev_callbacks(),
                    thinking_enabled=True
                )

                final_text = result.final_text
                log_info(f"REMINDER: Processed in {result.passes_executed} pass(es)", prefix="⏰")

                self._conversation_mgr.add_turn(
                    role="assistant",
                    content=final_text,
                    input_type="text"
                )

                self._emit(EngineEventType.RESPONSE_COMPLETE,
                           text=final_text, source="reminder",
                           provider=result.final_provider)

                if result.clarification_requested and result.clarification_data:
                    self._emit(EngineEventType.CLARIFICATION_REQUESTED,
                               data=result.clarification_data)
            else:
                error_msg = f"Reminder pulse API error: {response.error}"
                log_error(f"REMINDER: API call failed - {error_msg}")
                self._emit(EngineEventType.PROCESSING_ERROR,
                           error=response.error, error_type="api_error")

        except Exception as e:
            error_msg = f"Reminder pulse exception: {str(e)}"
            tb = traceback.format_exc()
            log_error(f"REMINDER: Exception - {error_msg}")
            log_error(f"REMINDER: Traceback:\n{tb}")
            self._emit(EngineEventType.PROCESSING_ERROR,
                       error=str(e), error_type=None)

        finally:
            log_info("=== ChatEngine.process_reminder() completing ===", prefix="⏰")
            if self._pulse_manager:
                self._pulse_manager.mark_pulse_complete()
            self._emit(EngineEventType.PROCESSING_COMPLETE)
            self._resume_timers()
            self._is_processing = False

    # ------------------------------------------------------------------
    # Telegram
    # ------------------------------------------------------------------

    def process_telegram(self, message):
        """Process an inbound Telegram message.

        Handles image attachments, memory injection, LLM call, tool
        processing, and auto-reply via Telegram gateway.

        Args:
            message: InboundMessage with .text, .from_user, .image fields
        """
        log_info(f"=== ChatEngine.process_telegram() START ===", prefix="📱")

        self._is_processing = True
        self._emit(EngineEventType.PROCESSING_STARTED, source="telegram")
        self._emit(EngineEventType.TELEGRAM_RECEIVED,
                   text=message.text,
                   from_user=getattr(message, 'from_user', '') or '')

        try:
            self._pause_timers()
            self._emit(EngineEventType.STATUS_UPDATE,
                       text="Processing Telegram message...", type="thinking")

            # Store the message as user input
            self._conversation_mgr.add_turn(
                role="user",
                content=message.text,
                input_type="telegram"
            )

            # Build prompt
            assembled = self._prompt_builder.build(
                user_input=message.text,
                system_prompt=""
            )

            history = self._conversation_mgr.get_api_messages()

            # Build user message - include Telegram image if present
            if hasattr(message, 'image') and message.image:
                user_message = self._build_telegram_image_message(
                    message.text, message.image)
                log_info("Telegram message includes user-sent image", prefix="📷")
            else:
                user_message = {"role": "user", "content": message.text}

            # Inject relevant memories
            relevant_memories = assembled.session_context.get("relevant_memories")
            self._inject_memories(user_message, relevant_memories)
            if relevant_memories:
                self._emit(EngineEventType.MEMORIES_INJECTED)

            history.append(user_message)

            tools = get_tool_definitions()

            # LLM call (non-streaming for Telegram)
            self._emit(EngineEventType.STATUS_UPDATE,
                       text="Responding to Telegram...", type="thinking")
            response = self._llm_router.chat(
                messages=history,
                system_prompt=assembled.full_system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=0.7,
                tools=tools,
                thinking_enabled=True
            )

            if response.success:
                result = process_with_tools(
                    llm_router=self._llm_router,
                    response=response,
                    history=history,
                    system_prompt=assembled.full_system_prompt,
                    max_passes=getattr(config, 'COMMAND_MAX_PASSES', 40),
                    pulse_callback=self._on_pulse_interval_change,
                    tools=tools,
                    dev_mode_callbacks=self._build_dev_callbacks(),
                    thinking_enabled=True
                )

                final_text = result.final_text
                telegram_sent = result.telegram_sent

                # Store response
                self._conversation_mgr.add_turn(
                    role="assistant",
                    content=final_text,
                    input_type="text"
                )

                self._emit(EngineEventType.RESPONSE_COMPLETE,
                           text=final_text, source="telegram",
                           provider=result.final_provider,
                           telegram_sent=telegram_sent)

                if result.clarification_requested and result.clarification_data:
                    self._emit(EngineEventType.CLARIFICATION_REQUESTED,
                               data=result.clarification_data)

                # Send response back to Telegram (only if not already sent via tool)
                if config.TELEGRAM_ENABLED and not telegram_sent:
                    try:
                        from communication.telegram_gateway import get_telegram_gateway
                        gateway = get_telegram_gateway()
                        if gateway.is_available():
                            gateway.send(final_text)
                            log_info("Telegram response sent successfully", prefix="📱")
                            self._emit(EngineEventType.TELEGRAM_SENT, text=final_text)
                        else:
                            log_warning("Telegram gateway not available for response")
                    except Exception as e:
                        log_warning(f"Failed to send response to Telegram: {e}")
            else:
                error_type = getattr(response, 'error_type', None)
                if error_type == "both_models_unavailable":
                    self.schedule_retry(message.text, source="telegram")
                    self._emit(EngineEventType.PROCESSING_ERROR,
                               error=response.error,
                               error_type="both_models_unavailable")
                    # Notify via Telegram
                    try:
                        if config.TELEGRAM_ENABLED:
                            from communication.telegram_gateway import get_telegram_gateway
                            gateway = get_telegram_gateway()
                            if gateway.is_available():
                                gateway.send("\u26a0 Both models are currently unavailable. Will retry in 20 minutes.")
                    except Exception:
                        pass
                else:
                    self._emit(EngineEventType.PROCESSING_ERROR,
                               error=response.error, error_type="api_error")

        except Exception as e:
            error_msg = f"Telegram message processing error: {str(e)}"
            tb = traceback.format_exc()
            log_error(f"Exception in process_telegram: {error_msg}")
            log_error(f"Traceback:\n{tb}")
            self._emit(EngineEventType.PROCESSING_ERROR,
                       error=str(e), error_type=None)

        finally:
            log_info("=== ChatEngine.process_telegram() completing ===", prefix="📱")
            self._emit(EngineEventType.PROCESSING_COMPLETE)
            self._resume_timers()
            self._is_processing = False

    # ------------------------------------------------------------------
    # Deferred retry
    # ------------------------------------------------------------------

    def schedule_retry(self, original_input: str, source: str = "user"):
        """Schedule a deferred retry when models are unavailable.

        Args:
            original_input: The original user input text to retry
            source: "user" or "telegram"
        """
        def retry_callback():
            self.process_deferred_retry(original_input, source)

        self._retry_manager.schedule(callback=retry_callback, source=source)
        self._emit(EngineEventType.RETRY_SCHEDULED, source=source)

    def process_deferred_retry(self, original_input: str, source: str):
        """Retry a previously failed message.

        Uses non-streaming (simpler, user isn't actively watching).

        Args:
            original_input: The original user input text
            source: "user" or "telegram"
        """
        log_info(f"=== ChatEngine.process_deferred_retry({source}) START ===", prefix="🔄")

        if self._is_processing:
            log_warning("Deferred retry skipped - already processing")
            return

        self._is_processing = True
        self._emit(EngineEventType.PROCESSING_STARTED, source="retry")
        self._emit(EngineEventType.STATUS_UPDATE,
                   text=f"Retrying {source} message...", type="thinking")

        try:
            self._pause_timers()

            # Rebuild prompt and history fresh
            assembled = self._prompt_builder.build(
                user_input=original_input,
                system_prompt=""
            )
            history = self._conversation_mgr.get_api_messages()

            if source == "telegram":
                user_message = {"role": "user", "content": original_input}
            else:
                user_message = self._capture_visuals_for_message(original_input)

            # Inject relevant memories
            relevant_memories = assembled.session_context.get("relevant_memories")
            self._inject_memories(user_message, relevant_memories)

            history.append(user_message)
            tools = get_tool_definitions()

            response = self._llm_router.chat(
                messages=history,
                system_prompt=assembled.full_system_prompt,
                task_type=TaskType.CONVERSATION,
                temperature=0.7,
                tools=tools,
                thinking_enabled=True
            )

            if response.success:
                result = process_with_tools(
                    llm_router=self._llm_router,
                    response=response,
                    history=history,
                    system_prompt=assembled.full_system_prompt,
                    max_passes=getattr(config, 'COMMAND_MAX_PASSES', 40),
                    pulse_callback=self._on_pulse_interval_change,
                    tools=tools,
                    thinking_enabled=True
                )

                final_text = result.final_text

                # Prepend deferred notice
                notice = "\u26a0 Delayed response to your earlier message:\n\n"
                final_text = notice + final_text

                # Store response
                self._conversation_mgr.add_turn(
                    role="assistant",
                    content=final_text,
                    input_type="text"
                )

                self._emit(EngineEventType.RESPONSE_COMPLETE,
                           text=final_text, source="retry",
                           provider=result.final_provider,
                           original_source=source,
                           telegram_sent=result.telegram_sent)

                # Send to Telegram if needed
                if source == "telegram" and not result.telegram_sent:
                    try:
                        if config.TELEGRAM_ENABLED:
                            from communication.telegram_gateway import get_telegram_gateway
                            gateway = get_telegram_gateway()
                            if gateway.is_available():
                                gateway.send(final_text)
                    except Exception as e:
                        log_warning(f"Failed to send deferred retry to Telegram: {e}")

                log_info(f"Deferred {source} retry succeeded", prefix="🔄")
            else:
                log_warning(f"Deferred {source} retry also failed: {response.error}")
                self._emit(EngineEventType.RETRY_FAILED,
                           source=source, error=response.error)

                # Notify Telegram if relevant
                if source == "telegram":
                    try:
                        if config.TELEGRAM_ENABLED:
                            from communication.telegram_gateway import get_telegram_gateway
                            gateway = get_telegram_gateway()
                            if gateway.is_available():
                                gateway.send("[Retry failed \u2014 models still unavailable]")
                    except Exception:
                        pass

        except Exception as e:
            log_error(f"Deferred {source} retry exception: {e}")
            self._emit(EngineEventType.RETRY_FAILED,
                       source=source, error=str(e))

        finally:
            self._emit(EngineEventType.PROCESSING_COMPLETE)
            self._resume_timers()
            self._is_processing = False
