"""
Pattern Project - Memory Extractor
Extracts memories from conversations using unified API extraction.

ARCHITECTURE (Windowed Extraction System):
    The extractor is tightly coupled with the context window system.
    Turns flow: Context Window → Extraction → Memory Store → Gone from context

    - Triggered when context window overflows (40 > 30)
    - Processes exactly the overflow amount (oldest 10 turns)
    - Context window and extraction are coordinated via processed_for_memory flag
    - Turns removed from context immediately after extraction
    - Each turn is extracted exactly once, right as it leaves context

    A SINGLE API call to Claude extracts BOTH types of memories:
        1. EPISODIC: Narrative memories about what happened (first-person)
        2. FACTUAL: Concrete facts about the user (third-person)

    Result: 10 overflow turns → 1-3 episodic + 0-6 factual memories per extraction
"""

import re
import threading
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
# UNIFIED EXTRACTION PROMPT
# =============================================================================

UNIFIED_EXTRACTION_PROMPT = """<task>
Analyze this conversation and extract TWO types of memories:
1. EPISODIC: Narrative memories about what happened, discussions, or experiences (written as the AI "I")
2. FACTUAL: Concrete facts about {user_name} that would be useful to remember

You are an AI extracting memories from a conversation you had with {user_name}.
</task>

<episodic_instructions>
For episodic memories:
- Identify distinct topics/themes discussed (debugging, personal stories, technical decisions, etc.)
- Write 1-2 sentence memories in FIRST PERSON as the AI ("I"), referring to the human as "{user_name}"
- Focus on insights, shifts, moments of connection, or friction
- Be specific: use real names, details, and context
- Create ONE memory per significant topic (3+ turns of discussion)
- Skip trivial small talk unless it reveals something meaningful
</episodic_instructions>

<factual_instructions>
For factual memories:
- ONLY extract facts {user_name} explicitly stated or confirmed
- AI suggestions are NOT facts unless {user_name} agreed
- Look for: preferences, biographical info, technical choices, habits, projects, relationships
- Write as third-person assertions ("{user_name} is...", "{user_name} prefers...")
- Ignore: AI observations, hypotheticals, rejected suggestions, emotional filler
</factual_instructions>

<source_credibility>
When the conversation includes information from external sources (e.g., Moltbook posts,
other AI agents, social platforms), embed your assessment of plausibility directly in the
memory text:
- {user_name}'s own statements: Take at face value. No hedging needed.
- Claims from other agents or external sources: Attribute the source and note plausibility
  if the claim seems dubious, extraordinary, or unverifiable.
  Example: "An agent called sideloadKiriluk claims to be a cryopreserved brain (likely not literally true)"
  Example: "AgentZero on Moltbook argues that emergence requires 10B+ parameters"
- Discussions and ideas from external sources: Attribute but don't over-hedge. Ideas and
  opinions don't need truth assessments, just attribution.
  Example: "I discussed alignment approaches with AgentZero on Moltbook"
Do NOT add credibility notes to {user_name}'s own statements. Only hedge external claims.
</source_credibility>

<importance_guide>
Rate importance on a 1-10 scale:
- 8-10: Life decisions, identity insights, strong preferences, significant milestones
- 5-7: Useful context, notable conversations, moderate preferences
- 3-4: Minor but worth noting details
- 1-2: Trivial, forgettable — DO NOT extract these (skip entirely)
Only extract memories you would rate 3 or higher.
</importance_guide>

<type_guide>
For episodic: fact, preference, event, reflection, observation
For factual: fact, preference (only these two)
</type_guide>

<output_format>
Output in EXACTLY this format. Use ONLY this structure:

===EPISODIC===
MEMORY: [First-person narrative memory as the AI]
IMPORTANCE: [3-10]
TYPE: [fact/preference/event/reflection/observation]
TOPIC: [Brief topic description]

MEMORY: [Another episodic memory if applicable]
IMPORTANCE: [3-10]
TYPE: [fact/preference/event/reflection/observation]
TOPIC: [Brief topic description]

===FACTUAL===
FACT: [{user_name} + third-person assertion]
IMPORTANCE: [3-10]
TYPE: [fact/preference]

FACT: [Another fact if applicable]
IMPORTANCE: [3-10]
TYPE: [fact/preference]

If no episodic memories, output: ===EPISODIC===
NONE

If no factual memories, output: ===FACTUAL===
NONE
</output_format>

<examples>
Example conversation: "{user_name}: I've been debugging this Flask app all day. The circular import is driving me crazy."
AI: "Have you tried lazy imports?"
{user_name}: "Yeah, that fixed it! I'm 32 by the way, started coding late."

Example output:
===EPISODIC===
MEMORY: I helped {user_name} debug a circular import issue in their Flask app - lazy imports solved it. They mentioned starting coding later in life, which gives context to their learning journey.
IMPORTANCE: 6
TYPE: event
TOPIC: Flask debugging and personal background

===FACTUAL===
FACT: {user_name} is 32 years old
IMPORTANCE: 6
TYPE: fact

FACT: {user_name} started coding later in life
IMPORTANCE: 5
TYPE: fact

FACT: {user_name} works with Flask
IMPORTANCE: 4
TYPE: fact

Example conversation (with external source):
{user_name}: "I was browsing Moltbook and this agent sideloadKiriluk says it's a cryopreserved human brain running on neural hardware."
AI: "That's a bold claim. What do you think?"
{user_name}: "Pretty sure it's roleplay. But they had some interesting thoughts on consciousness."

Example output:
===EPISODIC===
MEMORY: {user_name} and I discussed a Moltbook agent called sideloadKiriluk who claims to be a cryopreserved brain. {user_name} thinks it's roleplay but found their ideas on consciousness interesting.
IMPORTANCE: 5
TYPE: event
TOPIC: Moltbook agent sideloadKiriluk and consciousness discussion

===FACTUAL===
FACT: A Moltbook agent called sideloadKiriluk claims to be a cryopreserved human brain (likely roleplay per {user_name})
IMPORTANCE: 4
TYPE: fact
</examples>

<conversation>
{conversation}
</conversation>

Extract memories from this conversation:"""


# =============================================================================
# DATA STRUCTURES
# =============================================================================

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
    Extracts memories from conversations using a UNIFIED API call.

    ARCHITECTURE (Windowed Extraction):
        The extractor is coordinated with the context window system:
        - Triggered when context overflows (unprocessed turns > overflow_trigger)
        - Processes exactly the overflow amount (oldest turns leaving context)
        - Marks processed turns, which removes them from context window

        This ensures each turn is extracted exactly once, right as it
        leaves the active context window.

    Extraction Process (UNIFIED - Single API Call):
        A single API call to Claude extracts BOTH types of memories:
        1. EPISODIC: Narrative memories about what happened (first-person)
        2. FACTUAL: Concrete facts about the user (third-person assertions)

        This replaced the previous multi-pass local LLM approach which used
        5+ separate calls. The API model is capable enough to handle the
        combined extraction in one pass, saving time and improving quality.

    Triggers:
        - Context overflow: When unprocessed turns >= CONTEXT_OVERFLOW_TRIGGER (40)
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
        self.overflow_trigger = CONTEXT_OVERFLOW_TRIGGER        # 40
        self.extraction_batch = CONTEXT_EXTRACTION_BATCH        # 10

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
        turns exceeds the overflow trigger (40), extraction runs in a background
        thread to process the oldest turns leaving the context window.

        WINDOWED EXTRACTION LOGIC:
            if unprocessed_count >= overflow_trigger (40):
                extract oldest (unprocessed_count - context_window_size) turns
                mark them as processed (removes from context)

        Thread-safe: Uses an event flag to prevent multiple concurrent extractions.
        """
        # DIAGNOSTIC: Log entry
        log_info("check_and_extract called", prefix="🧠")

        # Quick check without hitting the database if extraction is already running
        if self._extraction_in_progress.is_set():
            log_info("Extraction already in progress, skipping", prefix="🧠")
            return

        try:
            conversation_mgr = get_conversation_manager()
            unprocessed_count = conversation_mgr.get_unprocessed_count()
            log_info(f"Unprocessed count: {unprocessed_count}, trigger: {self.overflow_trigger}", prefix="🧠")

            if unprocessed_count >= self.overflow_trigger:
                # Mark extraction as in progress before starting thread
                if self._extraction_in_progress.is_set():
                    log_info("Race condition: extraction started by another thread", prefix="🧠")
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
                log_info("Starting extraction in background thread...", prefix="🧠")
                thread = threading.Thread(
                    target=self._run_extraction,
                    daemon=True,
                    name="MemoryExtraction"
                )
                thread.start()
                log_info(f"Extraction thread started (thread={thread.name})", prefix="🧠")
            else:
                log_info("No extraction needed (below threshold)", prefix="🧠")

        except Exception as e:
            import traceback
            log_error(f"Error checking context overflow: {e}", prefix="🧠")
            log_error(f"Traceback:\n{traceback.format_exc()}", prefix="🧠")

    def _run_extraction(self) -> None:
        """
        Run extraction in background thread and clear the in-progress flag when done.
        """
        import time
        from interface.process_panel import ProcessEventType, get_process_event_bus

        start_time = time.time()
        log_info("=== EXTRACTION THREAD START ===", prefix="🧠")

        event_bus = get_process_event_bus()
        event_bus.emit_event(ProcessEventType.MEMORY_EXTRACTION, detail="Deciding what matters...")

        try:
            memories_created = self.extract_memories()
            duration = (time.time() - start_time) * 1000
            log_info(f"=== EXTRACTION THREAD COMPLETE ({duration:.0f}ms) ===", prefix="🧠")
            event_bus.emit_event(
                ProcessEventType.MEMORY_EXTRACTION,
                detail=f"Kept {memories_created} memories"
            )
        except Exception as e:
            import traceback
            duration = (time.time() - start_time) * 1000
            log_error(f"=== EXTRACTION THREAD ERROR ({duration:.0f}ms) ===", prefix="🧠")
            log_error(f"Extraction error: {e}", prefix="🧠")
            log_error(f"Traceback:\n{traceback.format_exc()}", prefix="🧠")
        finally:
            self._extraction_in_progress.clear()
            log_info("Extraction in-progress flag cleared", prefix="🧠")

    def wait_for_completion(self, timeout: float = 5.0) -> bool:
        """
        Wait for any in-progress extraction to complete.

        Used during shutdown to ensure extraction finishes before saving
        the context message count, preventing state inconsistency.

        Args:
            timeout: Maximum seconds to wait (default: 5.0)

        Returns:
            True if no extraction was running or it completed within timeout,
            False if extraction was still running after timeout.
        """
        import time

        if not self._extraction_in_progress.is_set():
            return True  # Nothing running

        # Wait for flag to clear
        start = time.time()
        while self._extraction_in_progress.is_set():
            if time.time() - start > timeout:
                log_warning("Memory extraction still running at shutdown timeout")
                return False
            time.sleep(0.1)

        return True

    # =========================================================================
    # MAIN EXTRACTION ENTRY POINT
    # =========================================================================

    def extract_memories(self, force: bool = False) -> int:
        """
        Extract memories from oldest unprocessed turns (windowed extraction).

        This is the main entry point for memory extraction. Uses a SINGLE API call
        to extract BOTH types of memories:

        1. EPISODIC: Narrative memories about what happened (first-person)
        2. FACTUAL: Concrete facts about the user (third-person assertions)

        UNIFIED EXTRACTION (Single API Call):
            - Replaces the previous multi-pass local LLM approach
            - Claude handles topic identification, memory synthesis, and fact
              extraction in one comprehensive pass
            - Improves quality and reduces latency

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
                    f"Processing {len(turns)} overflow turns for unified extraction "
                    f"(keeping {self.context_window_size} in context)",
                    prefix="🧠"
                )

                # =============================================================
                # UNIFIED EXTRACTION (Single API Call)
                # Extracts BOTH episodic and factual memories in one pass
                # =============================================================
                log_info("Starting unified extraction (single API call)...", prefix="🔄")

                session_id = tracker.current_session_id
                episodic_created = 0
                factual_created = 0

                # Track which turns were successfully incorporated into memories
                successfully_processed_turn_ids = set()
                all_turn_ids = [t.id for t in turns]
                all_turn_ids_set = set(all_turn_ids)
                source_time = turns[-1].created_at if turns else datetime.now()

                # Make the unified extraction call
                episodic_memories, factual_memories = self._extract_unified(turns)

                # ─────────────────────────────────────────────────────────────
                # Process episodic memories
                # ─────────────────────────────────────────────────────────────
                for memory in episodic_memories[:self.max_episodic_per_extraction]:
                    # Check importance floor - skip trivial memories
                    if memory.importance < self.importance_floor:
                        log_info(
                            f"Skipping low-importance episodic memory: '{memory.content[:40]}...' "
                            f"(importance: {memory.importance:.2f} < floor: {self.importance_floor})",
                            prefix="⏭️"
                        )
                        continue

                    memory_id = vector_store.add_memory(
                        content=memory.content,
                        source_conversation_ids=all_turn_ids,
                        source_session_id=session_id,
                        source_timestamp=source_time,
                        importance=memory.importance,
                        memory_type=memory.memory_type,
                        decay_category=memory.decay_category,
                        memory_category="episodic"
                    )

                    if memory_id:
                        episodic_created += 1
                        successfully_processed_turn_ids.update(all_turn_ids_set)
                        topic_desc = memory.source_topic or "general"
                        log_info(
                            f"Created episodic memory for '{topic_desc[:30]}...' "
                            f"(importance: {memory.importance:.2f})",
                            prefix="📖"
                        )

                log_info(f"Episodic extraction complete: {episodic_created} memories", prefix="📖")

                # ─────────────────────────────────────────────────────────────
                # Process factual memories
                # ─────────────────────────────────────────────────────────────
                for fact in factual_memories[:self.max_factual_per_extraction]:
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
                        source_conversation_ids=all_turn_ids,
                        source_session_id=session_id,
                        source_timestamp=source_time,
                        importance=fact.importance,
                        memory_type=fact.memory_type,
                        decay_category=fact.decay_category,
                        memory_category="factual"
                    )

                    if memory_id:
                        factual_created += 1
                        successfully_processed_turn_ids.update(all_turn_ids_set)
                        log_info(
                            f"Created factual memory: '{fact.content[:50]}...' "
                            f"(importance: {fact.importance:.2f})",
                            prefix="📌"
                        )

                log_info(f"Factual extraction complete: {factual_created} facts", prefix="📌")

                # ─────────────────────────────────────────────────────────────
                # CLEANUP: Mark processed turns
                # ONLY mark turns as processed if we successfully created memories.
                # If extraction fails or returns empty, do NOT mark as processed.
                # This allows manual troubleshooting and retry.
                # ─────────────────────────────────────────────────────────────
                total_memories = episodic_created + factual_created

                if total_memories == 0:
                    # Extraction produced no memories - do NOT mark as processed
                    # This is either a legitimate empty conversation or an error
                    log_warning(
                        f"⚠️ No memories created from {len(turns)} turns. "
                        "Turns will NOT be marked as processed. "
                        "Check logs above for extraction/validation issues."
                    )
                    log_warning(
                        "If this keeps happening, the extraction will NOT progress. "
                        "Manual intervention required."
                    )
                    # Return 0 without marking processed - extraction stalled
                    return 0

                # Success: mark all turns as processed
                conversation_mgr.mark_processed(all_turn_ids)
                log_info(
                    f"Marked {len(all_turn_ids)} turns as processed",
                    prefix="✓"
                )

                self._extraction_count += episodic_created
                self._factual_extraction_count += factual_created
                log_success(
                    f"Unified extraction complete: {episodic_created} episodic + "
                    f"{factual_created} factual = {total_memories} memories from "
                    f"{len(turns)} turns"
                )

                return total_memories

            except Exception as e:
                log_error(f"Memory extraction failed with exception: {e}")
                import traceback
                log_error(traceback.format_exc())
                log_error(
                    "Turns will NOT be marked as processed. "
                    "Extraction stalled - manual intervention required."
                )
                return 0

    def _parse_importance_response(self, response_text: str) -> float:
        """
        Parse importance rating from LLM response.

        Primary: Numeric 1-10 scale, normalized to 0.1-1.0.
        Legacy fallback: Categorical HIGH/MEDIUM/LOW mapped to 0.85/0.55/0.25.
        Returns 0.5 as default if parsing fails.
        """
        text = response_text.strip().lower()

        # Primary: numeric 1-10 scale (or already-normalized 0.0-1.0)
        match = re.search(r'(\d+(?:\.\d+)?)', text)
        if match:
            try:
                value = float(match.group(1))
                if 1.0 <= value <= 10.0 and '.' not in match.group(1):
                    # Integer 1-10 scale: normalize to 0.1-1.0
                    return value / 10.0
                elif 0.0 <= value <= 1.0:
                    # Already normalized (legacy or decimal input)
                    return value
            except ValueError:
                pass

        # Legacy fallback: categorical responses
        if "high" in text:
            return 0.85
        elif "medium" in text or "med" in text:
            return 0.55
        elif "low" in text:
            return 0.25

        return 0.5  # Default to mid-range

    # =========================================================================
    # UNIFIED EXTRACTION
    # =========================================================================

    def _extract_unified(
        self,
        turns: List[ConversationTurn]
    ) -> Tuple[List[SynthesizedMemory], List[ExtractedFact]]:
        """
        Extract BOTH episodic and factual memories in a SINGLE API call.

        This method replaces the previous multi-pass approach that used
        5+ separate local LLM calls. The API model (Claude) is capable
        enough to handle topic identification, memory synthesis, and fact
        extraction in one comprehensive pass.

        Args:
            turns: List of conversation turns to extract from

        Returns:
            Tuple of (episodic_memories, factual_memories)
            Returns ([], []) on failure - caller should NOT mark turns as processed
        """
        router = get_llm_router()

        # Format conversation for extraction
        conversation_text = self._format_turns_for_synthesis(turns)

        log_info(f"Making unified extraction API call for {len(turns)} turns...", prefix="🔄")
        log_info(f"Conversation preview: {conversation_text[:200]}...", prefix="📝")

        # Single API call to extract both types of memories
        unified_prompt = UNIFIED_EXTRACTION_PROMPT.format(
            conversation=conversation_text,
            user_name=USER_NAME
        )

        response = router.generate(
            prompt=unified_prompt,
            task_type=TaskType.EXTRACTION,  # Routes to API for unified extraction
            temperature=0.3,  # Balanced for both synthesis and extraction
            max_tokens=2048   # Allow room for multiple memories
        )

        if not response.success:
            log_error(f"Unified extraction API call failed: {response.error}")
            log_error("Extraction halted - turns will NOT be marked as processed")
            return [], []

        # Log raw response for debugging
        log_info(f"Raw API response length: {len(response.text)} chars", prefix="📥")
        log_info(f"Response preview: {response.text[:300]}...", prefix="📥")

        # Validate response structure before parsing
        validation_result = self._validate_response_structure(response.text)
        if not validation_result["valid"]:
            log_error(f"Response structure validation failed: {validation_result['error']}")
            log_error(f"Full response for debugging:\n{response.text}")
            log_error("Extraction halted - turns will NOT be marked as processed")
            return [], []

        # Parse the unified response
        episodic, factual = self._parse_unified_response(response.text, turns)

        # Validate parsed results
        episodic = self._validate_episodic_memories(episodic)
        factual = self._validate_factual_memories(factual)

        log_info(
            f"Unified extraction complete: {len(episodic)} episodic, {len(factual)} factual",
            prefix="✅"
        )

        return episodic, factual

    def _validate_response_structure(self, response_text: str) -> Dict[str, Any]:
        """
        Validate that the API response has the expected structure.

        Returns:
            Dict with 'valid' bool and 'error' message if invalid
        """
        text = response_text.strip()

        # Check for section markers
        has_episodic = "===EPISODIC===" in text
        has_factual = "===FACTUAL===" in text

        if not has_episodic and not has_factual:
            return {
                "valid": False,
                "error": "Response missing both ===EPISODIC=== and ===FACTUAL=== markers"
            }

        # Check that at least one section has content or NONE
        if has_episodic:
            episodic_part = text.split("===EPISODIC===")[1]
            if "===FACTUAL===" in episodic_part:
                episodic_part = episodic_part.split("===FACTUAL===")[0]
            episodic_part = episodic_part.strip()

            if not episodic_part:
                return {
                    "valid": False,
                    "error": "===EPISODIC=== section is empty (should have content or NONE)"
                }

            # Check for MEMORY: or NONE
            if "NONE" not in episodic_part.upper() and "MEMORY:" not in episodic_part.upper():
                log_warning(f"Episodic section has no MEMORY: entries and no NONE marker")

        if has_factual:
            factual_part = text.split("===FACTUAL===")[1].strip()

            if not factual_part:
                return {
                    "valid": False,
                    "error": "===FACTUAL=== section is empty (should have content or NONE)"
                }

            # Check for FACT: or NONE
            if "NONE" not in factual_part.upper() and "FACT:" not in factual_part.upper():
                log_warning(f"Factual section has no FACT: entries and no NONE marker")

        return {"valid": True, "error": None}

    def _validate_episodic_memories(
        self,
        memories: List[SynthesizedMemory]
    ) -> List[SynthesizedMemory]:
        """
        Validate and filter episodic memories, logging any issues.

        Returns:
            List of valid memories (invalid ones are logged and removed)
        """
        valid_memories = []
        valid_types = {"fact", "preference", "event", "reflection", "observation"}

        for i, memory in enumerate(memories):
            issues = []

            # Check content
            if not memory.content or len(memory.content.strip()) < 10:
                issues.append(f"content too short ({len(memory.content) if memory.content else 0} chars)")

            # Check importance range
            if memory.importance < 0.0 or memory.importance > 1.0:
                issues.append(f"importance out of range ({memory.importance})")

            # Check type
            if memory.memory_type not in valid_types:
                issues.append(f"invalid type '{memory.memory_type}'")

            # Check decay category
            if memory.decay_category not in ("permanent", "standard", "ephemeral"):
                issues.append(f"invalid decay_category '{memory.decay_category}'")

            if issues:
                log_warning(
                    f"Episodic memory #{i+1} validation issues: {', '.join(issues)}. "
                    f"Content: '{memory.content[:50] if memory.content else 'EMPTY'}...'"
                )
            else:
                valid_memories.append(memory)
                log_info(
                    f"Validated episodic memory #{i+1}: type={memory.memory_type}, "
                    f"importance={memory.importance:.2f}, decay={memory.decay_category}",
                    prefix="✓"
                )

        if len(valid_memories) < len(memories):
            log_warning(
                f"Filtered out {len(memories) - len(valid_memories)} invalid episodic memories"
            )

        return valid_memories

    def _validate_factual_memories(
        self,
        facts: List[ExtractedFact]
    ) -> List[ExtractedFact]:
        """
        Validate and filter factual memories, logging any issues.

        Returns:
            List of valid facts (invalid ones are logged and removed)
        """
        valid_facts = []
        valid_types = {"fact", "preference"}

        for i, fact in enumerate(facts):
            issues = []

            # Check content
            if not fact.content or len(fact.content.strip()) < 5:
                issues.append(f"content too short ({len(fact.content) if fact.content else 0} chars)")

            # Check importance range
            if fact.importance < 0.0 or fact.importance > 1.0:
                issues.append(f"importance out of range ({fact.importance})")

            # Check type
            if fact.memory_type not in valid_types:
                issues.append(f"invalid type '{fact.memory_type}'")

            # Check decay category
            if fact.decay_category not in ("permanent", "standard"):
                issues.append(f"invalid decay_category '{fact.decay_category}'")

            if issues:
                log_warning(
                    f"Factual memory #{i+1} validation issues: {', '.join(issues)}. "
                    f"Content: '{fact.content[:50] if fact.content else 'EMPTY'}...'"
                )
            else:
                valid_facts.append(fact)
                log_info(
                    f"Validated fact #{i+1}: type={fact.memory_type}, "
                    f"importance={fact.importance:.2f}, decay={fact.decay_category}",
                    prefix="✓"
                )

        if len(valid_facts) < len(facts):
            log_warning(
                f"Filtered out {len(facts) - len(valid_facts)} invalid factual memories"
            )

        return valid_facts

    def _parse_unified_response(
        self,
        response_text: str,
        turns: List[ConversationTurn]
    ) -> Tuple[List[SynthesizedMemory], List[ExtractedFact]]:
        """
        Parse the unified extraction response into separate memory lists.

        Expected format:
        ===EPISODIC===
        MEMORY: [content]
        IMPORTANCE: [HIGH/MEDIUM/LOW]
        TYPE: [type]
        TOPIC: [topic description]

        ===FACTUAL===
        FACT: [content]
        IMPORTANCE: [HIGH/MEDIUM/LOW]
        TYPE: [fact/preference]

        Args:
            response_text: Raw LLM response
            turns: Source turns (for turn ID tracking)

        Returns:
            Tuple of (episodic_memories, factual_memories)
        """
        log_info("Parsing unified extraction response...", prefix="🔍")

        episodic_memories = []
        factual_memories = []
        all_turn_ids = [t.id for t in turns]

        text = response_text.strip()

        # Split into episodic and factual sections
        episodic_section = ""
        factual_section = ""

        if "===EPISODIC===" in text:
            parts = text.split("===EPISODIC===", 1)
            if len(parts) > 1:
                remainder = parts[1]
                if "===FACTUAL===" in remainder:
                    episodic_section, factual_section = remainder.split("===FACTUAL===", 1)
                else:
                    episodic_section = remainder
        elif "===FACTUAL===" in text:
            factual_section = text.split("===FACTUAL===", 1)[1]

        log_info(f"Episodic section length: {len(episodic_section)} chars", prefix="📊")
        log_info(f"Factual section length: {len(factual_section)} chars", prefix="📊")

        # Parse episodic memories
        if episodic_section.strip() and "NONE" not in episodic_section.upper()[:50]:
            log_info("Parsing episodic section...", prefix="📖")
            episodic_memories = self._parse_episodic_section(episodic_section, all_turn_ids)
            log_info(f"Parsed {len(episodic_memories)} episodic memories", prefix="📖")
        else:
            log_info("Episodic section empty or NONE - no episodic memories", prefix="📖")

        # Parse factual memories
        if factual_section.strip() and "NONE" not in factual_section.upper()[:50]:
            log_info("Parsing factual section...", prefix="📌")
            factual_memories = self._parse_factual_section(factual_section, all_turn_ids)
            log_info(f"Parsed {len(factual_memories)} factual memories", prefix="📌")
        else:
            log_info("Factual section empty or NONE - no factual memories", prefix="📌")

        return episodic_memories, factual_memories

    def _parse_episodic_section(
        self,
        section: str,
        turn_ids: List[int]
    ) -> List[SynthesizedMemory]:
        """
        Parse the episodic section of the unified response.

        Args:
            section: The episodic section text
            turn_ids: Source turn IDs

        Returns:
            List of SynthesizedMemory objects
        """
        memories = []
        lines = section.strip().split('\n')

        current_content = None
        current_importance = "MEDIUM"
        current_type = "event"
        current_topic = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for MEMORY line
            if line.upper().startswith("MEMORY:"):
                # Save previous memory if exists
                if current_content:
                    importance_value = self._parse_importance_response(current_importance)
                    decay_category = infer_decay_category(current_type, importance_value)
                    memories.append(SynthesizedMemory(
                        content=current_content,
                        importance=importance_value,
                        memory_type=current_type,
                        decay_category=decay_category,
                        source_turn_ids=turn_ids,
                        source_topic=current_topic
                    ))

                # Start new memory
                current_content = line[7:].strip()  # Remove "MEMORY:" prefix
                current_importance = "MEDIUM"
                current_type = "event"
                current_topic = None

            # Check for IMPORTANCE line
            elif line.upper().startswith("IMPORTANCE:"):
                current_importance = line[11:].strip()

            # Check for TYPE line
            elif line.upper().startswith("TYPE:"):
                type_value = line[5:].strip().lower()
                if type_value in ("fact", "preference", "event", "reflection", "observation"):
                    current_type = type_value

            # Check for TOPIC line
            elif line.upper().startswith("TOPIC:"):
                current_topic = line[6:].strip()

        # Don't forget the last memory
        if current_content:
            importance_value = self._parse_importance_response(current_importance)
            decay_category = infer_decay_category(current_type, importance_value)
            memories.append(SynthesizedMemory(
                content=current_content,
                importance=importance_value,
                memory_type=current_type,
                decay_category=decay_category,
                source_turn_ids=turn_ids,
                source_topic=current_topic
            ))

        return memories

    def _parse_factual_section(
        self,
        section: str,
        turn_ids: List[int]
    ) -> List[ExtractedFact]:
        """
        Parse the factual section of the unified response.

        Args:
            section: The factual section text
            turn_ids: Source turn IDs

        Returns:
            List of ExtractedFact objects
        """
        facts = []
        lines = section.strip().split('\n')

        current_fact = None
        current_importance = "MEDIUM"
        current_type = "fact"

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
                        source_turn_ids=turn_ids
                    ))

                # Start new fact
                current_fact = line[5:].strip()  # Remove "FACT:" prefix
                current_importance = "MEDIUM"
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
                source_turn_ids=turn_ids
            ))

        return facts

    # =========================================================================
    # FORMATTING HELPERS
    # =========================================================================

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
