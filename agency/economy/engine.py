"""
Pattern Project - Agency Economy Engine
Main orchestration loop for the agency system
"""

from datetime import datetime, timedelta
from typing import Optional, Tuple

import config
from core.logger import log_info, log_warning, log_section

from agency.goals import get_goal_manager, Goal
from agency.economy.manager import get_economy_manager
from agency.economy.models import (
    AgencyDecision,
    AuctionResult,
    TempoDecision,
    AuctionWinner
)


class AgencyEconomyEngine:
    """
    Main orchestration engine for the agency economy.

    This engine is called on each system wake-up and runs the
    complete agency cycle:

    1. INCOME: Calculate points earned since last wake-up
    2. AUCTION: AI bids against user for topic control
    3. ACTION: If AI won, work on goal tree
    4. TEMPO: Select next wake-up interval

    The engine creates emergent "flow state" behavior:
    - High engagement → short pulses → burst of activity
    - Goal complete → no urgency → long rest → accumulate
    """

    def __init__(self):
        self._goal_manager = get_goal_manager()
        self._economy_manager = get_economy_manager()

    def on_wakeup(self, trigger_type: str = "pulse") -> AgencyDecision:
        """
        Process a system wake-up through the full agency cycle.

        Args:
            trigger_type: What triggered this wake-up
                - 'pulse': Regular system pulse timer
                - 'scheduled': Purchased tempo wake-up
                - 'user_input': User sent a message

        Returns:
            AgencyDecision with complete cycle results
        """
        log_section(f"Agency Cycle ({trigger_type})", "🎯")

        # Get initial state
        state = self._economy_manager.get_state()
        points_before = state.agency_points

        # =====================================================================
        # PHASE 1: INCOME
        # =====================================================================
        time_delta = 0.0
        if state.last_income_at:
            time_delta = (datetime.now() - state.last_income_at).total_seconds()

        points_earned = self._economy_manager.add_income(time_delta)
        points_after_income = self._economy_manager.get_balance()

        log_info(
            f"Income: {points_before:.0f} → {points_after_income:.0f} pts "
            f"(+{points_earned:.1f} over {time_delta:.0f}s)",
            prefix="💰"
        )

        # =====================================================================
        # PHASE 2: GOAL URGENCY CALCULATION
        # =====================================================================
        goal_urgency, current_goal = self._calculate_goal_urgency()

        # =====================================================================
        # PHASE 3: CONTEXT AUCTION
        # =====================================================================
        auction_result = self._economy_manager.run_auction(
            goal_urgency=goal_urgency,
            user_input_value=config.AUCTION_USER_BID_DEFAULT
        )

        points_after_auction = self._economy_manager.get_balance()

        log_info(
            f"Auction: {auction_result.reason}",
            prefix="🏛️"
        )

        # =====================================================================
        # PHASE 4: TEMPO MARKET (if AI won and has remaining points)
        # =====================================================================
        tempo_decision = None

        if auction_result.ai_won and current_goal is not None:
            # AI won - it will act on its goal
            # Decide on tempo based on remaining points and goal state
            tempo_decision = self._make_tempo_decision(
                points_after_auction,
                goal_urgency,
                current_goal
            )

        points_remaining = self._economy_manager.get_balance()

        # Build final decision
        decision = AgencyDecision(
            time_delta_seconds=time_delta,
            points_earned=points_earned,
            points_before=points_before,
            points_after_income=points_after_income,
            auction_result=auction_result,
            points_after_auction=points_after_auction,
            current_goal_description=current_goal.description if current_goal else None,
            goal_urgency=goal_urgency,
            tempo_decision=tempo_decision,
            points_remaining=points_remaining
        )

        self._log_decision_summary(decision)

        return decision

    def _calculate_goal_urgency(self) -> Tuple[float, Optional[Goal]]:
        """
        Calculate the AI's goal urgency for auction bidding.

        Urgency is based on:
        - Whether there's an active goal (base urgency)
        - Goal priority/difficulty
        - Time since last progress (staleness bonus)

        Returns:
            Tuple of (urgency_score, current_goal)
        """
        # Check for active top goal
        top_goal = self._goal_manager.get_active_top_goal()
        if top_goal is None:
            return 0.0, None

        # Base urgency for having an active goal
        urgency = config.GOAL_URGENCY_BASE

        # Get the current actionable item
        current_action = self._goal_manager.get_easiest_actionable()

        if current_action is None:
            # No actionable items - reduced urgency
            return urgency * 0.5, top_goal

        # Adjust based on difficulty (easier = slightly higher urgency to complete)
        difficulty_factor = 1.0 + (10 - current_action.difficulty_estimate) * 0.05
        urgency *= difficulty_factor

        # Add staleness bonus (more urgent if haven't made progress)
        state = self._economy_manager.get_state()
        if state.last_action_at:
            hours_since_action = (datetime.now() - state.last_action_at).total_seconds() / 3600
            staleness_bonus = min(hours_since_action * config.GOAL_URGENCY_STALE_BONUS, 100)
            urgency += staleness_bonus

        return urgency, current_action

    def _make_tempo_decision(
        self,
        available_points: float,
        goal_urgency: float,
        current_goal: Goal
    ) -> Optional[TempoDecision]:
        """
        Decide which tempo option to purchase.

        The AI considers:
        - Available points
        - Goal urgency (higher = shorter interval)
        - Current goal state

        Returns:
            TempoDecision if a purchase was made, None otherwise
        """
        options = self._economy_manager.get_tempo_options(available_points)

        if not options:
            return None

        # Decision logic:
        # - High urgency (>150) and can afford → focus_5min
        # - Medium urgency (100-150) and can afford → focus_10min or focus_15min
        # - Low urgency or low points → standard

        selected_name = "standard"

        if goal_urgency > 150 and available_points >= 150:
            # Very high urgency - shortest affordable interval
            for opt in reversed(options):  # Options are sorted longest to shortest
                if opt.name.startswith("focus_5min"):
                    selected_name = opt.name
                    break
                elif opt.name.startswith("focus_10min"):
                    selected_name = opt.name
                    break

        elif goal_urgency > 100 and available_points >= 100:
            # Medium urgency
            for opt in options:
                if opt.name.startswith("focus_15min") or opt.name.startswith("focus_10min"):
                    selected_name = opt.name
                    break

        elif goal_urgency > 50 and available_points >= 50:
            # Lower urgency - modest investment
            for opt in options:
                if opt.name.startswith("focus_30min"):
                    selected_name = opt.name
                    break

        # Purchase the selected option
        return self._economy_manager.purchase_tempo(selected_name)

    def _log_decision_summary(self, decision: AgencyDecision) -> None:
        """Log a summary of the agency decision."""
        if decision.ai_is_acting:
            tempo_info = ""
            if decision.tempo_decision:
                tempo_info = f", next wakeup in {decision.tempo_decision.selected_option.wakeup_minutes:.0f}m"

            log_info(
                f"AI acting on: {decision.current_goal_description[:40]}... "
                f"({decision.points_remaining:.0f} pts remaining{tempo_info})",
                prefix="▶️"
            )
        else:
            log_info(
                f"User controls topic ({decision.points_remaining:.0f} pts saved)",
                prefix="👤"
            )

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def should_bootstrap(self) -> bool:
        """Check if the bootstrap goal should be created."""
        if not config.BOOTSTRAP_GOAL_ENABLED:
            return False

        return self._goal_manager.get_active_top_goal() is None

    def run_bootstrap(self) -> Optional[int]:
        """Run bootstrap if needed, creating the first goal."""
        if self.should_bootstrap():
            return self._goal_manager.initialize_bootstrap_goal()
        return None

    def get_current_focus(self) -> Optional[str]:
        """Get description of current goal focus (for prompts)."""
        action = self._goal_manager.get_easiest_actionable()
        if action:
            return action.description

        top_goal = self._goal_manager.get_active_top_goal()
        if top_goal:
            return top_goal.description

        return None

    def get_status_summary(self) -> str:
        """Get a brief status summary for display."""
        state = self._economy_manager.get_state()
        stats = self._goal_manager.get_stats()

        parts = [
            f"Points: {state.agency_points:.0f}",
            f"Goals: {stats['active']} active, {stats['completed']} done",
        ]

        if state.next_scheduled_wakeup:
            remaining = (state.next_scheduled_wakeup - datetime.now()).total_seconds()
            if remaining > 0:
                parts.append(f"Next: {remaining / 60:.0f}m")

        return " | ".join(parts)


# Global engine instance
_engine: Optional[AgencyEconomyEngine] = None


def get_agency_engine() -> AgencyEconomyEngine:
    """Get the global agency engine instance."""
    global _engine
    if _engine is None:
        _engine = AgencyEconomyEngine()
    return _engine


def init_agency_engine() -> AgencyEconomyEngine:
    """Initialize the global agency engine."""
    global _engine
    _engine = AgencyEconomyEngine()
    return _engine
