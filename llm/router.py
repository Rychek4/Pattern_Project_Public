"""
Pattern Project - LLM Router
Routes requests to appropriate LLM provider based on task type
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from core.logger import log_info, log_warning, log_error, log_success
from core.prompt_logger import log_api_request
from llm.kobold_client import KoboldClient, KoboldResponse, get_kobold_client
from llm.anthropic_client import AnthropicClient, AnthropicResponse, ToolCall, get_anthropic_client


class LLMProvider(Enum):
    """Available LLM providers."""
    ANTHROPIC = "anthropic"
    KOBOLD = "kobold"


class TaskType(Enum):
    """Types of LLM tasks."""
    CONVERSATION = "conversation"  # User-facing chat
    EXTRACTION = "extraction"      # Memory/data extraction
    ANALYSIS = "analysis"          # Analysis tasks
    SIMPLE = "simple"              # Simple/quick tasks


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    text: str
    success: bool
    provider: LLMProvider
    tokens_in: int = 0
    tokens_out: int = 0
    error: Optional[str] = None
    # Web search fields
    web_searches_used: int = 0
    citations: List[Any] = None  # List of WebSearchCitation
    # Native tool use fields
    stop_reason: Optional[str] = None
    tool_calls: List[ToolCall] = None
    raw_content: List[Any] = None  # Original content blocks for continuation

    def __post_init__(self):
        if self.citations is None:
            self.citations = []
        if self.tool_calls is None:
            self.tool_calls = []
        if self.raw_content is None:
            self.raw_content = []

    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls (excluding web_search)."""
        return len(self.tool_calls) > 0


class LLMRouter:
    """
    Routes LLM requests to appropriate providers.

    Handles:
    - Task-based routing (conversation vs extraction)
    - Fallback on failure
    - Provider health monitoring
    """

    def __init__(
        self,
        primary_provider: LLMProvider = LLMProvider.ANTHROPIC,
        fallback_enabled: bool = True
    ):
        """
        Initialize the router.

        Args:
            primary_provider: Primary provider for conversation
            fallback_enabled: Whether to fall back to secondary on failure
        """
        self.primary_provider = primary_provider
        self.fallback_enabled = fallback_enabled
        self._anthropic: Optional[AnthropicClient] = None
        self._kobold: Optional[KoboldClient] = None
        self._provider_status: Dict[LLMProvider, bool] = {}

    def _get_anthropic(self) -> AnthropicClient:
        """Get or create Anthropic client."""
        if self._anthropic is None:
            self._anthropic = get_anthropic_client()
        return self._anthropic

    def _get_kobold(self) -> KoboldClient:
        """Get or create Kobold client."""
        if self._kobold is None:
            self._kobold = get_kobold_client()
        return self._kobold

    def check_providers(self) -> Dict[LLMProvider, tuple[bool, str]]:
        """
        Check status of all providers.

        Returns:
            Dict mapping provider to (is_available, status_message)
        """
        status = {}

        # Check Anthropic
        try:
            client = self._get_anthropic()
            is_available = client.is_available()
            if is_available:
                status[LLMProvider.ANTHROPIC] = (True, f"Available ({client.model})")
            else:
                status[LLMProvider.ANTHROPIC] = (False, "API key not configured")
        except Exception as e:
            status[LLMProvider.ANTHROPIC] = (False, str(e))

        # Check Kobold
        try:
            client = self._get_kobold()
            is_available = client.is_available()
            if is_available:
                model = client.get_model_name() or "Unknown model"
                status[LLMProvider.KOBOLD] = (True, f"Available ({model})")
            else:
                status[LLMProvider.KOBOLD] = (False, "Not responding")
        except Exception as e:
            status[LLMProvider.KOBOLD] = (False, str(e))

        self._provider_status = {p: s[0] for p, s in status.items()}
        return status

    def get_provider_for_task(self, task_type: TaskType) -> LLMProvider:
        """
        Determine which provider to use for a task type.

        Args:
            task_type: The type of task

        Returns:
            The provider to use
        """
        if task_type == TaskType.EXTRACTION:
            # Always use local for extraction (cost-free, runs continuously)
            return LLMProvider.KOBOLD

        if task_type == TaskType.SIMPLE:
            # Use local for simple tasks
            return LLMProvider.KOBOLD

        # For conversation and analysis, use primary provider
        return self.primary_provider

    def chat(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        task_type: TaskType = TaskType.CONVERSATION,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        force_provider: Optional[LLMProvider] = None,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> LLMResponse:
        """
        Send a chat request, routing to appropriate provider.

        Supports both text-only and multimodal messages. When using multimodal,
        message content can be an array of content blocks (text + images).

        Args:
            messages: List of message dicts. Content can be string or content array.
            system_prompt: Optional system prompt
            task_type: Type of task for routing
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            force_provider: Force a specific provider (bypass routing)
            tools: Optional list of tool definitions for native tool use (Anthropic only)

        Returns:
            LLMResponse with generated text and any tool calls
        """
        # Determine provider
        if force_provider:
            provider = force_provider
        else:
            provider = self.get_provider_for_task(task_type)

        # Check web search availability for conversation tasks on Anthropic
        enable_web_search = False
        web_search_max_uses = None
        web_search_unavailable_msg = None

        if provider == LLMProvider.ANTHROPIC and task_type == TaskType.CONVERSATION:
            enable_web_search, web_search_max_uses, web_search_unavailable_msg = (
                self._check_web_search_availability()
            )

        # If web search is unavailable due to daily limit, notify Claude in system prompt
        if web_search_unavailable_msg and system_prompt:
            system_prompt = f"{system_prompt}\n\n{web_search_unavailable_msg}"
        elif web_search_unavailable_msg:
            system_prompt = web_search_unavailable_msg

        # Try primary provider
        response = self._send_to_provider(
            provider=provider,
            messages=messages,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            enable_web_search=enable_web_search,
            web_search_max_uses=web_search_max_uses,
            tools=tools
        )

        # Record web search usage if any were used
        if response.success and response.web_searches_used > 0:
            self._record_web_search_usage(response.web_searches_used)

        # Handle fallback - but NOT for conversation tasks
        # Falling back to a weaker model for user-facing chat degrades experience
        if not response.success and self.fallback_enabled and task_type != TaskType.CONVERSATION:
            fallback_provider = (
                LLMProvider.KOBOLD if provider == LLMProvider.ANTHROPIC
                else LLMProvider.ANTHROPIC
            )

            log_warning(
                f"{provider.value} failed, falling back to {fallback_provider.value}"
            )

            response = self._send_to_provider(
                provider=fallback_provider,
                messages=messages,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                enable_web_search=False,  # No web search on fallback
                web_search_max_uses=None
            )
        elif not response.success and task_type == TaskType.CONVERSATION:
            log_warning(f"{provider.value} failed for CONVERSATION task - not falling back to preserve quality")

        return response

    def _check_web_search_availability(self) -> tuple[bool, Optional[int], Optional[str]]:
        """
        Check if web search should be enabled for this request.

        Returns:
            Tuple of (enable_web_search, max_uses, unavailable_message)
        """
        import config

        if not config.WEB_SEARCH_ENABLED:
            return (False, None, None)

        try:
            from agency.web_search_limiter import get_web_search_limiter
            limiter = get_web_search_limiter()

            if not limiter.is_available():
                # Daily limit hit - notify Claude
                used, total = limiter.get_usage()
                log_warning(f"Web search daily limit reached ({used}/{total})")
                return (
                    False,
                    None,
                    "<web_search_notice>Web search is unavailable today (daily limit reached). "
                    "Rely on your knowledge or ask the user to try again tomorrow.</web_search_notice>"
                )

            # Web search is available
            max_uses = limiter.get_max_for_request()
            log_info(f"Web search enabled (max {max_uses} uses this request)", prefix="🔍")
            return (True, max_uses, None)

        except Exception as e:
            log_error(f"Web search limiter error, disabling web search: {e}")
            return (False, None, None)  # Gracefully disable web search

    def _record_web_search_usage(self, count: int) -> None:
        """Record web search usage to the limiter."""
        from agency.web_search_limiter import get_web_search_limiter
        limiter = get_web_search_limiter()
        limiter.record_usage(count)

    def _send_to_provider(
        self,
        provider: LLMProvider,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str],
        max_tokens: Optional[int],
        temperature: float,
        enable_web_search: bool = False,
        web_search_max_uses: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> LLMResponse:
        """Send request to a specific provider."""
        try:
            if provider == LLMProvider.ANTHROPIC:
                client = self._get_anthropic()
                response = client.chat(
                    messages=messages,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    enable_web_search=enable_web_search,
                    web_search_max_uses=web_search_max_uses,
                    tools=tools
                )

                llm_response = LLMResponse(
                    text=response.text,
                    success=response.success,
                    provider=provider,
                    tokens_in=response.input_tokens,
                    tokens_out=response.output_tokens,
                    error=response.error,
                    web_searches_used=response.web_searches_used,
                    citations=response.citations,
                    stop_reason=response.stop_reason,
                    tool_calls=response.tool_calls,
                    raw_content=response.raw_content
                )

                # Log the API request/response
                log_api_request(
                    provider=provider.value,
                    model=client.model,
                    system_prompt=system_prompt,
                    messages=messages,
                    settings={
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "web_search_enabled": enable_web_search,
                        "web_search_max_uses": web_search_max_uses
                    },
                    response_text=response.text,
                    tokens_in=response.input_tokens,
                    tokens_out=response.output_tokens,
                    success=response.success,
                    error=response.error
                )

                return llm_response

            elif provider == LLMProvider.KOBOLD:
                client = self._get_kobold()
                response = client.chat(
                    messages=messages,
                    system_prompt=system_prompt,
                    max_length=max_tokens,
                    temperature=temperature
                )

                llm_response = LLMResponse(
                    text=response.text,
                    success=response.success,
                    provider=provider,
                    tokens_out=response.tokens_generated,
                    error=response.error
                )

                # Log the API request/response
                log_api_request(
                    provider=provider.value,
                    model=client.get_model_name() or "kobold-local",
                    system_prompt=system_prompt,
                    messages=messages,
                    settings={"temperature": temperature, "max_tokens": max_tokens},
                    response_text=response.text,
                    tokens_in=0,  # Kobold doesn't report input tokens
                    tokens_out=response.tokens_generated,
                    success=response.success,
                    error=response.error
                )

                return llm_response

            else:
                log_error(f"Unknown provider: {provider}")
                return LLMResponse(
                    text="",
                    success=False,
                    provider=provider,
                    error=f"Unknown provider: {provider}"
                )

        except Exception as e:
            log_error(f"LLM provider error ({provider.value}): {e}")
            return LLMResponse(
                text="",
                success=False,
                provider=provider,
                error=str(e)
            )

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        task_type: TaskType = TaskType.CONVERSATION,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7
    ) -> LLMResponse:
        """
        Simple text generation (wraps chat with single user message).

        Args:
            prompt: The prompt text
            system_prompt: Optional system prompt
            task_type: Type of task for routing
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            LLMResponse with generated text
        """
        messages = [{"role": "user", "content": prompt}]
        return self.chat(
            messages=messages,
            system_prompt=system_prompt,
            task_type=task_type,
            max_tokens=max_tokens,
            temperature=temperature
        )


# Global router instance
_router: Optional[LLMRouter] = None


def get_llm_router() -> LLMRouter:
    """Get the global LLM router instance."""
    global _router
    if _router is None:
        from config import LLM_PRIMARY_PROVIDER, LLM_FALLBACK_ENABLED
        primary = LLMProvider(LLM_PRIMARY_PROVIDER)
        _router = LLMRouter(
            primary_provider=primary,
            fallback_enabled=LLM_FALLBACK_ENABLED
        )
    return _router


def init_llm_router(
    primary_provider: str = "anthropic",
    fallback_enabled: bool = True
) -> LLMRouter:
    """Initialize the global LLM router."""
    global _router
    _router = LLMRouter(
        primary_provider=LLMProvider(primary_provider),
        fallback_enabled=fallback_enabled
    )
    return _router
