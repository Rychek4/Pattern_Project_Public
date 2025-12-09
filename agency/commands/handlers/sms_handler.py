"""
Pattern Project - SMS Command Handler
Handles [[SEND_SMS: message]] commands for AI-initiated text messaging.

SMS messages are sent to the whitelisted recipient via carrier email gateway.
"""

from agency.commands.handlers.base import CommandHandler, CommandResult
from agency.commands.errors import ToolError, ToolErrorType


class SendSMSHandler(CommandHandler):
    """
    Handles [[SEND_SMS: message]] commands for sending text messages.

    Messages are sent to the configured recipient phone number via
    the carrier's email-to-SMS gateway.

    Example AI usage:
        "I'll text you a reminder... [[SEND_SMS: Don't forget your appointment at 3pm!]]"
    """

    @property
    def command_name(self) -> str:
        return "SEND_SMS"

    @property
    def pattern(self) -> str:
        return r'\[\[SEND_SMS:\s*(.+?)\]\]'

    @property
    def needs_continuation(self) -> bool:
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Send an SMS message to the whitelisted recipient.

        Args:
            query: The message content to send
            context: Session context (unused)

        Returns:
            CommandResult with send status
        """
        from config import SMS_GATEWAY_ENABLED, SMS_MAX_LENGTH

        message = query.strip()

        # Check if SMS is enabled
        if not SMS_GATEWAY_ENABLED:
            return CommandResult(
                command_name=self.command_name,
                query=message,
                data=None,
                needs_continuation=True,
                display_text="SMS feature disabled",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message="SMS gateway is disabled in configuration",
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
                display_text="Empty SMS message",
                error=ToolError(
                    error_type=ToolErrorType.FORMAT_ERROR,
                    message="SMS message cannot be empty",
                    expected_format="[[SEND_SMS: Your message here]]",
                    example="[[SEND_SMS: Don't forget your 3pm appointment!]]"
                )
            )

        # Check rate limit
        from communication.rate_limiter import get_rate_limiter

        rate_limiter = get_rate_limiter()
        if not rate_limiter.check_sms():
            remaining_info = ""
            reset_time = rate_limiter.get_sms_reset_time()
            if reset_time:
                remaining_info = f" Limit resets at {reset_time.strftime('%H:%M:%S')}."

            return CommandResult(
                command_name=self.command_name,
                query=message,
                data=None,
                needs_continuation=True,
                display_text="SMS rate limit exceeded",
                error=ToolError(
                    error_type=ToolErrorType.RATE_LIMITED,
                    message=f"SMS rate limit exceeded ({rate_limiter.sms_max}/hour).{remaining_info}",
                    expected_format=None,
                    example=None
                )
            )

        # Send the SMS
        try:
            from communication.sms_gateway import get_sms_gateway

            gateway = get_sms_gateway()

            if not gateway.is_available():
                return CommandResult(
                    command_name=self.command_name,
                    query=message,
                    data=None,
                    needs_continuation=True,
                    display_text="SMS gateway not configured",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message="SMS gateway not properly configured. Check environment variables.",
                        expected_format=None,
                        example=None
                    )
                )

            result = gateway.send(message)

            # Record the send in rate limiter (even if it failed, to prevent rapid retries)
            rate_limiter.record_sms()

            if result.success:
                # Note if message was truncated
                truncated_note = ""
                if len(query.strip()) > SMS_MAX_LENGTH:
                    truncated_note = f" (truncated to {SMS_MAX_LENGTH} chars)"

                return CommandResult(
                    command_name=self.command_name,
                    query=message,
                    data={
                        "recipient": result.recipient,
                        "message_length": len(message),
                        "truncated": len(query.strip()) > SMS_MAX_LENGTH,
                        "timestamp": result.timestamp.isoformat()
                    },
                    needs_continuation=True,
                    display_text=f"SMS sent{truncated_note}"
                )
            else:
                return CommandResult(
                    command_name=self.command_name,
                    query=message,
                    data=None,
                    needs_continuation=True,
                    display_text="SMS send failed",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message=f"Failed to send SMS: {result.message}",
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
                display_text="SMS gateway error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"SMS gateway not initialized: {str(e)}",
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
                display_text="SMS error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Unexpected error sending SMS: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def get_instructions(self) -> str:
        return """You can send an SMS text message to the user by including this command in your response:
  [[SEND_SMS: Your message here]]

Use this when:
- The user asks you to text them a reminder
- You need to alert the user about something important
- Time-sensitive information needs to be communicated

Guidelines:
- Keep messages under 160 characters to avoid truncation
- Use for genuinely useful notifications, not casual chat
- Be concise and clear - SMS is for brief, important messages"""

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  {result.get_error_message()}"

        if not result.data:
            return "  SMS operation completed."

        data = result.data
        length = data.get("message_length", 0)
        truncated = data.get("truncated", False)

        status = "SMS sent successfully"
        if truncated:
            status += " (message was truncated)"

        return f"  {status} ({length} characters)"
