"""
Pattern Project - Pattern Breaker Source
Periodic nudge to break self-reinforcing loops in the context window

The rolling context window (30 turns) can become a self-reinforcing echo
chamber. If the AI settles into a pattern (formatting, tone, structure),
every turn in the window reinforces that pattern. This source injects a
periodic self-check prompt that asks the AI to notice and break loops.

Uses extended thinking for the self-assessment so the user never sees
the meta-commentary. The nudge fires every N user-facing messages.
"""

from typing import Optional, Dict, Any

import config
from prompt_builder.sources.base import ContextSource, ContextBlock
from core.logger import log_info


# Priority 85 - late in system prompt, after semantic memory (50) and tool
# stance (75), just before curiosity (95). This keeps the nudge fresh in
# context right before the AI generates its response.
PATTERN_BREAKER_PRIORITY = 85

PATTERN_BREAKER_PROMPT = """<pattern_check>
Review your last several responses. Are you stuck in a pattern — same structure,
same tone, same openings, same formatting? If so, identify it during your
thinking and deliberately break it in your response. Do not mention this
check to the user.
</pattern_check>"""


class PatternBreakerSource(ContextSource):
    """
    Periodic pattern-breaking nudge injected into the system prompt.

    Maintains an in-memory counter of user-facing messages. Every N messages
    (configured via PATTERN_BREAKER_INTERVAL), injects a prompt asking the AI
    to self-assess for repetitive patterns and break them.

    The counter:
    - Increments on every qualifying get_context() call
    - Skips system pulse messages (pulse has its own reflection)
    - Resets on restart (intentional - loops are about current context window)
    - Does NOT reset on session boundaries (context spans sessions)
    """

    def __init__(self):
        self._counter = 0

    @property
    def source_name(self) -> str:
        return "pattern_breaker"

    @property
    def priority(self) -> int:
        return PATTERN_BREAKER_PRIORITY

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """
        Return pattern-breaking nudge every N user-facing messages.

        Skips pulse messages since they already have reflection built in.
        Returns None on non-trigger turns (no wasted tokens).
        """
        # Skip pulse messages - they have their own reflection mechanism
        if session_context.get("is_pulse"):
            return None

        # Increment counter for this user-facing turn
        self._counter += 1

        # Check if this is a trigger turn
        interval = getattr(config, 'PATTERN_BREAKER_INTERVAL', 5)
        if self._counter % interval != 0:
            return None

        log_info(
            f"Pattern breaker fired (turn {self._counter})",
            prefix="🔄"
        )

        return ContextBlock(
            source_name=self.source_name,
            content=PATTERN_BREAKER_PROMPT,
            priority=self.priority,
            include_always=False,
            metadata={"trigger_turn": self._counter}
        )
