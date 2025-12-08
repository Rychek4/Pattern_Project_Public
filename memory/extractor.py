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

import re
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
# PHASE 1: TOPIC SEGMENTATION (MULTI-PASS APPROACH)
# =============================================================================
# Topic identification is split into two simple LLM calls:
#   Pass 1: Identify topics (natural language output)
#   Pass 2: Assign turns to topics (simple JSON mapping)
#   Significance: Calculated from turn count (no LLM needed)
#
# This approach is more reliable because:
# - Each prompt has ONE simple task
# - Less chance of schema errors
# - Local LLM calls are free, so multiple calls cost nothing
# - Easier to debug which step failed

# Pass 1: Identify what topics exist (natural language, no JSON)
TOPIC_IDENTIFICATION_PROMPT = """You are analyzing a conversation. List the distinct topics discussed.

Instructions:
1. Read the conversation below
2. Identify the main topics or subjects discussed
3. List each topic on its own line with a number
4. Keep descriptions brief (under 15 words each)
5. Combine closely related subjects into one topic
6. List 1-5 topics maximum

Example output format:
1. Debugging a Python circular import error
2. Brief joke about AI not being able to eat lunch

Conversation:
"""

# Pass 2: Assign turn numbers to topics (simple JSON)
TURN_ASSIGNMENT_PROMPT = """Assign each conversation turn to one of the topics below.

Topics:
{topics}

Instructions:
1. Look at each turn number in the conversation
2. Decide which topic it belongs to
3. Output a JSON object mapping topic numbers to turn numbers

Example output:
{{"1": [1, 2, 3, 5], "2": [4, 6]}}

Conversation:
{conversation}

Output only the JSON object:"""


# =============================================================================
# PHASE 2: MEMORY SYNTHESIS (MULTI-PASS APPROACH)
# =============================================================================
# Memory synthesis is split into three simple LLM calls:
#   Pass 1: Write a 1-2 sentence memory summary (natural language)
#   Pass 2: Rate importance 0-10 (single number)
#   Pass 3: Classify type (single word)
#   decay_category: Inferred from type + importance (no LLM needed)
#
# This approach is more reliable because:
# - Each prompt has ONE simple task
# - No complex JSON schema to follow
# - Local LLM calls are free

# Pass 1: Synthesize memory content (natural language)
MEMORY_CONTENT_PROMPT = """Write a 1-2 sentence memory summarizing this conversation topic.

Instructions:
1. Write in third person using "User" and "AI"
2. Focus on the key insight or outcome
3. Be specific: use names like "the Flask app" or "the Python script"
4. Capture what's worth remembering long-term

Topic: {topic}

Conversation:
{turns}

Write your 1-2 sentence summary:"""

# Pass 2: Rate importance (single number)
MEMORY_IMPORTANCE_PROMPT = """Rate the importance of this memory from 0 to 10.

Scoring guide:
- 8-10: Major decisions, strong preferences, significant events, personal revelations
- 5-7: Useful information, moderate preferences, notable interactions
- 2-4: Minor details, casual observations, brief exchanges
- 0-1: Trivial or forgettable

Memory: {content}

Respond with only a number from 0 to 10:"""

# Pass 3: Classify type (single word)
MEMORY_TYPE_PROMPT = """Classify this memory into one category.

Categories:
- fact: Factual information learned about user or world
- preference: User likes, dislikes, or preferences
- event: Something that happened or was accomplished
- reflection: Insight or realization from the conversation
- observation: General observation about behavior or patterns

Memory: {content}

Respond with only one word (fact, preference, event, reflection, or observation):"""


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

    Attributes:
        content: The synthesized memory text (1-2 sentences)
        importance: Score from 0.0-1.0 indicating significance
        memory_type: Category like 'fact', 'preference', 'event', etc.
        decay_category: Controls freshness decay rate:
            - 'permanent': Never decays (core identity, lasting preferences)
            - 'standard': Normal 30-day half-life (events, discussions)
            - 'ephemeral': Fast 7-day half-life (temporary observations)
        source_turn_ids: Database IDs of conversation turns this came from
        source_topic: Description of the topic cluster this was synthesized from
    """
    content: str
    importance: float
    memory_type: str
    decay_category: str  # 'permanent', 'standard', or 'ephemeral'
    source_turn_ids: List[int] = field(default_factory=list)
    source_topic: Optional[str] = None


# =============================================================================
# DECAY CATEGORY INFERENCE
# =============================================================================
# Instead of asking the LLM to classify decay_category (which would add another
# API call), we infer it from the memory_type and importance score. This is
# deterministic, fast, and aligns with the multi-pass philosophy of keeping
# each step simple.
#
# The logic:
#   - High-importance facts/preferences about the user → permanent
#     (e.g., "User is a software engineer", "User prefers Python")
#   - Events, reflections, and moderate-importance items → standard
#     (e.g., "User debugged a Flask app", "AI reflected on consciousness")
#   - Low-importance observations → ephemeral
#     (e.g., "User mentioned being tired", "Brief joke about lunch")

def infer_decay_category(memory_type: str, importance: float) -> str:
    """
    Infer the appropriate decay category from memory type and importance.

    This function determines how quickly a memory should fade from relevance
    based on its characteristics. No LLM call required - purely deterministic.

    Args:
        memory_type: The classified type ('fact', 'preference', 'event',
                     'reflection', 'observation')
        importance: Score from 0.0 to 1.0

    Returns:
        One of: 'permanent', 'standard', 'ephemeral'

    Inference Rules:
        1. High-importance (≥0.7) facts or preferences → 'permanent'
           These are core identity information that should never fade.

        2. Observations with low importance (<0.5) → 'ephemeral'
           Casual observations fade quickly as they're often situational.

        3. Everything else → 'standard'
           Events, reflections, and moderate-importance items decay normally.
    """
    # Rule 1: High-importance facts/preferences are permanent
    # These represent core user identity and lasting preferences
    if importance >= 0.7 and memory_type in ("fact", "preference"):
        return "permanent"

    # Rule 2: Low-importance observations are ephemeral
    # These are often time-bound or situational
    if memory_type == "observation" and importance < 0.5:
        return "ephemeral"

    # Rule 3: Everything else uses standard decay
    # This includes events, reflections, moderate facts, etc.
    return "standard"


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
                            decay_category=synthesized.decay_category
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
    # PHASE 1: TOPIC SEGMENTATION (MULTI-PASS)
    # =========================================================================

    def _identify_topics(self, turns: List[ConversationTurn]) -> List[TopicCluster]:
        """
        Phase 1: Identify distinct topic clusters using a multi-pass approach.

        Pass 1: Ask LLM to list topics (natural language, no JSON)
        Pass 2: Ask LLM to assign turn numbers to topics (simple JSON)
        Significance: Calculated from turn count (no LLM call needed)

        This multi-pass approach is more reliable than single-pass because:
        - Each prompt has ONE simple task
        - Less chance of schema errors
        - Local LLM calls are free, so multiple calls cost nothing
        - Easier to debug which step failed

        Args:
            turns: List of conversation turns to analyze

        Returns:
            List of TopicCluster objects, or empty list on failure
        """
        router = get_llm_router()
        conversation_text = self._format_conversation_with_ids(turns)
        valid_turn_ids = {t.id for t in turns}

        # =====================================================================
        # PASS 1: Identify topics (natural language output)
        # =====================================================================
        log_info("Pass 1: Identifying topics...", prefix="🔍")

        topics_response = router.generate(
            prompt=f"{TOPIC_IDENTIFICATION_PROMPT}{conversation_text}",
            task_type=TaskType.EXTRACTION,
            temperature=0.3,  # Slightly higher for understanding
            max_tokens=512
        )

        if not topics_response.success:
            log_error(f"Topic identification failed: {topics_response.error}")
            return []

        # Parse the numbered topic list
        topic_descriptions = self._parse_topic_list(topics_response.text)

        if not topic_descriptions:
            log_warning("No topics identified in conversation")
            return []

        log_info(f"Identified {len(topic_descriptions)} topics", prefix="✅")

        # =====================================================================
        # PASS 2: Assign turns to topics (simple JSON)
        # =====================================================================
        log_info("Pass 2: Assigning turns to topics...", prefix="🔗")

        # Format topics for the prompt
        topics_formatted = "\n".join(
            f"{i+1}. {desc}" for i, desc in enumerate(topic_descriptions)
        )

        assignment_prompt = TURN_ASSIGNMENT_PROMPT.format(
            topics=topics_formatted,
            conversation=conversation_text
        )

        assignment_response = router.generate(
            prompt=assignment_prompt,
            task_type=TaskType.EXTRACTION,
            temperature=0.1,  # Low for structured output
            max_tokens=256
        )

        if not assignment_response.success:
            log_error(f"Turn assignment failed: {assignment_response.error}")
            return []

        # Parse the turn assignments
        turn_assignments = self._parse_turn_assignments(
            assignment_response.text, valid_turn_ids
        )

        if not turn_assignments:
            log_warning("Failed to parse turn assignments")
            return []

        log_info(f"Assigned turns to {len(turn_assignments)} topics", prefix="✅")

        # =====================================================================
        # BUILD TopicCluster OBJECTS
        # =====================================================================
        topics = []
        for topic_num, turn_ids in turn_assignments.items():
            topic_idx = int(topic_num) - 1  # Convert 1-based to 0-based

            if topic_idx < 0 or topic_idx >= len(topic_descriptions):
                log_warning(f"Invalid topic number: {topic_num}")
                continue

            if not turn_ids:
                continue

            # Significance calculated from turn count (no LLM needed!)
            significance = "major" if len(turn_ids) >= 3 else "minor"

            topics.append(TopicCluster(
                topic_id=int(topic_num),
                description=topic_descriptions[topic_idx],
                turn_ids=turn_ids,
                significance=significance
            ))

        log_info(f"Created {len(topics)} topic clusters", prefix="📦")
        return topics

    def _parse_topic_list(self, response_text: str) -> List[str]:
        """
        Parse a numbered list of topics from natural language response.

        Expected format:
        1. First topic description
        2. Second topic description

        Returns:
            List of topic description strings
        """
        topics = []
        lines = response_text.strip().split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Match patterns like "1. Topic" or "1) Topic" or "1: Topic"
            match = re.match(r'^(\d+)[.\):\-]\s*(.+)$', line)
            if match:
                topic_desc = match.group(2).strip()
                if topic_desc:
                    topics.append(topic_desc)

        return topics

    def _parse_turn_assignments(
        self,
        response_text: str,
        valid_turn_ids: set
    ) -> Dict[str, List[int]]:
        """
        Parse turn assignments from simple JSON response.

        Expected format: {"1": [1, 2, 3], "2": [4, 5]}

        Returns:
            Dict mapping topic number (as string) to list of turn IDs
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
                log_warning("No JSON found in turn assignment response")
                return {}

            json_str = text[start:end]
            data = json.loads(json_str)

            # Validate and filter turn IDs
            result = {}
            for topic_num, turn_ids in data.items():
                if not isinstance(turn_ids, list):
                    continue

                # Filter to valid turn IDs only
                valid_ids = [
                    tid for tid in turn_ids
                    if isinstance(tid, int) and tid in valid_turn_ids
                ]

                if valid_ids:
                    result[str(topic_num)] = valid_ids

            return result

        except (json.JSONDecodeError, ValueError) as e:
            log_warning(f"Failed to parse turn assignments: {e}")
            return {}

    # =========================================================================
    # PHASE 2: MEMORY SYNTHESIS
    # =========================================================================

    def _synthesize_topic_memory(
        self,
        topic: TopicCluster,
        turns: List[ConversationTurn]
    ) -> Optional[SynthesizedMemory]:
        """
        Phase 2: Synthesize ONE consolidated memory using multi-pass approach.

        Pass 1: Write a 1-2 sentence memory summary (natural language)
        Pass 2: Rate importance 0-10 (single number)
        Pass 3: Classify type (single word)
        decay_category: Inferred from type + importance (no LLM call needed)

        This multi-pass approach is more reliable than single-pass JSON because:
        - Each prompt has ONE simple task
        - No complex JSON schema to follow
        - Local LLM calls are free

        Args:
            topic: The topic cluster to synthesize
            turns: The actual conversation turns belonging to this topic

        Returns:
            SynthesizedMemory object, or None on failure
        """
        router = get_llm_router()
        turns_text = self._format_turns_for_synthesis(turns)

        # =====================================================================
        # PASS 1: Generate memory content (natural language)
        # =====================================================================
        log_info(f"Synthesizing memory for '{topic.description[:30]}...'", prefix="📝")

        content_prompt = MEMORY_CONTENT_PROMPT.format(
            topic=topic.description,
            turns=turns_text
        )

        content_response = router.generate(
            prompt=content_prompt,
            task_type=TaskType.EXTRACTION,
            temperature=0.3,  # Slightly creative for good summaries
            max_tokens=256
        )

        if not content_response.success:
            log_error(f"Memory content generation failed: {content_response.error}")
            return None

        content = self._parse_content_response(content_response.text)
        if not content:
            log_warning("Failed to extract memory content")
            return None

        # =====================================================================
        # PASS 2: Rate importance (single number 0-10)
        # =====================================================================
        importance_prompt = MEMORY_IMPORTANCE_PROMPT.format(content=content)

        importance_response = router.generate(
            prompt=importance_prompt,
            task_type=TaskType.EXTRACTION,
            temperature=0.1,  # Low for consistent scoring
            max_tokens=16
        )

        importance = self._parse_importance_response(importance_response.text)

        # =====================================================================
        # PASS 3: Classify type (single word)
        # =====================================================================
        type_prompt = MEMORY_TYPE_PROMPT.format(content=content)

        type_response = router.generate(
            prompt=type_prompt,
            task_type=TaskType.EXTRACTION,
            temperature=0.1,  # Low for consistent classification
            max_tokens=16
        )

        memory_type = self._parse_type_response(type_response.text)

        # =====================================================================
        # INFER DECAY CATEGORY
        # =====================================================================
        # Decay category determines how quickly this memory fades from relevance.
        # We infer it from the memory type and importance rather than making
        # another LLM call - this is fast, deterministic, and reliable.
        decay_category = infer_decay_category(memory_type, importance)

        log_info(
            f"Memory: type={memory_type}, importance={importance:.2f}, "
            f"decay={decay_category}",
            prefix="🏷️"
        )

        # =====================================================================
        # BUILD MEMORY OBJECT
        # =====================================================================
        return SynthesizedMemory(
            content=content,
            importance=importance,
            memory_type=memory_type,
            decay_category=decay_category,
            source_turn_ids=topic.turn_ids,
            source_topic=topic.description
        )

    def _parse_content_response(self, response_text: str) -> Optional[str]:
        """
        Parse memory content from natural language response.
        Extracts the summary, stripping any preamble or formatting.
        """
        text = response_text.strip()

        # Remove common preambles
        for prefix in ["Here's", "Here is", "Summary:", "Memory:"]:
            if text.lower().startswith(prefix.lower()):
                text = text[len(prefix):].strip()
                if text.startswith(":"):
                    text = text[1:].strip()

        # Remove quotes if wrapped
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]

        # Validate we got something meaningful
        if len(text) < 10:
            return None

        return text

    def _parse_importance_response(self, response_text: str) -> float:
        """
        Parse importance rating from LLM response.
        Expects a number 0-10, converts to 0.0-1.0 scale.
        Returns 0.5 as default if parsing fails.
        """
        text = response_text.strip()

        # Extract first number found
        match = re.search(r'(\d+(?:\.\d+)?)', text)
        if match:
            try:
                value = float(match.group(1))
                # Convert 0-10 scale to 0.0-1.0
                if value > 1.0:
                    value = value / 10.0
                # Clamp to valid range
                return max(0.0, min(1.0, value))
            except ValueError:
                pass

        return 0.5  # Default

    def _parse_type_response(self, response_text: str) -> str:
        """
        Parse memory type from LLM response.
        Expects one of: fact, preference, event, reflection, observation.
        Returns 'observation' as default if parsing fails.
        """
        text = response_text.strip().lower()

        valid_types = {"fact", "preference", "event", "reflection", "observation"}

        # Check if response contains a valid type
        for memory_type in valid_types:
            if memory_type in text:
                return memory_type

        return "observation"  # Default

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
