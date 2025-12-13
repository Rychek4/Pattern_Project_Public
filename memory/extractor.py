"""
Pattern Project - Memory Extractor
Extracts memories from conversations using topic-based clustering.

ARCHITECTURE (Windowed Extraction System):
    The extractor is tightly coupled with the context window system.
    Turns flow: Context Window → Extraction → Memory Store → Gone from context

    OLD SYSTEM (Threshold-Based) - DEPRECATED:
        - Triggered when unprocessed turns >= 10
        - Processed up to 50 turns at once
        - Context window and extraction were independent
        - Problem: Same turns could be in context AND queued for extraction
        - Problem: Same facts extracted from different turn batches

    NEW SYSTEM (Windowed):
        - Triggered when context window overflows (35 > 30)
        - Processes exactly the overflow amount (oldest 5 turns)
        - Context window and extraction are coordinated via processed_for_memory flag
        - Turns removed from context immediately after extraction
        - Clean flow: turns are extracted exactly once, right as they leave context

    The key insight: extraction happens AT THE BOUNDARY of the context window,
    not independently. This ensures each turn is extracted exactly once.

Extraction Process:
    The extractor uses a TWO-PHASE approach to create high-quality, consolidated memories:

    Phase 1 - Topic Segmentation:
        Analyzes conversation turns to identify distinct topic clusters.
        Example: 5 turns about debugging + 2 turns about lunch = 2 topic clusters

    Phase 2 - Memory Synthesis:
        For each significant topic cluster, synthesizes ONE consolidated memory.
        Example: 5 debugging turns → 1 memory capturing the key insight

    Result: 5 overflow turns → 1-3 high-quality memories (not 1 per turn)

    Additionally, a parallel FACTUAL EXTRACTION pass extracts concrete facts
    (e.g., "Brian is 45 years old") as separate memories.
"""

import re
import threading
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from core.logger import log_info, log_warning, log_error, log_success
from core.temporal import get_temporal_tracker
from memory.conversation import get_conversation_manager, ConversationTurn
from memory.vector_store import get_vector_store
from llm.router import get_llm_router, TaskType
from concurrency.locks import get_lock_manager
from config import USER_NAME, AI_NAME


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

# Pass 2: Classify each turn into a topic (Linear method - one decision at a time)
# Uses letter-based turn labels (A, B, C...) to prevent LLM from hallucinating extra turns
# The distinct symbol space (letters for turns, numbers for topics) reduces confusion
TURN_ASSIGNMENT_PROMPT = """Classify each turn into one of the topics below.

Topics:
{topics}

The conversation has exactly {num_turns} turns labeled {turn_labels}.
Output a JSON object mapping each turn letter to its topic number (1-{num_topics}).
Include exactly {num_turns} entries matching the turns shown.

Example for this {num_turns}-turn conversation:
{example}

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

# Pass 1: Synthesize memory content (natural language, first-person)
MEMORY_CONTENT_PROMPT = """Write a 1-2 sentence memory from this conversation.

Instructions:
1. Write in first person as the AI ("I"), referring to the human as "{user_name}"
2. Focus on what mattered—the insight, the shift, or the moment of connection
3. Be specific: use real names, details, and context
4. If there was friction, surprise, or uncertainty, include it

Topic: {topic}

Conversation:
{turns}

Write your memory:"""

# Pass 2: Rate importance (categorical - more reliable than numeric scale)
MEMORY_IMPORTANCE_PROMPT = """Rate this memory's importance.

Choose ONE:
- HIGH: Life decisions, identity insights, strong preferences, significant milestones
- MEDIUM: Useful context, notable conversations, moderate preferences
- LOW: Casual observations, minor details, brief or forgettable exchanges

Memory: {content}

Respond with one word (HIGH, MEDIUM, or LOW):"""

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
# FACTUAL EXTRACTION PROMPTS (DUAL-TRACK SYSTEM)
# =============================================================================
# Factual extraction runs as a parallel pass alongside episodic extraction.
# It focuses on extracting concrete facts rather than narrative summaries.
#
# Key differences from episodic extraction:
# - Output style: Third-person assertions ("Brian is 45") not first-person narratives
# - No topic clustering: Facts are extracted from the whole conversation at once
# - More granular: One fact per statement, atomic facts
# - Different decay: Facts generally persist longer than episodic observations

FACTUAL_EXTRACTION_PROMPT = """<task>
Extract facts about {user_name} from this conversation. Focus on durable information that would be useful to remember in future conversations.
</task>

<critical_rules>
1. ONLY extract facts {user_name} explicitly stated or confirmed
2. AI suggestions are NOT user preferences unless {user_name} agreed
3. If the AI suggested something and {user_name} pushed back or was uncertain, that is NOT a preference
4. NEVER extract what the AI said, thought, or observed - only information about {user_name}
5. Look for confirmation patterns: "yes", "I like", "I prefer", "that's right", agreement
6. Look for rejection patterns: "maybe too", "not sure", "but", uncertainty, pushback
</critical_rules>

<what_to_extract>
- {user_name}'s stated preferences, likes, and dislikes
- Biographical information (age, location, job, relationships)
- Technical choices and tools {user_name} uses
- Habits and routines mentioned
- Projects or goals {user_name} is working on
- References to people, pets, or things {user_name} knows
</what_to_extract>

<what_to_ignore>
- Anything the AI said or suggested (unless {user_name} confirmed it)
- AI's observations, reactions, or opinions
- Hypotheticals and "what ifs"
- Emotional reactions and conversational filler
- Preferences still being explored or debated
</what_to_ignore>

<output_format>
For each fact, output exactly this format using {user_name}'s name (not "the user"):
FACT: [{user_name} + third-person assertion]
IMPORTANCE: [HIGH/MEDIUM/LOW]
TYPE: [fact/preference]

If no concrete facts are present, output only: NONE
</output_format>

<examples>
Example 1 - Correct extraction:
Conversation: "{user_name}: I'm 32 and work as a data scientist"
FACT: {user_name} is 32 years old
IMPORTANCE: MEDIUM
TYPE: fact
FACT: {user_name} works as a data scientist
IMPORTANCE: MEDIUM
TYPE: fact

Example 2 - Attribution error to avoid:
Conversation: "Claude: Maybe try a minimalist design? {user_name}: Hmm, that might be too plain"
WRONG: "{user_name} prefers minimalist design" (AI suggested it, user pushed back)
CORRECT: Output NONE or note {user_name} finds minimalist design too plain

Example 3 - User confirmation:
Conversation: "Claude: So you prefer TypeScript? {user_name}: Yes, definitely over JavaScript"
FACT: {user_name} prefers TypeScript over JavaScript
IMPORTANCE: MEDIUM
TYPE: preference
</examples>

<conversation>
{conversation}
</conversation>

Extract facts about {user_name} (output NONE if no concrete facts are present):"""


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


@dataclass
class ExtractedFact:
    """
    A concrete fact extracted from conversation.

    Created during factual extraction (parallel to episodic extraction).
    Facts are atomic assertions about people, places, or things.

    Attributes:
        content: The fact statement (third-person assertion)
        importance: Score from 0.0-1.0 indicating significance
        memory_type: 'fact' or 'preference' (factual extraction only produces these)
        decay_category: Controls freshness decay rate (more generous for facts)
        source_turn_ids: Database IDs of conversation turns this came from
    """
    content: str
    importance: float
    memory_type: str  # 'fact' or 'preference'
    decay_category: str  # 'permanent' or 'standard' (no ephemeral for facts)
    source_turn_ids: List[int] = field(default_factory=list)


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


def infer_decay_category_factual(memory_type: str, importance: float) -> str:
    """
    Infer decay category for factual memories (more generous than episodic).

    Facts generally should be more persistent than episodic memories because
    facts don't become "less true" over time the way experiences fade.

    Args:
        memory_type: 'fact' or 'preference' (factual extraction only produces these)
        importance: Score from 0.0 to 1.0

    Returns:
        One of: 'permanent', 'standard' (no 'ephemeral' for facts)

    Inference Rules:
        1. High or medium-high importance (≥0.6) → 'permanent'
           Lower threshold than episodic because facts are inherently more stable.

        2. Everything else → 'standard'
           Low-importance facts can decay normally, but not ephemerally.
           No 'ephemeral' category for facts - they're either worth keeping or not.
    """
    # Rule 1: Facts/preferences with reasonable importance are permanent
    # Lower threshold (0.6) than episodic (0.7) because facts are stable
    if importance >= 0.6:
        return "permanent"

    # Rule 2: Low-importance facts use standard decay
    # No ephemeral for facts - if it's worth extracting, give it standard lifetime
    return "standard"


# =============================================================================
# MEMORY EXTRACTOR CLASS
# =============================================================================

class MemoryExtractor:
    """
    Extracts memories from conversations using topic-based clustering.

    ARCHITECTURE (Windowed Extraction):
        The extractor is coordinated with the context window system:
        - Triggered when context overflows (unprocessed turns > overflow_trigger)
        - Processes exactly the overflow amount (oldest turns leaving context)
        - Marks processed turns, which removes them from context window

        This ensures each turn is extracted exactly once, right as it
        leaves the active context window.

    Extraction Process:
        1. Topic Segmentation: Identify distinct topic clusters
        2. Memory Synthesis: Create ONE consolidated memory per significant topic
        3. Factual Extraction: Extract concrete facts as separate memories

    Triggers:
        - Context overflow: When unprocessed turns >= CONTEXT_OVERFLOW_TRIGGER (35)
        - Manual /extract command (processes current overflow if any)

    Note: Session end NO LONGER triggers extraction. The context window
    persists across sessions for AI continuity.
    """

    def __init__(self):
        """
        Initialize the memory extractor with windowed extraction settings.
        """
        self._lock_manager = get_lock_manager()
        self._extraction_count = 0
        self._factual_extraction_count = 0
        self._extraction_in_progress = threading.Event()

        # Load windowed extraction settings
        from config import (
            CONTEXT_WINDOW_SIZE,
            CONTEXT_OVERFLOW_TRIGGER,
            CONTEXT_EXTRACTION_BATCH,
            MEMORY_MIN_TURNS_PER_TOPIC,
            MEMORY_MAX_PER_EXTRACTION,
            MEMORY_SKIP_MINOR_TOPICS,
            MEMORY_LARGE_TOPIC_THRESHOLD,
            MEMORY_SMALL_BATCH_THRESHOLD,
            MEMORY_IMPORTANCE_FLOOR,
            MEMORY_MAX_EPISODIC_PER_EXTRACTION,
            MEMORY_MAX_FACTUAL_PER_EXTRACTION
        )

        # Windowed extraction settings (NEW)
        self.context_window_size = CONTEXT_WINDOW_SIZE          # 30
        self.overflow_trigger = CONTEXT_OVERFLOW_TRIGGER        # 35
        self.extraction_batch = CONTEXT_EXTRACTION_BATCH        # 5

        # Episodic extraction settings (topic-based)
        self.min_turns_per_topic = MEMORY_MIN_TURNS_PER_TOPIC
        self.max_memories_per_extraction = MEMORY_MAX_PER_EXTRACTION  # Legacy
        self.max_episodic_per_extraction = MEMORY_MAX_EPISODIC_PER_EXTRACTION
        self.skip_minor_topics = MEMORY_SKIP_MINOR_TOPICS
        self.large_topic_threshold = MEMORY_LARGE_TOPIC_THRESHOLD
        self.small_batch_threshold = MEMORY_SMALL_BATCH_THRESHOLD
        self.importance_floor = MEMORY_IMPORTANCE_FLOOR

        # Factual extraction settings
        self.max_factual_per_extraction = MEMORY_MAX_FACTUAL_PER_EXTRACTION

    # =========================================================================
    # WINDOWED EXTRACTION TRIGGER
    # =========================================================================

    def check_and_extract(self) -> None:
        """
        Check if context window has overflowed and trigger extraction.

        Called after each conversation turn is added. If the number of unprocessed
        turns exceeds the overflow trigger (35), extraction runs in a background
        thread to process the oldest turns leaving the context window.

        WINDOWED EXTRACTION LOGIC:
            if unprocessed_count >= overflow_trigger (35):
                extract oldest (unprocessed_count - context_window_size) turns
                mark them as processed (removes from context)

        Thread-safe: Uses an event flag to prevent multiple concurrent extractions.
        """
        # Quick check without hitting the database if extraction is already running
        if self._extraction_in_progress.is_set():
            return

        try:
            conversation_mgr = get_conversation_manager()
            unprocessed_count = conversation_mgr.get_unprocessed_count()

            if unprocessed_count >= self.overflow_trigger:
                # Mark extraction as in progress before starting thread
                if self._extraction_in_progress.is_set():
                    return  # Another thread beat us to it
                self._extraction_in_progress.set()

                # Calculate how many turns to extract (the overflow)
                overflow_count = unprocessed_count - self.context_window_size

                log_info(
                    f"Context overflow: {unprocessed_count} turns >= {self.overflow_trigger} trigger. "
                    f"Extracting oldest {overflow_count} turns.",
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
            log_error(f"Error checking context overflow: {e}")

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
        Extract memories from oldest unprocessed turns (windowed extraction).

        This is the main entry point for memory extraction. Runs TWO extraction passes:

        1. EPISODIC EXTRACTION:
           - Identifies topic clusters in the conversation
           - Synthesizes narrative memories per significant topic
           - Captures "what happened" - relationship texture and experiences

        2. FACTUAL EXTRACTION:
           - Scans conversation for concrete facts
           - Extracts atomic assertions about people, places, things
           - Captures "what is true" - factual scaffolding

        WINDOWED EXTRACTION:
            - Processes only the OLDEST turns that exceed context_window_size
            - Example: 37 unprocessed turns → extract oldest 7 (37 - 30 = 7)
            - Marks extracted turns as processed, removing them from context

        Args:
            force: If True, extract any overflow even if below normal trigger.
                   NOTE: force no longer means "extract all" - context window
                   is always preserved for AI continuity.

        Returns:
            Total number of memories created (episodic + factual)
        """
        with self._lock_manager.acquire("memory_extraction"):
            try:
                conversation_mgr = get_conversation_manager()
                vector_store = get_vector_store()
                tracker = get_temporal_tracker()

                # Calculate how many turns to extract (the overflow)
                unprocessed_count = conversation_mgr.get_unprocessed_count()

                if unprocessed_count <= self.context_window_size:
                    # No overflow - nothing to extract
                    if not force:
                        return 0
                    # Even with force, we preserve the context window
                    log_info(
                        f"No overflow to extract ({unprocessed_count} <= {self.context_window_size})",
                        prefix="🧠"
                    )
                    return 0

                # Extract only the overflow (oldest turns leaving context window)
                overflow_count = unprocessed_count - self.context_window_size
                turns = conversation_mgr.get_unprocessed_turns(limit=overflow_count)

                if not turns:
                    return 0

                log_info(
                    f"Processing {len(turns)} overflow turns for dual-track extraction "
                    f"(keeping {self.context_window_size} in context)",
                    prefix="🧠"
                )

                # =============================================================
                # TRACK 1: EPISODIC EXTRACTION
                # Narrative memories about what happened
                # =============================================================
                log_info("Starting episodic extraction (narrative memories)...", prefix="📖")

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
                episodic_created = 0
                factual_created = 0

                # Track which turns were successfully incorporated into memories
                successfully_processed_turn_ids = set()

                # Adaptive minor topic handling: for small batches, preserve all topics
                # This ensures short but meaningful conversations create episodic memories
                effective_skip_minor = self.skip_minor_topics
                if len(turns) < self.small_batch_threshold:
                    effective_skip_minor = False
                    log_info(
                        f"Small batch ({len(turns)} turns < {self.small_batch_threshold}) - "
                        "preserving minor topics for episodic memory",
                        prefix="🧠"
                    )

                for topic in topics:
                    # Check if we've hit the episodic memory cap for this extraction run
                    if episodic_created >= self.max_episodic_per_extraction:
                        log_info(f"Hit max episodic memories per extraction ({self.max_episodic_per_extraction})")
                        break

                    # Skip minor topics if configured (adaptive based on batch size)
                    if effective_skip_minor and not topic.is_major():
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
                        # Check importance floor - skip trivial memories
                        if synthesized.importance < self.importance_floor:
                            log_info(
                                f"Skipping low-importance memory for topic '{topic.description[:40]}...' "
                                f"(importance: {synthesized.importance:.2f} < floor: {self.importance_floor})",
                                prefix="⏭️"
                            )
                            continue

                        # Determine source timestamp from the topic's turns
                        source_time = topic_turns[-1].created_at if topic_turns else datetime.now()

                        memory_id = vector_store.add_memory(
                            content=synthesized.content,
                            source_conversation_ids=topic.turn_ids,
                            source_session_id=session_id,
                            source_timestamp=source_time,
                            importance=synthesized.importance,
                            memory_type=synthesized.memory_type,
                            decay_category=synthesized.decay_category,
                            memory_category="episodic"  # Dual-track: narrative memories
                        )

                        if memory_id:
                            episodic_created += 1
                            # Track turns that successfully became part of a memory
                            successfully_processed_turn_ids.update(topic.turn_ids)
                            log_info(
                                f"Created episodic memory for topic '{topic.description[:40]}...' "
                                f"(importance: {synthesized.importance:.2f})",
                                prefix="📖"
                            )

                log_info(f"Episodic extraction complete: {episodic_created} memories", prefix="📖")

                # =============================================================
                # TRACK 2: FACTUAL EXTRACTION
                # Concrete facts extracted from conversation
                # =============================================================
                log_info("Starting factual extraction (concrete facts)...", prefix="📌")

                # Extract facts from the entire conversation batch
                # No topic clustering needed - facts are extracted globally
                facts = self._extract_facts(turns)

                if facts:
                    all_turn_ids_set = set(t.id for t in turns)
                    source_time = turns[-1].created_at if turns else datetime.now()

                    for fact in facts[:self.max_factual_per_extraction]:
                        # Check importance floor
                        if fact.importance < self.importance_floor:
                            log_info(
                                f"Skipping low-importance fact: '{fact.content[:40]}...' "
                                f"(importance: {fact.importance:.2f})",
                                prefix="⏭️"
                            )
                            continue

                        memory_id = vector_store.add_memory(
                            content=fact.content,
                            source_conversation_ids=list(all_turn_ids_set),
                            source_session_id=session_id,
                            source_timestamp=source_time,
                            importance=fact.importance,
                            memory_type=fact.memory_type,
                            decay_category=fact.decay_category,
                            memory_category="factual"  # Dual-track: concrete facts
                        )

                        if memory_id:
                            factual_created += 1
                            # Facts come from entire conversation, mark all turns
                            successfully_processed_turn_ids.update(all_turn_ids_set)
                            log_info(
                                f"Created factual memory: '{fact.content[:50]}...' "
                                f"(importance: {fact.importance:.2f})",
                                prefix="📌"
                            )

                log_info(f"Factual extraction complete: {factual_created} facts", prefix="📌")

                # ─────────────────────────────────────────────────────────────
                # CLEANUP: Mark processed turns
                # Only mark turns that were successfully incorporated into
                # memories. If none succeeded, mark all anyway to prevent
                # infinite retry loops, but log a warning.
                # ─────────────────────────────────────────────────────────────
                all_turn_ids = [t.id for t in turns]
                total_memories = episodic_created + factual_created

                if successfully_processed_turn_ids:
                    # Normal case: mark only the turns that produced memories
                    conversation_mgr.mark_processed(list(successfully_processed_turn_ids))
                    unprocessed_count = len(all_turn_ids) - len(successfully_processed_turn_ids)
                    if unprocessed_count > 0:
                        log_info(
                            f"Marked {len(successfully_processed_turn_ids)} turns as processed; "
                            f"{unprocessed_count} turns will be retried next extraction"
                        )
                else:
                    # No memories created - mark all to prevent infinite loops
                    # This can happen if all topics were skipped or LLM/embedding failed
                    log_warning(
                        f"No memories created from {len(turns)} turns - "
                        "marking all as processed to prevent infinite retry loop"
                    )
                    conversation_mgr.mark_processed(all_turn_ids)

                self._extraction_count += episodic_created
                self._factual_extraction_count += factual_created
                log_success(
                    f"Dual-track extraction complete: {episodic_created} episodic + "
                    f"{factual_created} factual = {total_memories} memories from "
                    f"{len(turns)} turns"
                )

                return total_memories

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
        Pass 2: Ask LLM to assign turn labels to topics (simple JSON with letters)
        Significance: Calculated from turn count (no LLM call needed)

        This multi-pass approach is more reliable than single-pass because:
        - Each prompt has ONE simple task
        - Less chance of schema errors
        - Local LLM calls are free, so multiple calls cost nothing
        - Easier to debug which step failed

        Uses letter-based turn labels (A, B, C...) instead of numbers to prevent
        the LLM from hallucinating extra turns by pattern-matching on examples.

        Args:
            turns: List of conversation turns to analyze

        Returns:
            List of TopicCluster objects, or empty list on failure
        """
        router = get_llm_router()

        # Format with letter-based labels (A, B, C...) to prevent hallucination
        # The label_to_id mapping lets us translate back to real DB IDs
        conversation_text, label_to_id = self._format_conversation_indexed(turns)
        valid_labels = set(label_to_id.keys())  # {"A", "B", "C", ...}
        num_turns = len(turns)

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
        # PASS 2: Assign turns to topics (simple JSON with letter labels)
        # =====================================================================
        log_info("Pass 2: Assigning turns to topics...", prefix="🔗")

        # Format topics for the prompt
        topics_formatted = "\n".join(
            f"{i+1}. {desc}" for i, desc in enumerate(topic_descriptions)
        )

        # Generate dynamic example matching actual turn count
        num_topics = len(topic_descriptions)
        turn_labels = self._generate_turn_labels(num_turns)
        example = self._generate_assignment_example(num_turns, num_topics)

        assignment_prompt = TURN_ASSIGNMENT_PROMPT.format(
            topics=topics_formatted,
            num_topics=num_topics,
            num_turns=num_turns,
            turn_labels=turn_labels,
            example=example,
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

        # Parse the turn assignments (validates turn labels and topic numbers)
        turn_assignments = self._parse_turn_assignments(
            assignment_response.text,
            valid_labels,
            num_topics=num_topics
        )

        if not turn_assignments:
            log_warning("Failed to parse turn assignments")
            return []

        log_info(f"Assigned turns to {len(turn_assignments)} topics", prefix="✅")

        # =====================================================================
        # BUILD TopicCluster OBJECTS
        # Translate letter labels back to real database IDs
        # =====================================================================
        topics = []
        for topic_num, turn_labels_list in turn_assignments.items():
            topic_idx = int(topic_num) - 1  # Convert 1-based to 0-based

            if topic_idx < 0 or topic_idx >= len(topic_descriptions):
                log_warning(f"Invalid topic number: {topic_num}")
                continue

            if not turn_labels_list:
                continue

            # Translate labels back to real database IDs
            turn_ids = [label_to_id[label] for label in turn_labels_list if label in label_to_id]

            if not turn_ids:
                log_warning(f"No valid turn IDs for topic {topic_num} after label translation")
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
        valid_labels: set,
        num_topics: int
    ) -> Dict[str, List[str]]:
        """
        Parse turn assignments from Linear method JSON response.

        Expected format: {"A": 2, "B": 2, "C": 1, "D": 3}
        (turn_label -> topic_number)

        This function flips the mapping to: {"1": ["C"], "2": ["A", "B"], "3": ["D"]}
        (topic_number -> [turn_labels])

        Args:
            response_text: Raw LLM response containing JSON
            valid_labels: Set of valid turn labels (e.g., {"A", "B", "C"})
                         that the LLM was shown in the conversation
            num_topics: Number of valid topics (1 to num_topics are valid)

        Returns:
            Dict mapping topic number (as string) to list of valid turn labels
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

            # Flip from {turn_label: topic} to {topic: [turn_labels]}
            # While validating both turn labels and topic numbers
            result: Dict[str, List[str]] = {}

            for turn_label, topic_num in data.items():
                # Normalize turn label (uppercase, stripped)
                turn_label = str(turn_label).strip().upper()

                # Validate turn label
                if turn_label not in valid_labels:
                    log_warning(f"Turn label not in conversation: {turn_label}")
                    continue

                # Validate topic number
                if not isinstance(topic_num, int):
                    # Try to convert string to int
                    try:
                        topic_num = int(topic_num)
                    except (ValueError, TypeError):
                        log_warning(f"Invalid topic type for turn {turn_label}: {topic_num}")
                        continue

                if topic_num < 1 or topic_num > num_topics:
                    log_warning(f"Invalid topic number: {topic_num} (valid: 1-{num_topics})")
                    continue

                # Add to flipped result
                topic_str = str(topic_num)
                if topic_str not in result:
                    result[topic_str] = []
                result[topic_str].append(turn_label)

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
            turns=turns_text,
            user_name=USER_NAME
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
        Expects categorical: HIGH, MEDIUM, or LOW.
        Maps to: HIGH → 0.85, MEDIUM → 0.55, LOW → 0.25
        Returns 0.55 (MEDIUM) as default if parsing fails.
        """
        text = response_text.strip().lower()

        # Map categorical responses to numerical values
        # These values are chosen to create meaningful differentiation:
        # - HIGH (0.85): Will often become "permanent" for facts/preferences
        # - MEDIUM (0.55): Standard decay, useful but not critical
        # - LOW (0.25): Below importance floor (0.3), will be filtered out
        if "high" in text:
            return 0.85
        elif "medium" in text:
            return 0.55
        elif "low" in text:
            return 0.25

        # Fallback: check for legacy numeric responses (in case of model variation)
        match = re.search(r'(\d+(?:\.\d+)?)', text)
        if match:
            try:
                value = float(match.group(1))
                if value > 1.0:
                    value = value / 10.0
                return max(0.0, min(1.0, value))
            except ValueError:
                pass

        return 0.55  # Default to MEDIUM

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
    # FACTUAL EXTRACTION (DUAL-TRACK SYSTEM)
    # =========================================================================

    def _extract_facts(self, turns: List[ConversationTurn]) -> List[ExtractedFact]:
        """
        Extract concrete facts from conversation turns.

        Unlike episodic extraction, factual extraction:
        - Processes the entire conversation at once (no topic clustering)
        - Extracts atomic facts as third-person assertions
        - Uses a single LLM call with structured output parsing

        Args:
            turns: List of conversation turns to extract facts from

        Returns:
            List of ExtractedFact objects, or empty list on failure
        """
        router = get_llm_router()

        # Format conversation for factual extraction
        conversation_text = self._format_turns_for_synthesis(turns)

        log_info("Extracting facts from conversation...", prefix="📌")

        # Single LLM call to extract all facts
        # Include user_name so facts are extracted with proper entity naming
        fact_prompt = FACTUAL_EXTRACTION_PROMPT.format(
            conversation=conversation_text,
            user_name=USER_NAME
        )

        fact_response = router.generate(
            prompt=fact_prompt,
            task_type=TaskType.FACT_EXTRACTION,  # Routes to API for higher accuracy
            temperature=0.2,  # Low for consistent extraction
            max_tokens=1024   # Allow multiple facts
        )

        if not fact_response.success:
            log_error(f"Factual extraction failed: {fact_response.error}")
            return []

        # Parse the response into ExtractedFact objects
        facts = self._parse_facts_response(fact_response.text, turns)

        log_info(f"Extracted {len(facts)} facts from conversation", prefix="📌")
        return facts

    def _parse_facts_response(
        self,
        response_text: str,
        turns: List[ConversationTurn]
    ) -> List[ExtractedFact]:
        """
        Parse factual extraction response into ExtractedFact objects.

        Expected format:
        FACT: [fact statement]
        IMPORTANCE: [HIGH/MEDIUM/LOW]
        TYPE: [fact/preference]

        Args:
            response_text: Raw LLM response
            turns: Source turns (for turn ID tracking)

        Returns:
            List of ExtractedFact objects
        """
        facts = []
        text = response_text.strip()

        # Check for "NONE" response (no facts found)
        if text.upper() == "NONE" or "no concrete facts" in text.lower():
            return []

        # Split into fact blocks
        # Each block starts with "FACT:" and continues until the next "FACT:" or end
        lines = text.split('\n')

        current_fact = None
        current_importance = "MEDIUM"
        current_type = "fact"

        all_turn_ids = [t.id for t in turns]

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for FACT line
            if line.upper().startswith("FACT:"):
                # Save previous fact if exists
                if current_fact:
                    importance_value = self._parse_importance_response(current_importance)
                    decay_category = infer_decay_category_factual(current_type, importance_value)
                    facts.append(ExtractedFact(
                        content=current_fact,
                        importance=importance_value,
                        memory_type=current_type,
                        decay_category=decay_category,
                        source_turn_ids=all_turn_ids
                    ))

                # Start new fact
                current_fact = line[5:].strip()  # Remove "FACT:" prefix
                current_importance = "MEDIUM"  # Reset defaults
                current_type = "fact"

            # Check for IMPORTANCE line
            elif line.upper().startswith("IMPORTANCE:"):
                current_importance = line[11:].strip()

            # Check for TYPE line
            elif line.upper().startswith("TYPE:"):
                type_value = line[5:].strip().lower()
                if type_value in ("fact", "preference"):
                    current_type = type_value

        # Don't forget the last fact
        if current_fact:
            importance_value = self._parse_importance_response(current_importance)
            decay_category = infer_decay_category_factual(current_type, importance_value)
            facts.append(ExtractedFact(
                content=current_fact,
                importance=importance_value,
                memory_type=current_type,
                decay_category=decay_category,
                source_turn_ids=all_turn_ids
            ))

        return facts

    # =========================================================================
    # FORMATTING HELPERS
    # =========================================================================

    def _format_conversation_indexed(
        self,
        turns: List[ConversationTurn]
    ) -> Tuple[str, Dict[str, int]]:
        """
        Format conversation turns with letter-based labels (A, B, C...) for LLM consumption.

        Uses letters instead of numbers to create distinct symbol spaces:
        - Turn labels: A, B, C... (letters)
        - Topic numbers: 1, 2, 3... (integers)

        This prevents the LLM from pattern-matching on numeric examples and
        hallucinating extra turn indices. Letters are more obviously "labels"
        that must correspond to actual conversation turns shown.

        Args:
            turns: List of conversation turns

        Returns:
            Tuple of (formatted_text, label_to_id_mapping)
            - formatted_text: String with [A] Role: content, [B] Role: content, etc.
            - label_to_id_mapping: Dict mapping letter label to actual database ID
        """
        lines = []
        label_to_id = {}

        for i, turn in enumerate(turns):
            # Convert index to letter: 0->A, 1->B, 2->C, etc.
            # For >26 turns, use AA, AB, etc. (though unlikely in practice)
            label = self._index_to_letter(i)
            # Use actual names for better semantic embedding of extracted memories
            name = USER_NAME if turn.role == "user" else AI_NAME
            lines.append(f"[{label}] {name}: {turn.content}")
            label_to_id[label] = turn.id

        return "\n".join(lines), label_to_id

    def _index_to_letter(self, index: int) -> str:
        """
        Convert a 0-based index to a letter label.

        0 -> A, 1 -> B, ..., 25 -> Z, 26 -> AA, 27 -> AB, etc.
        """
        if index < 26:
            return chr(ord('A') + index)
        else:
            # For indices >= 26, use AA, AB, etc.
            first = chr(ord('A') + (index // 26) - 1)
            second = chr(ord('A') + (index % 26))
            return first + second

    def _generate_turn_labels(self, num_turns: int) -> str:
        """Generate comma-separated list of turn labels for the prompt."""
        labels = [self._index_to_letter(i) for i in range(num_turns)]
        return ", ".join(labels)

    def _generate_assignment_example(self, num_turns: int, num_topics: int) -> str:
        """
        Generate a dynamic example JSON matching the actual turn count.

        This prevents the LLM from pattern-matching on a fixed-size example
        and hallucinating extra turns.
        """
        example = {}
        for i in range(num_turns):
            label = self._index_to_letter(i)
            # Distribute across topics in a round-robin fashion for realistic example
            topic = (i % num_topics) + 1
            example[label] = topic
        return json.dumps(example)

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
            # Use actual names for better semantic embedding of extracted memories
            name = USER_NAME if turn.role == "user" else AI_NAME
            lines.append(f"[{i}] {name}: {turn.content}")
        return "\n".join(lines)

    def _format_conversation(self, turns: List[ConversationTurn]) -> str:
        """
        Legacy format method - kept for backwards compatibility.

        Formats conversation with sequential line numbers.
        """
        lines = ["Conversation Block:"]
        for i, turn in enumerate(turns, 1):
            # Use actual names for better semantic embedding of extracted memories
            name = USER_NAME if turn.role == "user" else AI_NAME
            lines.append(f"[{i}] {name}: {turn.content}")
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
            "total_episodic_extractions": self._extraction_count,
            "total_factual_extractions": self._factual_extraction_count,
            "total_extractions": self._extraction_count + self._factual_extraction_count,
            "extraction_in_progress": self._extraction_in_progress.is_set(),
            # Windowed extraction settings
            "context_window_size": self.context_window_size,
            "overflow_trigger": self.overflow_trigger,
            "extraction_batch": self.extraction_batch,
            # Episodic settings
            "min_turns_per_topic": self.min_turns_per_topic,
            "max_episodic_per_extraction": self.max_episodic_per_extraction,
            "skip_minor_topics": self.skip_minor_topics,
            "small_batch_threshold": self.small_batch_threshold,
            # Factual settings
            "max_factual_per_extraction": self.max_factual_per_extraction,
            # Shared settings
            "importance_floor": self.importance_floor
        }


# =============================================================================
# GLOBAL INSTANCE MANAGEMENT
# =============================================================================

_extractor: Optional[MemoryExtractor] = None


def get_memory_extractor() -> MemoryExtractor:
    """Get the global memory extractor instance (lazy initialization)."""
    global _extractor
    if _extractor is None:
        _extractor = MemoryExtractor()
    return _extractor


def init_memory_extractor() -> MemoryExtractor:
    """Initialize the global memory extractor (explicit initialization)."""
    global _extractor
    _extractor = MemoryExtractor()
    return _extractor
