"""
Pattern Project - LLM Router
Routes requests to appropriate LLM provider based on task type
"""

from enum import Enum
from typing import Optional, List, Dict, Any, Generator
from dataclasses import dataclass

from core.logger import log_info, log_warning, log_error, log_success
from core.prompt_logger import log_api_request
from llm.kobold_client import KoboldClient, KoboldResponse, get_kobold_client
from llm.anthropic_client import (
    AnthropicClient, AnthropicResponse, ToolCall, StreamingState, get_anthropic_client
)


class LLMProvider(Enum):
    """Available LLM providers."""
    ANTHROPIC = "anthropic"
    KOBOLD = "kobold"


class TaskType(Enum):
    """Types of LLM tasks."""
    CONVERSATION = "conversation"  # User-facing chat
    EXTRACTION = "extraction"      # Memory/data extraction (unified API call)
    FACT_EXTRACTION = "fact_extraction"  # Legacy: now merged into EXTRACTION
    ANALYSIS = "analysis"          # Analysis tasks
    SIMPLE = "simple"              # Simple/quick tasks
    DELEGATION = "delegation"      # Lightweight sub-agent tasks (Haiku)


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    text: str
    success: bool
    provider: LLMProvider
    tokens_in: int = 0
    tokens_out: int = 0
    error: Optional[str] = None
    error_type: Optional[str] = None  # "overloaded", "rate_limited", "server_error", etc.
    # Web search fields
    web_searches_used: int = 0
    citations: List[Any] = None  # List of WebSearchCitation
    # Web fetch fields
    web_fetches_used: int = 0
    # Native tool use fields
    stop_reason: Optional[str] = None
    tool_calls: List[ToolCall] = None
    raw_content: List[Any] = None  # Original content blocks for continuation
    # Server-side tool details (web_search, web_fetch) for process panel
    server_tool_details: List[Any] = None
    # Extended thinking fields
    thinking_text: str = ""  # Claude's internal reasoning (not shown to user by default)

    def __post_init__(self):
        if self.citations is None:
            self.citations = []
        if self.tool_calls is None:
            self.tool_calls = []
        if self.raw_content is None:
            self.raw_content = []
        if self.server_tool_details is None:
            self.server_tool_details = []

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

    def _get_failover_model(self, current_model: str) -> Optional[str]:
        """
        Get the failover model for a given model.

        Returns:
            The failover model name, or None if no failover configured.
        """
        import config
        failover_map = getattr(config, 'ANTHROPIC_MODEL_FAILOVER', {})
        return failover_map.get(current_model)

    def _is_failover_eligible(self, error_type: Optional[str]) -> bool:
        """Check if an error type should trigger model failover."""
        return error_type in ("overloaded", "rate_limited", "server_error", "timeout", "connection_error")

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
            # Use API for unified extraction (episodic + factual in one call)
            # Consolidated from multi-pass local extraction for better quality
            return LLMProvider.ANTHROPIC

        if task_type == TaskType.FACT_EXTRACTION:
            # Legacy: now merged into EXTRACTION, but still routes to API
            return LLMProvider.ANTHROPIC

        if task_type == TaskType.SIMPLE:
            # Use Anthropic for simple tasks (uses default Sonnet model)
            return LLMProvider.ANTHROPIC

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
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking_enabled: bool = False,
        thinking_budget_tokens: Optional[int] = None
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
            thinking_enabled: Whether to enable extended thinking (Anthropic only)
            thinking_budget_tokens: Max tokens for thinking (None = use config default)

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

        # Check web fetch availability for conversation tasks on Anthropic
        enable_web_fetch = False
        web_fetch_max_uses = None
        web_fetch_config = None
        web_fetch_unavailable_msg = None

        if provider == LLMProvider.ANTHROPIC and task_type == TaskType.CONVERSATION:
            enable_web_search, web_search_max_uses, web_search_unavailable_msg = (
                self._check_web_search_availability()
            )
            enable_web_fetch, web_fetch_max_uses, web_fetch_config, web_fetch_unavailable_msg = (
                self._check_web_fetch_availability()
            )

        # If web search is unavailable due to daily limit, notify Claude in system prompt
        unavailable_notices = []
        if web_search_unavailable_msg:
            unavailable_notices.append(web_search_unavailable_msg)
        if web_fetch_unavailable_msg:
            unavailable_notices.append(web_fetch_unavailable_msg)

        if unavailable_notices:
            notice_text = "\n\n".join(unavailable_notices)
            if system_prompt:
                system_prompt = f"{system_prompt}\n\n{notice_text}"
            else:
                system_prompt = notice_text

        # Try primary provider
        response = self._send_to_provider(
            provider=provider,
            messages=messages,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            enable_web_search=enable_web_search,
            web_search_max_uses=web_search_max_uses,
            enable_web_fetch=enable_web_fetch,
            web_fetch_max_uses=web_fetch_max_uses,
            web_fetch_config=web_fetch_config,
            tools=tools,
            task_type=task_type,
            thinking_enabled=thinking_enabled,
            thinking_budget_tokens=thinking_budget_tokens
        )

        # If web_fetch domain was blocked by Anthropic's crawler, retry without web_fetch
        # This happens when the model tries to fetch a domain that blocks Anthropic's user agent
        # (e.g., reddit.com). The API returns 400 instead of a tool error, so we retry without
        # web_fetch to let the model continue without that capability.
        if (not response.success
                and response.error_type == "web_fetch_domain_blocked"
                and enable_web_fetch):
            log_warning(
                f"Web fetch blocked by domain restriction, retrying without web_fetch: "
                f"{response.error}"
            )
            response = self._send_to_provider(
                provider=provider,
                messages=messages,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                enable_web_search=enable_web_search,
                web_search_max_uses=web_search_max_uses,
                enable_web_fetch=False,
                web_fetch_max_uses=None,
                web_fetch_config=None,
                tools=tools,
                task_type=task_type,
                thinking_enabled=thinking_enabled,
                thinking_budget_tokens=thinking_budget_tokens
            )

        # Record web search usage if any were used
        if response.success and response.web_searches_used > 0:
            self._record_web_search_usage(response.web_searches_used)

        # Record web fetch usage if any were used
        if response.success and response.web_fetches_used > 0:
            self._record_web_fetch_usage(response.web_fetches_used)

        # Model failover for Anthropic: try alternate Claude model on overload/rate limit
        if (not response.success
                and provider == LLMProvider.ANTHROPIC
                and self._is_failover_eligible(response.error_type)):
            # Determine which model was used for this request
            import config as _cfg
            if task_type == TaskType.CONVERSATION:
                from core.user_settings import get_user_settings
                user_model = get_user_settings().conversation_model
                primary_model = user_model if user_model else _cfg.ANTHROPIC_MODEL_CONVERSATION
            elif task_type in (TaskType.EXTRACTION, TaskType.FACT_EXTRACTION):
                primary_model = _cfg.ANTHROPIC_MODEL_EXTRACTION
            elif task_type == TaskType.DELEGATION:
                primary_model = _cfg.DELEGATION_MODEL
            else:
                primary_model = _cfg.ANTHROPIC_MODEL

            failover_model = self._get_failover_model(primary_model)
            if failover_model:
                log_warning(
                    f"Model {primary_model} failed ({response.error_type}), "
                    f"trying failover model: {failover_model}"
                )
                failover_response = self._send_to_provider(
                    provider=LLMProvider.ANTHROPIC,
                    messages=messages,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    enable_web_search=enable_web_search,
                    web_search_max_uses=web_search_max_uses,
                    enable_web_fetch=enable_web_fetch,
                    web_fetch_max_uses=web_fetch_max_uses,
                    web_fetch_config=web_fetch_config,
                    tools=tools,
                    task_type=task_type,
                    thinking_enabled=thinking_enabled,
                    thinking_budget_tokens=thinking_budget_tokens,
                    model_override=failover_model
                )

                if failover_response.success:
                    # Prepend notification to response text
                    notice = "\u26a0 Response from fallback model (primary temporarily unavailable)\n\n"
                    failover_response.text = notice + failover_response.text
                    log_info(f"Failover to {failover_model} succeeded")
                    return failover_response
                else:
                    # Both models failed - mark as both_unavailable for deferred retry
                    log_warning(
                        f"Failover model {failover_model} also failed ({failover_response.error_type}). "
                        f"Both models unavailable."
                    )
                    response.error_type = "both_models_unavailable"
                    return response

        # Handle fallback to Kobold - but NOT for conversation tasks
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
                web_search_max_uses=None,
                task_type=task_type
            )
        elif not response.success and task_type == TaskType.CONVERSATION:
            log_warning(f"{provider.value} failed for CONVERSATION task - error_type={response.error_type}")

        return response

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        task_type: TaskType = TaskType.CONVERSATION,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking_enabled: bool = False,
        thinking_budget_tokens: Optional[int] = None
    ) -> Generator[tuple[str, StreamingState], None, None]:
        """
        Stream a chat request, yielding text chunks as they arrive.

        Only supports Anthropic provider (streaming not available for Kobold).

        Args:
            messages: List of message dicts
            system_prompt: Optional system prompt
            task_type: Type of task for routing
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            tools: Optional list of tool definitions
            thinking_enabled: Whether to enable extended thinking
            thinking_budget_tokens: Max tokens for thinking (None = use config default)

        Yields:
            Tuple of (text_chunk, streaming_state)
        """
        # Streaming only supported for Anthropic
        provider = LLMProvider.ANTHROPIC

        # Check web search availability
        enable_web_search = False
        web_search_max_uses = None
        web_search_unavailable_msg = None

        # Check web fetch availability
        enable_web_fetch = False
        web_fetch_max_uses = None
        web_fetch_config = None
        web_fetch_unavailable_msg = None

        if task_type == TaskType.CONVERSATION:
            enable_web_search, web_search_max_uses, web_search_unavailable_msg = (
                self._check_web_search_availability()
            )
            enable_web_fetch, web_fetch_max_uses, web_fetch_config, web_fetch_unavailable_msg = (
                self._check_web_fetch_availability()
            )

        # Modify system prompt if web tools unavailable
        final_system_prompt = system_prompt
        unavailable_notices = []
        if web_search_unavailable_msg:
            unavailable_notices.append(web_search_unavailable_msg)
        if web_fetch_unavailable_msg:
            unavailable_notices.append(web_fetch_unavailable_msg)

        if unavailable_notices:
            notice_text = "\n\n".join(unavailable_notices)
            if system_prompt:
                final_system_prompt = f"{system_prompt}\n\n{notice_text}"
            else:
                final_system_prompt = notice_text

        # Select model based on task type
        import config
        if task_type == TaskType.CONVERSATION:
            from core.user_settings import get_user_settings
            user_model = get_user_settings().conversation_model
            model = user_model if user_model else config.ANTHROPIC_MODEL_CONVERSATION
        elif task_type in (TaskType.EXTRACTION, TaskType.FACT_EXTRACTION):
            model = config.ANTHROPIC_MODEL_EXTRACTION
        elif task_type == TaskType.DELEGATION:
            model = config.DELEGATION_MODEL
        else:
            model = config.ANTHROPIC_MODEL

        # DIAGNOSTIC: Log streaming request details
        log_info(f"=== STREAM REQUEST START ===", prefix="🔍")
        log_info(f"Model: {model}, Task: {task_type.value}", prefix="🔍")
        log_info(f"Messages count: {len(messages)}", prefix="🔍")
        log_info(f"Tools enabled: {tools is not None and len(tools) > 0}", prefix="🔍")
        log_info(f"Web search: {enable_web_search}", prefix="🔍")
        log_info(f"Web fetch: {enable_web_fetch}", prefix="🔍")
        log_info(f"Thinking: {thinking_enabled}", prefix="🔍")

        # Log message structure (not full content for privacy)
        for i, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str):
                content_preview = content[:100] + "..." if len(content) > 100 else content
                log_info(f"  [{i}] {role}: {len(content)} chars - {content_preview}", prefix="🔍")
            elif isinstance(content, list):
                # Multimodal content
                block_types = [b.get("type", "?") for b in content if isinstance(b, dict)]
                log_info(f"  [{i}] {role}: multimodal with {len(content)} blocks: {block_types}", prefix="🔍")
            else:
                log_info(f"  [{i}] {role}: unknown content type {type(content)}", prefix="🔍")

        try:
            client = self._get_anthropic()
            final_state = None
            chunk_count = 0
            content_yielded_to_caller = False

            for chunk, state in client.chat_stream(
                messages=messages,
                system_prompt=final_system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                enable_web_search=enable_web_search,
                web_search_max_uses=web_search_max_uses,
                enable_web_fetch=enable_web_fetch,
                web_fetch_max_uses=web_fetch_max_uses,
                web_fetch_config=web_fetch_config,
                tools=tools,
                model=model,
                thinking_enabled=thinking_enabled,
                thinking_budget_tokens=thinking_budget_tokens
            ):
                final_state = state
                chunk_count += 1

                # Intercept error states before yielding to caller
                # (only if no content has been sent to the user yet)
                if state.stop_reason == "error" and not content_yielded_to_caller:
                    # Don't yield this error - we'll try failover below
                    continue

                if chunk_count == 1:
                    log_info(f"First chunk received", prefix="🔍")
                if chunk:
                    content_yielded_to_caller = True
                yield (chunk, state)

            # DIAGNOSTIC: Log streaming completion
            log_info(f"=== STREAM REQUEST COMPLETE ===", prefix="🔍")
            log_info(f"Total chunks: {chunk_count}", prefix="🔍")
            if final_state:
                log_info(f"Stop reason: {final_state.stop_reason}", prefix="🔍")
                log_info(f"Text length: {len(final_state.text)} chars", prefix="🔍")
                log_info(f"Tool calls: {len(final_state.tool_calls)}", prefix="🔍")
                if final_state.stop_reason == "error":
                    error_msg = getattr(final_state, '_error_message', 'unknown')
                    log_error(f"Stream ended with error: {error_msg}", prefix="🔍")

            # Web fetch domain blocked: retry stream without web_fetch before trying failover
            # This mirrors the chat() retry at lines 278-304.
            if (final_state
                    and final_state.stop_reason == "error"
                    and not content_yielded_to_caller
                    and enable_web_fetch):
                blocked_error_type = getattr(final_state, '_error_type', None)
                if blocked_error_type == "web_fetch_domain_blocked":
                    log_warning(
                        f"Web fetch blocked by domain restriction, "
                        f"retrying stream without web_fetch: "
                        f"{getattr(final_state, '_error_message', 'unknown')}"
                    )
                    retry_state = None
                    retry_content_yielded = False
                    for retry_chunk, retry_st in client.chat_stream(
                        messages=messages,
                        system_prompt=final_system_prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        enable_web_search=enable_web_search,
                        web_search_max_uses=web_search_max_uses,
                        enable_web_fetch=False,
                        web_fetch_max_uses=None,
                        web_fetch_config=None,
                        tools=tools,
                        model=model,
                        thinking_enabled=thinking_enabled,
                        thinking_budget_tokens=thinking_budget_tokens
                    ):
                        retry_state = retry_st
                        if retry_st.stop_reason == "error" and not retry_content_yielded:
                            break
                        if retry_chunk:
                            retry_content_yielded = True
                        yield (retry_chunk, retry_st)

                    if retry_content_yielded:
                        log_info("Stream retry without web_fetch succeeded")
                        if retry_state and retry_state.web_searches_used > 0:
                            self._record_web_search_usage(retry_state.web_searches_used)
                        return

                    # Retry also failed — update final_state for failover below
                    if retry_state:
                        final_state = retry_state

            # Model failover: if primary stream failed before yielding content, try alternate model
            if (final_state
                    and final_state.stop_reason == "error"
                    and not content_yielded_to_caller):
                error_type = getattr(final_state, '_error_type', None)
                error_msg = getattr(final_state, '_error_message', 'unknown')

                if self._is_failover_eligible(error_type):
                    failover_model = self._get_failover_model(model)
                    if failover_model:
                        log_warning(
                            f"Streaming model {model} failed ({error_type}), "
                            f"trying failover: {failover_model}"
                        )

                        # Try failover model
                        failover_state = None
                        failover_content_yielded = False
                        notification = "\u26a0 Response from fallback model (primary temporarily unavailable)\n\n"

                        for fb_chunk, fb_state in client.chat_stream(
                            messages=messages,
                            system_prompt=final_system_prompt,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            enable_web_search=enable_web_search,
                            web_search_max_uses=web_search_max_uses,
                            enable_web_fetch=enable_web_fetch,
                            web_fetch_max_uses=web_fetch_max_uses,
                            web_fetch_config=web_fetch_config,
                            tools=tools,
                            model=failover_model,
                            thinking_enabled=thinking_enabled,
                            thinking_budget_tokens=thinking_budget_tokens
                        ):
                            failover_state = fb_state

                            # If failover also errors before content, break out
                            if fb_state.stop_reason == "error" and not failover_content_yielded:
                                break

                            # Yield notification prefix before first real content
                            if not failover_content_yielded and fb_chunk:
                                yield (notification, fb_state)
                                failover_content_yielded = True

                            yield (fb_chunk, fb_state)

                        if failover_content_yielded:
                            # Failover succeeded - record usage and return
                            log_info(f"Streaming failover to {failover_model} succeeded")
                            if failover_state and failover_state.web_searches_used > 0:
                                self._record_web_search_usage(failover_state.web_searches_used)
                            if failover_state and failover_state.web_fetches_used > 0:
                                self._record_web_fetch_usage(failover_state.web_fetches_used)
                            return

                        # Both models failed
                        log_warning(
                            f"Failover model {failover_model} also failed. Both models unavailable."
                        )
                        both_failed_state = StreamingState()
                        both_failed_state.stop_reason = "error"
                        both_failed_state._error_message = "Both models unavailable"
                        both_failed_state._error_type = "both_models_unavailable"
                        yield ("", both_failed_state)
                        return

                # Not failover-eligible or no failover model — yield original error
                yield ("", final_state)
                return

            # Record web search usage after streaming complete
            if final_state and final_state.web_searches_used > 0:
                self._record_web_search_usage(final_state.web_searches_used)

            # Record web fetch usage after streaming complete
            if final_state and final_state.web_fetches_used > 0:
                self._record_web_fetch_usage(final_state.web_fetches_used)

        except Exception as e:
            import traceback
            log_error(f"Router streaming error: {e}", prefix="🔍")
            log_error(f"Router traceback:\n{traceback.format_exc()}", prefix="🔍")
            # Yield error state
            error_state = StreamingState()
            error_state.stop_reason = "error"
            error_state._error_message = str(e)
            yield ("", error_state)

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

    def _check_web_fetch_availability(self) -> tuple[bool, Optional[int], Optional[Dict[str, Any]], Optional[str]]:
        """
        Check if web fetch should be enabled for this request.

        Returns:
            Tuple of (enable_web_fetch, max_uses, fetch_config, unavailable_message)
        """
        import config

        if not config.WEB_FETCH_ENABLED:
            return (False, None, None, None)

        try:
            from agency.web_fetch_limiter import get_web_fetch_limiter
            limiter = get_web_fetch_limiter()

            if not limiter.is_available():
                # Daily limit hit - notify Claude
                used, total = limiter.get_usage()
                log_warning(f"Web fetch daily limit reached ({used}/{total})")
                return (
                    False,
                    None,
                    None,
                    "<web_fetch_notice>Web fetch is unavailable today (daily limit reached). "
                    "Rely on your knowledge or web search snippets instead.</web_fetch_notice>"
                )

            # Web fetch is available - build config
            max_uses = limiter.get_max_for_request()

            # Build fetch config from settings + domain manager
            from agency.web_fetch_domains import get_web_fetch_domain_manager
            domain_mgr = get_web_fetch_domain_manager()
            domain_config = domain_mgr.get_domain_config()

            fetch_config = {}
            fetch_config.update(domain_config)  # allowed_domains, blocked_domains

            if config.WEB_FETCH_MAX_CONTENT_TOKENS:
                fetch_config["max_content_tokens"] = config.WEB_FETCH_MAX_CONTENT_TOKENS

            if config.WEB_FETCH_CITATIONS_ENABLED:
                fetch_config["citations"] = {"enabled": True}

            log_info(f"Web fetch enabled (max {max_uses} uses this request)", prefix="🌐")
            return (True, max_uses, fetch_config, None)

        except Exception as e:
            log_error(f"Web fetch limiter error, disabling web fetch: {e}")
            return (False, None, None, None)  # Gracefully disable web fetch

    def _record_web_fetch_usage(self, count: int) -> None:
        """Record web fetch usage to the limiter."""
        from agency.web_fetch_limiter import get_web_fetch_limiter
        limiter = get_web_fetch_limiter()
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
        enable_web_fetch: bool = False,
        web_fetch_max_uses: Optional[int] = None,
        web_fetch_config: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        task_type: TaskType = TaskType.CONVERSATION,
        thinking_enabled: bool = False,
        thinking_budget_tokens: Optional[int] = None,
        model_override: Optional[str] = None
    ) -> LLMResponse:
        """Send request to a specific provider."""
        try:
            if provider == LLMProvider.ANTHROPIC:
                client = self._get_anthropic()

                # Select model: use override if provided, else based on task type
                import config
                if model_override:
                    model = model_override
                elif task_type == TaskType.CONVERSATION:
                    # Check user preference first, fall back to config
                    from core.user_settings import get_user_settings
                    user_model = get_user_settings().conversation_model
                    model = user_model if user_model else config.ANTHROPIC_MODEL_CONVERSATION
                elif task_type in (TaskType.EXTRACTION, TaskType.FACT_EXTRACTION):
                    model = config.ANTHROPIC_MODEL_EXTRACTION  # Sonnet for extraction
                elif task_type == TaskType.DELEGATION:
                    model = config.DELEGATION_MODEL  # Haiku for delegated sub-tasks
                else:
                    model = config.ANTHROPIC_MODEL  # Default (Sonnet) for simple/analysis

                response = client.chat(
                    messages=messages,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    enable_web_search=enable_web_search,
                    web_search_max_uses=web_search_max_uses,
                    enable_web_fetch=enable_web_fetch,
                    web_fetch_max_uses=web_fetch_max_uses,
                    web_fetch_config=web_fetch_config,
                    tools=tools,
                    model=model,
                    thinking_enabled=thinking_enabled,
                    thinking_budget_tokens=thinking_budget_tokens
                )

                llm_response = LLMResponse(
                    text=response.text,
                    success=response.success,
                    provider=provider,
                    tokens_in=response.input_tokens,
                    tokens_out=response.output_tokens,
                    error=response.error,
                    error_type=response.error_type,
                    web_searches_used=response.web_searches_used,
                    web_fetches_used=response.web_fetches_used,
                    citations=response.citations,
                    stop_reason=response.stop_reason,
                    tool_calls=response.tool_calls,
                    raw_content=response.raw_content,
                    server_tool_details=response.server_tool_details,
                    thinking_text=response.thinking_text
                )

                # Log the API request/response
                log_api_request(
                    provider=provider.value,
                    model=model,  # Use the selected model, not client.model
                    system_prompt=system_prompt,
                    messages=messages,
                    settings={
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "web_search_enabled": enable_web_search,
                        "web_search_max_uses": web_search_max_uses,
                        "web_fetch_enabled": enable_web_fetch,
                        "web_fetch_max_uses": web_fetch_max_uses,
                        "thinking_enabled": thinking_enabled,
                        "thinking_budget_tokens": thinking_budget_tokens
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
