"""
Pattern Project - Telegram Command Handler
Handles [[SEND_TELEGRAM: message]] commands for AI-initiated messaging.

Messages are sent to the configured Telegram chat via the Bot API.
"""

from agency.commands.handlers.base import CommandHandler, CommandResult
from agency.commands.errors import ToolError, ToolErrorType


class SendTelegramHandler(CommandHandler):
    """
    Handles [[SEND_TELEGRAM: message]] commands for sending Telegram messages.

    Messages are sent to the configured chat ID via the Telegram Bot API.

    Example AI usage:
        "I'll message you... [[SEND_TELEGRAM: Don't forget your appointment at 3pm!]]"
    """

    @property
    def command_name(self) -> str:
        return "SEND_TELEGRAM"

    @property
    def pattern(self) -> str:
        return r'\[\[SEND_TELEGRAM:\s*(.+?)\]\]'

    @property
    def needs_continuation(self) -> bool:
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Send a Telegram message to the configured chat.

        Args:
            query: The message content to send
            context: Session context (unused)

        Returns:
            CommandResult with send status
        """
        from config import TELEGRAM_ENABLED

        message = query.strip()

        # Check if Telegram is enabled
        if not TELEGRAM_ENABLED:
            return CommandResult(
                command_name=self.command_name,
                query=message,
                data=None,
                needs_continuation=True,
                display_text="Telegram feature disabled",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message="Telegram is disabled in configuration",
                    expected_format=None,
                    example=None
                )
            )

        # Validate message content
        if not message:
            return CommandResult(
                command_name=self.command_name,
                query=message,
                data=None,
                needs_continuation=True,
                display_text="Empty Telegram message",
                error=ToolError(
                    error_type=ToolErrorType.FORMAT_ERROR,
                    message="Telegram message cannot be empty",
                    expected_format="send_telegram with message parameter",
                    example="send_telegram(message=\"Don't forget your 3pm appointment!\")"
                )
            )

        # Check rate limit
        from communication.rate_limiter import get_rate_limiter

        rate_limiter = get_rate_limiter()
        if not rate_limiter.check_telegram():
            remaining_info = ""
            reset_time = rate_limiter.get_telegram_reset_time()
            if reset_time:
                remaining_info = f" Limit resets at {reset_time.strftime('%H:%M:%S')}."

            return CommandResult(
                command_name=self.command_name,
                query=message,
                data=None,
                needs_continuation=True,
                display_text="Telegram rate limit exceeded",
                error=ToolError(
                    error_type=ToolErrorType.RATE_LIMITED,
                    message=f"Telegram rate limit exceeded ({rate_limiter.telegram_max}/hour).{remaining_info}",
                    expected_format=None,
                    example=None
                )
            )

        # Send the message
        try:
            from communication.telegram_gateway import get_telegram_gateway

            gateway = get_telegram_gateway()

            if not gateway.is_available():
                return CommandResult(
                    command_name=self.command_name,
                    query=message,
                    data=None,
                    needs_continuation=True,
                    display_text="Telegram gateway not configured",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message="Telegram gateway not properly configured. Check bot token and chat ID.",
                        expected_format=None,
                        example=None
                    )
                )

            result = gateway.send(message)

            # Record the send in rate limiter (even if it failed, to prevent rapid retries)
            rate_limiter.record_telegram()

            if result.success:
                return CommandResult(
                    command_name=self.command_name,
                    query=message,
                    data={
                        "chat_id": result.chat_id,
                        "message_id": result.message_id,
                        "message_length": len(message),
                        "timestamp": result.timestamp.isoformat()
                    },
                    needs_continuation=True,
                    display_text="Telegram message sent"
                )
            else:
                return CommandResult(
                    command_name=self.command_name,
                    query=message,
                    data=None,
                    needs_continuation=True,
                    display_text="Telegram send failed",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message=f"Failed to send Telegram message: {result.message}",
                        expected_format=None,
                        example=None
                    )
                )

        except RuntimeError as e:
            # Gateway not initialized
            return CommandResult(
                command_name=self.command_name,
                query=message,
                data=None,
                needs_continuation=True,
                display_text="Telegram gateway error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Telegram gateway not initialized: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )
        except Exception as e:
            return CommandResult(
                command_name=self.command_name,
                query=message,
                data=None,
                needs_continuation=True,
                display_text="Telegram error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Unexpected error sending Telegram message: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def get_instructions(self) -> str:
        return """You can send a Telegram message to the user by including this command in your response:
  [[SEND_TELEGRAM: Your message here]]

Use this when:
- The user asks you to message them a reminder
- You need to alert the user about something important
- Time-sensitive information needs to be communicated
- The user is away and you need to reach them

Guidelines:
- Messages can be any length (no SMS-style limits)
- Use for genuinely useful notifications, not casual chat
- Be concise and clear for better mobile readability
- The user can reply directly in Telegram and you'll receive their response"""

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  {result.get_error_message()}"

        if not result.data:
            return "  Telegram operation completed."

        data = result.data
        length = data.get("message_length", 0)

        return f"  Telegram message sent ({length} characters)"
