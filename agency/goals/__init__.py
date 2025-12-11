"""
Pattern Project - Goal System
Hierarchical goal tree for AI objective management
"""

from agency.goals.models import (
    Goal,
    GoalTree,
    GoalPath,
    GoalLevel,
    GoalStatus
)

from agency.goals.manager import (
    GoalManager,
    get_goal_manager,
    init_goal_manager
)

__all__ = [
    # Models
    "Goal",
    "GoalTree",
    "GoalPath",
    "GoalLevel",
    "GoalStatus",
    # Manager
    "GoalManager",
    "get_goal_manager",
    "init_goal_manager",
]
