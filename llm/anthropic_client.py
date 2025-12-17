"""
Pattern Project - Anthropic Claude Client
Client for Claude API (frontier reasoning)
"""

from typing import Optional, List, Dict, Any, Generator, Iterator
from dataclasses import dataclass, field

from core.logger import log_info, log_error, log_success


@dataclass
class WebSearchCitation:
    """A citation from web search results."""
    cited_text: str
    title: str
    url: str


@dataclass
class ToolCall:
    """A tool call from Claude's response."""
    id: str
    name: str
    input: Dict[str, Any]


@dataclass
class AnthropicResponse:
    """Response from Anthropic API."""
    text: str
    input_tokens: int
    output_tokens: int
    success: bool
    error: Optional[str] = None
    stop_reason: Optional[str] = None
    # Web search fields
    web_searches_used: int = 0
    citations: List[WebSearchCitation] = field(default_factory=list)
    # Native tool use fields
    tool_calls: List[ToolCall] = field(default_factory=list)
    raw_content: List[Any] = field(default_factory=list)  # Original content blocks for continuation

    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls (excluding web_search)."""
        return len(self.tool_calls) > 0


@dataclass
class StreamingState:
    """Tracks state during streaming response."""
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: List[ToolCall] = field(default_factory=list)
    raw_content: List[Any] = field(default_factory=list)
    stop_reason: Optional[str] = None
    web_searches_used: int = 0
    citations: List[WebSearchCitation] = field(default_factory=list)
    # Track partial tool call being built
    _current_tool_id: Optional[str] = None
    _current_tool_name: Optional[str] = None
    _current_tool_input_json: str = ""

    def to_response(self) -> AnthropicResponse:
        """Convert streaming state to final AnthropicResponse."""
        return AnthropicResponse(
            text=self.text,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            success=True,
            stop_reason=self.stop_reason,
            web_searches_used=self.web_searches_used,
            citations=self.citations,
            tool_calls=self.tool_calls,
            raw_content=self.raw_content
        )

    def has_tool_calls(self) -> bool:
        """Check if any tool calls have been collected."""
        return len(self.tool_calls) > 0


class AnthropicClient:
    """
    Client for Anthropic Claude API.

    Provides access to Claude models for high-quality reasoning
    and conversation.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5-20250929",
        max_tokens: int = 4096,
        timeout: int = 120
    ):
        """
        Initialize the Anthropic client.

        Args:
            api_key: Anthropic API key
            model: Model to use
            max_tokens: Maximum tokens to generate
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client = None

    def _get_client(self):
        """Lazy-load the Anthropic client."""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(
                    api_key=self.api_key,
                    timeout=self.timeout
                )
            except ImportError:
                raise ImportError("anthropic package not installed. Run: pip install anthropic")
        return self._client

    def is_available(self) -> bool:
        """Check if Anthropic API is configured and accessible."""
        if not self.api_key:
            return False
        try:
            # Just check if we can create a client
            self._get_client()
            return True
        except Exception:
            return False

    def chat(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        stop_sequences: Optional[List[str]] = None,
        enable_web_search: bool = False,
        web_search_max_uses: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None
    ) -> AnthropicResponse:
        """
        Send a chat completion request.

        Supports both text-only and multimodal messages.

        Text-only message format:
            {"role": "user", "content": "Hello"}

        Multimodal message format (with images):
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "..."}},
                    {"type": "text", "text": "What's in this image?"}
                ]
            }

        Args:
            messages: List of message dicts. Content can be string or content array.
            system_prompt: Optional system prompt
            max_tokens: Maximum tokens to generate (uses default if None)
            temperature: Sampling temperature
            stop_sequences: Optional list of stop sequences
            enable_web_search: Whether to enable Claude's web search tool
            web_search_max_uses: Max searches per request (None = no limit)
            tools: Optional list of tool definitions for native tool use
            model: Optional model override (uses instance model if None)

        Returns:
            AnthropicResponse with generated text and any tool calls
        """
        if max_tokens is None:
            max_tokens = self.max_tokens

        try:
            client = self._get_client()

            # Build request parameters
            # Use model override if provided, otherwise fall back to instance model
            request_params = {
                "model": model or self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages
            }

            if system_prompt:
                request_params["system"] = system_prompt

            if stop_sequences:
                request_params["stop_sequences"] = stop_sequences

            # Build tools list (combine native tools with web search if both enabled)
            all_tools = []

            # Add native tools if provided
            if tools:
                all_tools.extend(tools)

            # Add web search tool if enabled
            if enable_web_search:
                web_search_tool = {
                    "type": "web_search_20250305",
                    "name": "web_search",
                }
                if web_search_max_uses is not None:
                    web_search_tool["max_uses"] = web_search_max_uses
                all_tools.append(web_search_tool)

            if all_tools:
                request_params["tools"] = all_tools

            # Make the request
            response = client.messages.create(**request_params)

            # Parse response content
            # Note: All iterations use defensive (x or []) pattern to handle None values
            # The hasattr() check alone is insufficient - an attribute can exist but be None
            text = ""
            web_searches_used = 0
            citations: List[WebSearchCitation] = []
            tool_calls: List[ToolCall] = []

            # Safely iterate over response content blocks
            content_blocks = getattr(response, "content", None) or []
            for block in content_blocks:
                if hasattr(block, "text"):
                    # Regular text block - safely get text (could be None or empty)
                    block_text = getattr(block, "text", None)
                    if block_text:
                        text += block_text
                elif hasattr(block, "type") and block.type == "tool_use":
                    tool_name = getattr(block, "name", None)
                    if tool_name == "web_search":
                        # Claude invoked web search (built-in tool)
                        web_searches_used += 1
                        log_info(f"Web search invoked ({web_searches_used})", prefix="🔍")
                    else:
                        # Native tool call - capture it
                        tool_calls.append(ToolCall(
                            id=getattr(block, "id", ""),
                            name=tool_name or "",
                            input=getattr(block, "input", {}) or {}
                        ))
                        log_info(f"Tool call: {tool_name}", prefix="🔧")

            # Extract citations from the response if present
            # Citations appear in server_tool_use blocks or as part of the response metadata
            for block in content_blocks:
                if hasattr(block, "type") and block.type == "web_search_tool_result":
                    # Extract citations from search results
                    # Safely get block.content - could be None even if attribute exists
                    block_content = getattr(block, "content", None) or []
                    for result_block in block_content:
                        # Safely get citations - could be None even if attribute exists
                        result_citations = getattr(result_block, "citations", None) or []
                        for citation in result_citations:
                            citations.append(WebSearchCitation(
                                cited_text=getattr(citation, "cited_text", ""),
                                title=getattr(citation, "title", ""),
                                url=getattr(citation, "url", "")
                            ))
                # Also check for citations in text blocks
                # Safely get block.citations - could be None even if attribute exists
                block_citations = getattr(block, "citations", None) or []
                for citation in block_citations:
                    citations.append(WebSearchCitation(
                        cited_text=getattr(citation, "cited_text", ""),
                        title=getattr(citation, "title", ""),
                        url=getattr(citation, "url", "")
                    ))

            # Build raw_content for continuation (serialize content blocks)
            # This preserves the original structure for tool_result messages
            raw_content_list = []
            for block in content_blocks:
                if hasattr(block, "text"):
                    raw_content_list.append({"type": "text", "text": getattr(block, "text", "")})
                elif hasattr(block, "type") and block.type == "tool_use":
                    raw_content_list.append({
                        "type": "tool_use",
                        "id": getattr(block, "id", ""),
                        "name": getattr(block, "name", ""),
                        "input": getattr(block, "input", {})
                    })

            return AnthropicResponse(
                text=text,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                success=True,
                stop_reason=response.stop_reason,
                web_searches_used=web_searches_used,
                citations=citations,
                tool_calls=tool_calls,
                raw_content=raw_content_list
            )

        except Exception as e:
            error_msg = str(e)

            # Handle specific error types
            if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
                error_msg = "Invalid API key"
            elif "rate" in error_msg.lower():
                error_msg = "Rate limit exceeded"
            elif "overloaded" in error_msg.lower():
                error_msg = "API overloaded, try again later"

            return AnthropicResponse(
                text="",
                input_tokens=0,
                output_tokens=0,
                success=False,
                error=error_msg
            )

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        stop_sequences: Optional[List[str]] = None,
        enable_web_search: bool = False,
        web_search_max_uses: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None
    ) -> Generator[tuple[str, StreamingState], None, None]:
        """
        Stream a chat completion request, yielding text chunks as they arrive.

        Yields:
            Tuple of (text_chunk, streaming_state) for each text delta.
            The streaming_state accumulates the full response and tool calls.

        The final StreamingState can be converted to AnthropicResponse via .to_response()
        """
        import json

        if max_tokens is None:
            max_tokens = self.max_tokens

        try:
            client = self._get_client()

            # Build request parameters (same as chat())
            request_params = {
                "model": model or self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages
            }

            if system_prompt:
                request_params["system"] = system_prompt

            if stop_sequences:
                request_params["stop_sequences"] = stop_sequences

            # Build tools list
            all_tools = []
            if tools:
                all_tools.extend(tools)

            if enable_web_search:
                web_search_tool = {
                    "type": "web_search_20250305",
                    "name": "web_search",
                }
                if web_search_max_uses is not None:
                    web_search_tool["max_uses"] = web_search_max_uses
                all_tools.append(web_search_tool)

            if all_tools:
                request_params["tools"] = all_tools

            # Initialize streaming state
            state = StreamingState()

            # Use the streaming API
            with client.messages.stream(**request_params) as stream:
                current_block_type = None
                current_block_index = -1

                for event in stream:
                    event_type = getattr(event, "type", None)

                    if event_type == "message_start":
                        # Extract input token count from message start
                        message = getattr(event, "message", None)
                        if message:
                            usage = getattr(message, "usage", None)
                            if usage:
                                state.input_tokens = getattr(usage, "input_tokens", 0)

                    elif event_type == "content_block_start":
                        # New content block starting
                        content_block = getattr(event, "content_block", None)
                        current_block_index = getattr(event, "index", -1)

                        if content_block:
                            block_type = getattr(content_block, "type", None)
                            current_block_type = block_type

                            if block_type == "tool_use":
                                # Starting a tool call
                                state._current_tool_id = getattr(content_block, "id", "")
                                state._current_tool_name = getattr(content_block, "name", "")
                                state._current_tool_input_json = ""

                                if state._current_tool_name == "web_search":
                                    state.web_searches_used += 1
                                    log_info(f"Web search invoked ({state.web_searches_used})", prefix="🔍")

                    elif event_type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta:
                            delta_type = getattr(delta, "type", None)

                            if delta_type == "text_delta":
                                # Text chunk arrived
                                text_chunk = getattr(delta, "text", "")
                                if text_chunk:
                                    state.text += text_chunk
                                    yield (text_chunk, state)

                            elif delta_type == "input_json_delta":
                                # Tool input JSON chunk
                                partial_json = getattr(delta, "partial_json", "")
                                if partial_json:
                                    state._current_tool_input_json += partial_json

                    elif event_type == "content_block_stop":
                        # Content block finished
                        if current_block_type == "tool_use" and state._current_tool_name:
                            # Finalize the tool call
                            tool_input = {}
                            if state._current_tool_input_json:
                                try:
                                    tool_input = json.loads(state._current_tool_input_json)
                                except json.JSONDecodeError:
                                    log_error(f"Failed to parse tool input JSON", prefix="[Stream]")

                            if state._current_tool_name != "web_search":
                                state.tool_calls.append(ToolCall(
                                    id=state._current_tool_id or "",
                                    name=state._current_tool_name,
                                    input=tool_input
                                ))
                                log_info(f"Tool call: {state._current_tool_name}", prefix="🔧")

                            # Add to raw_content
                            state.raw_content.append({
                                "type": "tool_use",
                                "id": state._current_tool_id or "",
                                "name": state._current_tool_name,
                                "input": tool_input
                            })

                            # Reset tool tracking
                            state._current_tool_id = None
                            state._current_tool_name = None
                            state._current_tool_input_json = ""

                        elif current_block_type == "text":
                            # Add text block to raw_content
                            state.raw_content.append({
                                "type": "text",
                                "text": state.text
                            })

                        current_block_type = None

                    elif event_type == "message_delta":
                        # Message-level updates (stop reason, output tokens)
                        delta = getattr(event, "delta", None)
                        if delta:
                            state.stop_reason = getattr(delta, "stop_reason", None)

                        usage = getattr(event, "usage", None)
                        if usage:
                            state.output_tokens = getattr(usage, "output_tokens", 0)

                    elif event_type == "message_stop":
                        # Stream complete
                        pass

        except Exception as e:
            error_msg = str(e)
            log_error(f"Streaming error: {error_msg}", prefix="[Stream]")

            # Handle specific error types
            if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
                error_msg = "Invalid API key"
            elif "rate" in error_msg.lower():
                error_msg = "Rate limit exceeded"
            elif "overloaded" in error_msg.lower():
                error_msg = "API overloaded, try again later"

            # Yield error state
            error_state = StreamingState()
            error_state.stop_reason = "error"
            yield ("", error_state)

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7
    ) -> AnthropicResponse:
        """
        Simple text generation from a prompt.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            AnthropicResponse with generated text
        """
        messages = [{"role": "user", "content": prompt}]
        return self.chat(
            messages=messages,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature
        )

    def validate_connection(self) -> tuple[bool, str]:
        """
        Validate the API connection.

        Returns:
            Tuple of (is_valid, status_message)
        """
        if not self.api_key:
            return False, "API key not configured"

        try:
            # Make a minimal request to validate
            response = self.generate(
                prompt="Say 'OK' and nothing else.",
                max_tokens=10,
                temperature=0
            )

            if response.success:
                return True, f"Connected to Anthropic API ({self.model})"
            else:
                return False, f"API error: {response.error}"

        except Exception as e:
            return False, f"Connection error: {e}"


# Global client instance
_anthropic_client: Optional[AnthropicClient] = None


def get_anthropic_client() -> AnthropicClient:
    """Get the global Anthropic client instance."""
    global _anthropic_client
    if _anthropic_client is None:
        from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, ANTHROPIC_MAX_TOKENS
        _anthropic_client = AnthropicClient(
            api_key=ANTHROPIC_API_KEY,
            model=ANTHROPIC_MODEL,
            max_tokens=ANTHROPIC_MAX_TOKENS
        )
    return _anthropic_client


def init_anthropic_client(
    api_key: str,
    model: str = "claude-sonnet-4-5-20250929",
    max_tokens: int = 4096
) -> AnthropicClient:
    """Initialize the global Anthropic client."""
    global _anthropic_client
    _anthropic_client = AnthropicClient(
        api_key=api_key,
        model=model,
        max_tokens=max_tokens
    )
    return _anthropic_client
