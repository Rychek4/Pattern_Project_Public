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
        model: str = None,                    # Changed: None = use fallback list
        max_tokens: int = 4096,
        timeout: int = 120
    ):
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client = None

        # Load fallback chain from config
        import config as cfg
        self.fallback_models = getattr(cfg, 'OPENROUTER_FREE_MODELS', [
            "stepfun/step-3.5-flash:free",
            "meta-llama/llama-4-maverick:free",
            "google/gemini-flash-1.5-8b:free",
            "meta-llama/llama-3.1-8b-instruct:free",
        ])

        # If user explicitly passed a model, use only that one (no fallback)
        if model is not None:
            self.model = model
            self.fallback_models = [model]
        else:
            self.model = self.fallback_models[0]   # Start with the best one

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

    def _classify_error(self, error: Exception) -> tuple[str, str]:
        """
        Classify an OpenAI SDK error and also detect HTML error pages 
        (very common on OpenRouter free tier when rate-limited or model down).
        """
        try:
            error_msg = str(error).strip()
            response_obj = getattr(error, 'response', None)

            # === Detect HTML error pages (this is what was causing your original error) ===
            if response_obj is not None:
                try:
                    # Get the raw response body
                    content = getattr(response_obj, 'text', None)
                    if content is None:
                        content = str(response_obj)

                    content_preview = content[:800].lower()

                    if content.strip().startswith('<!DOCTYPE html') or '<html' in content_preview:
                        # Try to extract a meaningful title or message from the HTML
                        import re
                        title_match = re.search(r'<title>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
                        title = title_match.group(1).strip() if title_match else "Unknown HTML Error"

                        # Also look for common OpenRouter error phrases
                        if "rate limit" in content_preview or "429" in content_preview:
                            return ("rate_limited", f"Rate limit hit - {title}")
                        elif "overloaded" in content_preview or "529" in content_preview:
                            return ("overloaded", f"Model overloaded - {title}")
                        else:
                            return ("html_error_page", f"OpenRouter returned HTML error page: {title}")
                except:
                    pass  # Fall through to normal classification

            # === Standard OpenAI SDK error classification ===
            import openai

            if isinstance(error, openai.APITimeoutError):
                return ("timeout", "Request timed out")
            elif isinstance(error, openai.APIConnectionError):
                return ("connection_error", "Connection failed")
            elif isinstance(error, openai.RateLimitError):
                return ("rate_limited", "Rate limit exceeded")
            elif isinstance(error, openai.APIStatusError):
                status = error.status_code
                if status == 529:
                    return ("overloaded", "API overloaded (529)")
                elif status in (500, 502, 503):
                    return ("server_error", f"Server error ({status})")
                elif status in (401, 403):
                    return ("auth_error", "Authentication failed")
                elif status == 400:
                    return ("bad_request", error_msg)

            # Fallback: check error message text
            error_lower = error_msg.lower()
            if "overloaded" in error_lower or "529" in error_msg:
                return ("overloaded", "API overloaded")
            elif "rate" in error_lower or "429" in error_msg:
                return ("rate_limited", "Rate limit exceeded")
            elif "html" in error_lower or "<!doctype" in error_lower or "<html" in error_lower:
                return ("html_error_page", f"Received HTML error page: {error_msg[:150]}...")

            return ("unknown", error_msg)

        except Exception as e:
            return ("unknown", f"Error during classification: {str(e)}")

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
        Now includes automatic fallback across multiple free models + HTML error detection.
        """
        if max_tokens is None:
            max_tokens = self.max_tokens

        import time
        import config as cfg

        max_attempts = getattr(cfg, 'API_RETRY_MAX_ATTEMPTS', 3)
        delay = getattr(cfg, 'API_RETRY_INITIAL_DELAY', 1.0)
        backoff = getattr(cfg, 'API_RETRY_BACKOFF_MULTIPLIER', 2.0)

        # Warn about unsupported Anthropic features
        if thinking_enabled:
            log_warning("thinking_enabled=True ignored — not supported by OpenRouterClient", prefix="[OpenRouter]")
        if enable_web_search or enable_web_fetch:
            log_warning("Web search/fetch ignored — not supported by OpenRouterClient", prefix="[OpenRouter]")

        # Determine which models to try (fallback chain)
        models_to_try = [model] if model is not None else self.fallback_models

        last_error_type = "unknown"
        last_error_msg = "Unknown error"

        for attempt_model in models_to_try:
            active_model = attempt_model
            log_info(f"Trying OpenRouter model: {active_model}", prefix="[OpenRouter]")

            # Build messages (OpenAI format)
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
            if tools:
                request_params["tools"] = tools

            # Retry loop for transient errors on this specific model
            for attempt in range(max_attempts):
                try:
                    client = self._get_client()
                    response = client.chat.completions.create(**request_params)

                    # Success!
                    log_success(f"✅ OpenRouter succeeded with model: {active_model}", prefix="[OpenRouter]")

                    # Parse response (same as before)
                    choice = response.choices[0] if response.choices else None
                    text = ""
                    tool_calls: List[ToolCall] = []

                    if choice:
                        msg = choice.message
                        if msg.content:
                            text = msg.content

                        if hasattr(msg, 'tool_calls') and msg.tool_calls:
                            for tc in msg.tool_calls:
                                import json
                                try:
                                    tc_input = json.loads(tc.function.arguments) if tc.function.arguments else {}
                                except:
                                    tc_input = {}
                                tool_calls.append(ToolCall(
                                    id=tc.id or "",
                                    name=tc.function.name or "",
                                    input=tc_input
                                ))

                    stop_reason = getattr(choice, 'finish_reason', None) if choice else None

                    usage = getattr(response, 'usage', None)
                    input_tokens = getattr(usage, 'prompt_tokens', 0) or 0
                    output_tokens = getattr(usage, 'completion_tokens', 0) or 0

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
                    last_error_type = error_type
                    last_error_msg = error_msg

                    log_warning(
                        f"Attempt {attempt+1}/{max_attempts} failed with {active_model}: "
                        f"{error_type} - {error_msg}",
                        prefix="[OpenRouter]"
                    )

                    if error_type == "html_error_page":
                        log_warning(
                            "HTML error page detected — this usually means the free model is "
                            "rate-limited or temporarily unavailable.",
                            prefix="[OpenRouter]"
                        )

                    # Decide whether to retry this model or move to next fallback
                    if self._is_transient_error(error_type) and attempt < max_attempts - 1:
                        time.sleep(delay)
                        delay *= backoff
                        continue
                    else:
                        break  # Move to next model in fallback list

            # If we get here, this model failed completely — try next one
            log_warning(f"Model {active_model} exhausted all retries. Trying next fallback...", prefix="[OpenRouter]")

        # All models in the fallback list failed
        log_error(f"❌ All OpenRouter free models failed. Last error: {last_error_type} - {last_error_msg}", prefix="[OpenRouter]")
        return AnthropicResponse(
            text="",
            input_tokens=0,
            output_tokens=0,
            success=False,
            error=last_error_msg,
            error_type=last_error_type
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
        """Safe streaming fallback that prevents huge HTML dumps."""
        log_info("OpenRouter chat_stream called — falling back to non-streaming chat()", prefix="[OpenRouter]")

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

        if not response.success:
            error_msg = response.error or "Unknown OpenRouter error"
            if "<!DOCTYPE html" in error_msg or "<html" in error_msg:
                error_msg = "OpenRouter returned HTML error page (likely rate limit or service issue). Check logs for details."
            log_error(f"OpenRouter failed: {error_msg}", prefix="[OpenRouter]")

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


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

_openrouter_client: Optional[OpenRouterClient] = None


def get_openrouter_client() -> OpenRouterClient:
    """Get the global OpenRouter client instance."""
    global _openrouter_client
    if _openrouter_client is None:
        from config import OPENROUTER_API_KEY, ANTHROPIC_MAX_TOKENS

        _openrouter_client = OpenRouterClient(
            api_key=OPENROUTER_API_KEY,
            model=None,                                   # None = use the new fallback list
            max_tokens=min(ANTHROPIC_MAX_TOKENS, 4096)    # Free models have lower limits
        )
    return _openrouter_client


def init_openrouter_client(
    api_key: str,
    model: str = None,                                    # Allow None for fallback chain
    max_tokens: int = 4096
) -> OpenRouterClient:
    """Initialize the global OpenRouter client."""
    global _openrouter_client
    _openrouter_client = OpenRouterClient(
        api_key=api_key,
        model=model,                                      # None = use fallback list
        max_tokens=max_tokens
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
