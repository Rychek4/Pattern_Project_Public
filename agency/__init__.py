"""
Pattern Project - Agency System
Proactive AI behaviors including goals, economy, thoughts, and intentions
"""

# Re-export key classes for convenience
from agency.goals import (
    Goal,
    GoalTree,
    GoalPath,
    GoalLevel,
    GoalStatus,
    GoalManager,
    get_goal_manager,
    init_goal_manager,
)

from agency.economy import (
    EconomyState,
    AuctionResult,
    TempoOption,
    TempoDecision,
    AgencyDecision,
    AgencyEconomyManager,
    AgencyEconomyEngine,
    get_economy_manager,
    get_agency_engine,
    init_economy_manager,
    init_agency_engine,
)

__all__ = [
    # Goals
    "Goal",
    "GoalTree",
    "GoalPath",
    "GoalLevel",
    "GoalStatus",
    "GoalManager",
    "get_goal_manager",
    "init_goal_manager",
    # Economy
    "EconomyState",
    "AuctionResult",
    "TempoOption",
    "TempoDecision",
    "AgencyDecision",
    "AgencyEconomyManager",
    "AgencyEconomyEngine",
    "get_economy_manager",
    "get_agency_engine",
    "init_economy_manager",
    "init_agency_engine",
]
