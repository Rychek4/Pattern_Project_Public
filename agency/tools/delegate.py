"""
Pattern Project - Task Delegation Runner
Runs lightweight sub-agent instances for contained tasks.

A delegated task spins up a fresh, ephemeral conversation with a smaller model
(Haiku by default). The sub-agent is a browser automation agent with tools to
navigate websites, interact with page elements, and access service credentials.

The sub-agent has NO access to Isaac's memories, identity, active thoughts,
or communication tools. It is a stateless browser worker that completes a
task and returns the result to Isaac's main conversation.

Usage:
    from agency.tools.delegate import run_delegated_task

    result = run_delegated_task(
        task="Log into Reddit and post 'Hello from Isaac' to r/test",
        context="Use the reddit credentials. Post as a text post.",
        max_rounds=15
    )
"""

import asyncio
import time
from typing import Any, Dict, List, Optional

import config
from core.logger import log_info, log_warning, log_error
from interface.process_panel import ProcessEventType, get_process_event_bus


# =============================================================================
# SUB-AGENT SYSTEM PROMPT
# =============================================================================

DELEGATE_SYSTEM_PROMPT = """You are a browser automation agent. You interact with websites using your tools to complete tasks assigned to you.

You have NO memory, NO context about the user, and NO knowledge beyond this task description. Everything you need to know is in the task you've been given.

Available tools:
- navigate(url): Go to a web page
- read_page(): See the current page — returns numbered interactive elements and visible text
- click(element_id): Click an element by its number from read_page()
- type(element_id, text): Type into an input field by its number from read_page()
- wait(seconds): Wait for page content to load (0.5-10 seconds)
- get_credentials(service): Look up login credentials for a service
- report_result(result): Report your final result and stop. You MUST call this when your task is complete.

Workflow:
1. If the task requires logging in, call get_credentials() first to get the login URL and credentials.
2. Navigate to the target page.
3. Call read_page() after navigating or clicking to see the result — you cannot see the page without it.
4. Use the element numbers from read_page() with click() and type() to interact.
5. After submitting forms or clicking buttons, call read_page() to verify the result.
6. When done, call report_result() with a clear summary of what you accomplished or found. Do NOT continue browsing after the task is complete.

Important:
- Before making any tool calls, output a brief numbered plan (3-7 steps) of exactly what you will do. Then execute against that plan step by step.
- NEVER guess what's on a page. Always call read_page() to see it.
- If you encounter a CAPTCHA, 2FA challenge, or unexpected verification screen, call report_result() to report the blocker and stop — do not try to solve it.
- If a login fails, try once more, then call report_result() to report the failure.
- Once you have completed the task or found the requested information, call report_result() IMMEDIATELY. Do not re-read a page unless you performed an action that changed it.
- Be methodical: navigate → read → act → read → verify → report_result.
- Stay focused on the assigned task. Do not browse unrelated pages."""


# =============================================================================
# DELEGATE TOOL DEFINITIONS
# =============================================================================

REPORT_RESULT_TOOL: Dict[str, Any] = {
    "name": "report_result",
    "description": (
        "Report the final result of your task and stop. Call this when you have "
        "completed the assigned task or gathered the requested information. "
        "Include a clear summary of what you accomplished or found. After calling "
        "this tool, no further tool calls will be made."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "result": {
                "type": "string",
                "description": "Clear summary of what was accomplished or found"
            }
        },
        "required": ["result"]
    }
}


def get_delegate_tool_definitions() -> List[Dict[str, Any]]:
    """
    Get tool definitions available to delegated sub-agents.

    The delegate is a browser-only agent. Its tools are:
    - navigate, read_page, click, type, wait (browser interaction)
    - get_credentials (read-only service credential lookup)
    - report_result (signal task completion and return result)

    Sub-agents do NOT get:
    - Memory tools (search_memories, set_active_thoughts)
    - Communication tools (send_telegram, send_email)
    - State tools (set_pulse_interval, advance_curiosity)
    - Delegation itself (no recursive spawning)
    - Visual capture tools
    - File tools
    - Social platform tools (these are replaced by browser automation)

    Returns:
        List of tool definition dicts for the Anthropic API
    """
    from agency.tools.browser.tools import get_browser_tool_definitions
    tools = get_browser_tool_definitions()
    tools.append(REPORT_RESULT_TOOL)
    return tools


# =============================================================================
# DELEGATE TOOL EXECUTOR
# =============================================================================

class DelegateToolExecutor:
    """
    Executes tools for delegated sub-agents.

    Wraps the BrowserToolExecutor and manages the async event loop
    needed for Playwright operations. The browser is lazy-initialized
    on the first tool call that needs it.
    """

    def __init__(self):
        """Initialize with an async event loop and browser tool executor."""
        # Create a dedicated event loop for async Playwright operations
        self._loop = asyncio.new_event_loop()

        # Resolve paths from config (already Path objects)
        sessions_dir = config.BROWSER_SESSIONS_DIR
        credentials_path = config.BROWSER_CREDENTIALS_PATH

        # Ensure sessions directory exists
        sessions_dir.mkdir(parents=True, exist_ok=True)

        from agency.tools.browser.tools import BrowserToolExecutor
        self._browser_executor = BrowserToolExecutor(
            sessions_dir=sessions_dir,
            credentials_path=credentials_path,
            event_loop=self._loop
        )

    def execute(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_use_id: str
    ) -> Dict[str, Any]:
        """
        Execute a tool call and return a result dict.

        All tools are browser tools routed through BrowserToolExecutor.

        Args:
            tool_name: Name of the tool to execute
            tool_input: Structured input from the model
            tool_use_id: Unique ID for result correlation

        Returns:
            Dict with 'tool_use_id', 'content', and optional 'is_error'
        """
        return self._browser_executor.execute(tool_name, tool_input, tool_use_id)

    def cleanup(self) -> None:
        """Shut down the browser and event loop."""
        try:
            self._loop.run_until_complete(self._browser_executor.close())
        except Exception as e:
            log_warning(f"Browser cleanup error: {e}")
        finally:
            try:
                self._loop.close()
            except Exception:
                pass


# =============================================================================
# DELEGATION RUNNER
# =============================================================================

def run_delegated_task(
    task: str,
    context: str = "",
    max_rounds: Optional[int] = None
) -> str:
    """
    Run a delegated task on a lightweight browser-capable sub-agent.

    Creates a fresh conversation with the delegation model (Haiku),
    gives it a browser-agent system prompt and browser tools, and runs
    a multi-pass tool loop until the sub-agent finishes or hits the
    round limit.

    The browser is lazy-initialized — if the sub-agent doesn't use any
    browser tools, no Playwright process is started.

    Args:
        task: Description of what the sub-agent should accomplish.
              Must be specific: include exact URLs, full text content,
              and clear instructions. The sub-agent has no other context.
        context: Optional additional context for the sub-agent
        max_rounds: Max continuation passes (default from config, hard cap 15)

    Returns:
        The sub-agent's final text response
    """
    from llm.router import TaskType, get_llm_router

    # Resolve max rounds — hard cap at 20 for browser workflows
    config_max = config.DELEGATION_MAX_ROUNDS
    if max_rounds is not None:
        max_rounds = min(max_rounds, 20)  # Hard cap at 20
    else:
        max_rounds = min(config_max, 20)  # Also cap the config default

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

    # Emit delegation start to process panel
    event_bus = get_process_event_bus()
    event_bus.emit_event(
        ProcessEventType.DELEGATION_START,
        detail=f"{task[:100]} (max {max_rounds} rounds)"
    )

    # Track accumulated text across all passes
    accumulated_text = ""

    try:
        for round_num in range(1, max_rounds + 1):
            # Call the model
            response = router.chat(
                messages=messages,
                system_prompt=DELEGATE_SYSTEM_PROMPT,
                task_type=TaskType.DELEGATION,
                max_tokens=config.DELEGATION_MAX_TOKENS,
                temperature=config.DELEGATION_TEMPERATURE,
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
                event_bus.emit_event(
                    ProcessEventType.DELEGATION_COMPLETE,
                    detail=f"{round_num} round(s), {duration_ms:.0f}ms"
                )
                return accumulated_text

            # Execute tool calls and build continuation
            tool_results = []
            report_received = False
            for tool_call in response.tool_calls:
                # Check for report_result — delegate is explicitly done
                if tool_call.name == "report_result":
                    report_text = ""
                    if isinstance(tool_call.input, dict):
                        report_text = tool_call.input.get("result", "")
                    if report_text:
                        accumulated_text = (
                            (accumulated_text + "\n\n" + report_text).strip()
                        )
                    report_received = True
                    log_info(
                        f"  Delegate tool: report_result -> done",
                        prefix="🤖"
                    )
                    event_bus.emit_event(
                        ProcessEventType.DELEGATION_TOOL,
                        detail="report_result"
                    )
                    break

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

                # Emit delegate sub-tool call to process panel
                tool_input = tool_call.input if hasattr(tool_call, 'input') else {}
                tool_detail = tool_call.name
                if isinstance(tool_input, dict):
                    if tool_call.name == "navigate" and "url" in tool_input:
                        tool_detail = f"{tool_call.name}: {tool_input['url']}"
                    elif tool_call.name == "click" and "element_id" in tool_input:
                        tool_detail = f"{tool_call.name}: element #{tool_input['element_id']}"
                    elif tool_call.name == "type" and "text" in tool_input:
                        tool_detail = f"{tool_call.name}: {tool_input['text'][:50]}"
                    elif tool_call.name == "wait" and "seconds" in tool_input:
                        tool_detail = f"{tool_call.name}: {tool_input['seconds']}s"
                    elif tool_call.name == "get_credentials" and "service" in tool_input:
                        tool_detail = f"{tool_call.name}: {tool_input['service']}"
                if status == "error":
                    tool_detail += " [error]"
                event_bus.emit_event(
                    ProcessEventType.DELEGATION_TOOL,
                    detail=tool_detail
                )

            # If delegate reported its result, we're done
            if report_received:
                duration_ms = (time.time() - start_time) * 1000
                log_info(
                    f"Delegation complete (reported): {round_num} round(s), "
                    f"{duration_ms:.0f}ms",
                    prefix="🤖"
                )
                event_bus.emit_event(
                    ProcessEventType.DELEGATION_COMPLETE,
                    detail=f"{round_num} round(s), {duration_ms:.0f}ms"
                )
                return accumulated_text

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
        event_bus.emit_event(
            ProcessEventType.DELEGATION_COMPLETE,
            detail=f"hit max rounds ({max_rounds}), {duration_ms:.0f}ms"
        )

        if accumulated_text:
            return accumulated_text
        return "[Delegation completed but produced no text output]"

    finally:
        # Always clean up the browser, even if an error occurs
        executor.cleanup()
