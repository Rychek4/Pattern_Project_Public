"""
Pattern Project - Goal Models
Data structures for the hierarchical goal tree
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
from enum import Enum


class GoalLevel(Enum):
    """Classification of goal in the hierarchy."""
    TOP_GOAL = "top_goal"
    SUB_GOAL = "sub_goal"
    ACTION = "action"


class GoalStatus(Enum):
    """Lifecycle states for goals."""
    PENDING = "pending"      # Created but not yet started
    ACTIVE = "active"        # Currently being worked on
    COMPLETED = "completed"  # Successfully finished (with reflection)
    ABANDONED = "abandoned"  # Cancelled without completion


@dataclass
class Goal:
    """
    A single goal in the AI's goal tree.

    Goals form a strict hierarchy:
    - top_goal: The highest-level objective (only one active at a time)
    - sub_goal: Decomposed objectives that serve the top goal
    - action: Concrete tasks that accomplish sub-goals

    Attributes:
        id: Database primary key
        parent_id: ID of parent goal (None for top goals)
        level: Position in hierarchy (top_goal, sub_goal, action)
        description: What this goal aims to achieve
        status: Current lifecycle state
        completion_reflection: AI's self-assessment when completed
        difficulty_estimate: 1-10 scale for "easiest next" selection
        created_at: When the goal was created
        activated_at: When work began on this goal
        completed_at: When the goal was finished
        sibling_order: Order among siblings for display
        children: Child goals (populated when building tree views)
    """
    id: int
    parent_id: Optional[int]
    level: str
    description: str
    status: str
    completion_reflection: Optional[str]
    difficulty_estimate: int
    created_at: datetime
    activated_at: Optional[datetime]
    completed_at: Optional[datetime]
    sibling_order: int = 0
    children: List['Goal'] = field(default_factory=list)

    @property
    def is_top_goal(self) -> bool:
        """Check if this is a top-level goal."""
        return self.level == GoalLevel.TOP_GOAL.value

    @property
    def is_action(self) -> bool:
        """Check if this is an actionable leaf node."""
        return self.level == GoalLevel.ACTION.value

    @property
    def is_active(self) -> bool:
        """Check if this goal is currently active."""
        return self.status == GoalStatus.ACTIVE.value

    @property
    def is_completed(self) -> bool:
        """Check if this goal is completed."""
        return self.status == GoalStatus.COMPLETED.value

    @property
    def is_pending(self) -> bool:
        """Check if this goal is pending."""
        return self.status == GoalStatus.PENDING.value

    def get_level_enum(self) -> GoalLevel:
        """Get the level as an enum."""
        return GoalLevel(self.level)

    def get_status_enum(self) -> GoalStatus:
        """Get the status as an enum."""
        return GoalStatus(self.status)


@dataclass
class GoalTree:
    """
    Complete view of the goal tree from a root.

    Attributes:
        root: The root goal (usually the active top_goal)
        all_goals: Flat list of all goals in the tree
        active_path: Path from root to current active action
        current_action: The currently active action (if any)
        total_count: Total number of goals in tree
        completed_count: Number of completed goals
        pending_count: Number of pending goals
    """
    root: Optional[Goal]
    all_goals: List[Goal] = field(default_factory=list)
    active_path: List[Goal] = field(default_factory=list)
    current_action: Optional[Goal] = None
    total_count: int = 0
    completed_count: int = 0
    pending_count: int = 0

    @property
    def has_active_goal(self) -> bool:
        """Check if there's any active goal."""
        return self.root is not None and self.root.is_active

    @property
    def progress_ratio(self) -> float:
        """Get completion ratio (0.0 to 1.0)."""
        if self.total_count == 0:
            return 0.0
        return self.completed_count / self.total_count


@dataclass
class GoalPath:
    """
    Path through the goal tree from top to current action.

    Used for displaying the current focus and ancestry.
    """
    top_goal: Goal
    sub_goals: List[Goal] = field(default_factory=list)
    current_action: Optional[Goal] = None

    def to_string(self, separator: str = " → ") -> str:
        """Format path as string."""
        parts = [self.top_goal.description[:50]]
        for sub in self.sub_goals:
            parts.append(sub.description[:40])
        if self.current_action:
            parts.append(f"[{self.current_action.description[:30]}]")
        return separator.join(parts)
