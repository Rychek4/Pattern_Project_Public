"""
Pattern Project - Goal Tree Context Source
Injects the AI's hierarchical goal tree into prompts
"""

from typing import Optional, Dict, Any

import config
from prompt_builder.sources.base import ContextSource, ContextBlock
from core.logger import log_info


# Priority for goal tree: after core memory (10), before active thoughts (18)
# Goals are foundational to the AI's motivated behavior
GOAL_TREE_PRIORITY = 15


class GoalTreeSource(ContextSource):
    """
    Provides the AI's goal tree - its hierarchical objectives.

    The goal tree has three levels:
    - top_goal: The highest-level objective (only one active)
    - sub_goal: Decomposed objectives serving the top goal
    - action: Concrete tasks to accomplish

    The AI controls this via commands:
    - [[SET_GOAL: parent_id | description | difficulty]]
    - [[COMPLETE_GOAL: goal_id | reflection]]
    - [[SELECT_TOP_GOAL: description]] (only after first goal complete)
    """

    @property
    def source_name(self) -> str:
        return "goal_tree"

    @property
    def priority(self) -> int:
        return GOAL_TREE_PRIORITY

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """Get goal tree context for prompt injection."""
        if not config.AGENCY_ECONOMY_ENABLED:
            return None

        from agency.goals import get_goal_manager

        try:
            manager = get_goal_manager()
            tree = manager.get_tree()

            if tree.root is None:
                content = self._build_empty_context()
                can_select = manager.can_select_new_top_goal()
            else:
                content = self._build_tree_context(tree, manager)
                can_select = manager.can_select_new_top_goal()

            # Store in session context for other sources
            session_context["has_active_goal"] = tree.has_active_goal
            session_context["goal_count"] = tree.total_count
            session_context["can_select_top_goal"] = can_select

            return ContextBlock(
                source_name=self.source_name,
                content=content,
                priority=self.priority,
                include_always=True,
                metadata={
                    "has_active_goal": tree.has_active_goal,
                    "total_goals": tree.total_count,
                    "completed_goals": tree.completed_count,
                    "can_select_top_goal": can_select
                }
            )

        except Exception as e:
            log_info(f"GoalTreeSource error: {e}")
            return None

    def _build_empty_context(self) -> str:
        """Build context when there are no goals."""
        return """<goal_tree>
Your goal tree is empty.

This system gives you hierarchical objectives to work toward:
- top_goal: Your highest-level aspiration (one at a time)
- sub_goal: Decomposed objectives serving the top goal
- action: Concrete tasks you can complete

The bootstrap goal will be created automatically. Once you complete it,
you gain the ability to select your own top goals.

Commands:
  [[SET_GOAL: parent_id | description | difficulty]]
  [[COMPLETE_GOAL: goal_id | reflection]]
  [[ACTIVATE_GOAL: goal_id]]
</goal_tree>"""

    def _build_tree_context(self, tree, manager) -> str:
        """Build context with the goal tree."""
        lines = ["<goal_tree>"]

        # Show top goal
        root = tree.root
        status_emoji = self._get_status_emoji(root.status)
        lines.append(f"Top Goal: {root.description}")
        lines.append(f"Status: {status_emoji} {root.status.title()}")

        # Show progress
        if tree.total_count > 1:
            lines.append(f"Progress: {tree.completed_count}/{tree.total_count - 1} sub-items complete")

        lines.append("")

        # Show current focus path
        if tree.active_path and len(tree.active_path) > 1:
            lines.append("Current Focus:")
            self._render_active_path(tree.active_path, lines)
            lines.append("")

        # Show next actionable item
        easiest = manager.get_easiest_actionable()
        if easiest:
            lines.append(f"Next Action (easiest): [{easiest.id}] {easiest.description}")
            lines.append(f"  Difficulty: {easiest.difficulty_estimate}/10")
            lines.append("")

        # Show command reference
        lines.append("Commands:")
        lines.append("  [[SET_GOAL: parent_id | description | difficulty]]")
        lines.append("  [[COMPLETE_GOAL: goal_id | reflection]]")
        lines.append("  [[ACTIVATE_GOAL: goal_id]]")

        # Show SELECT_TOP_GOAL only if allowed
        if manager.can_select_new_top_goal():
            lines.append("  [[SELECT_TOP_GOAL: description]] - You've earned this!")
        elif root.is_completed:
            lines.append("  (SELECT_TOP_GOAL available - no active top goal)")

        lines.append("</goal_tree>")

        return "\n".join(lines)

    def _render_active_path(self, path, lines, indent=2) -> None:
        """Render the active path as an indented tree."""
        for i, goal in enumerate(path):
            prefix = " " * indent
            connector = "└─" if i == len(path) - 1 else "├─"
            status = self._get_status_emoji(goal.status)

            if goal.level == "action":
                lines.append(f"{prefix}{connector} Action [{goal.id}]: {goal.description[:50]}")
            elif goal.level == "sub_goal":
                lines.append(f"{prefix}{connector} Sub-goal [{goal.id}]: {goal.description[:50]}")
            else:
                continue  # Skip top goal in path (already shown above)

            indent += 3

    def _get_status_emoji(self, status: str) -> str:
        """Get emoji for goal status."""
        return {
            "pending": "⏸️",
            "active": "▶️",
            "completed": "✅",
            "abandoned": "❌"
        }.get(status, "❓")


# Global instance
_goal_tree_source: Optional[GoalTreeSource] = None


def get_goal_tree_source() -> GoalTreeSource:
    """Get the global GoalTreeSource instance."""
    global _goal_tree_source
    if _goal_tree_source is None:
        _goal_tree_source = GoalTreeSource()
    return _goal_tree_source
