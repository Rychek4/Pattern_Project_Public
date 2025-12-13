"""
Pattern Project - Curiosity Goal Selector
Weighted random selection of curiosity goals.
"""

import random
from typing import List, Optional

from agency.curiosity.analyzer import CuriosityCandidate, get_curiosity_analyzer
from core.logger import log_info


class CuriositySelector:
    """
    Selects curiosity goals via weighted random selection.

    Ensures there is ALWAYS a goal selected - no None returns.
    Uses candidate weights to probabilistically favor more
    relevant/dormant topics while maintaining variety.
    """

    def select(self, candidates: List[CuriosityCandidate]) -> CuriosityCandidate:
        """
        Select a curiosity candidate via weighted random.

        Args:
            candidates: List of weighted candidates

        Returns:
            Selected candidate (NEVER None)
        """
        if not candidates:
            # Fallback - should rarely happen
            analyzer = get_curiosity_analyzer()
            return analyzer.get_fallback_candidate()

        if len(candidates) == 1:
            return candidates[0]

        # Weighted random selection
        return self._weighted_random(candidates)

    def _weighted_random(self, candidates: List[CuriosityCandidate]) -> CuriosityCandidate:
        """
        Perform weighted random selection.

        Args:
            candidates: Non-empty list of candidates with weights

        Returns:
            Randomly selected candidate (weighted by candidate.weight)
        """
        # Extract weights
        weights = [max(c.weight, 0.01) for c in candidates]  # Ensure positive weights
        total_weight = sum(weights)

        # Normalize weights to probabilities
        probabilities = [w / total_weight for w in weights]

        # Select using cumulative distribution
        r = random.random()
        cumulative = 0.0

        for candidate, prob in zip(candidates, probabilities):
            cumulative += prob
            if r <= cumulative:
                return candidate

        # Fallback to last candidate (shouldn't reach here due to float precision)
        return candidates[-1]


# Global instance
_selector: Optional[CuriositySelector] = None


def get_curiosity_selector() -> CuriositySelector:
    """Get the global CuriositySelector instance."""
    global _selector
    if _selector is None:
        _selector = CuriositySelector()
    return _selector
