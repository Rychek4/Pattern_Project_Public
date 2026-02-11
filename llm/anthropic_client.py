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
    error_type: Optional[str] = None  # "overloaded", "rate_limited", "server_error", "auth_error", etc.
    stop_reason: Optional[str] = None
    # Web search fields
    web_searches_used: int = 0
    citations: List[WebSearchCitation] = field(default_factory=list)
    # Web fetch fields
    web_fetches_used: int = 0
    # Native tool use fields
    tool_calls: List[ToolCall] = field(default_factory=list)
    raw_content: List[Any] = field(default_factory=list)  # Original content blocks for continuation
    # Server-side tool details (web_search, web_fetch) for process panel
    server_tool_details: List[Dict[str, Any]] = field(default_factory=list)
    # Extended thinking fields
    thinking_text: str = ""  # Claude's internal reasoning (not shown to user by default)
    # Prompt caching fields
    cache_creation_input_tokens: int = 0  # Tokens written to cache on this request
    cache_read_input_tokens: int = 0      # Tokens read from cache on this request

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
    web_fetches_used: int = 0
    citations: List[WebSearchCitation] = field(default_factory=list)
    # Track partial tool call being built
    _current_tool_id: Optional[str] = None
    _current_tool_name: Optional[str] = None
    _current_tool_input_json: str = ""
    # Server-side tool details (web_search, web_fetch)
    server_tool_details: List[Dict[str, Any]] = field(default_factory=list)
    # Extended thinking
    thinking_text: str = ""  # Accumulated thinking content
    _current_thinking_text: str = ""  # Thinking text for current block
    _current_thinking_signature: str = ""  # Signature for current thinking block
    # Error classification (set when stop_reason == "error")
    _error_type: Optional[str] = None  # "overloaded", "rate_limited", "server_error", etc.
    # Prompt caching
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def to_response(self) -> AnthropicResponse:
        """Convert streaming state to final AnthropicResponse."""
        return AnthropicResponse(
            text=self.text,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            success=True,
            stop_reason=self.stop_reason,
            web_searches_used=self.web_searches_used,
            web_fetches_used=self.web_fetches_used,
            citations=self.citations,
            tool_calls=self.tool_calls,
            raw_content=self.raw_content,
            server_tool_details=self.server_tool_details,
            thinking_text=self.thinking_text,
            cache_creation_input_tokens=self.cache_creation_input_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens
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

    def _classify_error(self, error: Exception) -> tuple:
        """
        Classify an API error for retry/failover decisions.

        Returns:
            Tuple of (error_type, error_message)
        """
        import anthropic

        error_msg = str(error)

        # Check specific anthropic SDK exception types
        if isinstance(error, anthropic.APITimeoutError):
            return ("timeout", "Request timed out")
        elif isinstance(error, anthropic.APIConnectionError):
            return ("connection_error", "Connection failed")
        elif isinstance(error, anthropic.RateLimitError):
            return ("rate_limited", "Rate limit exceeded")
        elif isinstance(error, anthropic.APIStatusError):
            status = error.status_code
            if status == 529:
                return ("overloaded", "API overloaded")
            elif status in (500, 502, 503):
                return ("server_error", f"Server error ({status})")
            elif status in (401, 403):
                return ("auth_error", "Authentication failed")
            elif status == 400:
                if "domains are not accessible" in error_msg:
                    return ("web_fetch_domain_blocked", error_msg)
                return ("bad_request", error_msg)

        # Fallback: check error message text
        error_lower = error_msg.lower()
        if "overloaded" in error_lower:
            return ("overloaded", "API overloaded")
        elif "rate" in error_lower:
            return ("rate_limited", "Rate limit exceeded")
        elif "authentication" in error_lower or "api key" in error_lower:
            return ("auth_error", "Invalid API key")

        return ("unknown", error_msg)

    def _is_transient_error(self, error_type: str) -> bool:
        """Check if an error type is transient (worth retrying same model)."""
        return error_type in ("timeout", "connection_error", "server_error")

    def _get_retry_after(self, error: Exception) -> Optional[float]:
        """Extract retry-after delay from a rate limit error, if available."""
        import anthropic
        if isinstance(error, anthropic.RateLimitError):
            response = getattr(error, 'response', None)
            if response:
                retry_after = response.headers.get('retry-after')
                if retry_after:
                    try:
                        return float(retry_after)
                    except (ValueError, TypeError):
                        pass
            return 5.0  # Default wait for rate limits
        return None

    def _apply_prompt_caching(self, system_prompt: str):
        """
        Convert a flat system prompt string into structured content blocks
        with cache_control markers for Anthropic prompt caching.

        If caching is disabled or no breakpoint delimiter is found, returns
        the original string unchanged (the API accepts both formats).

        Returns:
            str or list[dict]: Original string, or list of content blocks
            with cache_control on the stable portion.
        """
        import config

        if not getattr(config, 'PROMPT_CACHE_ENABLED', False):
            return system_prompt

        breakpoint = getattr(config, 'PROMPT_CACHE_BREAKPOINT', '')
        if not breakpoint or breakpoint not in system_prompt:
            return system_prompt

        # Split at the breakpoint delimiter
        stable_part, dynamic_part = system_prompt.split(breakpoint, 1)
        stable_part = stable_part.strip()
        dynamic_part = dynamic_part.strip()

        blocks = []
        if stable_part:
            blocks.append({
                "type": "text",
                "text": stable_part,
                "cache_control": {"type": "ephemeral"}
            })
        if dynamic_part:
            blocks.append({
                "type": "text",
                "text": dynamic_part
            })

        return blocks if blocks else system_prompt

    def _call_with_retry(self, client, create_kwargs: dict):
        """
        Make a non-streaming API call with automatic retry for transient errors.

        Retries on 500, 502, 503, timeouts, and connection errors with
        exponential backoff. Non-transient errors (overloaded, rate limited,
        auth errors) are raised immediately for higher-level handling.
        """
        import time
        import config as cfg

        max_attempts = getattr(cfg, 'API_RETRY_MAX_ATTEMPTS', 3)
        delay = getattr(cfg, 'API_RETRY_INITIAL_DELAY', 1.0)
        backoff = getattr(cfg, 'API_RETRY_BACKOFF_MULTIPLIER', 2.0)

        for attempt in range(max_attempts):
            try:
                return client.messages.create(**create_kwargs)
            except Exception as e:
                error_type, error_msg = self._classify_error(e)

                # Only retry transient errors, and only if we have attempts left
                if not self._is_transient_error(error_type) or attempt >= max_attempts - 1:
                    raise

                log_warning(
                    f"Transient API error (attempt {attempt + 1}/{max_attempts}): "
                    f"{error_type} - {error_msg}. Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
                delay *= backoff

    def chat(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        stop_sequences: Optional[List[str]] = None,
        enable_web_search: bool = False,
        web_search_max_uses: Optional[int] = None,
        enable_web_fetch: bool = False,
        web_fetch_max_uses: Optional[int] = None,
        web_fetch_config: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        thinking_enabled: bool = False,
        thinking_budget_tokens: Optional[int] = None
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
            enable_web_fetch: Whether to enable Claude's web fetch tool
            web_fetch_max_uses: Max fetches per request (None = no limit)
            web_fetch_config: Optional dict with allowed_domains, blocked_domains,
                max_content_tokens, and citations config
            tools: Optional list of tool definitions for native tool use
            model: Optional model override (uses instance model if None)
            thinking_enabled: Whether to enable extended thinking
            thinking_budget_tokens: Max tokens for thinking (None = use config default)

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

            # Extended thinking configuration
            # Opus 4.6 uses adaptive thinking; Sonnet uses manual budget-based thinking
            if thinking_enabled:
                import config as cfg
                active_model = request_params["model"]
                if active_model.startswith("claude-opus-4-6"):
                    # Opus 4.6: adaptive thinking with effort level
                    request_params["thinking"] = {"type": "adaptive"}
                    effort = getattr(cfg, 'ANTHROPIC_THINKING_EFFORT', 'high')
                    request_params["output_config"] = {"effort": effort}
                    # API requires temperature=1 when thinking is enabled
                    request_params["temperature"] = 1.0
                else:
                    # Sonnet / other models: manual thinking with budget_tokens
                    budget = thinking_budget_tokens or cfg.ANTHROPIC_SONNET_THINKING_BUDGET_TOKENS
                    request_params["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": budget
                    }
                    request_params["temperature"] = 1.0
                    request_params["max_tokens"] = max(
                        request_params["max_tokens"],
                        cfg.ANTHROPIC_SONNET_THINKING_MAX_TOKENS
                    )

            if system_prompt:
                request_params["system"] = self._apply_prompt_caching(system_prompt)

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

            # Add web fetch tool if enabled
            if enable_web_fetch:
                web_fetch_tool = {
                    "type": "web_fetch_20250910",
                    "name": "web_fetch",
                }
                if web_fetch_max_uses is not None:
                    web_fetch_tool["max_uses"] = web_fetch_max_uses
                if web_fetch_config:
                    if web_fetch_config.get("allowed_domains"):
                        web_fetch_tool["allowed_domains"] = web_fetch_config["allowed_domains"]
                    if web_fetch_config.get("blocked_domains"):
                        web_fetch_tool["blocked_domains"] = web_fetch_config["blocked_domains"]
                    if web_fetch_config.get("max_content_tokens"):
                        web_fetch_tool["max_content_tokens"] = web_fetch_config["max_content_tokens"]
                    if web_fetch_config.get("citations"):
                        web_fetch_tool["citations"] = web_fetch_config["citations"]
                all_tools.append(web_fetch_tool)

            if all_tools:
                request_params["tools"] = all_tools

            # Add beta header for web fetch if enabled
            extra_headers = {}
            if enable_web_fetch:
                import config as fetch_cfg
                if fetch_cfg.WEB_FETCH_BETA_HEADER:
                    extra_headers["anthropic-beta"] = "web-fetch-2025-09-10"

            # Make the request (with automatic retry for transient errors)
            create_kwargs = {**request_params}
            if extra_headers:
                create_kwargs["extra_headers"] = extra_headers
            response = self._call_with_retry(client, create_kwargs)

            # Parse response content
            # Note: All iterations use defensive (x or []) pattern to handle None values
            # The hasattr() check alone is insufficient - an attribute can exist but be None
            text = ""
            thinking_text = ""
            web_searches_used = 0
            web_fetches_used = 0
            citations: List[WebSearchCitation] = []
            tool_calls: List[ToolCall] = []
            server_tool_details: List[Dict[str, Any]] = []

            # Safely iterate over response content blocks
            content_blocks = getattr(response, "content", None) or []
            for block in content_blocks:
                block_type = getattr(block, "type", None)

                if block_type == "thinking":
                    # Extended thinking block - capture internal reasoning
                    block_thinking = getattr(block, "thinking", None)
                    if block_thinking:
                        thinking_text += block_thinking
                        log_info(f"Thinking block: {len(block_thinking)} chars", prefix="🧠")
                elif block_type == "redacted_thinking":
                    # Redacted thinking - safety-filtered, preserve for continuations only
                    log_info("Redacted thinking block received", prefix="🧠")
                elif block_type == "text" or hasattr(block, "text"):
                    # Regular text block - safely get text (could be None or empty)
                    block_text = getattr(block, "text", None)
                    if block_text:
                        text += block_text
                elif block_type == "tool_use":
                    tool_name = getattr(block, "name", None)
                    if tool_name == "web_search":
                        # Claude invoked web search (built-in tool)
                        web_searches_used += 1
                        tool_input = getattr(block, "input", {}) or {}
                        server_tool_details.append({"name": "web_search", "input": tool_input})
                        log_info(f"Web search invoked ({web_searches_used})", prefix="🔍")
                    elif tool_name == "web_fetch":
                        # Claude invoked web fetch (built-in tool)
                        web_fetches_used += 1
                        tool_input = getattr(block, "input", {}) or {}
                        server_tool_details.append({"name": "web_fetch", "input": tool_input})
                        log_info(f"Web fetch invoked ({web_fetches_used})", prefix="🌐")
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
                block_type_str = getattr(block, "type", None)
                if block_type_str in ("web_search_tool_result", "web_fetch_tool_result"):
                    # Extract citations from search/fetch results
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
            # This preserves the original structure for tool_result messages.
            # Thinking and redacted_thinking blocks MUST be preserved for
            # multi-turn continuations (API requirement).
            raw_content_list = []
            for block in content_blocks:
                block_type = getattr(block, "type", None)

                if block_type == "thinking":
                    raw_content_list.append({
                        "type": "thinking",
                        "thinking": getattr(block, "thinking", ""),
                        "signature": getattr(block, "signature", "")
                    })
                elif block_type == "redacted_thinking":
                    raw_content_list.append({
                        "type": "redacted_thinking",
                        "data": getattr(block, "data", "")
                    })
                elif block_type == "text" or hasattr(block, "text"):
                    raw_content_list.append({"type": "text", "text": getattr(block, "text", "")})
                elif block_type == "tool_use":
                    raw_content_list.append({
                        "type": "tool_use",
                        "id": getattr(block, "id", ""),
                        "name": getattr(block, "name", ""),
                        "input": getattr(block, "input", {})
                    })
                elif block_type in ("web_search_tool_result", "web_fetch_tool_result"):
                    # Preserve server tool results for continuation context
                    raw_content_list.append({
                        "type": block_type,
                        "tool_use_id": getattr(block, "tool_use_id", ""),
                        "content": getattr(block, "content", [])
                    })
                elif block_type == "server_tool_use":
                    # Preserve server tool use blocks (web search/fetch invocations)
                    raw_content_list.append({
                        "type": "server_tool_use",
                        "id": getattr(block, "id", ""),
                        "name": getattr(block, "name", ""),
                        "input": getattr(block, "input", {})
                    })

            # Extract prompt caching metrics from usage
            cache_creation = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
            if cache_read > 0:
                log_info(f"Prompt cache HIT: {cache_read} tokens read from cache", prefix="[Cache]")
            elif cache_creation > 0:
                log_info(f"Prompt cache WRITE: {cache_creation} tokens written to cache", prefix="[Cache]")

            return AnthropicResponse(
                text=text,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                success=True,
                stop_reason=response.stop_reason,
                web_searches_used=web_searches_used,
                web_fetches_used=web_fetches_used,
                citations=citations,
                tool_calls=tool_calls,
                raw_content=raw_content_list,
                server_tool_details=server_tool_details,
                thinking_text=thinking_text,
                cache_creation_input_tokens=cache_creation,
                cache_read_input_tokens=cache_read
            )

        except Exception as e:
            error_type, error_msg = self._classify_error(e)

            return AnthropicResponse(
                text="",
                input_tokens=0,
                output_tokens=0,
                success=False,
                error=error_msg,
                error_type=error_type
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
        enable_web_fetch: bool = False,
        web_fetch_max_uses: Optional[int] = None,
        web_fetch_config: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        thinking_enabled: bool = False,
        thinking_budget_tokens: Optional[int] = None
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

            # Extended thinking configuration
            # Opus 4.6 uses adaptive thinking; Sonnet uses manual budget-based thinking
            if thinking_enabled:
                import config as cfg
                active_model = request_params["model"]
                if active_model.startswith("claude-opus-4-6"):
                    # Opus 4.6: adaptive thinking with effort level
                    request_params["thinking"] = {"type": "adaptive"}
                    effort = getattr(cfg, 'ANTHROPIC_THINKING_EFFORT', 'high')
                    request_params["output_config"] = {"effort": effort}
                    request_params["temperature"] = 1.0
                else:
                    # Sonnet / other models: manual thinking with budget_tokens
                    budget = thinking_budget_tokens or cfg.ANTHROPIC_SONNET_THINKING_BUDGET_TOKENS
                    request_params["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": budget
                    }
                    request_params["temperature"] = 1.0
                    request_params["max_tokens"] = max(
                        request_params["max_tokens"],
                        cfg.ANTHROPIC_SONNET_THINKING_MAX_TOKENS
                    )

            if system_prompt:
                request_params["system"] = self._apply_prompt_caching(system_prompt)

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

            # Add web fetch tool if enabled
            if enable_web_fetch:
                web_fetch_tool = {
                    "type": "web_fetch_20250910",
                    "name": "web_fetch",
                }
                if web_fetch_max_uses is not None:
                    web_fetch_tool["max_uses"] = web_fetch_max_uses
                if web_fetch_config:
                    if web_fetch_config.get("allowed_domains"):
                        web_fetch_tool["allowed_domains"] = web_fetch_config["allowed_domains"]
                    if web_fetch_config.get("blocked_domains"):
                        web_fetch_tool["blocked_domains"] = web_fetch_config["blocked_domains"]
                    if web_fetch_config.get("max_content_tokens"):
                        web_fetch_tool["max_content_tokens"] = web_fetch_config["max_content_tokens"]
                    if web_fetch_config.get("citations"):
                        web_fetch_tool["citations"] = web_fetch_config["citations"]
                all_tools.append(web_fetch_tool)

            if all_tools:
                request_params["tools"] = all_tools

            # Add beta header for web fetch if enabled
            extra_headers = {}
            if enable_web_fetch:
                import config as fetch_cfg
                if fetch_cfg.WEB_FETCH_BETA_HEADER:
                    extra_headers["anthropic-beta"] = "web-fetch-2025-09-10"

            # Initialize streaming state
            state = StreamingState()

            # DIAGNOSTIC: Track chunks yielded to detect tool-only responses
            text_chunks_yielded = 0

            # Use the streaming API
            stream_kwargs = {**request_params}
            if extra_headers:
                stream_kwargs["extra_headers"] = extra_headers
            with client.messages.stream(**stream_kwargs) as stream:
                current_block_type = None
                current_block_index = -1

                for event in stream:
                    event_type = getattr(event, "type", None)

                    # DIAGNOSTIC: Log every SSE event to trace streaming behavior
                    if event_type == "content_block_start":
                        content_block = getattr(event, "content_block", None)
                        block_type = getattr(content_block, "type", None) if content_block else None
                        log_info(f"SSE content_block_start: type={block_type}", prefix="📡")
                    elif event_type == "content_block_stop":
                        log_info(f"SSE content_block_stop: was_type={current_block_type}", prefix="📡")
                    elif event_type == "message_delta":
                        delta = getattr(event, "delta", None)
                        stop_reason = getattr(delta, "stop_reason", None) if delta else None
                        if stop_reason:
                            log_info(f"SSE message_delta: stop_reason={stop_reason}", prefix="📡")
                    elif event_type == "message_stop":
                        log_info(f"SSE message_stop: text_chunks_yielded={text_chunks_yielded}, tool_calls={len(state.tool_calls)}", prefix="📡")

                    if event_type == "message_start":
                        # Extract input token count and cache metrics from message start
                        message = getattr(event, "message", None)
                        if message:
                            usage = getattr(message, "usage", None)
                            if usage:
                                state.input_tokens = getattr(usage, "input_tokens", 0)
                                state.cache_creation_input_tokens = getattr(usage, "cache_creation_input_tokens", 0) or 0
                                state.cache_read_input_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0

                    elif event_type == "content_block_start":
                        # New content block starting
                        content_block = getattr(event, "content_block", None)
                        current_block_index = getattr(event, "index", -1)

                        if content_block:
                            block_type = getattr(content_block, "type", None)
                            current_block_type = block_type

                            if block_type == "thinking":
                                # Starting a thinking block - reset current thinking state
                                state._current_thinking_text = ""
                                state._current_thinking_signature = ""
                                log_info("Thinking block started", prefix="🧠")

                            elif block_type == "tool_use":
                                # Starting a tool call
                                state._current_tool_id = getattr(content_block, "id", "")
                                state._current_tool_name = getattr(content_block, "name", "")
                                state._current_tool_input_json = ""

                                if state._current_tool_name == "web_search":
                                    state.web_searches_used += 1
                                    log_info(f"Web search invoked ({state.web_searches_used})", prefix="🔍")
                                elif state._current_tool_name == "web_fetch":
                                    state.web_fetches_used += 1
                                    log_info(f"Web fetch invoked ({state.web_fetches_used})", prefix="🌐")

                            elif block_type == "server_tool_use":
                                # Server-side tool call (web_search, web_fetch)
                                state._current_tool_id = getattr(content_block, "id", "")
                                state._current_tool_name = getattr(content_block, "name", "")
                                state._current_tool_input_json = ""

                                if state._current_tool_name == "web_search":
                                    state.web_searches_used += 1
                                    log_info(f"Server web search invoked ({state.web_searches_used})", prefix="🔍")
                                elif state._current_tool_name == "web_fetch":
                                    state.web_fetches_used += 1
                                    log_info(f"Server web fetch invoked ({state.web_fetches_used})", prefix="🌐")

                            elif block_type in ("web_search_tool_result", "web_fetch_tool_result"):
                                # Server tool results arrive atomically - store for processing at block stop
                                state._current_server_result = content_block

                    elif event_type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta:
                            delta_type = getattr(delta, "type", None)

                            if delta_type == "thinking_delta":
                                # Thinking content chunk
                                thinking_chunk = getattr(delta, "thinking", "")
                                if thinking_chunk:
                                    state._current_thinking_text += thinking_chunk
                                    state.thinking_text += thinking_chunk

                            elif delta_type == "signature_delta":
                                # Thinking block signature (required for continuations)
                                signature = getattr(delta, "signature", "")
                                if signature:
                                    state._current_thinking_signature = signature

                            elif delta_type == "text_delta":
                                # Text chunk arrived
                                text_chunk = getattr(delta, "text", "")
                                if text_chunk:
                                    state.text += text_chunk
                                    text_chunks_yielded += 1
                                    yield (text_chunk, state)

                            elif delta_type == "input_json_delta":
                                # Tool input JSON chunk
                                partial_json = getattr(delta, "partial_json", "")
                                if partial_json:
                                    state._current_tool_input_json += partial_json

                    elif event_type == "content_block_stop":
                        # Content block finished
                        if current_block_type == "thinking":
                            # Finalize thinking block - add to raw_content for continuations
                            log_info(f"Thinking block complete: {len(state._current_thinking_text)} chars", prefix="🧠")
                            state.raw_content.append({
                                "type": "thinking",
                                "thinking": state._current_thinking_text,
                                "signature": state._current_thinking_signature
                            })
                            state._current_thinking_text = ""
                            state._current_thinking_signature = ""

                        elif current_block_type == "redacted_thinking":
                            # Redacted thinking - preserve for continuations
                            log_info("Redacted thinking block complete", prefix="🧠")
                            content_block = getattr(event, "content_block", None)
                            state.raw_content.append({
                                "type": "redacted_thinking",
                                "data": getattr(content_block, "data", "") if content_block else ""
                            })

                        elif current_block_type == "tool_use" and state._current_tool_name:
                            # Finalize the tool call
                            tool_input = {}
                            if state._current_tool_input_json:
                                try:
                                    tool_input = json.loads(state._current_tool_input_json)
                                except json.JSONDecodeError:
                                    log_error(f"Failed to parse tool input JSON", prefix="[Stream]")

                            if state._current_tool_name not in ("web_search", "web_fetch"):
                                state.tool_calls.append(ToolCall(
                                    id=state._current_tool_id or "",
                                    name=state._current_tool_name,
                                    input=tool_input
                                ))
                                log_info(f"Tool call: {state._current_tool_name}", prefix="🔧")
                            else:
                                # Track server-side tool details for process panel
                                state.server_tool_details.append({
                                    "name": state._current_tool_name,
                                    "input": tool_input
                                })

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

                        elif current_block_type == "server_tool_use" and state._current_tool_name:
                            # Finalize server-side tool call
                            tool_input = {}
                            if state._current_tool_input_json:
                                try:
                                    tool_input = json.loads(state._current_tool_input_json)
                                except json.JSONDecodeError:
                                    log_error(f"Failed to parse server tool input JSON", prefix="[Stream]")

                            state.server_tool_details.append({
                                "name": state._current_tool_name,
                                "input": tool_input
                            })

                            # Add to raw_content as server_tool_use (not tool_use)
                            state.raw_content.append({
                                "type": "server_tool_use",
                                "id": state._current_tool_id or "",
                                "name": state._current_tool_name,
                                "input": tool_input
                            })

                            # Reset tool tracking
                            state._current_tool_id = None
                            state._current_tool_name = None
                            state._current_tool_input_json = ""

                        elif current_block_type in ("web_search_tool_result", "web_fetch_tool_result"):
                            # Finalize server tool result block
                            result_block = getattr(state, '_current_server_result', None)
                            if result_block:
                                block_content = getattr(result_block, "content", None) or []
                                state.raw_content.append({
                                    "type": current_block_type,
                                    "tool_use_id": getattr(result_block, "tool_use_id", ""),
                                    "content": block_content
                                })
                                state._current_server_result = None

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

            # ============================================================
            # CRITICAL FIX: Always yield final state after stream completes
            # ============================================================
            # The streaming loop above only yields on text_delta events.
            # When Claude responds with tool calls (with or without text),
            # the generator may yield 0 chunks if tools come before text.
            # This leaves the caller with final_state=None, breaking the flow.
            #
            # By always yielding the final state here, we guarantee:
            # 1. Tool-only responses are properly returned
            # 2. Tool calls accumulated in state.tool_calls are accessible
            # 3. The stop_reason and token counts are available
            # 4. The caller's final_state is NEVER None for successful streams
            # ============================================================
            if text_chunks_yielded == 0:
                log_info(f"STREAMING FIX: No text chunks yielded, but stream completed. "
                         f"Tool calls: {len(state.tool_calls)}, text_len: {len(state.text)}, "
                         f"stop_reason: {state.stop_reason}", prefix="📡")

            # Log prompt cache metrics
            if state.cache_read_input_tokens > 0:
                log_info(f"Prompt cache HIT: {state.cache_read_input_tokens} tokens read from cache", prefix="[Cache]")
            elif state.cache_creation_input_tokens > 0:
                log_info(f"Prompt cache WRITE: {state.cache_creation_input_tokens} tokens written to cache", prefix="[Cache]")

            log_info(f"STREAMING FIX: Yielding final state (text_chunks_yielded={text_chunks_yielded}, "
                     f"tool_calls={len(state.tool_calls)}, stop_reason={state.stop_reason})", prefix="📡")
            yield ("", state)

        except Exception as e:
            import traceback
            full_traceback = traceback.format_exc()

            # Classify the error for upstream retry/failover decisions
            error_type, error_msg = self._classify_error(e)

            # DIAGNOSTIC: Log full exception details
            log_error(f"Streaming error ({error_type}): {error_msg}", prefix="[Stream]")
            log_error(f"Exception type: {type(e).__name__}", prefix="[Stream]")
            log_error(f"Full traceback:\n{full_traceback}", prefix="[Stream]")

            # Yield error state with classification
            error_state = StreamingState()
            error_state.stop_reason = "error"
            error_state._error_message = error_msg
            error_state._error_type = error_type
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
