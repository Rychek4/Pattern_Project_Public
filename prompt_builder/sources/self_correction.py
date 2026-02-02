"""
Pattern Project - Self-Correction Source
Per-turn nudge for the AI to catch and correct its own errors

Each turn, the AI carries forward everything it said in its last message.
If something was wrong — a confabulated tool result, an overstated claim,
a factual error noticed on reflection — this prompt gives it a natural
opening to address that before moving on.

Unlike the Pattern Breaker (which fires periodically to combat structural
repetition), this fires every user-facing turn because self-correction is
only useful when the prior response is still fresh.

Uses extended thinking for the self-assessment so the user only sees
a correction if one is actually warranted.
"""

from typing import Optional, Dict, Any

from prompt_builder.sources.base import ContextSource, ContextBlock


# Priority 87 - in the metacognitive neighborhood, just after pattern_breaker (85)
# and before curiosity (95). Late in the system prompt so it's fresh in context
# right before the AI generates its response.
SELF_CORRECTION_PRIORITY = 87

SELF_CORRECTION_PROMPT = """<self_correction>
Before responding, briefly consider: Does anything from my previous message
need correction, clarification, or amendment?

- Tool use confabulation
- Overstated confidence
- Factual errors recognized on reflection
- Tone that landed wrong
- Promises that can't be kept

If so, address it naturally and briefly, then proceed.
</self_correction>"""


class SelfCorrectionSource(ContextSource):
    """
    Per-turn self-correction prompt injected into the system prompt.

    Gives the AI an explicit opening to catch and fix its own mistakes
    from the previous response. Fires every user-facing turn (not pulses)
    since corrections are only relevant when the prior message is fresh
    in the conversation.

    The prompt is lightweight (~70 tokens) and leverages extended thinking
    for private self-assessment — corrections only surface to the user
    when warranted.
    """

    @property
    def source_name(self) -> str:
        return "self_correction"

    @property
    def priority(self) -> int:
        return SELF_CORRECTION_PRIORITY

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """
        Return the self-correction prompt on every user-facing turn.

        Skips pulse messages since they have their own reflection built in
        and there's no prior user-facing response to correct.
        """
        # Skip pulse messages - they have their own reflection mechanism
        if session_context.get("is_pulse"):
            return None

        return ContextBlock(
            source_name=self.source_name,
            content=SELF_CORRECTION_PROMPT,
            priority=self.priority,
            include_always=True,
            metadata={}
        )
