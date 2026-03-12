"""
Pattern Project - Memory Self-Model Source
Injects the memory self-model into the cached region of the system prompt.

The self-model is a compact block (~150-200 tokens) written in natural
self-knowledge register. Updated during reflective pulse metacognition.
Present every turn alongside core memory at P10.
"""

from typing import Optional, Dict, Any

from prompt_builder.sources.base import ContextSource, ContextBlock, SourcePriority
from core.database import get_database
from core.logger import log_error


class MemorySelfModelSource(ContextSource):
    """
    Reads the memory self-model from the state table and injects it
    into the cached region of the system prompt at P10.

    Returns None if no self-model exists yet (first run before any
    reflection cycle has produced one).
    """

    @property
    def source_name(self) -> str:
        return "memory_self_model"

    @property
    def priority(self) -> int:
        return SourcePriority.CORE_MEMORY  # P10, cached alongside core memory

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """Get the memory self-model if one exists."""
        try:
            db = get_database()
            content = db.get_state("memory_self_model")

            if not content or not isinstance(content, str) or not content.strip():
                return None

            return ContextBlock(
                source_name=self.source_name,
                content=f"[Memory Self-Awareness]\n{content.strip()}",
                priority=self.priority,
                include_always=True,
            )
        except Exception as e:
            log_error(f"MemorySelfModelSource: Failed to read self-model: {e}")
            return None
