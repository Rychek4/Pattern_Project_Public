"""
Pattern Project - Agency Economy Models
Data structures for the economic system that governs AI agency
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List
from enum import Enum


class AuctionWinner(Enum):
    """Who won the context auction."""
    AI = "ai"
    USER = "user"


class TempoType(Enum):
    """Types of tempo (wake-up schedule) options."""
    STANDARD = "standard"    # Default interval (free)
    FOCUS = "focus"          # Shortened interval (costs points)
    APPOINTMENT = "appointment"  # Specific timestamp (costs points)


@dataclass
class EconomyState:
    """
    Current state of the agency economy.

    The economy tracks:
    - Points balance (earned over time, spent on actions)
    - Next scheduled wake-up (from Tempo Market)
    - Statistics on earnings and spending
    """
    agency_points: float
    last_income_at: datetime
    next_scheduled_wakeup: Optional[datetime]
    scheduled_wakeup_type: Optional[str]
    total_points_earned: float
    total_points_spent: float
    total_topic_hijacks: int
    total_tempo_purchases: int
    last_action_at: Optional[datetime]
    last_auction_winner: Optional[str]
    updated_at: datetime

    @property
    def can_hijack_topic(self) -> bool:
        """Check if AI has enough points to hijack topic."""
        import config
        return self.agency_points >= config.AUCTION_HIJACK_COST

    @property
    def time_since_last_action(self) -> Optional[timedelta]:
        """Get time since last action."""
        if self.last_action_at is None:
            return None
        return datetime.now() - self.last_action_at


@dataclass
class AuctionResult:
    """
    Result of a context auction.

    The auction determines whether the AI or user "wins" the
    conversation topic. The AI must spend points to override.
    """
    winner: str  # 'ai' or 'user'
    ai_bid: float  # How much the AI was willing to bid
    user_bid: float  # The user's bid (typically fixed low value)
    cost_to_ai: float  # Points actually spent (0 if user won)
    ai_can_afford: bool  # Whether AI had enough points
    reason: str  # Human-readable explanation

    @property
    def ai_won(self) -> bool:
        """Check if AI won the auction."""
        return self.winner == AuctionWinner.AI.value

    @property
    def user_won(self) -> bool:
        """Check if user won the auction."""
        return self.winner == AuctionWinner.USER.value


@dataclass
class TempoOption:
    """
    A purchasable option from the Tempo Market.

    The Tempo Market allows the AI to spend points to
    control when it next wakes up.
    """
    name: str  # Identifier (e.g., 'focus_5min')
    display_name: str  # Human-readable name
    description: str  # What this option does
    cost: float  # Points required
    wakeup_seconds: int  # Seconds until next wakeup
    tempo_type: str  # 'standard', 'focus', or 'appointment'

    @property
    def is_free(self) -> bool:
        """Check if this option is free."""
        return self.cost == 0

    @property
    def wakeup_minutes(self) -> float:
        """Get wakeup time in minutes."""
        return self.wakeup_seconds / 60


@dataclass
class TempoDecision:
    """
    The AI's decision from the Tempo Market.

    After the auction and response, the AI decides how
    quickly to wake up next.
    """
    selected_option: TempoOption
    points_spent: float
    next_wakeup: datetime
    reason: str  # Why this option was selected


@dataclass
class AgencyDecision:
    """
    Complete decision from one agency cycle.

    This encapsulates everything that happens when the system
    wakes up: income, auction, and tempo selection.
    """
    # Income phase
    time_delta_seconds: float
    points_earned: float
    points_before: float
    points_after_income: float

    # Auction phase
    auction_result: AuctionResult
    points_after_auction: float

    # Goal context (if AI won auction)
    current_goal_description: Optional[str] = None
    goal_urgency: float = 0.0

    # Tempo phase
    tempo_decision: Optional[TempoDecision] = None
    points_remaining: float = 0.0

    @property
    def ai_is_acting(self) -> bool:
        """Check if AI won the auction and is acting on goals."""
        return self.auction_result.ai_won

    @property
    def total_points_spent(self) -> float:
        """Get total points spent this cycle."""
        auction_cost = self.auction_result.cost_to_ai
        tempo_cost = self.tempo_decision.points_spent if self.tempo_decision else 0
        return auction_cost + tempo_cost


@dataclass
class EconomyStats:
    """
    Statistics about the agency economy.

    Used for monitoring and debugging the economic system.
    """
    current_points: float
    total_earned: float
    total_spent: float
    total_hijacks: int
    total_tempo_purchases: int
    average_points_per_cycle: float = 0.0
    hijack_success_rate: float = 0.0
    last_action_ago: Optional[timedelta] = None
