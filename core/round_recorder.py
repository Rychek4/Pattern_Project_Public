"""
Pattern Project - Round Recorder
Captures the complete API payload for each pass of a single conversation round.

Each "round" starts when the user triggers the AI and ends when the final
response is complete (including all tool-use continuation passes). The recorder
stores the full request and response for every API call so that the export
reproduces exactly what the model saw at each decision point.

The export file is overwritten on every button press — it holds at most one round.
"""

import json
import copy
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.logger import log_info, log_error


@dataclass
class APICallRecord:
    """One complete API request/response pair."""
    pass_number: int
    is_streaming: bool

    # Request payload (exactly what the model receives)
    system_prompt: str
    messages: List[Dict[str, Any]]
    tools: List[Dict[str, Any]]
    model: str
    temperature: float
    thinking_enabled: bool
    thinking_budget_tokens: Optional[int]

    # Response payload
    response_text: str = ""
    thinking_text: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    raw_content: List[Any] = field(default_factory=list)
    stop_reason: str = ""
    tokens_in: int = 0
    tokens_out: int = 0


class RoundRecorder:
    """
    Collects full API payloads across all passes of a single round.

    Usage:
        recorder.start_round()
        recorder.record_request(...)     # Before each API call
        recorder.record_response(...)    # After each API response
        recorder.export_to_file(path)    # On button press
    """

    def __init__(self):
        self._calls: List[APICallRecord] = []
        self._round_timestamp: Optional[datetime] = None
        self._pass_counter: int = 0

    def start_round(self):
        """Reset state for a new round."""
        self._calls = []
        self._round_timestamp = datetime.now()
        self._pass_counter = 0

    def record_request(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        model: str,
        temperature: float,
        thinking_enabled: bool,
        thinking_budget_tokens: Optional[int] = None,
        is_streaming: bool = True,
    ):
        """Record a full API request payload. Call before each API call."""
        self._pass_counter += 1
        record = APICallRecord(
            pass_number=self._pass_counter,
            is_streaming=is_streaming,
            system_prompt=system_prompt,
            messages=_deep_copy_messages(messages),
            tools=_deep_copy_tools(tools),
            model=model,
            temperature=temperature,
            thinking_enabled=thinking_enabled,
            thinking_budget_tokens=thinking_budget_tokens,
        )
        self._calls.append(record)

    def record_response(
        self,
        response_text: str,
        thinking_text: str,
        tool_calls: list,
        raw_content: list,
        stop_reason: str,
        tokens_in: int,
        tokens_out: int,
    ):
        """Record response data onto the most recent request record."""
        if not self._calls:
            log_error("record_response called with no pending request")
            return
        record = self._calls[-1]
        record.response_text = response_text or ""
        record.thinking_text = thinking_text or ""
        record.tool_calls = _serialize_tool_calls(tool_calls)
        record.raw_content = _serialize_raw_content(raw_content)
        record.stop_reason = stop_reason or ""
        record.tokens_in = tokens_in
        record.tokens_out = tokens_out

    @property
    def has_data(self) -> bool:
        return len(self._calls) > 0

    # ── Export ───────────────────────────────────────────────────────────

    def export_to_file(self, path: str) -> bool:
        """
        Format the recorded round as human-readable text and write to file.
        The file is overwritten every time (single-round only).

        Returns True on success.
        """
        if not self._calls:
            log_info("RoundRecorder: nothing to export (no API calls recorded)")
            return False

        try:
            import os
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

            total_passes = len(self._calls)
            ts = self._round_timestamp.strftime("%Y-%m-%d %H:%M:%S") if self._round_timestamp else "unknown"

            lines: List[str] = []
            _header(lines, f"PROMPT EXPORT  --  {ts}")
            lines.append("")
            lines.append(f"    Total API calls in this round: {total_passes}")
            lines.append("")

            for call in self._calls:
                self._format_call(lines, call, total_passes)

            # Summary
            _divider_heavy(lines)
            lines.append("  ROUND SUMMARY")
            _divider_heavy(lines)
            total_in = sum(c.tokens_in for c in self._calls)
            total_out = sum(c.tokens_out for c in self._calls)
            tool_names = []
            for c in self._calls:
                for tc in c.tool_calls:
                    name = tc.get("name", "unknown")
                    if name not in tool_names:
                        tool_names.append(name)
            lines.append(f"    Total passes:     {total_passes}")
            lines.append(f"    Total tokens in:  {total_in}")
            lines.append(f"    Total tokens out: {total_out}")
            lines.append(f"    Tools called:     {', '.join(tool_names) if tool_names else '(none)'}")
            lines.append("")

            text = "\n".join(lines)

            with open(path, "w", encoding="utf-8") as f:
                f.write(text)

            log_info(f"RoundRecorder: exported {total_passes} API call(s) to {path}")
            return True

        except Exception as e:
            log_error(f"RoundRecorder: export failed: {e}")
            return False

    # ── Formatting helpers ──────────────────────────────────────────────

    def _format_call(self, lines: List[str], call: APICallRecord, total: int):
        """Format one complete API call (request + response)."""
        mode = "Streaming" if call.is_streaming else "Non-streaming"
        _divider_heavy(lines)
        lines.append(f"  API CALL {call.pass_number} of {total}  --  {mode}")
        _divider_heavy(lines)
        lines.append("")

        # ── REQUEST ──
        _divider_light(lines, "REQUEST")
        lines.append("")

        # Model config
        _section_open(lines, "MODEL CONFIGURATION")
        lines.append(f"        Model:            {call.model}")
        lines.append(f"        Temperature:      {call.temperature}")
        if call.thinking_enabled:
            if call.model.startswith("claude-opus-4-6"):
                import config as _cfg
                effort = getattr(_cfg, 'ANTHROPIC_THINKING_EFFORT', 'high')
                lines.append(f"        Thinking:         adaptive (effort={effort})")
            elif call.thinking_budget_tokens:
                lines.append(f"        Thinking:         enabled (budget={call.thinking_budget_tokens} tokens)")
            else:
                lines.append(f"        Thinking:         enabled")
        else:
            lines.append(f"        Thinking:         disabled")
        _section_close(lines)
        lines.append("")

        # System prompt
        _section_open(lines, "SYSTEM PROMPT")
        _indent_block(lines, call.system_prompt)
        _section_close(lines)
        lines.append("")

        # Messages
        msg_count = len(call.messages)
        _section_open(lines, f"MESSAGE HISTORY  ({msg_count} messages)")
        for i, msg in enumerate(call.messages):
            self._format_message(lines, i + 1, msg)
        _section_close(lines)
        lines.append("")

        # Tool definitions
        tool_count = len(call.tools)
        _section_open(lines, f"TOOL DEFINITIONS  ({tool_count} tools)")
        for tool_def in call.tools:
            self._format_tool_definition(lines, tool_def)
        _section_close(lines)
        lines.append("")

        # ── RESPONSE ──
        _divider_light(lines, "RESPONSE")
        lines.append("")

        # Thinking
        if call.thinking_text:
            _section_open(lines, "THINKING  (internal)")
            _indent_block(lines, call.thinking_text)
            _section_close(lines)
            lines.append("")

        # Response text
        _section_open(lines, "RESPONSE TEXT")
        if call.response_text:
            _indent_block(lines, call.response_text)
        else:
            lines.append("        (no text content)")
        _section_close(lines)
        lines.append("")

        # Tool calls
        if call.tool_calls:
            tc_count = len(call.tool_calls)
            _section_open(lines, f"TOOL CALLS  ({tc_count} call{'s' if tc_count != 1 else ''})")
            for j, tc in enumerate(call.tool_calls):
                lines.append(f"        [{j + 1}] {tc.get('name', 'unknown')}  (id: {tc.get('id', '?')})")
                tc_input = tc.get("input", {})
                try:
                    formatted = json.dumps(tc_input, indent=4, default=str)
                except (TypeError, ValueError):
                    formatted = str(tc_input)
                for fline in formatted.splitlines():
                    lines.append(f"            {fline}")
                lines.append("")
            _section_close(lines)
            lines.append("")

        # Stop reason & tokens
        lines.append(f"    Stop reason: {call.stop_reason}")
        lines.append(f"    Tokens:      {call.tokens_in} in / {call.tokens_out} out")
        lines.append("")

    def _format_message(self, lines: List[str], index: int, msg: Dict[str, Any]):
        """Format a single message from the history."""
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")

        lines.append(f"        ── [{index}] {role} ──")

        if isinstance(content, str):
            _indent_block(lines, content, indent=12)
        elif isinstance(content, list):
            # Multimodal content (text blocks, images, tool results, etc.)
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type", "unknown")
                    if block_type == "text":
                        _indent_block(lines, block.get("text", ""), indent=12)
                    elif block_type == "image":
                        source = block.get("source", {})
                        media = source.get("media_type", "?")
                        data_len = len(source.get("data", ""))
                        lines.append(f"            [IMAGE: {media}, {data_len} chars base64]")
                    elif block_type == "tool_use":
                        lines.append(f"            [TOOL_USE: {block.get('name', '?')}  id: {block.get('id', '?')}]")
                        try:
                            formatted = json.dumps(block.get("input", {}), indent=4, default=str)
                        except (TypeError, ValueError):
                            formatted = str(block.get("input", {}))
                        for fline in formatted.splitlines():
                            lines.append(f"                {fline}")
                    elif block_type == "tool_result":
                        is_err = block.get("is_error", False)
                        label = "TOOL_RESULT (ERROR)" if is_err else "TOOL_RESULT"
                        lines.append(f"            [{label}: id: {block.get('tool_use_id', '?')}]")
                        result_content = block.get("content", "")
                        if isinstance(result_content, str):
                            _indent_block(lines, result_content, indent=16)
                        elif isinstance(result_content, list):
                            for rc in result_content:
                                if isinstance(rc, dict) and rc.get("type") == "text":
                                    _indent_block(lines, rc.get("text", ""), indent=16)
                                else:
                                    lines.append(f"                {rc}")
                    elif block_type == "thinking":
                        lines.append(f"            [THINKING]")
                        _indent_block(lines, block.get("thinking", ""), indent=16)
                    else:
                        # Fallback: dump the block as JSON
                        try:
                            formatted = json.dumps(block, indent=4, default=str)
                        except (TypeError, ValueError):
                            formatted = str(block)
                        for fline in formatted.splitlines():
                            lines.append(f"            {fline}")
                else:
                    lines.append(f"            {block}")
        else:
            lines.append(f"            {content}")

        lines.append("")

    def _format_tool_definition(self, lines: List[str], tool_def: Dict[str, Any]):
        """Format a single tool definition."""
        name = tool_def.get("name", "unknown")
        desc = tool_def.get("description", "")
        lines.append(f"        {name}")
        if desc:
            # Show first line of description
            first_line = desc.split("\n")[0].strip()
            lines.append(f"            {first_line}")

        schema = tool_def.get("input_schema", {})
        props = schema.get("properties", {})
        required = schema.get("required", [])
        if props:
            for pname, pinfo in props.items():
                ptype = pinfo.get("type", "?")
                req = " (required)" if pname in required else ""
                lines.append(f"            - {pname}: {ptype}{req}")
        lines.append("")


# ── Module-level formatting utilities ────────────────────────────────────


def _header(lines: List[str], title: str):
    bar = "=" * 72
    lines.append(bar)
    lines.append(f"  {title}")
    lines.append(bar)


def _divider_heavy(lines: List[str]):
    lines.append("=" * 72)


def _divider_light(lines: List[str], label: str = ""):
    if label:
        lines.append(f"    {'─' * 20} {label} {'─' * 20}")
    else:
        lines.append(f"    {'─' * 50}")


def _section_open(lines: List[str], title: str):
    lines.append(f"    ┌─── {title} ───┐")


def _section_close(lines: List[str]):
    lines.append(f"    └{'─' * 50}┘")


def _indent_block(lines: List[str], text: str, indent: int = 8):
    """Add text with consistent indentation, preserving internal newlines."""
    prefix = " " * indent
    if not text:
        lines.append(f"{prefix}(empty)")
        return
    for line in text.splitlines():
        lines.append(f"{prefix}{line}")


def _deep_copy_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deep-copy message list, handling non-serializable content gracefully."""
    try:
        return copy.deepcopy(messages)
    except Exception:
        # Fallback: shallow copy each dict
        result = []
        for msg in messages:
            try:
                result.append(copy.deepcopy(msg))
            except Exception:
                result.append({"role": msg.get("role", "?"), "content": str(msg.get("content", ""))})
        return result


def _deep_copy_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deep-copy tool definitions."""
    try:
        return copy.deepcopy(tools)
    except Exception:
        return [{"name": t.get("name", "?"), "description": t.get("description", "")} for t in tools]


def _serialize_tool_calls(tool_calls: list) -> List[Dict[str, Any]]:
    """Convert ToolCall objects (or dicts) to plain dicts for storage."""
    result = []
    for tc in (tool_calls or []):
        if isinstance(tc, dict):
            result.append(tc)
        else:
            # Dataclass ToolCall from anthropic_client
            result.append({
                "id": getattr(tc, "id", "?"),
                "name": getattr(tc, "name", "?"),
                "input": getattr(tc, "input", {}),
            })
    return result


def _serialize_raw_content(raw_content: list) -> List[Any]:
    """Best-effort serialization of raw content blocks."""
    try:
        return copy.deepcopy(raw_content)
    except Exception:
        return [str(item) for item in (raw_content or [])]
