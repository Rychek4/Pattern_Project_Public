"""
Pattern Project - Memory Extractor
Background thread that extracts memories from conversations
"""

import threading
import time
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

from core.logger import log_info, log_warning, log_error, log_success
from core.temporal import get_temporal_tracker
from memory.conversation import get_conversation_manager, ConversationTurn
from memory.vector_store import get_vector_store
from llm.router import get_llm_router, TaskType
from concurrency.locks import get_lock_manager


# Prompt for memory extraction
EXTRACTION_PROMPT = """You are a memory extraction system. Analyze the following conversation and extract important memories.

For each memory, provide:
1. A concise statement of the memory (1-2 sentences)
2. The type: 'fact' (objective information), 'preference' (likes/dislikes), 'event' (something that happened), 'observation' (noticed pattern), or 'reflection' (insight/thought)
3. Importance: 0.0-1.0 (how important is this to remember?)
4. Temporal relevance: 'permanent' (always relevant), 'recent' (relevant now), or 'dated' (time-specific)

Output as JSON array:
[
  {
    "content": "The memory statement",
    "type": "fact|preference|event|observation|reflection",
    "importance": 0.0-1.0,
    "temporal_relevance": "permanent|recent|dated"
  }
]

If no significant memories are found, return an empty array: []

Conversation to analyze:
"""


class MemoryExtractor:
    """
    Background thread that extracts memories from conversations.

    Triggers based on:
    - Accumulated conversation turns
    - Session end
    - Manual trigger
    """

    def __init__(
        self,
        extraction_threshold: int = 10,
        check_interval: float = 60.0
    ):
        """
        Initialize the memory extractor.

        Args:
            extraction_threshold: Turns before triggering extraction
            check_interval: Seconds between extraction checks
        """
        self.extraction_threshold = extraction_threshold
        self.check_interval = check_interval
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock_manager = get_lock_manager()
        self._extraction_count = 0

    def start(self) -> None:
        """Start the background extraction thread."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._extraction_loop,
            daemon=True,
            name="MemoryExtractor"
        )
        self._thread.start()
        log_info("Memory extraction thread started", prefix="🧠")

    def stop(self) -> None:
        """Stop the background extraction thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        log_info("Memory extraction thread stopped", prefix="🧠")

    def _extraction_loop(self) -> None:
        """Main extraction loop."""
        while not self._stop_event.is_set():
            try:
                # Check if extraction is needed
                conversation_mgr = get_conversation_manager()
                unprocessed_count = conversation_mgr.get_unprocessed_count()

                if unprocessed_count >= self.extraction_threshold:
                    log_info(
                        f"Extraction triggered: {unprocessed_count} unprocessed turns",
                        prefix="🧠"
                    )
                    self.extract_memories()

            except Exception as e:
                log_error(f"Error in extraction loop: {e}")

            # Wait for next check
            self._stop_event.wait(self.check_interval)

    def extract_memories(self, force: bool = False) -> int:
        """
        Extract memories from unprocessed conversations.

        Args:
            force: Force extraction even if below threshold

        Returns:
            Number of memories extracted
        """
        with self._lock_manager.acquire("memory_extraction"):
            try:
                conversation_mgr = get_conversation_manager()
                vector_store = get_vector_store()
                router = get_llm_router()
                tracker = get_temporal_tracker()

                # Get unprocessed turns
                turns = conversation_mgr.get_unprocessed_turns(limit=50)

                if not turns and not force:
                    return 0

                if len(turns) < self.extraction_threshold and not force:
                    return 0

                # Format conversation for extraction
                conversation_text = self._format_conversation(turns)

                # Call local LLM for extraction
                response = router.generate(
                    prompt=EXTRACTION_PROMPT + conversation_text,
                    task_type=TaskType.EXTRACTION,
                    temperature=0.3,
                    max_tokens=1024
                )

                if not response.success:
                    log_error(f"Extraction LLM call failed: {response.error}")
                    return 0

                # Parse extracted memories
                memories = self._parse_extraction_response(response.text)

                if not memories:
                    log_info("No memories extracted from conversation")
                    # Still mark as processed
                    conversation_mgr.mark_processed([t.id for t in turns])
                    return 0

                # Store memories
                turn_ids = [t.id for t in turns]
                session_id = tracker.current_session_id
                source_time = turns[-1].created_at if turns else datetime.now()

                memories_created = 0
                for mem_data in memories:
                    memory_id = vector_store.add_memory(
                        content=mem_data["content"],
                        source_conversation_ids=turn_ids,
                        source_session_id=session_id,
                        source_timestamp=source_time,
                        importance=mem_data.get("importance", 0.5),
                        memory_type=mem_data.get("type"),
                        temporal_relevance=mem_data.get("temporal_relevance", "recent")
                    )
                    if memory_id:
                        memories_created += 1

                # Mark turns as processed
                conversation_mgr.mark_processed(turn_ids)

                self._extraction_count += memories_created
                log_success(
                    f"Extracted {memories_created} memories from {len(turns)} turns"
                )

                return memories_created

            except Exception as e:
                log_error(f"Memory extraction failed: {e}")
                return 0

    def _format_conversation(self, turns: List[ConversationTurn]) -> str:
        """Format conversation turns for extraction prompt."""
        lines = []
        for turn in turns:
            role = "Human" if turn.role == "user" else "AI"
            lines.append(f"{role}: {turn.content}")
        return "\n".join(lines)

    def _parse_extraction_response(self, response_text: str) -> List[Dict[str, Any]]:
        """Parse the JSON response from extraction LLM."""
        try:
            # Try to find JSON array in response
            text = response_text.strip()

            # Handle potential markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            # Find array brackets
            start = text.find("[")
            end = text.rfind("]") + 1

            if start == -1 or end == 0:
                return []

            json_str = text[start:end]
            memories = json.loads(json_str)

            # Validate structure
            valid_memories = []
            for mem in memories:
                if isinstance(mem, dict) and "content" in mem:
                    valid_memories.append({
                        "content": str(mem["content"]),
                        "type": mem.get("type", "observation"),
                        "importance": float(mem.get("importance", 0.5)),
                        "temporal_relevance": mem.get("temporal_relevance", "recent")
                    })

            return valid_memories

        except (json.JSONDecodeError, ValueError) as e:
            log_warning(f"Failed to parse extraction response: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Get extraction statistics."""
        return {
            "total_extractions": self._extraction_count,
            "is_running": self._thread is not None and self._thread.is_alive(),
            "threshold": self.extraction_threshold,
            "check_interval": self.check_interval
        }


# Global extractor instance
_extractor: Optional[MemoryExtractor] = None


def get_memory_extractor() -> MemoryExtractor:
    """Get the global memory extractor instance."""
    global _extractor
    if _extractor is None:
        from config import MEMORY_EXTRACTION_THRESHOLD, MEMORY_EXTRACTION_INTERVAL
        _extractor = MemoryExtractor(
            extraction_threshold=MEMORY_EXTRACTION_THRESHOLD,
            check_interval=MEMORY_EXTRACTION_INTERVAL
        )
    return _extractor


def init_memory_extractor() -> MemoryExtractor:
    """Initialize the global memory extractor."""
    global _extractor
    from config import MEMORY_EXTRACTION_THRESHOLD, MEMORY_EXTRACTION_INTERVAL
    _extractor = MemoryExtractor(
        extraction_threshold=MEMORY_EXTRACTION_THRESHOLD,
        check_interval=MEMORY_EXTRACTION_INTERVAL
    )
    return _extractor
