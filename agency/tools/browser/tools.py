"""
Pattern Project - Browser Tool Definitions and Executor

Defines the 6 browser tools available to the delegate sub-agent and
provides the BrowserToolExecutor that handles their execution.

Tools:
    navigate(url)              - Go to a URL
    read_page()                - Get interactive element map + visible text
    click(element_id)          - Click a numbered element
    type(element_id, text)     - Type into a numbered element
    wait(seconds)              - Wait for dynamic content to load
    get_credentials(service)   - Read-only credential lookup

The executor holds a reference to the BrowserEngine and manages the
async-to-sync bridge needed by the delegate's tool loop.
"""

import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, List

from core.logger import log_info, log_warning, log_error


# =============================================================================
# TOOL DEFINITIONS (for the Anthropic API)
# =============================================================================

NAVIGATE_TOOL: Dict[str, Any] = {
    "name": "navigate",
    "description": (
        "Navigate the browser to a URL. Use this to visit websites, "
        "follow links, or go to specific pages. After navigating, call "
        "read_page() to see what's on the page."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The full URL to navigate to (e.g., 'https://www.reddit.com')"
            }
        },
        "required": ["url"]
    }
}

READ_PAGE_TOOL: Dict[str, Any] = {
    "name": "read_page",
    "description": (
        "Read the current page. Returns a numbered list of interactive elements "
        "(links, buttons, inputs, etc.) and the visible text content. "
        "Always call this after navigating to understand the page structure. "
        "Use the element numbers with click() and type() to interact."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

CLICK_TOOL: Dict[str, Any] = {
    "name": "click",
    "description": (
        "Click an interactive element on the page by its element number "
        "from read_page(). Use this for buttons, links, checkboxes, tabs, "
        "and any other clickable elements."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "element_id": {
                "type": "integer",
                "description": "The element number from read_page() output (e.g., 1, 2, 3)"
            }
        },
        "required": ["element_id"]
    }
}

TYPE_TOOL: Dict[str, Any] = {
    "name": "type",
    "description": (
        "Type text into an input field by its element number from read_page(). "
        "The field is cleared before typing. Use this for text inputs, "
        "search boxes, text areas, and form fields."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "element_id": {
                "type": "integer",
                "description": "The element number of the input field from read_page()"
            },
            "text": {
                "type": "string",
                "description": "The text to type into the field"
            }
        },
        "required": ["element_id", "text"]
    }
}

WAIT_TOOL: Dict[str, Any] = {
    "name": "wait",
    "description": (
        "Wait for a specified number of seconds. Use this when a page is "
        "loading dynamic content, after clicking a submit button, or when "
        "you need to give the page time to update. Maximum 10 seconds."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "seconds": {
                "type": "number",
                "description": "Number of seconds to wait (0.5 to 10)"
            }
        },
        "required": ["seconds"]
    }
}

GET_CREDENTIALS_TOOL: Dict[str, Any] = {
    "name": "get_credentials",
    "description": (
        "Look up login credentials for a service. Returns username, password, "
        "and login URL if configured. Use this before logging into a website. "
        "Credentials are read-only and managed by the user."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "Service name to look up (e.g., 'reddit', 'twitter', 'gmail')"
            }
        },
        "required": ["service"]
    }
}


def get_browser_tool_definitions() -> List[Dict[str, Any]]:
    """
    Get all browser tool definitions for the delegate sub-agent.

    Returns:
        List of tool definition dicts for the Anthropic API
    """
    return [
        NAVIGATE_TOOL,
        READ_PAGE_TOOL,
        CLICK_TOOL,
        TYPE_TOOL,
        WAIT_TOOL,
        GET_CREDENTIALS_TOOL,
    ]


# =============================================================================
# BROWSER TOOL EXECUTOR
# =============================================================================

class BrowserToolExecutor:
    """
    Executes browser tools for the delegate sub-agent.

    Manages the BrowserEngine lifecycle and routes tool calls to
    the appropriate handlers. Handles the async-to-sync bridge
    since the delegate's tool loop is synchronous.
    """

    def __init__(
        self,
        sessions_dir: Path,
        credentials_path: Path,
        event_loop: asyncio.AbstractEventLoop
    ):
        """
        Initialize the browser tool executor.

        Args:
            sessions_dir: Directory for per-service browser session persistence
            credentials_path: Path to the read-only credentials.toml file
            event_loop: Asyncio event loop for running async Playwright calls
        """
        from agency.tools.browser.engine import BrowserEngine

        self._engine = BrowserEngine(sessions_dir=sessions_dir)
        self._credentials_path = credentials_path
        self._loop = event_loop

        self._handlers: Dict[str, Callable] = {
            "navigate": self._exec_navigate,
            "read_page": self._exec_read_page,
            "click": self._exec_click,
            "type": self._exec_type,
            "wait": self._exec_wait,
            "get_credentials": self._exec_get_credentials,
        }

    def execute(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_use_id: str
    ) -> Dict[str, Any]:
        """
        Execute a browser tool call.

        Args:
            tool_name: Name of the tool
            tool_input: Structured input from the model
            tool_use_id: Unique ID for result correlation

        Returns:
            Dict with 'tool_use_id', 'content', and optional 'is_error'
        """
        handler_fn = self._handlers.get(tool_name)
        if not handler_fn:
            log_warning(f"Delegate browser agent called unknown tool: {tool_name}")
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
            log_error(f"Browser tool error ({tool_name}): {e}")
            return {
                "tool_use_id": tool_use_id,
                "content": f"Tool error: {str(e)}",
                "is_error": True
            }

    def _run_async(self, coro):
        """Run an async coroutine synchronously on the event loop."""
        return self._loop.run_until_complete(coro)

    async def close(self):
        """Shut down the browser engine."""
        await self._engine.close()

    # =========================================================================
    # TOOL HANDLERS
    # =========================================================================

    def _exec_navigate(self, input: Dict) -> str:
        """Navigate to a URL."""
        url = input.get("url", "")
        if not url:
            return "Error: No URL provided"

        # Basic URL validation
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        async def _navigate():
            page = await self._engine.get_page()

            # Session loading is handled by get_credentials() — when the agent
            # looks up credentials for a service, the session is auto-loaded.
            # No domain-guessing needed here.

            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                status = response.status if response else "unknown"
                title = await page.title()
                return f"Navigated to: {page.url}\nStatus: {status}\nTitle: {title}"
            except Exception as e:
                return f"Navigation error: {str(e)}\nCurrent URL: {page.url}"

        return self._run_async(_navigate())

    def _exec_read_page(self, input: Dict) -> str:
        """Read the current page content and interactive elements."""
        async def _read():
            from agency.tools.browser.page_reader import read_page
            page = await self._engine.get_page()
            return await read_page(page)

        return self._run_async(_read())

    def _exec_click(self, input: Dict) -> str:
        """Click an element by its numbered ID."""
        element_id = input.get("element_id")
        if element_id is None:
            return "Error: No element_id provided"

        async def _click():
            from agency.tools.browser.page_reader import get_element_handle
            page = await self._engine.get_page()

            element, node_info = await get_element_handle(page, element_id)
            if element is None:
                return (
                    f"Error: Element [{element_id}] not found. "
                    f"Call read_page() to see current elements."
                )

            role = node_info.get("role", "")
            name = node_info.get("name", "")

            try:
                await element.click(timeout=5000)

                # Wait briefly for any navigation or dynamic update
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=3000)
                except Exception:
                    pass  # Page may not navigate — that's fine

                new_url = page.url
                new_title = await page.title()
                return (
                    f"Clicked [{element_id}] {role} \"{name}\"\n"
                    f"Current page: {new_title} ({new_url})"
                )
            except Exception as e:
                return f"Click error on [{element_id}] {role} \"{name}\": {str(e)}"

        return self._run_async(_click())

    def _exec_type(self, input: Dict) -> str:
        """Type text into an input element."""
        element_id = input.get("element_id")
        text = input.get("text", "")
        if element_id is None:
            return "Error: No element_id provided"
        if not text:
            return "Error: No text provided"

        async def _type():
            from agency.tools.browser.page_reader import get_element_handle
            page = await self._engine.get_page()

            element, node_info = await get_element_handle(page, element_id)
            if element is None:
                return (
                    f"Error: Element [{element_id}] not found. "
                    f"Call read_page() to see current elements."
                )

            role = node_info.get("role", "")
            name = node_info.get("name", "")

            try:
                # Clear the field first, then type
                await element.click(timeout=3000)
                await element.fill("")
                await element.fill(text)
                return f"Typed into [{element_id}] {role} \"{name}\": \"{text[:50]}{'...' if len(text) > 50 else ''}\""
            except Exception as e:
                # Fallback: try pressing keys one at a time
                try:
                    await element.click(timeout=3000)
                    # Select all + delete, then type
                    await page.keyboard.press("Control+a")
                    await page.keyboard.press("Delete")
                    await element.type(text)
                    return f"Typed into [{element_id}] {role} \"{name}\": \"{text[:50]}{'...' if len(text) > 50 else ''}\""
                except Exception as e2:
                    return f"Type error on [{element_id}] {role} \"{name}\": {str(e2)}"

        return self._run_async(_type())

    def _exec_wait(self, input: Dict) -> str:
        """Wait for a specified duration."""
        seconds = input.get("seconds", 1)

        # Clamp to reasonable range
        seconds = max(0.5, min(10, float(seconds)))

        async def _wait():
            page = await self._engine.get_page()
            await page.wait_for_timeout(int(seconds * 1000))
            title = await page.title()
            url = page.url
            return f"Waited {seconds}s. Current page: {title} ({url})"

        return self._run_async(_wait())

    def _exec_get_credentials(self, input: Dict) -> str:
        """Look up credentials for a service."""
        service = input.get("service", "")
        if not service:
            return "Error: No service name provided"

        from agency.tools.browser.credentials import get_credential, list_services

        cred = get_credential(self._credentials_path, service)
        if cred is None:
            available = list_services(self._credentials_path)
            if available:
                return (
                    f"No credentials found for '{service}'. "
                    f"Available services: {', '.join(available)}"
                )
            return (
                f"No credentials found for '{service}'. "
                f"The credentials file is empty or missing."
            )

        # Format credential info (password is included intentionally —
        # the delegate needs it for login automation, and the credential
        # stays inside the ephemeral sub-agent context)
        parts = [f"Credentials for '{service}':"]
        for key, value in cred.items():
            parts.append(f"  {key}: {value}")

        # Auto-load session for this service if browser is initialized
        if self._engine.is_initialized:
            try:
                loaded = self._run_async(self._engine.load_session(service))
                if loaded:
                    parts.append(f"\n(Existing browser session loaded for '{service}')")
            except Exception:
                pass

        return "\n".join(parts)
