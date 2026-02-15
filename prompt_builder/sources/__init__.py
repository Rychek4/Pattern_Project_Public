"""
Pattern Project - Context Sources
Pluggable sources for prompt context injection
"""

from prompt_builder.sources.base import ContextSource, ContextBlock
from prompt_builder.sources.core_memory import CoreMemorySource
from prompt_builder.sources.semantic_memory import SemanticMemorySource
from prompt_builder.sources.conversation import ConversationSource
from prompt_builder.sources.temporal import TemporalSource
from prompt_builder.sources.visual import VisualSource

__all__ = [
    "ContextSource",
    "ContextBlock",
    "CoreMemorySource",
    "SemanticMemorySource",
    "ConversationSource",
    "TemporalSource",
    "VisualSource",
]
