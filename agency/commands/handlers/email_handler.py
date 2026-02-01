"""
Pattern Project - Email Command Handler
Handles [[SEND_EMAIL: recipient | subject | body]] commands for AI-initiated email.

NOTE: This handler is built but DISABLED by default. Enable via EMAIL_GATEWAY_ENABLED config.
"""

from agency.commands.handlers.base import CommandHandler, CommandResult
from agency.commands.errors import ToolError, ToolErrorType


def _parse_email_command(query: str) -> tuple:
    """
    Parse an email command query into recipient, subject, and body.

    Args:
        query: The full query string (recipient | subject | body)

    Returns:
        Tuple of (recipient, subject, body)

    Raises:
        ValueError: If query format is invalid
    """
    if "|" not in query:
        raise ValueError("Email command requires format: recipient | subject | body")

    parts = query.split("|", 2)  # Split into max 3 parts

    if len(parts) != 3:
        raise ValueError("Email command requires format: recipient | subject | body")

    recipient = parts[0].strip()
    subject = parts[1].strip()
    body = parts[2].strip()

    if not recipient:
        raise ValueError("Recipient email cannot be empty")

    if not subject:
        raise ValueError("Subject cannot be empty")

    if not body:
        raise ValueError("Body cannot be empty")

    # Basic email validation
    if "@" not in recipient or "." not in recipient:
        raise ValueError(f"Invalid email address: {recipient}")

    return recipient, subject, body


class SendEmailHandler(CommandHandler):
    """
    Handles [[SEND_EMAIL: recipient | subject | body]] commands.

    Sends emails via the configured email gateway. Recipients must be
    on the whitelist for security.

    NOTE: This handler is DISABLED by default. Set EMAIL_GATEWAY_ENABLED=True
    in config to enable.

    Example AI usage:
        "I'll send that email now... [[SEND_EMAIL: user@example.com | Meeting Notes | Here are the notes...]]"
    """

    @property
    def command_name(self) -> str:
        return "SEND_EMAIL"

    @property
    def pattern(self) -> str:
        return r'\[\[SEND_EMAIL:\s*(.+?)\]\]'

    @property
    def needs_continuation(self) -> bool:
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Send an email to a whitelisted recipient.

        Args:
            query: "recipient | subject | body" format
            context: Session context (unused)

        Returns:
            CommandResult with send status
        """
        from config import EMAIL_GATEWAY_ENABLED, EMAIL_WHITELIST

        # Check if email is enabled
        if not EMAIL_GATEWAY_ENABLED:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Email feature disabled",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message="Email gateway is disabled in configuration",
                    expected_format=None,
                    example=None
                )
            )

        # Parse the command
        try:
            recipient, subject, body = _parse_email_command(query)
        except ValueError as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Invalid email command format",
                error=ToolError(
                    error_type=ToolErrorType.FORMAT_ERROR,
                    message=str(e),
                    expected_format="send_email with to, subject, and body parameters",
                    example="send_email(to='user@example.com', subject='Meeting Notes', body='Here are the meeting notes from today...')"
                )
            )

        # Check whitelist
        if EMAIL_WHITELIST and recipient.lower() not in [w.lower() for w in EMAIL_WHITELIST]:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Recipient not whitelisted",
                error=ToolError(
                    error_type=ToolErrorType.VALIDATION,
                    message=f"Recipient '{recipient}' is not on the whitelist. Only approved addresses can receive emails.",
                    expected_format=None,
                    example=None
                )
            )

        # Check rate limit
        from communication.rate_limiter import get_rate_limiter

        rate_limiter = get_rate_limiter()
        if not rate_limiter.check_email():
            remaining_info = ""
            reset_time = rate_limiter.get_email_reset_time()
            if reset_time:
                remaining_info = f" Limit resets at {reset_time.strftime('%H:%M:%S')}."

            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Email rate limit exceeded",
                error=ToolError(
                    error_type=ToolErrorType.RATE_LIMITED,
                    message=f"Email rate limit exceeded ({rate_limiter.email_max}/hour).{remaining_info}",
                    expected_format=None,
                    example=None
                )
            )

        # Send the email
        try:
            from communication.email_gateway import get_email_gateway

            gateway = get_email_gateway()

            if not gateway.is_available():
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text="Email gateway not configured",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message="Email gateway not properly configured. Check environment variables.",
                        expected_format=None,
                        example=None
                    )
                )

            result = gateway.send(
                recipient=recipient,
                subject=subject,
                body=body,
                is_sms=False
            )

            # Record the send in rate limiter
            rate_limiter.record_email()

            if result.success:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data={
                        "recipient": recipient,
                        "subject": subject,
                        "body_length": len(body),
                        "timestamp": result.timestamp.isoformat()
                    },
                    needs_continuation=True,
                    display_text=f"Email sent to {recipient}"
                )
            else:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text="Email send failed",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message=f"Failed to send email: {result.message}",
                        expected_format=None,
                        example=None
                    )
                )

        except RuntimeError as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Email gateway error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Email gateway not initialized: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )
        except Exception as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Email error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Unexpected error sending email: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def get_instructions(self) -> str:
        return """You can send an email by including this command in your response:
  [[SEND_EMAIL: recipient@example.com | Subject Line | Email body text]]

Use this when:
- The user asks you to send them or someone else an email
- Important information needs to be delivered via email

Guidelines:
- Only whitelisted recipients can receive emails
- Keep subjects clear and concise
- Email body can be longer than SMS, but be respectful of the recipient's time"""

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  {result.get_error_message()}"

        if not result.data:
            return "  Email operation completed."

        data = result.data
        recipient = data.get("recipient", "unknown")
        subject = data.get("subject", "")
        body_length = data.get("body_length", 0)

        return f"  Email sent to {recipient}\n  Subject: {subject}\n  Body: {body_length} characters"
