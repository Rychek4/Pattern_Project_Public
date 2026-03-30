"""
Pattern Project - OpenRouter Client (OpenAI-compatible)
Client for non-Anthropic models via OpenRouter's OpenAI-compatible API.

Use this for free or low-cost models (Llama, Gemini Flash, Mistral, etc.)
that don't speak the Anthropic SDK format.

Anthropic-specific features NOT supported here:
  - Extended thinking
  - Prompt caching (cache_control)
  - Native web_search / web_fetch server tools
  - Streaming (stub only — add if needed)

Intended task types: EXTRACTION, DELEGATION, SIMPLE, ANALYSIS
NOT intended for: CONVERSATION, PULSE_REFLECTIVE, PULSE_ACTION (use AnthropicClient)
"""

from typing import Optional, List, Dict, Any, Generator
from dataclasses import dataclass, field

from core.logger import log_info, log_error, log_warning

# Re-use the shared response/state types from the Anthropic client
# so the router can treat both clients uniformly.
from llm.anthropic_client import AnthropicResponse, ToolCall, StreamingState, WebSearchCitation


class OpenRouterClient:
    """
    Client for OpenRouter's OpenAI-compatible API.

    Supports any model available on OpenRouter that uses the OpenAI
    chat completions format (most non-Anthropic models).

    Example free models:
        meta-llama/llama-3.1-8b-instruct:free
        google/gemini-flash-1.5-8b:free
        mistralai/mistral-7b-instruct:free
        microsoft/phi-3-mini-128k-instruct:free

    See https://openrouter.ai/models?q=:free for the full list.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "meta-llama/llama-3.1-8b-instruct:free",
        max_tokens: int = 4096,
        timeout: int = 120
    ):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client = None

    def _get_client(self):
        """Lazy-load the OpenAI-compatible client pointed at OpenRouter."""
        if self._client is None:
            try:
                from openai import OpenAI
                import config as _cfg
                base_url = getattr(_cfg, 'OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
                self._client = OpenAI(
                    api_key=self.api_key,
                    base_url=base_url,
                    timeout=self.timeout
                )
            except ImportError:
                raise ImportError(
                    "openai package not installed. Run: pip install openai"
                )
        return self._client

    def is_available(self) -> bool:
        """Check if the client is configured and can reach OpenRouter."""
        if not self.api_key:
            return False
        try:
            self._get_client()
            return True
        except Exception:
            return False

    def _classify_error(self, error: Exception) -> tuple:
        """
        Classify an OpenAI SDK error for retry/failover decisions.

        Returns:
            Tuple of (error_type, error_message)
        """
        try:
            import openai
            error_msg = str(error)

            if isinstance(error, openai.APITimeoutError):
                return ("timeout", "Request timed out")
            elif isinstance(error, openai.APIConnectionError):
                return ("connection_error", "Connection failed")
            elif isinstance(error, openai.RateLimitError):
                return ("rate_limited", "Rate limit exceeded")
            elif isinstance(error, openai.APIStatusError):
                status = error.status_code
                if status == 529:
                    return ("overloaded", "API overloaded")
                elif status in (500, 502, 503):
                    return ("server_error", f"Server error ({status})")
                elif status in (401, 403):
                    return ("auth_error", "Authentication failed")
                elif status == 400:
                    return ("bad_request", error_msg)

            # Fallback: check error message text
            error_lower = error_msg.lower()
            if "overloaded" in error_lower:
                return ("overloaded", "API overloaded")
            elif "rate" in error_lower:
                return ("rate_limited", "Rate limit exceeded")
            elif "internal server error" in error_lower:
                return ("server_error", "Internal server error")
            elif "authentication" in error_lower or "api key" in error_lower:
                return ("auth_error", "Invalid API key")

            return ("unknown", error_msg)

        except ImportError:
            return ("unknown", str(error))

    def _is_transient_error(self, error_type: str) -> bool:
        """Check if an error type is transient (worth retrying)."""
        return error_type in ("timeout", "connection_error", "server_error")

    def chat(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        stop_sequences: Optional[List[str]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        # The following are Anthropic-only — accepted but silently ignored
        enable_web_search: bool = False,
        web_search_max_uses: Optional[int] = None,
        enable_web_fetch: bool = False,
        web_fetch_max_uses: Optional[int] = None,
        web_fetch_config: Optional[Dict[str, Any]] = None,
        thinking_enabled: bool = False,
        thinking_budget_tokens: Optional[int] = None
    ) -> AnthropicResponse:
        """
        Send a chat completion request via OpenRouter's OpenAI-compatible API.

        Returns an AnthropicResponse so the router can treat this client
        identically to AnthropicClient.

        Note: enable_web_search, enable_web_fetch, thinking_enabled, and
        thinking_budget_tokens are accepted for interface compatibility but
        are not supported by non-Anthropic models and will be ignored.
        """
        if max_tokens is None:
            max_tokens = self.max_tokens

        import time
        import config as cfg

        max_attempts = getattr(cfg, 'API_RETRY_MAX_ATTEMPTS', 3)
        delay = getattr(cfg, 'API_RETRY_INITIAL_DELAY', 1.0)
        backoff = getattr(cfg, 'API_RETRY_BACKOFF_MULTIPLIER', 2.0)

        # Warn if caller is expecting Anthropic-only features
        if thinking_enabled:
            log_warning(
                "thinking_enabled=True ignored — not supported by OpenRouterClient",
                prefix="[OpenRouter]"
            )
        if enable_web_search:
            log_warning(
                "enable_web_search=True ignored — not supported by OpenRouterClient",
                prefix="[OpenRouter]"
            )
        if enable_web_fetch:
            log_warning(
                "enable_web_fetch=True ignored — not supported by OpenRouterClient",
                prefix="[OpenRouter]"
            )

        try:
            client = self._get_client()
            active_model = model or self.model

            # Build messages: prepend system prompt as a system message
            # (OpenAI format uses messages array, not a separate system param)
            full_messages = []
            if system_prompt:
                full_messages.append({"role": "system", "content": system_prompt})
            full_messages.extend(messages)

            request_params = {
                "model": active_model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": full_messages,
            }

            if stop_sequences:
                request_params["stop"] = stop_sequences

            # Tools use OpenAI function-calling format
            if tools:
                request_params["tools"] = tools

            # Retry loop for transient errors
            last_error = None
            for attempt in range(max_attempts):
                try:
                    response = client.chat.completions.create(**request_params)
                    break
                except Exception as e:
                    error_type, error_msg = self._classify_error(e)
                    last_error = (error_type, error_msg, e)

                    if not self._is_transient_error(error_type) or attempt >= max_attempts - 1:
                        raise

                    log_warning(
                        f"Transient OpenRouter error (attempt {attempt + 1}/{max_attempts}): "
                        f"{error_type} - {error_msg}. Retrying in {delay:.1f}s...",
                        prefix="[OpenRouter]"
                    )
                    time.sleep(delay)
                    delay *= backoff

            # Parse response
            choice = response.choices[0] if response.choices else None
            text = ""
            tool_calls: List[ToolCall] = []

            if choice:
                msg = choice.message
                # Text content
                if msg.content:
                    text = msg.content

                # Tool calls (OpenAI format)
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    for tc in msg.tool_calls:
                        import json
                        try:
                            tc_input = json.loads(tc.function.arguments) if tc.function.arguments else {}
                        except (json.JSONDecodeError, AttributeError):
                            tc_input = {}
                        tool_calls.append(ToolCall(
                            id=tc.id or "",
                            name=tc.function.name or "",
                            input=tc_input
                        ))
                        log_info(f"Tool call: {tc.function.name}", prefix="[OpenRouter]")

            stop_reason = getattr(choice, 'finish_reason', None) if choice else None

            # Token usage
            usage = getattr(response, 'usage', None)
            input_tokens = getattr(usage, 'prompt_tokens', 0) or 0
            output_tokens = getattr(usage, 'completion_tokens', 0) or 0

            log_info(
                f"Response from {active_model} "
                f"({input_tokens} in / {output_tokens} out)",
                prefix="[OpenRouter]"
            )

            return AnthropicResponse(
                text=text,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=True,
                stop_reason=stop_reason,
                tool_calls=tool_calls,
                raw_content=[],
                server_tool_details=[],
                citations=[],
                thinking_text=""
            )

        except Exception as e:
            error_type, error_msg = self._classify_error(e)
            log_error(f"OpenRouter error ({error_type}): {error_msg}", prefix="[OpenRouter]")
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
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> Generator[tuple[str, StreamingState], None, None]:
        """
        Streaming stub — falls back to non-streaming chat() and yields result as one chunk.

        Full SSE streaming can be added here later if needed.
        The router currently only calls chat_stream for LLMProvider.ANTHROPIC,
        so this path is not exercised today but is provided for completeness.
        """
        log_warning(
            "chat_stream called on OpenRouterClient — falling back to non-streaming",
            prefix="[OpenRouter]"
        )
        response = self.chat(
            messages=messages,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop_sequences=stop_sequences,
            tools=tools,
            model=model
        )

        state = StreamingState()
        state.text = response.text
        state.input_tokens = response.input_tokens
        state.output_tokens = response.output_tokens
        state.stop_reason = response.stop_reason
        state.tool_calls = response.tool_calls

        if response.text:
            yield (response.text, state)

        yield ("", state)

    def validate_connection(self) -> tuple[bool, str]:
        """Validate the API connection with a minimal request."""
        if not self.api_key:
            return False, "API key not configured"
        try:
            response = self.chat(
                messages=[{"role": "user", "content": "Say OK"}],
                max_tokens=5,
                temperature=0
            )
            if response.success:
                return True, f"Connected to OpenRouter ({self.model})"
            else:
                return False, f"API error: {response.error}"
        except Exception as e:
            return False, f"Connection error: {e}"


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

_openrouter_client: Optional[OpenRouterClient] = None


def get_openrouter_client() -> OpenRouterClient:
    """Get the global OpenRouter client instance."""
    global _openrouter_client
    if _openrouter_client is None:
        from config import OPENROUTER_API_KEY, ANTHROPIC_MAX_TOKENS
        import config as cfg
        model = getattr(cfg, 'OPENROUTER_FREE_MODEL', 'meta-llama/llama-3.1-8b-instruct:free')
        _openrouter_client = OpenRouterClient(
            api_key=OPENROUTER_API_KEY,
            model=model,
            max_tokens=min(ANTHROPIC_MAX_TOKENS, 4096)  # Free models have lower limits
        )
    return _openrouter_client


def init_openrouter_client(
    api_key: str,
    model: str = "meta-llama/llama-3.1-8b-instruct:free",
    max_tokens: int = 4096
) -> OpenRouterClient:
    """Initialize the global OpenRouter client."""
    global _openrouter_client
    _openrouter_client = OpenRouterClient(
        api_key=api_key,
        model=model,
        max_tokens=max_tokens
    )
    return _openrouter_client
