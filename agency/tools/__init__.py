"""
Pattern Project - Native Tool Use System
Claude's native tool calling with structured arguments.

This module provides native tool use as an alternative to the [[COMMAND]] pattern.
Enable via config.USE_NATIVE_TOOLS = True.

Components:
    - definitions: Tool schemas for the Anthropic API
    - executor: Routes tool calls to existing handlers
    - processor: Processes responses and builds continuation messages

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
"""

from agency.tools.definitions import get_tool_definitions
from agency.tools.executor import ToolExecutor, ToolResult, get_tool_executor
from agency.tools.processor import ToolProcessor, ProcessedToolResponse, get_tool_processor


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
]
