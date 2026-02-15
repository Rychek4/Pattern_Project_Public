"""
Pattern Project - Native Tool Use System
Claude's native tool calling with structured arguments.

This is the primary tool system for the project. The legacy [[COMMAND]] pattern
has been deprecated in favor of this native tool approach.

Components:
    - definitions: Tool schemas for the Anthropic API
    - executor: Routes tool calls to existing handlers
    - processor: Processes responses and builds continuation messages
    - response_helper: Shared helper for multi-pass tool processing

Usage:
    from agency.tools import get_tool_definitions, get_tool_processor

    # Get tool schemas for API call
    tools = get_tool_definitions()

    # Process response with tool calls
    processor = get_tool_processor()
    result = processor.process(response, context)

    if result.needs_continuation:
        # Send tool results back to Claude
        next_response = client.chat(
            messages=[...previous..., assistant_msg, result.tool_result_message],
            tools=tools
        )

For simpler multi-pass processing, use the response helper:
    from agency.tools import process_with_tools

    result = process_with_tools(
        llm_router=router,
        response=response,
        history=history,
        system_prompt=system_prompt,
        pulse_callback=lambda interval: handle_pulse_change(interval)
    )
"""

from agency.tools.definitions import get_tool_definitions
from agency.tools.executor import ToolExecutor, ToolResult, get_tool_executor
from agency.tools.processor import ToolProcessor, ProcessedToolResponse, get_tool_processor
from agency.tools.response_helper import (
    ToolResponseHelper,
    ToolProcessingResult,
    process_with_tools
)


__all__ = [
    # Definitions
    'get_tool_definitions',
    # Executor
    'ToolExecutor',
    'ToolResult',
    'get_tool_executor',
    # Processor
    'ToolProcessor',
    'ProcessedToolResponse',
    'get_tool_processor',
    # Response Helper
    'ToolResponseHelper',
    'ToolProcessingResult',
    'process_with_tools',
]
