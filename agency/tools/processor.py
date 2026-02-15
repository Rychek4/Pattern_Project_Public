"""
Pattern Project - Tool Processor
Processes Claude's native tool use responses.

This processor handles the tool_use response flow:
1. Parse tool calls from response
2. Execute tools via ToolExecutor
3. Build tool_result messages for continuation
4. Handle images from visual tools
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agency.tools.executor import get_tool_executor, ToolResult
from llm.anthropic_client import AnthropicResponse
from core.logger import log_info, log_warning

if TYPE_CHECKING:
    from agency.visual_capture import ImageContent


@dataclass
class ProcessedToolResponse:
    """
    Result of processing a response for tool calls.

    Attributes:
        original_text: Text content from the response
        display_text: Text formatted for display
        tool_results: List of results from executed tools
        needs_continuation: Whether to call Claude again with results
        tool_result_message: Message dict to send tool results back to Claude
        continuation_images: Images to include in continuation (from visual tools)
        pulse_interval_change: New pulse interval in seconds if AI requested change
        telegram_sent: True if send_telegram was executed successfully
    """
    original_text: str
    display_text: str
    tool_results: List[ToolResult] = field(default_factory=list)
    needs_continuation: bool = False
    tool_result_message: Optional[Dict[str, Any]] = None
    continuation_images: Optional[List["ImageContent"]] = field(default=None)
    pulse_interval_change: Optional[int] = None
    telegram_sent: bool = False

    def has_tool_results(self) -> bool:
        """Check if any tools were executed."""
        return len(self.tool_results) > 0

    def has_continuation_images(self) -> bool:
        """Check if there are images to include in continuation."""
        return self.continuation_images is not None and len(self.continuation_images) > 0

    def has_pulse_interval_change(self) -> bool:
        """Check if pulse interval change was requested."""
        return self.pulse_interval_change is not None


class ToolProcessor:
    """
    Processes Claude responses containing tool calls.

    The processor:
    1. Checks if response contains tool_use blocks
    2. Executes each tool via the ToolExecutor
    3. Builds the tool_result message for the next API call
    4. Collects images from visual tools for multimodal continuation

    Usage:
        processor = ToolProcessor()
        result = processor.process(response, context)

        if result.needs_continuation:
            # Send result.tool_result_message back to Claude
            next_response = client.chat(
                messages=[...previous..., assistant_msg, result.tool_result_message],
                tools=tool_definitions
            )
    """

    def __init__(self):
        """Initialize the processor."""
        self._executor = get_tool_executor()

    def process(
        self,
        response: AnthropicResponse,
        context: Optional[Dict] = None
    ) -> ProcessedToolResponse:
        """
        Process a response for tool calls and execute them.

        Args:
            response: AnthropicResponse from the API
            context: Optional session context dict

        Returns:
            ProcessedToolResponse with execution results and continuation info
        """
        # Use 'is None' check instead of 'or {}' because empty dict is falsy
        # and 'or {}' would create a NEW dict, breaking context propagation
        if context is None:
            context = {}

        # If no tool calls, just return the text
        if not response.has_tool_calls():
            return ProcessedToolResponse(
                original_text=response.text,
                display_text=response.text,
                tool_results=[],
                needs_continuation=False,
                tool_result_message=None
            )

        # Execute all tool calls
        results: List[ToolResult] = []
        telegram_sent = False

        for tool_call in response.tool_calls:
            result = self._executor.execute(
                tool_name=tool_call.name,
                tool_input=tool_call.input,
                tool_use_id=tool_call.id,
                context=context
            )
            results.append(result)

            # Log execution
            status = "error" if result.is_error else "success"
            log_info(f"Tool {tool_call.name}: {status}", prefix="🔧")

            # Track telegram sends for response handling
            if tool_call.name == "send_telegram" and not result.is_error:
                telegram_sent = True

        # Build tool_result message for Claude
        tool_result_message = self._build_tool_result_message(results)

        # Collect images from visual tools
        continuation_images = self._collect_images(results)

        # Extract pulse interval change if requested
        pulse_interval_change = context.get("pulse_interval_change")

        return ProcessedToolResponse(
            original_text=response.text,
            display_text=response.text,
            tool_results=results,
            needs_continuation=True,  # Always continue after tool execution
            tool_result_message=tool_result_message,
            continuation_images=continuation_images,
            pulse_interval_change=pulse_interval_change,
            telegram_sent=telegram_sent
        )

    def _build_tool_result_message(self, results: List[ToolResult]) -> Dict[str, Any]:
        """
        Build the message to send tool results back to Claude.

        The message uses role="user" with tool_result content blocks.
        Each block correlates to a tool_use via tool_use_id.

        Args:
            results: List of ToolResult from executed tools

        Returns:
            Message dict ready to append to conversation history
        """
        content = []

        for result in results:
            tool_result_block: Dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": result.tool_use_id,
            }

            if result.is_error:
                tool_result_block["is_error"] = True

            # Content is always a string for tool results
            tool_result_block["content"] = str(result.content)

            content.append(tool_result_block)

            # If this tool returned images, add them as image blocks
            # These go after the tool_result block
            if result.has_images():
                for img in result.image_data:
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": img.media_type,
                            "data": img.data
                        }
                    })
                log_info(f"Added {len(result.image_data)} image(s) from {result.tool_name}", prefix="🖼️")

        return {"role": "user", "content": content}

    def _collect_images(self, results: List[ToolResult]) -> Optional[List["ImageContent"]]:
        """
        Collect images from tool results for tracking.

        Args:
            results: List of ToolResult

        Returns:
            List of ImageContent or None if no images
        """
        images = []
        for result in results:
            if result.has_images():
                images.extend(result.image_data)

        return images if images else None


# Global instance
_tool_processor: Optional[ToolProcessor] = None


def get_tool_processor() -> ToolProcessor:
    """Get the global tool processor instance."""
    global _tool_processor
    if _tool_processor is None:
        _tool_processor = ToolProcessor()
    return _tool_processor
