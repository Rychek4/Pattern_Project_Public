"""
Pattern Project - Base Context Source
Abstract interface for all context sources
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from enum import IntEnum


class SourcePriority(IntEnum):
    """
    Priority levels for context sources.
    Lower numbers = higher priority (included first in prompt).
    """
    CORE_MEMORY = 10       # Foundational, always included
    SYSTEM_PULSE = 25      # Pulse timer control (AI agency)
    AI_COMMANDS = 26       # Memory search, future AI-initiated commands
    TEMPORAL = 30          # Time awareness
    VISUAL = 40            # Current visual context
    SEMANTIC_MEMORY = 50   # Retrieved memories
    CONVERSATION = 60      # Recent exchanges
    # Future sources can use 70, 80, 90, etc.


@dataclass
class ContextBlock:
    """
    A block of context from a source.

    Attributes:
        source_name: Identifier for the source
        content: The formatted context text
        priority: Lower = higher priority (placed earlier in prompt)
        include_always: If True, never skip this block
        metadata: Additional data about this block
    """
    source_name: str
    content: str
    priority: int
    include_always: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        """Block is truthy if it has content."""
        return bool(self.content and self.content.strip())


class ContextSource(ABC):
    """
    Abstract base class for context sources.

    Each source is responsible for:
    1. Gathering relevant data from its domain
    2. Formatting it for prompt injection
    3. Returning a ContextBlock (or None if no context)

    Sources are pluggable - new sources can be added without
    modifying the PromptBuilder.
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier for this source."""
        pass

    @property
    @abstractmethod
    def priority(self) -> int:
        """
        Priority for ordering in prompt.
        Use SourcePriority enum values.
        """
        pass

    @abstractmethod
    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """
        Generate context block for the current prompt.

        Args:
            user_input: The user's current message
            session_context: Shared context dict for cross-source data
                Keys may include:
                - 'session_id': Current session ID
                - 'turn_count': Number of turns this session
                - 'user_id': User identifier (if applicable)
                - Additional keys added by other sources

        Returns:
            ContextBlock with formatted context, or None if no context
        """
        pass

    def initialize(self) -> bool:
        """
        Optional initialization hook.
        Called when source is registered with PromptBuilder.

        Returns:
            True if initialization successful
        """
        return True

    def shutdown(self) -> None:
        """
        Optional cleanup hook.
        Called when PromptBuilder is shutting down.
        """
        pass
