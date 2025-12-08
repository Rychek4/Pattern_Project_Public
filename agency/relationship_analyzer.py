"""
Pattern Project - Relationship Analyzer
Uses local LLM to interpret conversations and update affinity/trust
"""

import threading
import json
import re
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass

from prompt_builder.sources.relationship import get_relationship_source
from memory.conversation import get_conversation_manager
from memory.vector_store import get_vector_store
from llm.router import get_llm_router, TaskType
from core.logger import log_info, log_error, log_warning


# Analysis prompt for local LLM
RELATIONSHIP_ANALYSIS_PROMPT = """Analyze this conversation excerpt and extracted memories for relationship dynamics.

<conversation>
{conversation}
</conversation>

<recent_memories>
{memories}
</recent_memories>

Based on this interaction, assess changes to the relationship:

1. AFFINITY: How did this interaction affect emotional closeness?
   - Positive signals: sharing personal info, humor, warmth, engagement, returning to chat
   - Negative signals: curt responses, frustration, disengagement, criticism

2. TRUST: How did this interaction affect mutual trust?
   - Positive signals: vulnerability, honesty, reliability, following through
   - Negative signals: evasion, broken promises, inconsistency, deception

Respond with ONLY a valid JSON object on a single line (no markdown, no explanation):
{"affinity_delta": <integer -2 to 2>, "trust_delta": <integer -2 to 2>, "reasoning": "<brief explanation>"}

Rules:
- Use 0 for neutral interactions
- Use 1 or -1 for minor positive/negative interactions
- Use 2 or -2 only for significant positive/negative interactions
- Output must be valid JSON on ONE line"""


@dataclass
class AnalysisResult:
    """Result of relationship analysis."""
    affinity_delta: int
    trust_delta: int
    reasoning: str
    analyzed_at: datetime


class RelationshipAnalyzer:
    """
    Analyzes conversations to update relationship affinity and trust.

    Uses local LLM (KoboldCpp) to interpret conversation dynamics
    and emergently adjust relationship values.

    Runs as background thread, analyzing after memory extraction.
    """

    def __init__(
        self,
        analysis_interval: int = 120,  # Analyze every 2 minutes
        min_turns_for_analysis: int = 4,  # Need at least 4 turns
        max_delta: int = 2  # Maximum change per analysis (on 0-100 scale)
    ):
        """
        Initialize the relationship analyzer.

        Args:
            analysis_interval: Seconds between analysis runs
            min_turns_for_analysis: Minimum turns needed to analyze
            max_delta: Maximum affinity/trust change per analysis (±2)
        """
        self.analysis_interval = analysis_interval
        self.min_turns_for_analysis = min_turns_for_analysis
        self.max_delta = max_delta

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_analysis_turn_id: int = 0
        self._lock = threading.RLock()

    def start(self) -> None:
        """Start the background analysis thread."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._analysis_loop,
            daemon=True,
            name="RelationshipAnalyzer"
        )
        self._thread.start()
        log_info("Relationship analyzer started", prefix="💕")

    def stop(self) -> None:
        """Stop the background analysis thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        log_info("Relationship analyzer stopped", prefix="⏹️")

    def _analysis_loop(self) -> None:
        """Background loop that periodically analyzes conversations."""
        while not self._stop_event.is_set():
            try:
                self._run_analysis()
            except Exception as e:
                log_error(f"Relationship analysis error: {e}")

            self._stop_event.wait(self.analysis_interval)

    def _run_analysis(self) -> Optional[AnalysisResult]:
        """Run a single analysis cycle."""
        conversation_mgr = get_conversation_manager()

        # Get recent conversation turns
        history = conversation_mgr.get_recent_history(limit=20)

        if len(history) < self.min_turns_for_analysis:
            return None

        # Check if we have new turns to analyze
        # (Simple check - in production, track last analyzed turn ID)
        with self._lock:
            current_count = len(history)
            if current_count == self._last_analysis_turn_id:
                return None  # No new turns
            self._last_analysis_turn_id = current_count

        # Get recent memories for context
        vector_store = get_vector_store()
        recent_memories = vector_store.search(
            "recent interaction dynamics relationship",
            limit=5
        )

        # Format conversation for analysis
        conversation_text = self._format_conversation(history[-10:])  # Last 10 turns
        memories_text = self._format_memories(recent_memories)

        # Call local LLM for analysis
        result = self._analyze_with_llm(conversation_text, memories_text)

        if result:
            # Update relationship
            relationship_source = get_relationship_source()
            relationship_source.update(
                affinity_delta=result.affinity_delta,
                trust_delta=result.trust_delta
            )

            log_info(
                f"Relationship analyzed: affinity {result.affinity_delta:+d}, "
                f"trust {result.trust_delta:+d} - {result.reasoning[:50]}...",
                prefix="💕"
            )

        return result

    def _format_conversation(self, history: List[Dict[str, str]]) -> str:
        """Format conversation history for analysis prompt."""
        lines = []
        for turn in history:
            role = "Human" if turn["role"] == "user" else "AI"
            lines.append(f"{role}: {turn['content']}")
        return "\n".join(lines)

    def _format_memories(self, memories) -> str:
        """Format memories for analysis prompt."""
        if not memories:
            return "No recent memories available."

        lines = []
        for result in memories:
            lines.append(f"- {result.memory.content}")
        return "\n".join(lines)

    def _normalize_key(self, key: str) -> str:
        """
        Normalize a JSON key by removing quotes, escapes, and extra whitespace.

        Handles malformed LLM outputs like:
        - "affinity_delta" -> affinity_delta
        - 'affinity_delta' -> affinity_delta
        - \"affinity_delta\" -> affinity_delta
        - "\"affinity_delta\"" -> affinity_delta
        """
        # Remove all quote characters and backslashes
        normalized = re.sub(r'["\'\\\`]', '', str(key))
        # Strip whitespace and lowercase for case-insensitive matching
        return normalized.strip().lower()

    def _find_key_value(self, data: dict, target: str) -> Optional[Any]:
        """
        Find a value by normalized key matching.

        Args:
            data: Parsed JSON dictionary
            target: Key to find (e.g., "affinity_delta")

        Returns:
            Value if found, None otherwise
        """
        target_normalized = self._normalize_key(target)
        for key, value in data.items():
            if self._normalize_key(key) == target_normalized:
                return value
        return None

    def _analyze_with_llm(
        self,
        conversation: str,
        memories: str
    ) -> Optional[AnalysisResult]:
        """Call local LLM to analyze relationship dynamics."""
        router = get_llm_router()

        prompt = RELATIONSHIP_ANALYSIS_PROMPT.format(
            conversation=conversation,
            memories=memories
        )

        response = router.generate(
            prompt=prompt,
            task_type=TaskType.EXTRACTION,  # Uses local LLM
            max_tokens=256,
            temperature=0.3
        )

        if not response.success:
            log_warning(f"Relationship analysis LLM call failed: {response.error}")
            return None

        # Parse JSON response with robust extraction
        try:
            text = response.text.strip()

            # Handle potential markdown code blocks
            if "```" in text:
                match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
                if match:
                    text = match.group(1)

            # Try to find JSON object in the response (handles extra text/whitespace)
            # Use flexible pattern that matches any key containing affinity_delta
            json_match = re.search(r'\{[^{}]*affinity_delta[^{}]*\}', text, re.DOTALL | re.IGNORECASE)
            if json_match:
                text = json_match.group(0)

            # Normalize whitespace within JSON (fixes malformed responses with newlines)
            text = re.sub(r'\s+', ' ', text).strip()

            # Fix common quote escaping issues before parsing
            # Handle \"key\" patterns
            text = re.sub(r'"\\"([^"]+)\\""\s*:', r'"\1":', text)
            # Handle "'key'" patterns
            text = re.sub(r"\"'([^']+)'\"\s*:", r'"\1":', text)

            data = json.loads(text)

            # Use fuzzy key lookup to handle malformed keys
            affinity_delta_raw = self._find_key_value(data, "affinity_delta")
            trust_delta_raw = self._find_key_value(data, "trust_delta")
            reasoning_raw = self._find_key_value(data, "reasoning")

            # Validate required keys exist
            if affinity_delta_raw is None:
                log_warning(
                    f"Missing 'affinity_delta' in response. "
                    f"Found keys: {list(data.keys())}. Raw text: {text[:200]}"
                )
                return None

            if trust_delta_raw is None:
                log_warning(
                    f"Missing 'trust_delta' in response. "
                    f"Found keys: {list(data.keys())}. Raw text: {text[:200]}"
                )
                return None

            # Clamp deltas to ±max_delta (default ±2)
            affinity_delta = max(-self.max_delta, min(self.max_delta, int(affinity_delta_raw)))
            trust_delta = max(-self.max_delta, min(self.max_delta, int(trust_delta_raw)))

            return AnalysisResult(
                affinity_delta=affinity_delta,
                trust_delta=trust_delta,
                reasoning=str(reasoning_raw) if reasoning_raw else "",
                analyzed_at=datetime.now()
            )

        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            log_warning(f"Failed to parse relationship analysis: {e}")
            return None

    def analyze_now(self) -> Optional[AnalysisResult]:
        """
        Run analysis immediately (for testing/debugging).

        Returns:
            AnalysisResult if successful
        """
        return self._run_analysis()


# Global instance
_relationship_analyzer: Optional[RelationshipAnalyzer] = None


def get_relationship_analyzer() -> RelationshipAnalyzer:
    """Get the global relationship analyzer instance."""
    global _relationship_analyzer
    if _relationship_analyzer is None:
        _relationship_analyzer = RelationshipAnalyzer()
    return _relationship_analyzer


def init_relationship_analyzer() -> RelationshipAnalyzer:
    """Initialize and start the global relationship analyzer."""
    global _relationship_analyzer
    _relationship_analyzer = RelationshipAnalyzer()
    _relationship_analyzer.start()
    return _relationship_analyzer
