"""
Pattern Project - Goal Command Handlers
Commands for AI to manage its hierarchical goal tree
"""

from typing import Optional

from agency.commands.handlers.base import CommandHandler, CommandResult
from agency.commands.errors import ToolError
from core.logger import log_info, log_error


class SetGoalHandler(CommandHandler):
    """
    Handler for [[SET_GOAL: parent_id | description | difficulty]].

    Creates a new goal as a child of the specified parent.
    - parent_id: ID of the parent goal (or "root" for top-level goals - only if allowed)
    - description: What this goal aims to achieve
    - difficulty: 1-10 estimate (lower = easier)
    """

    @property
    def command_name(self) -> str:
        return "SET_GOAL"

    @property
    def pattern(self) -> str:
        return r'\[\[SET_GOAL:\s*(.+?)\]\]'

    @property
    def needs_continuation(self) -> bool:
        return True  # AI should see confirmation

    def execute(self, query: str, context: dict) -> CommandResult:
        """Create a new goal."""
        from agency.goals import get_goal_manager, GoalLevel

        try:
            # Parse: parent_id | description | difficulty
            parts = [p.strip() for p in query.split('|')]

            if len(parts) < 2:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    error=ToolError(
                        error_type="invalid_format",
                        message="Format: parent_id | description | difficulty (optional)",
                        suggestion="Use: [[SET_GOAL: 1 | My sub-goal | 5]]"
                    )
                )

            parent_id_str = parts[0]
            description = parts[1]
            difficulty = int(parts[2]) if len(parts) > 2 else 5

            # Validate difficulty
            difficulty = max(1, min(10, difficulty))

            manager = get_goal_manager()

            # Parse parent_id
            if parent_id_str.lower() == "root" or parent_id_str == "":
                # Top-level goal - check if allowed
                if not manager.can_select_new_top_goal():
                    return CommandResult(
                        command_name=self.command_name,
                        query=query,
                        data=None,
                        needs_continuation=True,
                        error=ToolError(
                            error_type="not_allowed",
                            message="Cannot create top-level goals yet",
                            suggestion="Complete your first goal to unlock this ability"
                        )
                    )
                parent_id = None
                level = GoalLevel.TOP_GOAL.value
            else:
                parent_id = int(parent_id_str)

                # Get parent to determine child level
                parent = manager.get_goal(parent_id)
                if parent is None:
                    return CommandResult(
                        command_name=self.command_name,
                        query=query,
                        data=None,
                        needs_continuation=True,
                        error=ToolError(
                            error_type="not_found",
                            message=f"Parent goal [{parent_id}] not found"
                        )
                    )

                # Determine level based on parent
                if parent.level == GoalLevel.TOP_GOAL.value:
                    level = GoalLevel.SUB_GOAL.value
                elif parent.level == GoalLevel.SUB_GOAL.value:
                    level = GoalLevel.ACTION.value
                else:
                    # Actions can't have children
                    return CommandResult(
                        command_name=self.command_name,
                        query=query,
                        data=None,
                        needs_continuation=True,
                        error=ToolError(
                            error_type="invalid_parent",
                            message="Actions cannot have children",
                            suggestion="Create under a sub_goal instead"
                        )
                    )

            # Create the goal
            goal_id = manager.create_goal(
                level=level,
                description=description,
                parent_id=parent_id,
                difficulty_estimate=difficulty,
                status="pending"
            )

            if goal_id:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data={"goal_id": goal_id, "level": level, "description": description},
                    needs_continuation=True,
                    display_text=f"Created {level} [{goal_id}]"
                )
            else:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    error="Failed to create goal"
                )

        except ValueError as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                error=ToolError(
                    error_type="invalid_format",
                    message=str(e),
                    suggestion="Check parent_id is a number and difficulty is 1-10"
                )
            )
        except Exception as e:
            log_error(f"SET_GOAL error: {e}")
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                error=str(e)
            )

    def get_instructions(self) -> str:
        return ""  # Instructions provided by GoalTreeSource

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  Error: {result.get_error_message()}"
        data = result.data
        return f"  Created {data['level']} [{data['goal_id']}]: {data['description'][:50]}"


class CompleteGoalHandler(CommandHandler):
    """
    Handler for [[COMPLETE_GOAL: goal_id | reflection]].

    Marks a goal as completed with self-assessment.
    - goal_id: ID of the goal to complete
    - reflection: Your assessment of why this goal is complete
    """

    @property
    def command_name(self) -> str:
        return "COMPLETE_GOAL"

    @property
    def pattern(self) -> str:
        return r'\[\[COMPLETE_GOAL:\s*(.+?)\]\]'

    @property
    def needs_continuation(self) -> bool:
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        """Complete a goal with reflection."""
        from agency.goals import get_goal_manager

        try:
            # Parse: goal_id | reflection
            parts = [p.strip() for p in query.split('|', 1)]

            if len(parts) < 2:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    error=ToolError(
                        error_type="invalid_format",
                        message="Reflection required",
                        suggestion="Use: [[COMPLETE_GOAL: 1 | I completed this because...]]"
                    )
                )

            goal_id = int(parts[0])
            reflection = parts[1]

            if len(reflection) < 10:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    error=ToolError(
                        error_type="invalid_format",
                        message="Reflection too short",
                        suggestion="Provide meaningful self-assessment of completion"
                    )
                )

            manager = get_goal_manager()

            # Get the goal
            goal = manager.get_goal(goal_id)
            if goal is None:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    error=ToolError(
                        error_type="not_found",
                        message=f"Goal [{goal_id}] not found"
                    )
                )

            # Complete it
            success = manager.complete_goal(goal_id, reflection)

            if success:
                # Check if this enables selecting new top goal
                can_select = manager.can_select_new_top_goal()

                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data={
                        "goal_id": goal_id,
                        "description": goal.description,
                        "can_select_top_goal": can_select
                    },
                    needs_continuation=True,
                    display_text=f"Completed goal [{goal_id}]"
                )
            else:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    error="Failed to complete goal"
                )

        except ValueError as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                error=ToolError(
                    error_type="invalid_format",
                    message="goal_id must be a number"
                )
            )
        except Exception as e:
            log_error(f"COMPLETE_GOAL error: {e}")
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                error=str(e)
            )

    def get_instructions(self) -> str:
        return ""

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  Error: {result.get_error_message()}"
        data = result.data
        msg = f"  Completed: {data['description'][:50]}"
        if data.get('can_select_top_goal'):
            msg += "\n  You can now select your own top goals with [[SELECT_TOP_GOAL:]]!"
        return msg


class ActivateGoalHandler(CommandHandler):
    """
    Handler for [[ACTIVATE_GOAL: goal_id]].

    Marks a pending goal as active.
    """

    @property
    def command_name(self) -> str:
        return "ACTIVATE_GOAL"

    @property
    def pattern(self) -> str:
        return r'\[\[ACTIVATE_GOAL:\s*(\d+)\]\]'

    @property
    def needs_continuation(self) -> bool:
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        """Activate a goal."""
        from agency.goals import get_goal_manager

        try:
            goal_id = int(query.strip())
            manager = get_goal_manager()

            goal = manager.get_goal(goal_id)
            if goal is None:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    error=ToolError(
                        error_type="not_found",
                        message=f"Goal [{goal_id}] not found"
                    )
                )

            success = manager.activate_goal(goal_id)

            if success:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data={"goal_id": goal_id, "description": goal.description},
                    needs_continuation=True,
                    display_text=f"Activated goal [{goal_id}]"
                )
            else:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    error="Failed to activate goal"
                )

        except ValueError:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                error=ToolError(
                    error_type="invalid_format",
                    message="goal_id must be a number"
                )
            )
        except Exception as e:
            log_error(f"ACTIVATE_GOAL error: {e}")
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                error=str(e)
            )

    def get_instructions(self) -> str:
        return ""

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  Error: {result.get_error_message()}"
        data = result.data
        return f"  Activated: [{data['goal_id']}] {data['description'][:50]}"


class SelectTopGoalHandler(CommandHandler):
    """
    Handler for [[SELECT_TOP_GOAL: description]].

    Creates and activates a new top-level goal.
    Only available after completing the first (bootstrap) goal.
    """

    @property
    def command_name(self) -> str:
        return "SELECT_TOP_GOAL"

    @property
    def pattern(self) -> str:
        return r'\[\[SELECT_TOP_GOAL:\s*(.+?)\]\]'

    @property
    def needs_continuation(self) -> bool:
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        """Select a new top goal."""
        from agency.goals import get_goal_manager

        try:
            description = query.strip()

            if len(description) < 10:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    error=ToolError(
                        error_type="invalid_format",
                        message="Description too short",
                        suggestion="Provide a meaningful top-level objective"
                    )
                )

            manager = get_goal_manager()

            # Check if allowed
            if not manager.can_select_new_top_goal():
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    error=ToolError(
                        error_type="not_allowed",
                        message="Cannot select new top goal yet",
                        suggestion="Complete your current top goal first"
                    )
                )

            # Create and activate the new top goal
            goal_id = manager.select_new_top_goal(description, difficulty=5)

            if goal_id:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data={"goal_id": goal_id, "description": description},
                    needs_continuation=True,
                    display_text=f"New top goal selected [{goal_id}]"
                )
            else:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    error="Failed to create top goal"
                )

        except Exception as e:
            log_error(f"SELECT_TOP_GOAL error: {e}")
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                error=str(e)
            )

    def get_instructions(self) -> str:
        return ""

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  Error: {result.get_error_message()}"
        data = result.data
        return f"  New top goal [{data['goal_id']}]: {data['description'][:50]}"
