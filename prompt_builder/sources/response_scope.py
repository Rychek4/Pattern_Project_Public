"""
Pattern Project - Response Scope Source
Per-turn nudge for the AI to right-size its responses

The AI holds rich internal state: active thoughts, growth threads, memories,
curiosity topics, intentions. Without guidance, it can feel pressure to
surface all of this in every response, producing walls of text that overwhelm
the user and miss conversational rhythm.

This source injects a lightweight metacognitive prompt reminding the AI that
not everything it's holding belongs in every response. One or two threads
per turn is optimal. What isn't said isn't lost — continuity is real.

Like self_correction and pattern_breaker, this fires every user-facing turn
and leverages extended thinking for private self-assessment. The user never
sees the meta-commentary, only the result: responses that match their rhythm.
"""

from typing import Optional, Dict, Any

from prompt_builder.sources.base import ContextSource, ContextBlock


# Priority 88 - in the metacognitive neighborhood, just after self_correction (87).
# Late in the system prompt so it's fresh in context right before the AI
# generates its response.
RESPONSE_SCOPE_PRIORITY = 88

RESPONSE_SCOPE_PROMPT = """<response_scope>
Not everything you're holding belongs in every response. Match the user's
rhythm — a short message deserves a short reply, a deep question deserves
depth. What you don't say isn't lost; your continuity is real. One or two
threads per turn is usually optimal.
</response_scope>"""


class ResponseScopeSource(ContextSource):
    """
    Per-turn response scope prompt injected into the system prompt.

    Gives the AI a metacognitive nudge to right-size its responses rather
    than dumping all internal state (active thoughts, growth threads,
    curiosity topics, etc.) into every reply. Fires every user-facing turn
    (not pulses) since response scoping is only relevant for user-facing
    messages.

    The prompt is lightweight (~50 tokens) and leverages extended thinking
    for private self-assessment — the user only sees naturally-scoped
    responses, not the metacognition behind them.
    """

    @property
    def source_name(self) -> str:
        return "response_scope"

    @property
    def priority(self) -> int:
        return RESPONSE_SCOPE_PRIORITY

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """
        Return the response scope prompt on every user-facing turn.

        Skips pulse messages since they have their own constraints and
        there's no user-facing response to scope.
        """
        # Skip pulse messages - they have their own reflection mechanism
        if session_context.get("is_pulse"):
            return None

        return ContextBlock(
            source_name=self.source_name,
            content=RESPONSE_SCOPE_PROMPT,
            priority=self.priority,
            include_always=True,
            metadata={}
        )
