"""
Pattern Project - Task Delegation Runner
Runs lightweight sub-agent instances for contained tasks.

A delegated task spins up a fresh, ephemeral conversation with a smaller model
(Haiku by default). The sub-agent has its own tool loop but NO access to
memories, identity, active thoughts, or communication tools.

The sub-agent works through the task, optionally using tools, and returns
its final text output to the caller (Isaac's main conversation).

Usage:
    from agency.tools.delegate import run_delegated_task

    result = run_delegated_task(
        task="Summarize the key themes in these notes",
        context="Focus on technical architecture decisions",
        max_rounds=5
    )
"""

import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import config
from core.logger import log_info, log_warning, log_error


# =============================================================================
# SUB-AGENT SYSTEM PROMPT
# =============================================================================

DELEGATE_SYSTEM_PROMPT = """You are a task-focused assistant. Complete the assigned task concisely and accurately.

You have access to tools if needed — use them when they help accomplish the task.
When you are done, provide your final answer as clear, well-organized text.

Guidelines:
- Stay focused on the task. Do not ask clarifying questions — work with what you have.
- Be concise but thorough.
- If a tool call fails, adapt and continue with what you can determine.
- Return your final answer directly — no preamble like "Here is the result:"."""


# =============================================================================
# DELEGATE TOOL DEFINITIONS
# =============================================================================
# Tools available to the sub-agent. This is deliberately minimal.
# Add new tools here as the delegation system grows.

def get_delegate_tool_definitions() -> List[Dict[str, Any]]:
    """
    Get tool definitions available to delegated sub-agents.

    Returns a curated, safe subset of tools. Sub-agents do NOT get:
    - Memory tools (search_memories, set_active_thoughts)
    - Communication tools (send_telegram, send_email)
    - State tools (set_pulse_interval, advance_curiosity)
    - Delegation itself (no recursive spawning)
    - Visual capture tools
    - Social platform tools

    Returns:
        List of tool definition dicts for the Anthropic API
    """
    tools = []

    # Example tool: get_current_time
    # Demonstrates the registration pattern and is marginally useful
    tools.append(GET_CURRENT_TIME_TOOL)

    # Future tools would be registered here:
    # tools.append(READ_FILE_TOOL)      # File reading
    # tools.append(WRITE_FILE_TOOL)     # File writing
    # tools.append(LIST_FILES_TOOL)     # File listing
    # etc.

    return tools


GET_CURRENT_TIME_TOOL: Dict[str, Any] = {
    "name": "get_current_time",
    "description": "Get the current date and time in ISO format.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}


# =============================================================================
# DELEGATE TOOL EXECUTOR
# =============================================================================

class DelegateToolExecutor:
    """
    Executes tools for delegated sub-agents.

    This is a minimal executor that only handles the tools registered in
    get_delegate_tool_definitions(). It is completely independent of the
    main ToolExecutor — the sub-agent cannot access any tool that isn't
    explicitly registered here.
    """

    def __init__(self):
        """Initialize with the delegate tool handler mappings."""
        self._handlers: Dict[str, Callable] = {
            "get_current_time": self._exec_get_current_time,
            # Add new tool handlers here as they are registered above
        }

    def execute(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_use_id: str
    ) -> Dict[str, Any]:
        """
        Execute a tool call and return a result dict.

        Args:
            tool_name: Name of the tool to execute
            tool_input: Structured input from the model
            tool_use_id: Unique ID for result correlation

        Returns:
            Dict with 'tool_use_id', 'content', and optional 'is_error'
        """
        handler_fn = self._handlers.get(tool_name)
        if not handler_fn:
            log_warning(f"Delegate sub-agent called unknown tool: {tool_name}")
            return {
                "tool_use_id": tool_use_id,
                "content": f"Unknown tool: {tool_name}. Available: {list(self._handlers.keys())}",
                "is_error": True
            }

        try:
            content = handler_fn(tool_input)
            return {
                "tool_use_id": tool_use_id,
                "content": content
            }
        except Exception as e:
            log_error(f"Delegate tool error ({tool_name}): {e}")
            return {
                "tool_use_id": tool_use_id,
                "content": f"Tool error: {str(e)}",
                "is_error": True
            }

    # =========================================================================
    # TOOL HANDLERS
    # =========================================================================

    def _exec_get_current_time(self, input: Dict) -> str:
        """Return the current date and time."""
        now = datetime.now(timezone.utc)
        local_now = datetime.now()
        return f"UTC: {now.isoformat()}\nLocal: {local_now.isoformat()}"


# =============================================================================
# DELEGATION RUNNER
# =============================================================================

def run_delegated_task(
    task: str,
    context: str = "",
    max_rounds: Optional[int] = None
) -> str:
    """
    Run a delegated task on a lightweight sub-agent.

    Creates a fresh conversation with the delegation model (Haiku),
    gives it a minimal system prompt and curated tool set, and runs
    a multi-pass tool loop until the sub-agent finishes or hits the
    round limit.

    Args:
        task: Description of what the sub-agent should accomplish
        context: Optional additional context for the sub-agent
        max_rounds: Max continuation passes (capped by config)

    Returns:
        The sub-agent's final text response
    """
    from llm.router import TaskType, get_llm_router

    # Resolve max rounds
    config_max = config.DELEGATION_MAX_ROUNDS
    if max_rounds is not None:
        max_rounds = min(max_rounds, 10)  # Hard cap at 10
    else:
        max_rounds = config_max

    # Build the user message
    user_content = task
    if context:
        user_content = f"{task}\n\nAdditional context:\n{context}"

    messages = [{"role": "user", "content": user_content}]

    # Get tools and executor
    tools = get_delegate_tool_definitions()
    executor = DelegateToolExecutor()

    # Get the router
    router = get_llm_router()

    log_info(f"Delegation started: {task[:80]}... (max {max_rounds} rounds)", prefix="🤖")
    start_time = time.time()

    # Track accumulated text across all passes
    accumulated_text = ""

    for round_num in range(1, max_rounds + 1):
        # Call the model
        response = router.chat(
            messages=messages,
            system_prompt=DELEGATE_SYSTEM_PROMPT,
            task_type=TaskType.DELEGATION,
            max_tokens=config.DELEGATION_MAX_TOKENS,
            temperature=0.5,
            tools=tools if tools else None,
            thinking_enabled=False
        )

        if not response.success:
            log_error(f"Delegation round {round_num} failed: {response.error}")
            if accumulated_text:
                return accumulated_text
            return f"[Delegation error: {response.error}]"

        # Accumulate any text from this response
        response_text = response.text.strip() if response.text else ""
        if response_text:
            if accumulated_text:
                accumulated_text = accumulated_text + "\n\n" + response_text
            else:
                accumulated_text = response_text

        # If no tool calls, we're done
        if not response.has_tool_calls():
            duration_ms = (time.time() - start_time) * 1000
            log_info(
                f"Delegation complete: {round_num} round(s), "
                f"{duration_ms:.0f}ms, "
                f"{response.tokens_in + response.tokens_out} tokens",
                prefix="🤖"
            )
            return accumulated_text

        # Execute tool calls and build continuation
        tool_results = []
        for tool_call in response.tool_calls:
            result = executor.execute(
                tool_name=tool_call.name,
                tool_input=tool_call.input,
                tool_use_id=tool_call.id
            )
            tool_results.append(result)

            status = "error" if result.get("is_error") else "ok"
            log_info(
                f"  Delegate tool: {tool_call.name} -> {status}",
                prefix="🤖"
            )

        # Build continuation messages
        # Assistant message with raw content blocks (includes tool_use blocks)
        messages.append({
            "role": "assistant",
            "content": response.raw_content
        })

        # Tool results message
        tool_result_content = []
        for result in tool_results:
            block = {
                "type": "tool_result",
                "tool_use_id": result["tool_use_id"],
                "content": str(result["content"])
            }
            if result.get("is_error"):
                block["is_error"] = True
            tool_result_content.append(block)

        messages.append({
            "role": "user",
            "content": tool_result_content
        })

    # Hit max rounds
    duration_ms = (time.time() - start_time) * 1000
    log_warning(
        f"Delegation hit max rounds ({max_rounds}), "
        f"{duration_ms:.0f}ms",
    )

    if accumulated_text:
        return accumulated_text
    return "[Delegation completed but produced no text output]"
