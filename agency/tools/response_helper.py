"""
Pattern Project - Tool Response Processing Helper
Shared helper for processing LLM responses with native tool use.

This module provides a unified approach for processing tool-based responses
across all entry points (GUI, CLI, pulse, telegram, etc.). It handles:
- Multi-pass tool execution
- Continuation message building
- Pulse interval change detection
- Telegram send tracking

Usage:
    from agency.tools.response_helper import ToolResponseHelper

    helper = ToolResponseHelper(
        llm_router=router,
        system_prompt=system_prompt,
        tools=get_tool_definitions()
    )

    result = helper.process_response(
        response=initial_response,
        history=conversation_history,
        max_passes=5,
        pulse_callback=lambda interval: signals.pulse_interval_change.emit(interval)
    )

    final_text = result.final_text
    telegram_sent = result.telegram_sent
"""

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from agency.tools import get_tool_definitions, get_tool_processor
from agency.tools.processor import ProcessedToolResponse
from core.logger import log_info, log_warning
from core.temporal import strip_temporal_echoes

if TYPE_CHECKING:
    from llm.anthropic_client import AnthropicResponse


def _build_tool_detail(tool_name: str, tool_input: Any) -> str:
    """
    Build a human-readable detail string for a tool invocation.

    Format: "tool_name: relevant_detail"
    The process panel splits on ":" to show tool name as label
    and everything after as the detail line.
    """
    if not isinstance(tool_input, dict):
        return tool_name

    # Memory tools
    if tool_name == "search_memories" and "query" in tool_input:
        return f"{tool_name}: {tool_input['query']}"

    # Communication tools
    if tool_name == "send_telegram" and "message" in tool_input:
        return f"{tool_name}: {tool_input['message'][:60]}"
    if tool_name == "send_email" and "subject" in tool_input:
        return f"{tool_name}: {tool_input['subject']}"

    # File tools
    if tool_name == "read_file" and "path" in tool_input:
        return f"{tool_name}: {tool_input['path']}"
    if tool_name == "write_file" and "path" in tool_input:
        return f"{tool_name}: {tool_input['path']}"
    if tool_name == "append_file" and "path" in tool_input:
        return f"{tool_name}: {tool_input['path']}"

    # Reminder tools
    if tool_name == "create_reminder" and "what" in tool_input:
        when = tool_input.get("when", "")
        what = tool_input["what"][:50]
        if when:
            return f"{tool_name}: {what} (at {when})"
        return f"{tool_name}: {what}"
    if tool_name == "complete_reminder" and "reminder_id" in tool_input:
        reminder_id = tool_input["reminder_id"]
        outcome = tool_input.get("outcome", "")[:40]
        try:
            from agency.intentions import get_intention_manager
            intention = get_intention_manager().get_intention(reminder_id)
            if intention:
                return f"{tool_name}: {intention.content[:50]} (I-{reminder_id})" + (f" - {outcome}" if outcome else "")
        except Exception:
            pass
        return f"{tool_name}: I-{reminder_id}" + (f" - {outcome}" if outcome else "")
    if tool_name == "dismiss_reminder" and "reminder_id" in tool_input:
        reminder_id = tool_input["reminder_id"]
        try:
            from agency.intentions import get_intention_manager
            intention = get_intention_manager().get_intention(reminder_id)
            if intention:
                return f"{tool_name}: {intention.content[:50]} (I-{reminder_id})"
        except Exception:
            pass
        return f"{tool_name}: I-{reminder_id}"

    # Curiosity tools
    if tool_name == "advance_curiosity" and "note" in tool_input:
        return f"{tool_name}: {tool_input['note'][:50]}"
    if tool_name == "resolve_curiosity" and "status" in tool_input:
        notes = tool_input.get("notes", "")[:40]
        return f"{tool_name}: {tool_input['status']}" + (f" - {notes}" if notes else "")

    # Pulse tool
    if tool_name == "set_pulse_interval" and "interval" in tool_input:
        return f"{tool_name}: {tool_input['interval']}"

    # Active thoughts
    if tool_name == "set_active_thoughts" and "thoughts" in tool_input:
        thoughts = tool_input["thoughts"]
        if isinstance(thoughts, list) and thoughts:
            first = thoughts[0]
            preview = first.get("topic", str(first)) if isinstance(first, dict) else str(first)
            return f"{tool_name}: {preview[:40]}..."
        return tool_name

    # Delegation tool
    if tool_name == "delegate_task" and "task" in tool_input:
        return f"{tool_name}: {tool_input['task'][:80]}"

    # Visual capture
    if tool_name == "capture_screenshot":
        return f"{tool_name}: screen capture"
    if tool_name == "capture_webcam":
        return f"{tool_name}: webcam capture"

    # Clipboard
    if tool_name == "set_clipboard" and "text" in tool_input:
        return f"{tool_name}: {tool_input['text'][:40]}"

    # Server-side tools (web_search, web_fetch)
    if tool_name == "web_search" and "query" in tool_input:
        return f"{tool_name}: {tool_input['query']}"
    if tool_name == "web_fetch" and "url" in tool_input:
        return f"{tool_name}: {tool_input['url']}"

    # Social platform tools
    if tool_name in ("reddit_search", "moltbook_search") and "query" in tool_input:
        return f"{tool_name}: {tool_input['query']}"
    if tool_name in ("reddit_create_post", "moltbook_create_post") and "title" in tool_input:
        return f"{tool_name}: {tool_input['title'][:50]}"
    if tool_name in ("reddit_comment", "moltbook_comment") and "body" in tool_input:
        return f"{tool_name}: {tool_input['body'][:50]}"
    if tool_name in ("reddit_feed", "moltbook_feed"):
        subreddit = tool_input.get("subreddit") or tool_input.get("submolt", "")
        if subreddit:
            return f"{tool_name}: {subreddit}"

    # Domain management
    if tool_name == "manage_fetch_domains" and "domain" in tool_input:
        action = tool_input.get("action", "")
        return f"{tool_name}: {action} {tool_input['domain']}"

    # Growth threads
    if tool_name == "set_growth_thread" and "slug" in tool_input:
        return f"{tool_name}: {tool_input['slug']}"

    # Core memory
    if tool_name == "store_core_memory" and "content" in tool_input:
        return f"{tool_name}: {tool_input['content'][:50]}"

    return tool_name


@dataclass
class ToolProcessingResult:
    """
    Result from complete tool response processing (all passes).

    Attributes:
        final_text: The final response text after all processing
        final_provider: The provider that generated the final response
        passes_executed: Number of API calls made
        telegram_sent: True if send_telegram was executed successfully (any pass)
        pulse_interval_changed: True if pulse interval was changed (any pass)
        total_duration_ms: Total processing time in milliseconds
        clarification_requested: True if request_clarification was used
        clarification_data: Dict with question, options, context if clarification requested
    """
    final_text: str
    final_provider: str
    passes_executed: int = 1
    telegram_sent: bool = False
    pulse_interval_changed: bool = False
    total_duration_ms: float = 0.0
    clarification_requested: bool = False
    clarification_data: Optional[Dict[str, Any]] = None


class ToolResponseHelper:
    """
    Helper class for processing LLM responses with native tool use.

    This consolidates the multi-pass tool execution logic that was duplicated
    across GUI and CLI interfaces. It provides a single, tested implementation
    for all message entry points (user input, pulse, telegram, reminders).

    The helper handles:
    1. Processing initial response for tool calls
    2. Building continuation messages with tool results
    3. Making continuation API calls with tools enabled
    4. Tracking pulse interval changes across all passes
    5. Tracking telegram sends to avoid duplicates
    6. Dev window event emission (if enabled)
    """

    def __init__(
        self,
        llm_router,
        system_prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        task_type=None,
        thinking_enabled: bool = False,
        thinking_budget_tokens: Optional[int] = None,
        round_recorder=None
    ):
        """
        Initialize the helper.

        Args:
            llm_router: The LLM router instance for making API calls
            system_prompt: System prompt for all API calls
            tools: Tool definitions (defaults to get_tool_definitions())
            task_type: Task type for router calls (defaults to CONVERSATION)
            thinking_enabled: Whether to enable extended thinking for continuations
            thinking_budget_tokens: Max tokens for thinking (None = use config default)
            round_recorder: Optional RoundRecorder for prompt export
        """
        self._router = llm_router
        self._system_prompt = system_prompt
        self._tools = tools if tools is not None else get_tool_definitions()
        self._task_type = task_type
        self._thinking_enabled = thinking_enabled
        self._thinking_budget_tokens = thinking_budget_tokens
        self._processor = get_tool_processor()
        self._round_recorder = round_recorder

    def process_response(
        self,
        response: "AnthropicResponse",
        history: List[Dict[str, Any]],
        max_passes: int = 5,
        pulse_callback: Optional[Callable[[int], None]] = None,
        dev_mode_callbacks: Optional[Dict[str, Callable]] = None,
        pass1_duration: float = 0.0
    ) -> ToolProcessingResult:
        """
        Process a response through multi-pass tool execution.

        Args:
            response: Initial AnthropicResponse from the API
            history: Conversation history (will be copied, not modified)
            max_passes: Maximum number of tool execution passes
            pulse_callback: Optional callback for pulse interval changes.
                            Called with interval in seconds when AI changes pulse.
            dev_mode_callbacks: Optional dict of callbacks for dev window:
                - emit_response_pass: (pass_num, provider, text, tokens_in, tokens_out, duration_ms, tools, ...) -> None
                - emit_command_executed: (name, query, result, error, needs_continuation) -> None
            pass1_duration: Duration of first API call in ms (for dev window)

        Returns:
            ToolProcessingResult with final text and metadata
        """
        import config
        from llm.router import TaskType
        from interface.process_panel import ProcessEventType, get_process_event_bus

        task_type = self._task_type or TaskType.CONVERSATION
        current_response = response
        current_history = history.copy()
        current_duration = pass1_duration

        # Track across all passes
        telegram_sent = False
        pulse_interval_changed = False
        clarification_requested = False
        clarification_data = None
        start_time = time.time()

        # Accumulate text across all passes to preserve original streamed text
        # This fixes a bug where text from early passes was lost if later
        # continuations returned empty text
        accumulated_text = ""

        event_bus = get_process_event_bus()

        for pass_num in range(1, max_passes + 1):
            # Create fresh context for each pass to avoid cross-contamination
            context = {}

            # Process response for tool calls
            processed = self._processor.process(current_response, context=context)

            # Accumulate text from this pass
            pass_text = processed.display_text.strip() if processed.display_text else ""
            pass_text = strip_temporal_echoes(pass_text)
            if pass_text:
                if accumulated_text:
                    # Append continuation text with separator
                    accumulated_text = accumulated_text + "\n\n" + pass_text
                else:
                    accumulated_text = pass_text

            # Emit to dev window if enabled
            if dev_mode_callbacks and config.DEV_MODE_ENABLED:
                self._emit_dev_events(
                    dev_mode_callbacks,
                    pass_num,
                    current_response,
                    processed,
                    current_duration
                )

            # Handle pulse interval change from this pass
            if processed.has_pulse_interval_change():
                pulse_interval_changed = True
                log_info(f"PULSE DEBUG: pulse_interval_change detected: {processed.pulse_interval_change}s", prefix="🔍")
                if pulse_callback:
                    log_info(f"PULSE DEBUG: Invoking pulse_callback({processed.pulse_interval_change})", prefix="🔍")
                    pulse_callback(processed.pulse_interval_change)
                    log_info("PULSE DEBUG: pulse_callback returned", prefix="🔍")
                else:
                    log_warning("PULSE DEBUG: No pulse_callback provided!")

            # Track telegram sends across all passes
            if processed.telegram_sent:
                telegram_sent = True

            # Track clarification requests (from context set by executor)
            if context.get("clarification_requested"):
                clarification_requested = True
                clarification_data = context["clarification_requested"]

            # Emit tool invocations to process panel
            if current_response.has_tool_calls():
                for tc in current_response.tool_calls:
                    tool_detail = _build_tool_detail(tc.name, tc.input if hasattr(tc, 'input') else {})
                    event_bus.emit_event(
                        ProcessEventType.TOOL_INVOKED,
                        detail=tool_detail,
                        round_number=pass_num
                    )

            # Emit server-side tool calls (web_search, web_fetch) to process panel
            server_tools = getattr(current_response, 'server_tool_details', []) or []
            for st in server_tools:
                tool_name = st.get("name", "")
                tool_input = st.get("input", {})
                tool_detail = _build_tool_detail(tool_name, tool_input)
                event_bus.emit_event(
                    ProcessEventType.TOOL_INVOKED,
                    detail=tool_detail,
                    round_number=pass_num
                )

            # If no continuation needed (no tool calls or stop_reason != "tool_use")
            if not processed.needs_continuation:
                return ToolProcessingResult(
                    final_text=accumulated_text,
                    final_provider=current_response.provider.value if hasattr(current_response.provider, 'value') else str(current_response.provider),
                    passes_executed=pass_num,
                    telegram_sent=telegram_sent,
                    pulse_interval_changed=pulse_interval_changed,
                    total_duration_ms=(time.time() - start_time) * 1000,
                    clarification_requested=clarification_requested,
                    clarification_data=clarification_data
                )

            # Warn if pass count is unusually high (possible tool loop)
            if pass_num >= 5:
                log_warning(f"Query has reached pass {pass_num}, which is unusually high — possible tool loop")

            # Build continuation: add assistant message with raw content blocks
            current_history.append({
                "role": "assistant",
                "content": current_response.raw_content
            })

            # Add tool results message
            current_history.append(processed.tool_result_message)

            # Record continuation request for prompt export
            if self._round_recorder:
                # Resolve model name for recording
                _model = getattr(config, 'ANTHROPIC_MODEL_CONVERSATION', 'unknown')
                self._round_recorder.record_request(
                    system_prompt=self._system_prompt,
                    messages=current_history,
                    tools=self._tools,
                    model=_model,
                    temperature=0.7,
                    thinking_enabled=self._thinking_enabled,
                    thinking_budget_tokens=self._thinking_budget_tokens,
                    is_streaming=False,
                )

            # Emit continuation start to process panel
            event_bus.emit_event(
                ProcessEventType.CONTINUATION_START,
                round_number=pass_num + 1,
                is_active=True
            )

            # Get next response with tools
            cont_start = time.time()
            continuation = self._router.chat(
                messages=current_history,
                system_prompt=self._system_prompt,
                task_type=task_type,
                temperature=0.7,
                tools=self._tools,
                thinking_enabled=self._thinking_enabled,
                thinking_budget_tokens=self._thinking_budget_tokens
            )
            current_duration = (time.time() - cont_start) * 1000

            # Record continuation response for prompt export
            if self._round_recorder and continuation.success:
                self._round_recorder.record_response(
                    response_text=continuation.text or "",
                    thinking_text=getattr(continuation, 'thinking_text', "") or "",
                    tool_calls=getattr(continuation, 'tool_calls', []) or [],
                    raw_content=getattr(continuation, 'raw_content', []) or [],
                    stop_reason=getattr(continuation, 'stop_reason', "") or "",
                    tokens_in=getattr(continuation, 'tokens_in', 0),
                    tokens_out=getattr(continuation, 'tokens_out', 0),
                )

            # Emit continuation complete to process panel
            cont_round = pass_num + 1
            if continuation.success:
                token_detail = ""
                if hasattr(continuation, 'tokens_out') and continuation.tokens_out:
                    token_detail = f"{continuation.tokens_out} tokens"
                event_bus.emit_event(
                    ProcessEventType.STREAM_COMPLETE,
                    detail=token_detail,
                    round_number=cont_round
                )

            if not continuation.success:
                # On failure, return accumulated text from successful passes
                log_warning(f"Continuation failed on pass {pass_num + 1}: {continuation.error}")

                # Surface the failure to the user so they know the round was truncated
                error_note = ""
                error_type = getattr(continuation, 'error_type', None)
                if error_type == "web_fetch_domain_blocked":
                    error_note = "\n\n⚠️ Web fetch was blocked for a domain that restricts automated access. The response may be incomplete."
                elif continuation.error:
                    error_note = f"\n\n⚠️ An error interrupted processing. The response may be incomplete."

                final_text = accumulated_text
                if error_note:
                    final_text = (accumulated_text + error_note) if accumulated_text else error_note.strip()

                return ToolProcessingResult(
                    final_text=final_text,
                    final_provider=current_response.provider.value if hasattr(current_response.provider, 'value') else str(current_response.provider),
                    passes_executed=pass_num,
                    telegram_sent=telegram_sent,
                    pulse_interval_changed=pulse_interval_changed,
                    total_duration_ms=(time.time() - start_time) * 1000,
                    clarification_requested=clarification_requested,
                    clarification_data=clarification_data
                )

            current_response = continuation

        # Hit max passes - return accumulated text plus any text from final response
        log_info(f"Reached max passes ({max_passes}), returning final response", prefix="🔧")

        # Include any text from the final unprocessed response
        final_response_text = current_response.text.strip() if current_response.text else ""
        final_response_text = strip_temporal_echoes(final_response_text)
        if final_response_text:
            if accumulated_text:
                accumulated_text = accumulated_text + "\n\n" + final_response_text
            else:
                accumulated_text = final_response_text

        return ToolProcessingResult(
            final_text=accumulated_text,
            final_provider=current_response.provider.value if hasattr(current_response.provider, 'value') else str(current_response.provider),
            passes_executed=max_passes,
            telegram_sent=telegram_sent,
            pulse_interval_changed=pulse_interval_changed,
            total_duration_ms=(time.time() - start_time) * 1000,
            clarification_requested=clarification_requested,
            clarification_data=clarification_data
        )

    def _emit_dev_events(
        self,
        callbacks: Dict[str, Callable],
        pass_num: int,
        response: "AnthropicResponse",
        processed: ProcessedToolResponse,
        duration_ms: float
    ):
        """Emit events to dev window if callbacks provided."""
        emit_pass = callbacks.get("emit_response_pass")
        emit_cmd = callbacks.get("emit_command_executed")

        if emit_pass:
            tool_names = [tc.name for tc in response.tool_calls] if response.has_tool_calls() else []
            emit_pass(
                pass_number=pass_num,
                provider=response.provider.value if pass_num == 1 else "continuation",
                response_text=response.text,
                tokens_in=getattr(response, 'tokens_in', 0) if pass_num == 1 else 0,
                tokens_out=getattr(response, 'tokens_out', 0) if pass_num == 1 else 0,
                duration_ms=duration_ms,
                commands_detected=tool_names,
                web_searches_used=getattr(response, 'web_searches_used', 0) if pass_num == 1 else 0,
                citations=getattr(response, 'citations', []) if pass_num == 1 else []
            )

        if emit_cmd:
            for result in processed.tool_results:
                emit_cmd(
                    command_name=result.tool_name,
                    query=str(result.content)[:100] if result.content else "",
                    result_data=result.content,
                    error=str(result.content) if result.is_error else None,
                    needs_continuation=True
                )


def process_with_tools(
    llm_router,
    response: "AnthropicResponse",
    history: List[Dict[str, Any]],
    system_prompt: str,
    max_passes: int = 5,
    pulse_callback: Optional[Callable[[int], None]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    dev_mode_callbacks: Optional[Dict[str, Callable]] = None,
    thinking_enabled: bool = False,
    thinking_budget_tokens: Optional[int] = None,
    round_recorder=None
) -> ToolProcessingResult:
    """
    Convenience function for processing a response with native tools.

    This is a simpler interface for cases where you don't need to reuse the helper.

    Args:
        llm_router: The LLM router instance
        response: Initial AnthropicResponse
        history: Conversation history
        system_prompt: System prompt
        max_passes: Maximum tool execution passes
        pulse_callback: Optional callback for pulse interval changes
        tools: Optional tool definitions
        dev_mode_callbacks: Optional dict of callbacks for dev window:
            - emit_response_pass: For Response Pipeline tab
            - emit_command_executed: For Tools tab
        thinking_enabled: Whether to enable extended thinking for continuations
        thinking_budget_tokens: Max tokens for thinking (None = use config default)
        round_recorder: Optional RoundRecorder for prompt export

    Returns:
        ToolProcessingResult with final text and metadata
    """
    helper = ToolResponseHelper(
        llm_router=llm_router,
        system_prompt=system_prompt,
        tools=tools,
        thinking_enabled=thinking_enabled,
        thinking_budget_tokens=thinking_budget_tokens,
        round_recorder=round_recorder
    )
    return helper.process_response(
        response=response,
        history=history,
        max_passes=max_passes,
        pulse_callback=pulse_callback,
        dev_mode_callbacks=dev_mode_callbacks
    )
