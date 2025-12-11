"""
Pattern Project - Agency Economy Context Source
Injects the AI's economic state and options into prompts
"""

from typing import Optional, Dict, Any

import config
from prompt_builder.sources.base import ContextSource, ContextBlock
from core.logger import log_info


# Priority for economy: after goal tree (15), before active thoughts (18)
AGENCY_ECONOMY_PRIORITY = 16


class AgencyEconomySource(ContextSource):
    """
    Provides the AI's agency economy state.

    The economy shows:
    - Current points balance
    - Last auction result
    - Available tempo options
    - Next scheduled wakeup

    The AI controls tempo via:
    - [[SET_TEMPO: option_name]]
    """

    @property
    def source_name(self) -> str:
        return "agency_economy"

    @property
    def priority(self) -> int:
        return AGENCY_ECONOMY_PRIORITY

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """Get economy context for prompt injection."""
        if not config.AGENCY_ECONOMY_ENABLED:
            return None

        from agency.economy import get_economy_manager

        try:
            manager = get_economy_manager()
            state = manager.get_state()
            options = manager.get_tempo_options(state.agency_points)

            content = self._build_context(state, options)

            # Store in session context
            session_context["agency_points"] = state.agency_points
            session_context["last_auction_winner"] = state.last_auction_winner

            return ContextBlock(
                source_name=self.source_name,
                content=content,
                priority=self.priority,
                include_always=True,
                metadata={
                    "agency_points": state.agency_points,
                    "last_auction_winner": state.last_auction_winner,
                    "tempo_options_count": len(options)
                }
            )

        except Exception as e:
            log_info(f"AgencyEconomySource error: {e}")
            return None

    def _build_context(self, state, options) -> str:
        """Build the economy context."""
        lines = ["<agency_economy>"]

        # Current balance
        lines.append(f"Agency Points: {state.agency_points:.0f}")

        # Last auction result
        if state.last_auction_winner:
            winner = "You" if state.last_auction_winner == "ai" else "User"
            lines.append(f"Last Auction: {winner} won topic control")

        # Time since last action
        if state.last_action_at:
            from core.temporal import format_fuzzy_relative_time
            lines.append(f"Last goal action: {format_fuzzy_relative_time(state.last_action_at)}")

        lines.append("")

        # Tempo options
        lines.append("Tempo Options (set your next wakeup):")
        for opt in options:
            cost_str = f"{opt.cost:.0f} pts" if opt.cost > 0 else "Free"
            affordable = "✓" if state.agency_points >= opt.cost else "✗"
            lines.append(f"  [{affordable}] {opt.name}: {opt.description} ({cost_str})")

        lines.append("")

        # Next scheduled wakeup
        if state.next_scheduled_wakeup:
            from datetime import datetime
            remaining = (state.next_scheduled_wakeup - datetime.now()).total_seconds()
            if remaining > 0:
                lines.append(f"Next scheduled wakeup: {remaining / 60:.0f} minutes")
            else:
                lines.append("Scheduled wakeup: imminent")
        else:
            lines.append("Next wakeup: Standard pulse interval")

        lines.append("")

        # Command reference
        lines.append("Commands:")
        lines.append("  [[SET_TEMPO: option_name]] - e.g., [[SET_TEMPO: focus_5min]]")

        # Economic tips
        lines.append("")
        lines.append("Economy tips:")
        lines.append(f"  - Points accumulate at {config.AGENCY_POINT_RATE}/sec while waiting")
        lines.append(f"  - Topic hijack costs {config.AUCTION_HIJACK_COST:.0f} pts")
        lines.append("  - Shorter wakeup intervals cost more points")
        lines.append("  - High engagement = spend on focus = burst of activity")

        lines.append("</agency_economy>")

        return "\n".join(lines)


# Global instance
_economy_source: Optional[AgencyEconomySource] = None


def get_agency_economy_source() -> AgencyEconomySource:
    """Get the global AgencyEconomySource instance."""
    global _economy_source
    if _economy_source is None:
        _economy_source = AgencyEconomySource()
    return _economy_source
