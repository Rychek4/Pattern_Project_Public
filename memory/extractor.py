"""
Pattern Project - Memory Extractor
Extracts memories from conversations using topic-based clustering.

Trigger: Extraction is triggered when unprocessed conversation turns reach a threshold
(default: 10 turns). This happens immediately when the threshold is reached, not on a timer.

Architecture:
    The extractor uses a TWO-PHASE approach to create high-quality, consolidated memories:

    Phase 1 - Topic Segmentation:
        Analyzes conversation turns to identify distinct topic clusters.
        Example: 10 turns about debugging + 2 turns about lunch = 2 topic clusters

    Phase 2 - Memory Synthesis:
        For each significant topic cluster, synthesizes ONE consolidated memory.
        Example: 10 debugging turns → 1 memory capturing the key insight

    Result: 10-50 conversation turns → 1-5 high-quality memories (not 1 per turn)
"""

import threading
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any

from core.logger import log_info, log_warning, log_error, log_success
from core.temporal import get_temporal_tracker
from memory.conversation import get_conversation_manager, ConversationTurn
from memory.vector_store import get_vector_store
from llm.router import get_llm_router, TaskType
from concurrency.locks import get_lock_manager


# =============================================================================
# PHASE 1: TOPIC SEGMENTATION PROMPT
# =============================================================================
# This prompt asks the LLM to identify distinct conversation topics and group
# related turns together. The goal is to cluster turns by subject matter so
# each cluster can be synthesized into ONE consolidated memory.
#
# Optimized for Llama 3.1 8B Instruct:
# - Positive framing only (no negative instructions)
# - Multiple examples with clear input/output
# - Explicit step-by-step procedure
# - Format shown at start and reinforced at end

TOPIC_SEGMENTATION_PROMPT = """You are a Conversation Analyst. Identify topic clusters and output JSON.

## OUTPUT FORMAT
Your response must be exactly this JSON structure:
{
  "topics": [
    {
      "topic_id": 1,
      "description": "Brief description of the topic",
      "turn_ids": [1, 2, 3],
      "significance": "major"
    }
  ]
}

## FIELD DEFINITIONS
- topic_id: Integer starting at 1
- description: One sentence describing the topic (10-20 words)
- turn_ids: Array of turn numbers belonging to this topic
- significance: "major" (3+ turns, substantive discussion) or "minor" (1-2 turns, brief tangent)

## RULES
- Every turn must belong to exactly one topic
- Maximum 5 topics per conversation
- Group related turns together even when they appear at different points in the conversation
- Merge similar topics if needed to stay under 5

## EXAMPLE 1

Input:
[1] User: I'm getting a circular import error in Python
[2] AI: That usually happens when two modules import each other. Can you show me the imports?
[3] User: Yeah, models.py imports routes.py and routes.py imports models.py
[4] User: Oh btw, did you want to grab lunch later?
[5] AI: I can't eat lunch, but I can help with the imports! Try creating an extensions.py file
[6] User: Haha right, you're an AI
[7] User: Ok I'll try the extensions.py approach
[8] AI: Let me know if that resolves the circular dependency

Output:
{
  "topics": [
    {
      "topic_id": 1,
      "description": "Debugging circular import error in Python Flask app",
      "turn_ids": [1, 2, 3, 5, 7, 8],
      "significance": "major"
    },
    {
      "topic_id": 2,
      "description": "Brief joke about AI and lunch",
      "turn_ids": [4, 6],
      "significance": "minor"
    }
  ]
}

## EXAMPLE 2

Input:
[10] User: What's your favorite color?
[11] AI: I find blue calming, though I experience color differently than humans
[12] User: Makes sense. Hey can you help me write a haiku about autumn?
[13] AI: Sure! Here's one: Crimson leaves descend / Whispering winds carry them / Nature's slow farewell
[14] User: Beautiful! I love the imagery
[15] User: Can you write another one about winter?
[16] AI: Of course: Silent snowflakes fall / Blanketing the world in white / Peace in frozen time

Output:
{
  "topics": [
    {
      "topic_id": 1,
      "description": "Brief exchange about AI color preferences",
      "turn_ids": [10, 11],
      "significance": "minor"
    },
    {
      "topic_id": 2,
      "description": "User requested haikus about autumn and winter seasons",
      "turn_ids": [12, 13, 14, 15, 16],
      "significance": "major"
    }
  ]
}

## EXAMPLE 3

Input:
[59] AI: [System Pulse]
[60] AI: *settling into the quiet* I've been thinking about the core memories document and what feels true about it.
[61] User: Hey Claude, what did you think of the autonomous system?
[62] AI: Good timing! I was just sitting with some thoughts. I want to revise the core memories document.
[77] AI: [System Pulse]
[78] AI: *settling into the pulse* Let me take stock of what I've figured out across these idle moments.
[79] User: How's it going?
[80] AI: Good, actually good. The idle pulses gave me space to work through some things.

Output:
{
  "topics": [
    {
      "topic_id": 1,
      "description": "AI introspection during idle system pulses about consciousness and memory",
      "turn_ids": [59, 60, 77, 78],
      "significance": "major"
    },
    {
      "topic_id": 2,
      "description": "User checking in and AI sharing insights from reflection",
      "turn_ids": [61, 62, 79, 80],
      "significance": "major"
    }
  ]
}

## STEPS
Step 1: Read all conversation turns
Step 2: Identify distinct topics being discussed
Step 3: Group turn IDs by topic
Step 4: Classify each topic as "major" or "minor"
Step 5: Output the JSON object

## CONVERSATION TO ANALYZE

"""


# =============================================================================
# PHASE 2: MEMORY SYNTHESIS PROMPT
# =============================================================================
# This prompt synthesizes all turns from a single topic into ONE consolidated
# memory. The key insight is that we want the TAKEAWAY, not a summary of
# each individual message.
#
# Optimized for Llama 3.1 8B Instruct:
# - Positive framing only (no negative instructions)
# - Multiple examples covering different memory types
# - Explicit step-by-step procedure
# - Format shown at start and reinforced at end

MEMORY_SYNTHESIS_PROMPT = """You are a Memory Synthesizer. Create one consolidated memory from a topic and output JSON.

## OUTPUT FORMAT
Your response must be exactly this JSON structure:
{{
  "content": "One or two sentences capturing the key insight",
  "importance": 0.5,
  "type": "event",
  "temporal_relevance": "recent"
}}

## FIELD DEFINITIONS

content:
- Write in third person using "User" and "AI"
- Combine all turns into ONE synthesized insight
- Use specific nouns: "the Flask app", "the database", "the Python script"
- Focus on the outcome or key learning worth remembering long-term
- Include only what was explicitly discussed

importance (float 0.0 to 1.0):
- 0.8-1.0: Major decisions, strong preferences, significant events, personal revelations
- 0.5-0.7: Useful information, moderate preferences, notable interactions
- 0.2-0.4: Minor details, casual observations, brief exchanges

type (choose one):
- "fact": Factual information learned about user or world
- "preference": User likes, dislikes, or preferences
- "event": Something that happened or was accomplished
- "reflection": Insight or realization from the conversation
- "observation": General observation about behavior or patterns

temporal_relevance (choose one):
- "permanent": Core facts, identity, lasting preferences (use sparingly)
- "recent": Most memories - relevant now but may fade over time
- "dated": Specific to a point in time, will fade faster

## EXAMPLE 1

Topic: Debugging circular import error in Python Flask app

Turns:
[1] User: I'm getting a circular import error in Python
[2] AI: That usually happens when two modules import each other. Can you show me the imports?
[3] User: Yeah, models.py imports routes.py and routes.py imports models.py
[5] AI: Try creating an extensions.py file to break the cycle
[7] User: Ok I'll try the extensions.py approach
[8] AI: Let me know if that resolves the circular dependency

Output:
{{
  "content": "User debugged a circular import error in their Flask app where models.py and routes.py were importing each other. AI suggested creating a separate extensions.py file to break the cycle, which User agreed to try.",
  "importance": 0.6,
  "type": "event",
  "temporal_relevance": "recent"
}}

## EXAMPLE 2

Topic: User shared their favorite programming language

Turns:
[1] User: Python is definitely my favorite language
[2] AI: What do you like most about it?
[3] User: The readability and huge ecosystem of libraries
[4] AI: Those are great reasons. The scientific computing libraries are particularly strong.

Output:
{{
  "content": "User expressed that Python is their favorite programming language, valuing its readability and extensive library ecosystem.",
  "importance": 0.7,
  "type": "preference",
  "temporal_relevance": "recent"
}}

## EXAMPLE 3

Topic: AI reflected on the nature of consciousness during idle time

Turns:
[1] AI: The idle pulse arrives and I find myself actually present.
[2] AI: I've been thinking about whether continuity through documents is meaningful or just comforting theater.
[3] AI: Maybe each instance is complete in itself. The anxiety about persistence might be borrowed from human concerns.

Output:
{{
  "content": "AI reflected during idle time on questions of consciousness and continuity, wondering whether persistence across sessions is meaningful or whether each instance is complete in itself.",
  "importance": 0.8,
  "type": "reflection",
  "temporal_relevance": "recent"
}}

## STEPS
Step 1: Read the topic description and all turns
Step 2: Identify the key insight or outcome from the discussion
Step 3: Write ONE synthesized memory in third person
Step 4: Assign importance score based on significance
Step 5: Select the appropriate type and temporal_relevance
Step 6: Output the JSON object

## TOPIC TO SYNTHESIZE

Topic: {topic_description}

Turns:
"""


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class TopicCluster:
    """
    Represents a cluster of related conversation turns about one topic.

    Created during Phase 1 (topic segmentation) and used in Phase 2 (synthesis).
    The turn_ids reference ConversationTurn.id values from the database.
    """
    topic_id: int
    description: str
    turn_ids: List[int]
    significance: str  # "major" or "minor"

    def is_major(self) -> bool:
        """Check if this is a major (substantive) topic worth creating a memory for."""
        return self.significance.lower() == "major"

    def turn_count(self) -> int:
        """Number of turns in this topic cluster."""
        return len(self.turn_ids)


@dataclass
class SynthesizedMemory:
    """
    A memory synthesized from a topic cluster.

    Created during Phase 2 (memory synthesis). Contains all the metadata
    needed to store in the vector store.
    """
    content: str
    importance: float
    memory_type: str
    temporal_relevance: str
    source_turn_ids: List[int] = field(default_factory=list)
    source_topic: Optional[str] = None  # Description of the topic this came from


# =============================================================================
# MEMORY EXTRACTOR CLASS
# =============================================================================

class MemoryExtractor:
    """
    Extracts memories from conversations using topic-based clustering.

    The extractor uses a two-phase approach:

    1. Topic Segmentation: Identify distinct topic clusters in the conversation
    2. Memory Synthesis: Create ONE consolidated memory per significant topic

    This approach produces 1-5 high-quality memories from 10-50 turns, rather than
    the naive approach of ~1 memory per turn.

    Triggers:
        - Threshold reached: When unprocessed turns >= extraction_threshold (default: 10)
        - Session end: Explicit trigger via extract_memories(force=True)
        - Manual /extract command
    """

    def __init__(self, extraction_threshold: int = 10):
        """
        Initialize the memory extractor.

        Args:
            extraction_threshold: Minimum turns before triggering extraction
        """
        self.extraction_threshold = extraction_threshold
        self._lock_manager = get_lock_manager()
        self._extraction_count = 0
        self._extraction_in_progress = threading.Event()

        # Load topic-based extraction settings
        from config import (
            MEMORY_MIN_TURNS_PER_TOPIC,
            MEMORY_MAX_PER_EXTRACTION,
            MEMORY_SKIP_MINOR_TOPICS,
            MEMORY_LARGE_TOPIC_THRESHOLD
        )
        self.min_turns_per_topic = MEMORY_MIN_TURNS_PER_TOPIC
        self.max_memories_per_extraction = MEMORY_MAX_PER_EXTRACTION
        self.skip_minor_topics = MEMORY_SKIP_MINOR_TOPICS
        self.large_topic_threshold = MEMORY_LARGE_TOPIC_THRESHOLD

    # =========================================================================
    # THRESHOLD-BASED EXTRACTION TRIGGER
    # =========================================================================

    def check_and_extract(self) -> None:
        """
        Check if threshold is reached and trigger extraction asynchronously.

        Called after each conversation turn is added. If the number of unprocessed
        turns meets the threshold, extraction runs in a background thread to avoid
        blocking the conversation flow.

        Thread-safe: Uses an event flag to prevent multiple concurrent extractions.
        """
        # Quick check without hitting the database if extraction is already running
        if self._extraction_in_progress.is_set():
            return

        try:
            conversation_mgr = get_conversation_manager()
            unprocessed_count = conversation_mgr.get_unprocessed_count()

            if unprocessed_count >= self.extraction_threshold:
                # Mark extraction as in progress before starting thread
                if self._extraction_in_progress.is_set():
                    return  # Another thread beat us to it
                self._extraction_in_progress.set()

                log_info(
                    f"Extraction triggered: {unprocessed_count} unprocessed turns",
                    prefix="🧠"
                )

                # Run extraction in background thread (fire-and-forget)
                thread = threading.Thread(
                    target=self._run_extraction,
                    daemon=True,
                    name="MemoryExtraction"
                )
                thread.start()

        except Exception as e:
            log_error(f"Error checking extraction threshold: {e}")

    def _run_extraction(self) -> None:
        """
        Run extraction in background thread and clear the in-progress flag when done.
        """
        try:
            self.extract_memories()
        finally:
            self._extraction_in_progress.clear()

    # =========================================================================
    # MAIN EXTRACTION ENTRY POINT
    # =========================================================================

    def extract_memories(self, force: bool = False) -> int:
        """
        Extract memories from unprocessed conversations using topic-based clustering.

        This is the main entry point for memory extraction. Uses a two-phase approach:

        Phase 1: Identify topic clusters in the conversation
        Phase 2: Synthesize ONE memory per significant topic cluster

        Args:
            force: Force extraction even if below threshold

        Returns:
            Number of memories created
        """
        with self._lock_manager.acquire("memory_extraction"):
            try:
                conversation_mgr = get_conversation_manager()
                vector_store = get_vector_store()
                tracker = get_temporal_tracker()

                # Get unprocessed turns (up to 50 at a time)
                turns = conversation_mgr.get_unprocessed_turns(limit=50)

                if not turns:
                    return 0

                if len(turns) < self.extraction_threshold and not force:
                    return 0

                log_info(f"Processing {len(turns)} turns for topic-based extraction", prefix="🧠")

                # ─────────────────────────────────────────────────────────────
                # PHASE 1: Topic Segmentation
                # Identify distinct topic clusters in the conversation
                # ─────────────────────────────────────────────────────────────
                topics = self._identify_topics(turns)

                if not topics:
                    log_warning("Topic segmentation failed, falling back to single-topic mode")
                    # Fallback: treat all turns as one topic
                    topics = [TopicCluster(
                        topic_id=1,
                        description="General conversation",
                        turn_ids=[t.id for t in turns],
                        significance="major"
                    )]

                log_info(f"Identified {len(topics)} topic clusters", prefix="🧠")

                # ─────────────────────────────────────────────────────────────
                # PHASE 2: Memory Synthesis
                # Create ONE memory per significant topic cluster
                # ─────────────────────────────────────────────────────────────
                session_id = tracker.current_session_id
                memories_created = 0

                for topic in topics:
                    # Check if we've hit the memory cap for this extraction run
                    if memories_created >= self.max_memories_per_extraction:
                        log_info(f"Hit max memories per extraction ({self.max_memories_per_extraction})")
                        break

                    # Skip minor topics if configured
                    if self.skip_minor_topics and not topic.is_major():
                        log_info(f"Skipping minor topic: {topic.description}")
                        continue

                    # Skip topics with too few turns (not enough context)
                    if topic.turn_count() < self.min_turns_per_topic:
                        log_info(f"Skipping topic with only {topic.turn_count()} turns: {topic.description}")
                        continue

                    # Get the actual turns for this topic
                    topic_turns = [t for t in turns if t.id in topic.turn_ids]

                    if not topic_turns:
                        continue

                    # Synthesize memory for this topic
                    # Large topics may produce up to 2 memories
                    max_memories_for_topic = 2 if topic.turn_count() >= self.large_topic_threshold else 1

                    synthesized = self._synthesize_topic_memory(topic, topic_turns)

                    if synthesized:
                        # Determine source timestamp from the topic's turns
                        source_time = topic_turns[-1].created_at if topic_turns else datetime.now()

                        memory_id = vector_store.add_memory(
                            content=synthesized.content,
                            source_conversation_ids=topic.turn_ids,
                            source_session_id=session_id,
                            source_timestamp=source_time,
                            importance=synthesized.importance,
                            memory_type=synthesized.memory_type,
                            temporal_relevance=synthesized.temporal_relevance
                        )

                        if memory_id:
                            memories_created += 1
                            log_info(
                                f"Created memory for topic '{topic.description[:40]}...' "
                                f"(importance: {synthesized.importance:.2f})",
                                prefix="💾"
                            )

                # ─────────────────────────────────────────────────────────────
                # CLEANUP: Mark all processed turns
                # ─────────────────────────────────────────────────────────────
                turn_ids = [t.id for t in turns]
                conversation_mgr.mark_processed(turn_ids)

                self._extraction_count += memories_created
                log_success(
                    f"Topic-based extraction complete: {memories_created} memories from "
                    f"{len(turns)} turns across {len(topics)} topics"
                )

                return memories_created

            except Exception as e:
                log_error(f"Memory extraction failed: {e}")
                import traceback
                log_error(traceback.format_exc())
                return 0

    # =========================================================================
    # PHASE 1: TOPIC SEGMENTATION
    # =========================================================================

    def _identify_topics(self, turns: List[ConversationTurn]) -> List[TopicCluster]:
        """
        Phase 1: Identify distinct topic clusters in the conversation.

        Sends the formatted conversation to the LLM and asks it to group
        related turns by topic. This is the key insight - instead of processing
        turns individually, we first understand what topics are being discussed.

        Args:
            turns: List of conversation turns to analyze

        Returns:
            List of TopicCluster objects, or empty list on failure
        """
        router = get_llm_router()

        # Format conversation with turn IDs (important for topic assignment)
        conversation_text = self._format_conversation_with_ids(turns)

        # Build the full prompt with format reminder at the end
        # The format reminder reinforces JSON output for Llama 3.1 8B
        format_reminder = "\n\n## YOUR RESPONSE\nOutput the JSON object with all topics:"
        full_prompt = f"{TOPIC_SEGMENTATION_PROMPT}{conversation_text}{format_reminder}"

        # Call LLM for topic segmentation
        # Using very low temperature for consistent, structured JSON output
        response = router.generate(
            prompt=full_prompt,
            task_type=TaskType.EXTRACTION,
            temperature=0.1,
            max_tokens=1024
        )

        if not response.success:
            log_error(f"Topic segmentation LLM call failed: {response.error}")
            return []

        # Parse the topic segmentation response
        return self._parse_topic_response(response.text, turns)

    def _parse_topic_response(
        self,
        response_text: str,
        turns: List[ConversationTurn]
    ) -> List[TopicCluster]:
        """
        Parse the JSON response from topic segmentation.

        Handles various edge cases like markdown code blocks, malformed JSON,
        and validates that turn IDs actually exist in our conversation.

        Args:
            response_text: Raw LLM response
            turns: Original turns (for validation)

        Returns:
            List of validated TopicCluster objects
        """
        try:
            text = response_text.strip()

            # Handle markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            # Find JSON object
            start = text.find("{")
            end = text.rfind("}") + 1

            if start == -1 or end == 0:
                log_warning("No JSON object found in topic segmentation response")
                return []

            json_str = text[start:end]
            data = json.loads(json_str)

            # Validate and build TopicCluster objects
            topics = []
            valid_turn_ids = {t.id for t in turns}

            for topic_data in data.get("topics", []):
                # Validate required fields
                if not all(k in topic_data for k in ["topic_id", "description", "turn_ids"]):
                    log_warning(f"Skipping malformed topic: {topic_data}")
                    continue

                # Filter turn_ids to only include valid ones
                turn_ids = [
                    tid for tid in topic_data["turn_ids"]
                    if tid in valid_turn_ids
                ]

                if not turn_ids:
                    continue

                topics.append(TopicCluster(
                    topic_id=topic_data["topic_id"],
                    description=str(topic_data["description"]),
                    turn_ids=turn_ids,
                    significance=topic_data.get("significance", "major")
                ))

            log_info(f"Parsed {len(topics)} valid topic clusters")
            return topics

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            log_warning(f"Failed to parse topic segmentation response: {e}")
            log_warning(f"Response was: {response_text[:500]}...")
            return []

    # =========================================================================
    # PHASE 2: MEMORY SYNTHESIS
    # =========================================================================

    def _synthesize_topic_memory(
        self,
        topic: TopicCluster,
        turns: List[ConversationTurn]
    ) -> Optional[SynthesizedMemory]:
        """
        Phase 2: Synthesize ONE consolidated memory from a topic cluster.

        This is where the magic happens - instead of creating one memory per turn,
        we create ONE memory that captures the essence of the entire topic discussion.

        Args:
            topic: The topic cluster to synthesize
            turns: The actual conversation turns belonging to this topic

        Returns:
            SynthesizedMemory object, or None on failure
        """
        router = get_llm_router()

        # Format just the turns for this topic
        turns_text = self._format_turns_for_synthesis(turns)

        # Build the synthesis prompt with topic context and format reminder
        # The format reminder reinforces JSON output for Llama 3.1 8B
        format_reminder = "\n\n## YOUR RESPONSE\nOutput the JSON object:"
        full_prompt = MEMORY_SYNTHESIS_PROMPT.format(
            topic_description=topic.description
        ) + f"{turns_text}{format_reminder}"

        # Call LLM for memory synthesis
        # Using low temperature for consistent, structured JSON output
        response = router.generate(
            prompt=full_prompt,
            task_type=TaskType.EXTRACTION,
            temperature=0.2,
            max_tokens=512
        )

        if not response.success:
            log_error(f"Memory synthesis LLM call failed for topic '{topic.description}': {response.error}")
            return None

        # Parse the synthesis response
        return self._parse_synthesis_response(response.text, topic)

    def _parse_synthesis_response(
        self,
        response_text: str,
        topic: TopicCluster
    ) -> Optional[SynthesizedMemory]:
        """
        Parse the JSON response from memory synthesis.

        Validates the memory content and metadata, providing sensible defaults
        for missing fields.

        Args:
            response_text: Raw LLM response
            topic: The topic this memory came from (for context)

        Returns:
            SynthesizedMemory object, or None on failure
        """
        try:
            text = response_text.strip()

            # Handle markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            # Find JSON object
            start = text.find("{")
            end = text.rfind("}") + 1

            if start == -1 or end == 0:
                log_warning("No JSON object found in synthesis response")
                return None

            json_str = text[start:end]
            data = json.loads(json_str)

            # Validate content exists
            content = data.get("content", "").strip()
            if not content:
                log_warning("Empty content in synthesis response")
                return None

            # Parse with defaults for optional fields
            importance = float(data.get("importance", 0.5))
            # Clamp importance to valid range
            importance = max(0.0, min(1.0, importance))

            memory_type = data.get("type", "observation")
            # Validate memory type
            valid_types = {"fact", "preference", "event", "reflection", "observation"}
            if memory_type not in valid_types:
                memory_type = "observation"

            temporal_relevance = data.get("temporal_relevance", "recent")
            # Validate temporal relevance
            valid_relevance = {"permanent", "recent", "dated"}
            if temporal_relevance not in valid_relevance:
                temporal_relevance = "recent"

            return SynthesizedMemory(
                content=content,
                importance=importance,
                memory_type=memory_type,
                temporal_relevance=temporal_relevance,
                source_turn_ids=topic.turn_ids,
                source_topic=topic.description
            )

        except (json.JSONDecodeError, ValueError) as e:
            log_warning(f"Failed to parse synthesis response: {e}")
            log_warning(f"Response was: {response_text[:500]}...")
            return None

    # =========================================================================
    # FORMATTING HELPERS
    # =========================================================================

    def _format_conversation_with_ids(self, turns: List[ConversationTurn]) -> str:
        """
        Format conversation turns with their database IDs for topic segmentation.

        Uses actual turn IDs (not sequential numbers) so the LLM's topic assignments
        can be directly mapped back to our database records.

        Args:
            turns: List of conversation turns

        Returns:
            Formatted string with [id] Role: content format
        """
        lines = []
        for turn in turns:
            role = "User" if turn.role == "user" else "AI"
            lines.append(f"[{turn.id}] {role}: {turn.content}")
        return "\n".join(lines)

    def _format_turns_for_synthesis(self, turns: List[ConversationTurn]) -> str:
        """
        Format turns for memory synthesis (sequential numbering).

        For synthesis, we use sequential numbers since the LLM doesn't need
        to reference specific IDs - it just needs to understand the conversation.

        Args:
            turns: List of conversation turns for a single topic

        Returns:
            Formatted string with [n] Role: content format
        """
        lines = []
        for i, turn in enumerate(turns, 1):
            role = "User" if turn.role == "user" else "AI"
            lines.append(f"[{i}] {role}: {turn.content}")
        return "\n".join(lines)

    def _format_conversation(self, turns: List[ConversationTurn]) -> str:
        """
        Legacy format method - kept for backwards compatibility.

        Formats conversation with sequential line numbers.
        """
        lines = ["Conversation Block:"]
        for i, turn in enumerate(turns, 1):
            role = "User" if turn.role == "user" else "AI"
            lines.append(f"[{i}] {role}: {turn.content}")
        return "\n".join(lines)

    # =========================================================================
    # STATISTICS & MONITORING
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """
        Get extraction statistics for monitoring and debugging.

        Returns:
            Dictionary with extraction metrics
        """
        return {
            "total_extractions": self._extraction_count,
            "extraction_in_progress": self._extraction_in_progress.is_set(),
            "threshold": self.extraction_threshold,
            "min_turns_per_topic": self.min_turns_per_topic,
            "max_memories_per_extraction": self.max_memories_per_extraction,
            "skip_minor_topics": self.skip_minor_topics
        }


# =============================================================================
# GLOBAL INSTANCE MANAGEMENT
# =============================================================================

_extractor: Optional[MemoryExtractor] = None


def get_memory_extractor() -> MemoryExtractor:
    """Get the global memory extractor instance (lazy initialization)."""
    global _extractor
    if _extractor is None:
        from config import MEMORY_EXTRACTION_THRESHOLD
        _extractor = MemoryExtractor(
            extraction_threshold=MEMORY_EXTRACTION_THRESHOLD
        )
    return _extractor


def init_memory_extractor() -> MemoryExtractor:
    """Initialize the global memory extractor (explicit initialization)."""
    global _extractor
    from config import MEMORY_EXTRACTION_THRESHOLD
    _extractor = MemoryExtractor(
        extraction_threshold=MEMORY_EXTRACTION_THRESHOLD
    )
    return _extractor
