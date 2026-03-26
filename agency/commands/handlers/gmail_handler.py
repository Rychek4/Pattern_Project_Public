"""
Pattern Project - Gmail Command Handlers
Handles email operations via the Gmail API native tools.

NOTE: These handlers are DISABLED by default. Enable via GMAIL_ENABLED config.
"""

from agency.commands.handlers.base import CommandHandler, CommandResult
from agency.commands.errors import ToolError, ToolErrorType


class SearchEmailsHandler(CommandHandler):
    """
    Handles searching/listing emails via the search_emails native tool.

    Queries the user's Gmail inbox using Gmail search syntax.

    Called by ToolExecutor when the AI invokes the search_emails tool.
    """

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Search emails matching a query.

        Args:
            query: Gmail search query string
            context: Session context containing gmail_params

        Returns:
            CommandResult with list of email summaries
        """
        from config import GMAIL_ENABLED

        if not GMAIL_ENABLED:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Gmail disabled",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message="Gmail is disabled in configuration",
                    expected_format=None,
                    example=None
                )
            )

        params = context.get("gmail_params", {})
        search_query = params.get("query", query)
        max_results = params.get("max_results", 10)

        try:
            from communication.gmail_gateway import get_gmail_gateway

            gateway = get_gmail_gateway()

            if not gateway.is_available():
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text="Gmail not configured",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message="Gmail credentials not found. Place OAuth2 credentials JSON in data/.",
                        expected_format=None,
                        example=None
                    )
                )

            result = gateway.list_emails(
                query=search_query,
                max_results=max_results,
            )

            if result.success:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=result.data,
                    needs_continuation=True,
                    display_text=result.message,
                )
            else:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text="Failed to search emails",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message=result.message,
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
                display_text="Gmail gateway error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Gmail gateway not initialized: {str(e)}",
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
                display_text="Gmail error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Unexpected error searching emails: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  {result.get_error_message()}"

        if not result.data:
            return "  No emails found matching the query."

        emails = result.data
        lines = [f"  Found {len(emails)} email(s):"]
        for email in emails:
            email_id = email.get("email_id", "")
            subject = email.get("subject", "(no subject)")
            sender = email.get("from", "")
            date = email.get("date", "")
            unread = " [UNREAD]" if email.get("is_unread") else ""
            snippet = email.get("snippet", "")
            if len(snippet) > 80:
                snippet = snippet[:80] + "..."

            lines.append(f"  - [{email_id}]{unread} {subject}")
            lines.append(f"    From: {sender} | Date: {date}")
            if snippet:
                lines.append(f"    {snippet}")

        return "\n".join(lines)


class ReadEmailHandler(CommandHandler):
    """
    Handles reading full email content via the read_email native tool.

    Fetches the full body and attachment list for a specific email.

    Called by ToolExecutor when the AI invokes the read_email tool.
    """

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Read a full email by ID.

        Args:
            query: The email_id string
            context: Session context containing gmail_params

        Returns:
            CommandResult with full email data
        """
        from config import GMAIL_ENABLED

        if not GMAIL_ENABLED:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Gmail disabled",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message="Gmail is disabled in configuration",
                    expected_format=None,
                    example=None
                )
            )

        params = context.get("gmail_params", {})
        email_id = params.get("email_id", query.strip())

        if not email_id:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Missing email ID",
                error=ToolError(
                    error_type=ToolErrorType.VALIDATION,
                    message="email_id is required to read an email",
                    expected_format=None,
                    example=None
                )
            )

        try:
            from communication.gmail_gateway import get_gmail_gateway

            gateway = get_gmail_gateway()

            if not gateway.is_available():
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text="Gmail not configured",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message="Gmail credentials not found. Place OAuth2 credentials JSON in data/.",
                        expected_format=None,
                        example=None
                    )
                )

            result = gateway.read_email(email_id=email_id)

            if result.success:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=result.data,
                    needs_continuation=True,
                    display_text=result.message,
                )
            else:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text="Failed to read email",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message=result.message,
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
                display_text="Gmail gateway error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Gmail gateway not initialized: {str(e)}",
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
                display_text="Gmail error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Unexpected error reading email: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  {result.get_error_message()}"

        if not result.data:
            return "  Email not found."

        data = result.data
        lines = [
            f"  Subject: {data.get('subject', '(no subject)')}",
            f"  From: {data.get('from', '')}",
            f"  To: {data.get('to', '')}",
        ]
        if data.get("cc"):
            lines.append(f"  CC: {data['cc']}")
        lines.append(f"  Date: {data.get('date', '')}")

        # Attachments
        attachments = data.get("attachments", [])
        if attachments:
            lines.append(f"  Attachments ({len(attachments)}):")
            for att in attachments:
                size = att.get("size_bytes", 0)
                size_str = f"{size:,} bytes" if size else "unknown size"
                lines.append(f"    - {att.get('filename', '?')} ({size_str}, id: {att.get('attachment_id', '')})")

        lines.append(f"  ---")
        body = data.get("body", "")
        if body:
            # Truncate very long bodies for readability
            if len(body) > 5000:
                body = body[:5000] + "\n... [truncated, body is very long]"
            lines.append(body)
        else:
            lines.append("  (empty body)")

        return "\n".join(lines)


class SendEmailHandler(CommandHandler):
    """
    Handles sending emails (new or reply) via the send_email native tool.

    Sends emails from the user's Gmail account. Supports replies via
    reply_to_message_id and file attachments from data/files/.

    Called by ToolExecutor when the AI invokes the send_email tool.
    """

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Send an email or reply to a thread.

        Args:
            query: Pipe-delimited "to | subject | body"
            context: Session context containing gmail_params with full fields

        Returns:
            CommandResult with sent message confirmation
        """
        from config import GMAIL_ENABLED

        if not GMAIL_ENABLED:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Gmail disabled",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message="Gmail is disabled in configuration",
                    expected_format=None,
                    example=None
                )
            )

        params = context.get("gmail_params", {})
        to = params.get("to", "")
        subject = params.get("subject", "")
        body = params.get("body", "")

        if not to or not subject or not body:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Missing required fields",
                error=ToolError(
                    error_type=ToolErrorType.VALIDATION,
                    message="to, subject, and body are all required to send an email",
                    expected_format=None,
                    example=None
                )
            )

        try:
            from communication.gmail_gateway import get_gmail_gateway

            gateway = get_gmail_gateway()

            if not gateway.is_available():
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text="Gmail not configured",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message="Gmail credentials not found. Place OAuth2 credentials JSON in data/.",
                        expected_format=None,
                        example=None
                    )
                )

            result = gateway.send_email(
                to=to,
                subject=subject,
                body=body,
                cc=params.get("cc", ""),
                bcc=params.get("bcc", ""),
                reply_to_message_id=params.get("reply_to_message_id", ""),
                attachment_paths=params.get("attachment_paths"),
            )

            if result.success:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=result.data,
                    needs_continuation=True,
                    display_text=result.message,
                )
            else:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text="Failed to send email",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message=result.message,
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
                display_text="Gmail gateway error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Gmail gateway not initialized: {str(e)}",
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
                display_text="Gmail error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Unexpected error sending email: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  {result.get_error_message()}"

        if not result.data:
            return "  Email sent."

        data = result.data
        lines = [
            f"  {result.display_text}",
            f"  Subject: {data.get('subject', '')}",
            f"  Message ID: {data.get('message_id', '')}",
        ]

        return "\n".join(lines)


class ManageEmailHandler(CommandHandler):
    """
    Handles email management actions via the manage_email native tool.

    Supports mark_read, mark_unread, trash, and download_attachment actions.

    Called by ToolExecutor when the AI invokes the manage_email tool.
    """

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Manage an email (mark read/unread, trash, download attachment).

        Args:
            query: The email_id string
            context: Session context containing gmail_params with action and optional attachment fields

        Returns:
            CommandResult with action confirmation
        """
        from config import GMAIL_ENABLED

        if not GMAIL_ENABLED:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Gmail disabled",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message="Gmail is disabled in configuration",
                    expected_format=None,
                    example=None
                )
            )

        params = context.get("gmail_params", {})
        email_id = params.get("email_id", "")
        action = params.get("action", "")

        if not email_id:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Missing email ID",
                error=ToolError(
                    error_type=ToolErrorType.VALIDATION,
                    message="email_id is required",
                    expected_format=None,
                    example=None
                )
            )

        if not action:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Missing action",
                error=ToolError(
                    error_type=ToolErrorType.VALIDATION,
                    message="action is required (mark_read, mark_unread, trash, download_attachment)",
                    expected_format=None,
                    example=None
                )
            )

        try:
            from communication.gmail_gateway import get_gmail_gateway

            gateway = get_gmail_gateway()

            if not gateway.is_available():
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text="Gmail not configured",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message="Gmail credentials not found. Place OAuth2 credentials JSON in data/.",
                        expected_format=None,
                        example=None
                    )
                )

            # Handle download_attachment separately since it needs extra params
            if action == "download_attachment":
                attachment_id = params.get("attachment_id", "")
                filename = params.get("filename", "")

                if not attachment_id or not filename:
                    return CommandResult(
                        command_name=self.command_name,
                        query=query,
                        data=None,
                        needs_continuation=True,
                        display_text="Missing attachment fields",
                        error=ToolError(
                            error_type=ToolErrorType.VALIDATION,
                            message="attachment_id and filename are required for download_attachment",
                            expected_format=None,
                            example=None
                        )
                    )

                result = gateway.download_attachment(
                    email_id=email_id,
                    attachment_id=attachment_id,
                    filename=filename,
                )
            else:
                result = gateway.manage_email(
                    email_id=email_id,
                    action=action,
                )

            if result.success:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=result.data,
                    needs_continuation=True,
                    display_text=result.message,
                )
            else:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text=f"Failed to {action}",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message=result.message,
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
                display_text="Gmail gateway error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Gmail gateway not initialized: {str(e)}",
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
                display_text="Gmail error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Unexpected error managing email: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  {result.get_error_message()}"

        if not result.data:
            return f"  {result.display_text}"

        data = result.data
        action = data.get("action", "")

        if action == "download_attachment":
            return (
                f"  Downloaded: {data.get('filename', '')}\n"
                f"  Saved to: {data.get('path', '')}\n"
                f"  Size: {data.get('size_bytes', 0):,} bytes"
            )

        return f"  {result.display_text}"
