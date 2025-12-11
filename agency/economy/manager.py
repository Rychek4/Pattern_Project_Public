"""
Pattern Project - Agency Economy Manager
Manages points, auctions, and tempo market for AI agency
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import config
from core.database import get_database
from core.logger import log_info, log_error, log_warning
from concurrency.locks import get_lock_manager
from concurrency.db_retry import db_retry

from agency.economy.models import (
    EconomyState,
    AuctionResult,
    TempoOption,
    TempoDecision,
    EconomyStats,
    AuctionWinner,
    TempoType
)


class AgencyEconomyManager:
    """
    Manages the agency economy: points, auctions, and tempo market.

    The economy has three main functions:
    1. Income: Points accumulate over time (patience → agency)
    2. Context Auction: AI bids to override user topic
    3. Tempo Market: AI purchases shorter wake-up intervals

    This creates emergent behavior:
    - Waiting earns agency points
    - High engagement → spend on short pulses → burst of activity
    - Goal complete → save points → long rest → accumulate
    """

    def __init__(self):
        self._lock_manager = get_lock_manager()

    # =========================================================================
    # STATE MANAGEMENT
    # =========================================================================

    @db_retry()
    def get_state(self) -> EconomyState:
        """Get the current economy state."""
        with self._lock_manager.acquire("database"):
            db = get_database()
            result = db.execute(
                "SELECT * FROM agency_economy WHERE id = 1",
                fetch=True
            )

            if not result:
                # Initialize if not exists
                self._initialize_economy()
                result = db.execute(
                    "SELECT * FROM agency_economy WHERE id = 1",
                    fetch=True
                )

            row = result[0]
            return self._row_to_state(row)

    @db_retry()
    def _initialize_economy(self) -> None:
        """Initialize the economy table if empty."""
        db = get_database()
        now = datetime.now()

        db.execute(
            """
            INSERT OR IGNORE INTO agency_economy
            (id, agency_points, last_income_at, updated_at)
            VALUES (1, 0.0, ?, ?)
            """,
            (now.isoformat(), now.isoformat())
        )
        log_info("Agency economy initialized", prefix="💰")

    @db_retry()
    def _update_state(self, **kwargs) -> None:
        """Update economy state fields."""
        with self._lock_manager.acquire("database"):
            db = get_database()
            now = datetime.now()

            # Build SET clause dynamically
            set_parts = ["updated_at = ?"]
            values = [now.isoformat()]

            for key, value in kwargs.items():
                if value is not None:
                    if isinstance(value, datetime):
                        value = value.isoformat()
                    set_parts.append(f"{key} = ?")
                    values.append(value)

            values.append(1)  # WHERE id = 1

            sql = f"UPDATE agency_economy SET {', '.join(set_parts)} WHERE id = ?"
            db.execute(sql, tuple(values))

    # =========================================================================
    # POINT MANAGEMENT
    # =========================================================================

    def calculate_income(self, time_delta_seconds: float) -> float:
        """
        Calculate points earned over a time period.

        Args:
            time_delta_seconds: Seconds since last income calculation

        Returns:
            Points earned (before cap application)
        """
        return time_delta_seconds * config.AGENCY_POINT_RATE

    @db_retry()
    def add_income(self, time_delta_seconds: Optional[float] = None) -> float:
        """
        Add income based on time elapsed since last income.

        Args:
            time_delta_seconds: Override time delta (uses actual elapsed if None)

        Returns:
            Points actually added (after cap)
        """
        state = self.get_state()

        # Calculate time delta if not provided
        if time_delta_seconds is None:
            if state.last_income_at:
                time_delta_seconds = (datetime.now() - state.last_income_at).total_seconds()
            else:
                time_delta_seconds = 0

        # Calculate earned points
        earned = self.calculate_income(time_delta_seconds)

        # Apply cap
        new_balance = min(
            state.agency_points + earned,
            config.AGENCY_POINT_CAP
        )
        actual_added = new_balance - state.agency_points

        # Update state
        now = datetime.now()
        self._update_state(
            agency_points=new_balance,
            last_income_at=now,
            total_points_earned=state.total_points_earned + actual_added
        )

        if actual_added > 0:
            log_info(
                f"Income: +{actual_added:.1f} pts ({time_delta_seconds:.0f}s × {config.AGENCY_POINT_RATE}/s)",
                prefix="💰"
            )

        return actual_added

    @db_retry()
    def spend_points(self, amount: float, reason: str) -> bool:
        """
        Spend points from the balance.

        Args:
            amount: Points to spend
            reason: Why points are being spent

        Returns:
            True if successful (had enough points)
        """
        state = self.get_state()

        if state.agency_points < amount:
            log_warning(f"Cannot spend {amount:.1f} pts - only have {state.agency_points:.1f}")
            return False

        new_balance = state.agency_points - amount

        self._update_state(
            agency_points=new_balance,
            total_points_spent=state.total_points_spent + amount
        )

        log_info(f"Spent: -{amount:.1f} pts ({reason})", prefix="💸")
        return True

    def get_balance(self) -> float:
        """Get current points balance."""
        return self.get_state().agency_points

    # =========================================================================
    # CONTEXT AUCTION
    # =========================================================================

    def run_auction(
        self,
        goal_urgency: float,
        user_input_value: Optional[float] = None
    ) -> AuctionResult:
        """
        Run the context auction to determine who controls the topic.

        The AI bids based on goal urgency. The user has a fixed bid.
        If the AI wins and can afford to pay, it hijacks the topic.

        Args:
            goal_urgency: AI's urgency score (higher = more willing to spend)
            user_input_value: User's bid (defaults to config value)

        Returns:
            AuctionResult with winner and costs
        """
        state = self.get_state()
        user_bid = user_input_value or config.AUCTION_USER_BID_DEFAULT
        hijack_cost = config.AUCTION_HIJACK_COST

        # AI bid is based on goal urgency
        ai_bid = goal_urgency

        # Determine winner
        ai_can_afford = state.agency_points >= hijack_cost

        if ai_bid > user_bid and ai_can_afford:
            # AI wins and pays
            self.spend_points(hijack_cost, "topic hijack")
            self._update_state(
                total_topic_hijacks=state.total_topic_hijacks + 1,
                last_auction_winner=AuctionWinner.AI.value,
                last_action_at=datetime.now()
            )

            return AuctionResult(
                winner=AuctionWinner.AI.value,
                ai_bid=ai_bid,
                user_bid=user_bid,
                cost_to_ai=hijack_cost,
                ai_can_afford=True,
                reason=f"AI won auction (urgency {ai_bid:.0f} > user {user_bid:.0f}, paid {hijack_cost:.0f})"
            )

        elif ai_bid > user_bid and not ai_can_afford:
            # AI wanted to win but couldn't afford it
            self._update_state(last_auction_winner=AuctionWinner.USER.value)

            return AuctionResult(
                winner=AuctionWinner.USER.value,
                ai_bid=ai_bid,
                user_bid=user_bid,
                cost_to_ai=0,
                ai_can_afford=False,
                reason=f"AI outbid user but couldn't afford ({state.agency_points:.0f} < {hijack_cost:.0f})"
            )

        else:
            # User wins (AI didn't outbid)
            self._update_state(last_auction_winner=AuctionWinner.USER.value)

            return AuctionResult(
                winner=AuctionWinner.USER.value,
                ai_bid=ai_bid,
                user_bid=user_bid,
                cost_to_ai=0,
                ai_can_afford=ai_can_afford,
                reason=f"User won auction (AI urgency {ai_bid:.0f} <= user {user_bid:.0f})"
            )

    # =========================================================================
    # TEMPO MARKET
    # =========================================================================

    def get_tempo_options(self, current_points: Optional[float] = None) -> List[TempoOption]:
        """
        Get available tempo options based on current points.

        Args:
            current_points: Points available (uses current balance if None)

        Returns:
            List of affordable TempoOptions
        """
        if current_points is None:
            current_points = self.get_balance()

        options = []

        # Standard (free)
        options.append(TempoOption(
            name="standard",
            display_name="Standard",
            description=f"Wake up in {config.TEMPO_STANDARD_INTERVAL // 60} minutes",
            cost=0,
            wakeup_seconds=config.TEMPO_STANDARD_INTERVAL,
            tempo_type=TempoType.STANDARD.value
        ))

        # Focus options (progressively shorter intervals)
        focus_intervals = [
            (30 * 60, "30min"),   # 30 minutes
            (15 * 60, "15min"),   # 15 minutes
            (10 * 60, "10min"),   # 10 minutes
            (5 * 60, "5min"),     # 5 minutes
        ]

        for seconds, label in focus_intervals:
            if seconds >= config.TEMPO_MIN_INTERVAL:
                # Cost increases as interval decreases
                reduction_from_standard = config.TEMPO_STANDARD_INTERVAL - seconds
                reduction_units = reduction_from_standard / 600  # Per 10-minute reduction
                cost = reduction_units * config.TEMPO_FOCUS_COST_PER_10MIN

                if current_points >= cost:
                    options.append(TempoOption(
                        name=f"focus_{label}",
                        display_name=f"Focus ({label})",
                        description=f"Wake up in {seconds // 60} minutes",
                        cost=cost,
                        wakeup_seconds=seconds,
                        tempo_type=TempoType.FOCUS.value
                    ))

        return options

    def purchase_tempo(self, option_name: str) -> Optional[TempoDecision]:
        """
        Purchase a tempo option and set the next wakeup.

        Args:
            option_name: Name of the option to purchase

        Returns:
            TempoDecision if successful, None if failed
        """
        state = self.get_state()
        options = self.get_tempo_options(state.agency_points)

        # Find the requested option
        selected = None
        for opt in options:
            if opt.name == option_name:
                selected = opt
                break

        if selected is None:
            log_warning(f"Tempo option '{option_name}' not available or not affordable")
            return None

        # Spend points if not free
        if selected.cost > 0:
            if not self.spend_points(selected.cost, f"tempo: {selected.display_name}"):
                return None

            self._update_state(
                total_tempo_purchases=state.total_tempo_purchases + 1
            )

        # Calculate next wakeup
        next_wakeup = datetime.now() + timedelta(seconds=selected.wakeup_seconds)

        # Update state with scheduled wakeup
        self._update_state(
            next_scheduled_wakeup=next_wakeup,
            scheduled_wakeup_type=selected.tempo_type
        )

        log_info(
            f"Tempo purchased: {selected.display_name} "
            f"(next wakeup in {selected.wakeup_seconds // 60}m)",
            prefix="⏰"
        )

        return TempoDecision(
            selected_option=selected,
            points_spent=selected.cost,
            next_wakeup=next_wakeup,
            reason=f"Selected {selected.display_name} for {selected.cost:.0f} pts"
        )

    def get_next_wakeup(self) -> Optional[datetime]:
        """Get the next scheduled wakeup time."""
        state = self.get_state()
        return state.next_scheduled_wakeup

    def clear_scheduled_wakeup(self) -> None:
        """Clear any scheduled wakeup (revert to standard pulse)."""
        self._update_state(
            next_scheduled_wakeup=None,
            scheduled_wakeup_type=None
        )

    # =========================================================================
    # STATISTICS
    # =========================================================================

    def get_stats(self) -> EconomyStats:
        """Get economy statistics."""
        state = self.get_state()

        last_action_ago = None
        if state.last_action_at:
            last_action_ago = datetime.now() - state.last_action_at

        return EconomyStats(
            current_points=state.agency_points,
            total_earned=state.total_points_earned,
            total_spent=state.total_points_spent,
            total_hijacks=state.total_topic_hijacks,
            total_tempo_purchases=state.total_tempo_purchases,
            last_action_ago=last_action_ago
        )

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _row_to_state(self, row) -> EconomyState:
        """Convert a database row to EconomyState."""
        def parse_datetime(value):
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(value)

        return EconomyState(
            agency_points=row["agency_points"] or 0.0,
            last_income_at=parse_datetime(row["last_income_at"]),
            next_scheduled_wakeup=parse_datetime(row["next_scheduled_wakeup"]),
            scheduled_wakeup_type=row["scheduled_wakeup_type"],
            total_points_earned=row["total_points_earned"] or 0.0,
            total_points_spent=row["total_points_spent"] or 0.0,
            total_topic_hijacks=row["total_topic_hijacks"] or 0,
            total_tempo_purchases=row["total_tempo_purchases"] or 0,
            last_action_at=parse_datetime(row["last_action_at"]),
            last_auction_winner=row["last_auction_winner"],
            updated_at=parse_datetime(row["updated_at"]) or datetime.now()
        )


# Global manager instance
_economy_manager: Optional[AgencyEconomyManager] = None


def get_economy_manager() -> AgencyEconomyManager:
    """Get the global economy manager instance."""
    global _economy_manager
    if _economy_manager is None:
        _economy_manager = AgencyEconomyManager()
    return _economy_manager


def init_economy_manager() -> AgencyEconomyManager:
    """Initialize the global economy manager."""
    global _economy_manager
    _economy_manager = AgencyEconomyManager()
    return _economy_manager
