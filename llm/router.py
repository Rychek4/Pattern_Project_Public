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
from llm.anthropic_client import AnthropicClient, AnthropicResponse, get_anthropic_client


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
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        task_type: TaskType = TaskType.CONVERSATION,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        force_provider: Optional[LLMProvider] = None
    ) -> LLMResponse:
        """
        Send a chat request, routing to appropriate provider.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."}
            system_prompt: Optional system prompt
            task_type: Type of task for routing
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            force_provider: Force a specific provider (bypass routing)

        Returns:
            LLMResponse with generated text
        """
        log_info(f"ROUTER DEBUG: chat() called with {len(messages)} messages, task_type={task_type}")

        # Determine provider
        if force_provider:
            provider = force_provider
            log_info(f"ROUTER DEBUG: Using forced provider: {provider}")
        else:
            provider = self.get_provider_for_task(task_type)
            log_info(f"ROUTER DEBUG: Selected provider for task: {provider}")

        log_info(f"ROUTER DEBUG: Primary provider is {self.primary_provider}, fallback_enabled={self.fallback_enabled}")

        # Try primary provider
        log_info(f"ROUTER DEBUG: Calling _send_to_provider({provider})...")
        response = self._send_to_provider(
            provider=provider,
            messages=messages,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature
        )
        log_info(f"ROUTER DEBUG: _send_to_provider returned: success={response.success}, error={response.error}")

        # Handle fallback
        if not response.success and self.fallback_enabled:
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
                temperature=temperature
            )
            log_info(f"ROUTER DEBUG: Fallback returned: success={response.success}, error={response.error}")

        log_info(f"ROUTER DEBUG: chat() returning response with success={response.success}")
        return response

    def _send_to_provider(
        self,
        provider: LLMProvider,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str],
        max_tokens: Optional[int],
        temperature: float
    ) -> LLMResponse:
        """Send request to a specific provider."""
        import traceback

        log_info(f"ROUTER DEBUG: _send_to_provider() called for {provider}")

        try:
            if provider == LLMProvider.ANTHROPIC:
                log_info("ROUTER DEBUG: Getting Anthropic client...")
                client = self._get_anthropic()
                log_info(f"ROUTER DEBUG: Got Anthropic client, model={client.model}")

                log_info(f"ROUTER DEBUG: Calling Anthropic chat with {len(messages)} messages...")
                response = client.chat(
                    messages=messages,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature
                )
                log_info(f"ROUTER DEBUG: Anthropic returned: success={response.success}, error={response.error}")

                llm_response = LLMResponse(
                    text=response.text,
                    success=response.success,
                    provider=provider,
                    tokens_in=response.input_tokens,
                    tokens_out=response.output_tokens,
                    error=response.error
                )

                # Log the API request/response
                log_info("ROUTER DEBUG: Logging API request...")
                log_api_request(
                    provider=provider.value,
                    model=client.model,
                    system_prompt=system_prompt,
                    messages=messages,
                    settings={"temperature": temperature, "max_tokens": max_tokens},
                    response_text=response.text,
                    tokens_in=response.input_tokens,
                    tokens_out=response.output_tokens,
                    success=response.success,
                    error=response.error
                )
                log_info("ROUTER DEBUG: API request logged successfully")

                return llm_response

            elif provider == LLMProvider.KOBOLD:
                log_info("ROUTER DEBUG: Getting Kobold client...")
                client = self._get_kobold()
                log_info(f"ROUTER DEBUG: Got Kobold client, url={client.api_url}")

                log_info(f"ROUTER DEBUG: Calling Kobold chat with {len(messages)} messages...")
                response = client.chat(
                    messages=messages,
                    system_prompt=system_prompt,
                    max_length=max_tokens,
                    temperature=temperature
                )
                log_info(f"ROUTER DEBUG: Kobold returned: success={response.success}, error={response.error}")

                llm_response = LLMResponse(
                    text=response.text,
                    success=response.success,
                    provider=provider,
                    tokens_out=response.tokens_generated,
                    error=response.error
                )

                # Log the API request/response
                log_info("ROUTER DEBUG: Logging API request...")
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
                log_info("ROUTER DEBUG: API request logged successfully")

                return llm_response

            else:
                log_error(f"ROUTER DEBUG: Unknown provider: {provider}")
                return LLMResponse(
                    text="",
                    success=False,
                    provider=provider,
                    error=f"Unknown provider: {provider}"
                )

        except Exception as e:
            tb = traceback.format_exc()
            log_error(f"ROUTER DEBUG: EXCEPTION in _send_to_provider!")
            log_error(f"ROUTER DEBUG: Exception: {str(e)}")
            log_error(f"ROUTER DEBUG: Traceback:\n{tb}")
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
