"""
Pattern Project - Prompt Builder
Orchestrates context sources to assemble rich, self-contained prompts
"""

from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from prompt_builder.sources.base import ContextSource, ContextBlock
from core.logger import log_info, log_error, log_section


@dataclass
class AssembledPrompt:
    """The final assembled prompt with metadata."""
    system_prompt: str
    user_message: str
    context_blocks: List[ContextBlock]
    session_context: Dict[str, Any]

    @property
    def full_system_prompt(self) -> str:
        """Get complete system prompt with all context."""
        import config

        parts = [self.system_prompt] if self.system_prompt else []

        # Add context blocks sorted by priority, inserting a cache breakpoint
        # between stable and dynamic content when prompt caching is enabled.
        sorted_blocks = sorted(self.context_blocks, key=lambda b: b.priority)
        breakpoint_inserted = False
        for block in sorted_blocks:
            if block.content:
                if (not breakpoint_inserted
                        and config.PROMPT_CACHE_ENABLED
                        and block.priority > config.PROMPT_CACHE_STABLE_PRIORITY):
                    parts.append(config.PROMPT_CACHE_BREAKPOINT)
                    breakpoint_inserted = True
                parts.append(block.content)

        return "\n\n".join(parts)


class PromptBuilder:
    """
    Orchestrates context sources to build rich prompts.

    Features:
    - Pluggable source architecture
    - Priority-based ordering
    - Session context sharing between sources
    - Fresh, self-contained prompts (no context accumulation)
    """

    def __init__(self):
        self._sources: List[ContextSource] = []
        self._initialized = False

    def register_source(self, source: ContextSource) -> bool:
        """
        Register a context source.

        Args:
            source: The context source to register

        Returns:
            True if registration successful
        """
        try:
            # Initialize the source
            if not source.initialize():
                log_error(f"Failed to initialize source: {source.source_name}")
                return False

            # Add and sort by priority
            self._sources.append(source)
            self._sources.sort(key=lambda s: s.priority)

            log_info(f"Registered source: {source.source_name} (priority {source.priority})")
            return True

        except Exception as e:
            log_error(f"Error registering source {source.source_name}: {e}")
            return False

    def unregister_source(self, source_name: str) -> bool:
        """
        Unregister a context source by name.

        Args:
            source_name: Name of the source to remove

        Returns:
            True if source was found and removed
        """
        for i, source in enumerate(self._sources):
            if source.source_name == source_name:
                source.shutdown()
                self._sources.pop(i)
                log_info(f"Unregistered source: {source_name}")
                return True
        return False

    def build(
        self,
        user_input: str,
        system_prompt: str = "",
        additional_context: Optional[Dict[str, Any]] = None
    ) -> AssembledPrompt:
        """
        Build a complete prompt from all registered sources.

        Args:
            user_input: The user's current message
            system_prompt: Base system prompt (persona, guidelines)
            additional_context: Extra context to pass to sources

        Returns:
            AssembledPrompt with all context assembled
        """
        # Initialize session context
        session_context: Dict[str, Any] = additional_context.copy() if additional_context else {}

        # Gather context from all sources
        blocks: List[ContextBlock] = []

        for source in self._sources:
            try:
                block = source.get_context(user_input, session_context)
                if block and block.content:
                    blocks.append(block)
            except Exception as e:
                log_error(f"Error getting context from {source.source_name}: {e}")
                # Continue with other sources

        return AssembledPrompt(
            system_prompt=system_prompt,
            user_message=user_input,
            context_blocks=blocks,
            session_context=session_context
        )

    def build_messages(
        self,
        user_input: str,
        system_prompt: str = "",
        additional_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build prompt in format ready for LLM API call.

        Args:
            user_input: The user's current message
            system_prompt: Base system prompt
            additional_context: Extra context for sources

        Returns:
            Dict with 'system' and 'messages' keys
        """
        assembled = self.build(user_input, system_prompt, additional_context)

        # Get conversation history from conversation source if available
        messages = []
        conversation_block = next(
            (b for b in assembled.context_blocks if b.source_name == "conversation"),
            None
        )

        if conversation_block and "raw_history" in conversation_block.metadata:
            messages = conversation_block.metadata["raw_history"]

        # Add current user message
        messages.append({
            "role": "user",
            "content": user_input
        })

        return {
            "system": assembled.full_system_prompt,
            "messages": messages,
            "session_context": assembled.session_context
        }

    def get_source(self, source_name: str) -> Optional[ContextSource]:
        """Get a registered source by name."""
        for source in self._sources:
            if source.source_name == source_name:
                return source
        return None

    def list_sources(self) -> List[str]:
        """Get list of registered source names."""
        return [s.source_name for s in self._sources]

    def shutdown(self) -> None:
        """Shutdown all sources."""
        for source in self._sources:
            try:
                source.shutdown()
            except Exception as e:
                log_error(f"Error shutting down {source.source_name}: {e}")

        self._sources.clear()
        log_info("PromptBuilder shutdown complete")


def create_default_builder() -> PromptBuilder:
    """
    Create a PromptBuilder with default sources.

    Returns:
        Configured PromptBuilder
    """
    import config
    from prompt_builder.sources.core_memory import CoreMemorySource
    from prompt_builder.sources.semantic_memory import SemanticMemorySource
    # ConversationSource DEPRECATED: Now using API messages with timestamps directly
    # Conversation context is provided via get_api_messages() in the messages array
    # instead of duplicating it in the system prompt. See memory/conversation.py
    from prompt_builder.sources.temporal import TemporalSource
    from prompt_builder.sources.system_pulse import SystemPulseSource
    from prompt_builder.sources.ai_commands import AICommandsSource
    from prompt_builder.sources.intention_source import IntentionSource
    from prompt_builder.sources.dev_mode import DevModeSource
    from prompt_builder.sources.active_thoughts import ActiveThoughtsSource
    from prompt_builder.sources.growth_threads import GrowthThreadsSource

    builder = PromptBuilder()

    log_section("Initializing PromptBuilder", "🔧")

    # Register sources in priority order (though they're sorted anyway)
    # NOTE: ConversationSource removed - conversation context now provided via
    # get_api_messages() in the messages array with semantic timestamps.
    # This eliminates duplicate tokens and provides unified time awareness.
    sources = [
        DevModeSource(),        # Dev mode awareness (priority 5) - first if enabled
        CoreMemorySource(),     # Core identity (priority 10)
        ActiveThoughtsSource(), # AI's working memory (priority 18)
        GrowthThreadsSource(),  # AI's developmental aspirations (priority 20)
        IntentionSource(),      # AI's forward-looking memory (priority 22)
        SystemPulseSource(),
        AICommandsSource(),
        TemporalSource(),
        SemanticMemorySource(),
    ]

    # Tool stance source (if enabled) - proactive tool usage guidance
    if getattr(config, 'TOOL_STANCE_ENABLED', True):
        from prompt_builder.sources.tool_stance import ToolStanceSource
        sources.append(ToolStanceSource())
        log_info("ToolStanceSource enabled", prefix="🔧")

    # Curiosity source (if enabled) - provides topic exploration context
    if getattr(config, 'CURIOSITY_ENABLED', True):
        from agency.curiosity.source import CuriositySource
        sources.append(CuriositySource())
        log_info("CuriositySource enabled", prefix="🔍")

    # Pattern breaker source (if enabled) - periodic nudge to break context loops
    if getattr(config, 'PATTERN_BREAKER_ENABLED', True):
        from prompt_builder.sources.pattern_breaker import PatternBreakerSource
        sources.append(PatternBreakerSource())
        log_info("PatternBreakerSource enabled", prefix="🔄")

    # Self-correction source (if enabled) - per-turn nudge to catch own errors
    if getattr(config, 'SELF_CORRECTION_ENABLED', True):
        from prompt_builder.sources.self_correction import SelfCorrectionSource
        sources.append(SelfCorrectionSource())
        log_info("SelfCorrectionSource enabled", prefix="🔍")

    # Legacy VisualSource is disabled - the new visual capture system sends images
    # directly to Claude via multimodal messages. VisualSource (which used Gemini
    # for text descriptions) is kept in code for potential fallback but not loaded.
    log_info("VisualSource disabled (using direct Claude multimodal)", prefix="📷")

    for source in sources:
        builder.register_source(source)

    log_info(f"PromptBuilder ready with {len(builder.list_sources())} sources")

    return builder


# Global instance
_prompt_builder: Optional[PromptBuilder] = None


def get_prompt_builder() -> PromptBuilder:
    """Get the global PromptBuilder instance."""
    global _prompt_builder
    if _prompt_builder is None:
        _prompt_builder = create_default_builder()
    return _prompt_builder


def init_prompt_builder() -> PromptBuilder:
    """Initialize the global PromptBuilder."""
    global _prompt_builder
    _prompt_builder = create_default_builder()
    return _prompt_builder
