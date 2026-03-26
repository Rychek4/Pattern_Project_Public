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


def ensure_tool_results(
    raw_content: List[Any],
    tool_result_message: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Ensure every CLIENT tool_use block in raw_content has a matching tool_result.

    This is a defensive safety net for the multi-pass tool loop.  It scans
    the assistant message's raw_content for `tool_use` blocks, compares
    their IDs against the `tool_result` blocks already present in the user
    message, and adds synthetic entries for any that are missing.

    SERVER-SIDE tools (web_search, web_fetch) are explicitly skipped:
    - Blocks typed as `server_tool_use` are ignored (correct type).
    - Blocks with `srvtoolu_` ID prefixes are ignored (server tool IDs).
    These tools are handled entirely by the Anthropic API and must NEVER
    receive client-side tool_result blocks.

    raw_content may contain a mix of plain dicts and SDK Pydantic objects
    (e.g. ToolUseBlock, ServerToolUseBlock).  Both are handled.

    See docs/reference/server_tool_use_bug.md for full history.

    Args:
        raw_content: The assistant message's raw content blocks
        tool_result_message: The user message dict with tool_result blocks
            (may be None if no client tools were executed)

    Returns:
        The tool_result_message dict, possibly augmented with synthetic entries
    """
    # Collect CLIENT tool_use IDs from the assistant message.
    # Skip server tools entirely — they must never have tool_result blocks.
    client_tool_use_ids = set()
    for block in raw_content:
        # Handle both plain dicts and SDK Pydantic objects
        if isinstance(block, dict):
            block_type = block.get("type")
            block_id = block.get("id")
        else:
            block_type = getattr(block, "type", None)
            block_id = getattr(block, "id", None)

        # Only collect IDs from client tool_use blocks
        if block_type == "tool_use" and block_id:
            # Skip server tool IDs (srvtoolu_ prefix)
            if isinstance(block_id, str) and block_id.startswith("srvtoolu_"):
                continue
            # Skip known server-side tools by name (safety net in case
            # the API ever sends them with a toolu_ prefix instead)
            block_name = block.get("name", "") if isinstance(block, dict) else getattr(block, "name", "")
            if block_name in ("web_search", "web_fetch"):
                continue
            client_tool_use_ids.add(block_id)
        # Explicitly skip server_tool_use blocks (no elif needed, just don't collect)

    if not client_tool_use_ids:
        # No client tool_use blocks — nothing to reconcile
        return tool_result_message or {"role": "user", "content": []}

    # Collect tool_result IDs already present in the user message
    existing_result_ids = set()
    if tool_result_message and tool_result_message.get("content"):
        for block in tool_result_message["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                result_id = block.get("tool_use_id")
                if result_id:
                    existing_result_ids.add(result_id)

    # Find orphaned client tool_use IDs (present in assistant but no tool_result)
    orphaned_ids = client_tool_use_ids - existing_result_ids
    if not orphaned_ids:
        return tool_result_message

    # Build or augment the tool_result message with synthetic entries
    log_warning(
        f"Adding synthetic tool_result for {len(orphaned_ids)} orphaned "
        f"client tool_use block(s) to prevent API 400 error"
    )
    if tool_result_message is None:
        tool_result_message = {"role": "user", "content": []}

    for orphan_id in orphaned_ids:
        tool_result_message["content"].append({
            "type": "tool_result",
            "tool_use_id": orphan_id,
            "content": "Tool execution completed.",
        })

    return tool_result_message


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

    # Image memory
    if tool_name == "save_image" and "description" in tool_input:
        return f"{tool_name}: {tool_input['description'][:60]}"

    # Server-side tools (web_search, web_fetch)
    if tool_name == "web_search" and "query" in tool_input:
        return f"{tool_name}: {tool_input['query']}"
    if tool_name == "web_fetch" and "url" in tool_input:
        return f"{tool_name}: {tool_input['url']}"

    # Domain management
    if tool_name == "manage_fetch_domains" and "domain" in tool_input:
        action = tool_input.get("action", "")
        return f"{tool_name}: {action} {tool_input['domain']}"

    # Growth threads
    if tool_name == "set_growth_thread" and "slug" in tool_input:
        return f"{tool_name}: {tool_input['slug']}"

    # Growth thread promotion
    if tool_name == "promote_growth_thread" and "thread_slug" in tool_input:
        return f"{tool_name}: {tool_input['thread_slug']}"

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
        clarification_requested: Reserved for future use
        clarification_data: Reserved for future use
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

    @staticmethod
    def _ensure_tool_results(
        raw_content: List[Any],
        tool_result_message: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Delegate to module-level ensure_tool_results()."""
        return ensure_tool_results(raw_content, tool_result_message)

    def process_response(
        self,
        response: "AnthropicResponse",
        history: List[Dict[str, Any]],
        max_passes: Optional[int] = None,
        pulse_callback: Optional[Callable[[int], None]] = None,
        dev_mode_callbacks: Optional[Dict[str, Callable]] = None,
        pass1_duration: float = 0.0
    ) -> ToolProcessingResult:
        """
        Process a response through multi-pass tool execution.

        Args:
            response: Initial AnthropicResponse from the API
            history: Conversation history (will be copied, not modified)
            max_passes: Maximum number of tool execution passes (default: config.COMMAND_MAX_PASSES)
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
        if max_passes is None:
            max_passes = getattr(config, 'COMMAND_MAX_PASSES', 40)
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
                change = processed.pulse_interval_change
                log_info(f"PULSE DEBUG: pulse_interval_change detected: {change}", prefix="🔍")
                if pulse_callback:
                    log_info(f"PULSE DEBUG: Invoking pulse_callback({change})", prefix="🔍")
                    pulse_callback(change)
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

            # Add tool results message, ensuring every tool_use block has
            # a matching tool_result (see _ensure_tool_results for details)
            tool_result_msg = self._ensure_tool_results(
                current_response.raw_content,
                processed.tool_result_message
            )
            current_history.append(tool_result_msg)

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
                    error_note = "\n\n⚠️ Web access was blocked for a domain that restricts automated access. Consider using delegate_task to browse the page directly."
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
    max_passes: Optional[int] = None,
    pulse_callback: Optional[Callable] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    dev_mode_callbacks: Optional[Dict[str, Callable]] = None,
    thinking_enabled: bool = False,
    thinking_budget_tokens: Optional[int] = None,
    round_recorder=None,
    task_type=None
) -> ToolProcessingResult:
    """
    Convenience function for processing a response with native tools.

    This is a simpler interface for cases where you don't need to reuse the helper.

    Args:
        llm_router: The LLM router instance
        response: Initial AnthropicResponse
        history: Conversation history
        system_prompt: System prompt
        max_passes: Maximum tool execution passes (default: config.COMMAND_MAX_PASSES)
        pulse_callback: Optional callback for pulse interval changes.
            Called with dict: {"pulse_type": str, "interval_seconds": int}
        tools: Optional tool definitions
        dev_mode_callbacks: Optional dict of callbacks for dev window:
            - emit_response_pass: For Response Pipeline tab
            - emit_command_executed: For Tools tab
        thinking_enabled: Whether to enable extended thinking for continuations
        thinking_budget_tokens: Max tokens for thinking (None = use config default)
        round_recorder: Optional RoundRecorder for prompt export
        task_type: Task type for router calls (defaults to CONVERSATION)

    Returns:
        ToolProcessingResult with final text and metadata
    """
    helper = ToolResponseHelper(
        llm_router=llm_router,
        system_prompt=system_prompt,
        tools=tools,
        task_type=task_type,
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
