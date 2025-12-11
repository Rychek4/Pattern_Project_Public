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
        parts = [self.system_prompt] if self.system_prompt else []

        # Add context blocks sorted by priority
        sorted_blocks = sorted(self.context_blocks, key=lambda b: b.priority)
        for block in sorted_blocks:
            if block.content:
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
    from prompt_builder.sources.conversation import ConversationSource
    from prompt_builder.sources.temporal import TemporalSource
    from prompt_builder.sources.visual import VisualSource
    from prompt_builder.sources.system_pulse import SystemPulseSource
    from prompt_builder.sources.ai_commands import AICommandsSource
    from prompt_builder.sources.intention_source import IntentionSource
    from prompt_builder.sources.dev_mode import DevModeSource
    from prompt_builder.sources.active_thoughts import ActiveThoughtsSource

    builder = PromptBuilder()

    log_section("Initializing PromptBuilder", "🔧")

    # Register sources in priority order (though they're sorted anyway)
    sources = [
        DevModeSource(),        # Dev mode awareness (priority 5) - first if enabled
        CoreMemorySource(),     # Core identity (priority 10)
        ActiveThoughtsSource(), # AI's working memory (priority 18)
        IntentionSource(),      # AI's forward-looking memory (priority 22)
        SystemPulseSource(),
        AICommandsSource(),
        TemporalSource(),
        VisualSource(),
        SemanticMemorySource(),
        ConversationSource(),
    ]

    # Add goal tree and agency economy sources if enabled
    if config.AGENCY_ECONOMY_ENABLED:
        from prompt_builder.sources.goal_tree import GoalTreeSource
        from prompt_builder.sources.agency_economy import AgencyEconomySource
        sources.insert(2, GoalTreeSource())      # Priority 15 - after core memory
        sources.insert(3, AgencyEconomySource()) # Priority 16 - after goal tree

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
