"""
Pattern Project - Economy Command Handlers
Commands for AI to interact with the agency economy
"""

from agency.commands.handlers.base import CommandHandler, CommandResult
from agency.commands.errors import ToolError
from core.logger import log_info, log_error


class SetTempoHandler(CommandHandler):
    """
    Handler for [[SET_TEMPO: option_name]].

    Purchases a tempo option to set the next wake-up time.
    Options include:
    - standard: Default interval (free)
    - focus_30min, focus_15min, focus_10min, focus_5min: Shortened intervals (costs points)
    """

    @property
    def command_name(self) -> str:
        return "SET_TEMPO"

    @property
    def pattern(self) -> str:
        return r'\[\[SET_TEMPO:\s*(\w+)\]\]'

    @property
    def needs_continuation(self) -> bool:
        return True  # AI should see confirmation

    def execute(self, query: str, context: dict) -> CommandResult:
        """Purchase a tempo option."""
        import config
        from agency.economy import get_economy_manager

        if not config.AGENCY_ECONOMY_ENABLED:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                error=ToolError(
                    error_type="disabled",
                    message="Agency economy is disabled"
                )
            )

        try:
            option_name = query.strip().lower()
            manager = get_economy_manager()

            # Get available options
            state = manager.get_state()
            options = manager.get_tempo_options(state.agency_points)
            option_names = [opt.name for opt in options]

            if option_name not in option_names:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    error=ToolError(
                        error_type="not_available",
                        message=f"Option '{option_name}' not available",
                        suggestion=f"Available options: {', '.join(option_names)}"
                    )
                )

            # Purchase the option
            decision = manager.purchase_tempo(option_name)

            if decision:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data={
                        "option": decision.selected_option.name,
                        "display_name": decision.selected_option.display_name,
                        "cost": decision.points_spent,
                        "next_wakeup_minutes": decision.selected_option.wakeup_minutes,
                        "reason": decision.reason
                    },
                    needs_continuation=True,
                    display_text=f"Tempo set: {decision.selected_option.display_name}"
                )
            else:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    error="Failed to purchase tempo option"
                )

        except Exception as e:
            log_error(f"SET_TEMPO error: {e}")
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                error=str(e)
            )

    def get_instructions(self) -> str:
        return ""  # Instructions provided by AgencyEconomySource

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  Error: {result.get_error_message()}"
        data = result.data
        cost_str = f"({data['cost']:.0f} pts)" if data['cost'] > 0 else "(free)"
        return f"  Tempo: {data['display_name']} {cost_str} - next wakeup in {data['next_wakeup_minutes']:.0f} minutes"
