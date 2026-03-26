"""Gmail tool definitions."""

from typing import Any, Dict

SEARCH_EMAILS_TOOL: Dict[str, Any] = {
    "name": "search_emails",
    "description": """Search and list emails from the user's Gmail inbox.

Use this when:
- The user asks about their emails, inbox, or recent messages
- You need to find a specific email (by sender, subject, date, etc.)
- The user asks "do I have any new emails" or "check my email"

Uses Gmail search query syntax. Examples:
  "from:alice@example.com" — emails from Alice
  "is:unread" — all unread emails
  "subject:invoice" — emails with "invoice" in the subject
  "has:attachment" — emails with attachments
  "newer_than:2d" — emails from the last 2 days
  "from:boss is:unread" — unread emails from boss
  "" (empty) — most recent emails

Results include email_id (needed for read_email, send_email replies, and manage_email),
subject, sender, date, snippet, and unread status.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Gmail search query (e.g., 'from:alice is:unread', 'subject:report has:attachment'). Empty string returns recent emails."
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of emails to return (default 10)",
                "minimum": 1,
                "maximum": 50
            }
        },
        "required": ["query"]
    }
}

READ_EMAIL_TOOL: Dict[str, Any] = {
    "name": "read_email",
    "description": """Read the full content of an email by its ID.

Use this when:
- The user wants to see the full body of an email (after finding it via search_emails)
- You need to read an email's content to answer a question about it
- You need to check what attachments an email has before downloading

Returns the full email body (plain text preferred, HTML stripped as fallback),
all headers (from, to, cc, date, subject), and a list of attachments with their
attachment_id, filename, size, and MIME type. Use the attachment_id with
manage_email's download_attachment action to save attachments.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "email_id": {
                "type": "string",
                "description": "The email ID to read (from search_emails results)"
            }
        },
        "required": ["email_id"]
    }
}

SEND_EMAIL_TOOL: Dict[str, Any] = {
    "name": "send_email",
    "description": """Send a new email or reply to an existing email thread.

Use this when:
- The user asks to send, compose, or write an email
- The user asks to reply to an email
- You need to send a file to the user or someone else via email

For replies: provide reply_to_message_id (the email_id from read_email or search_emails).
This threads the reply correctly in Gmail so it appears in the same conversation.
The subject will automatically get a "Re:" prefix for replies.

For attachments: provide file paths relative to or within the data/files/ directory.
Files must exist before sending. Use the file tools to write/prepare files first,
then attach them here.

Always confirm with the user before sending emails, especially to external recipients.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "Recipient email address(es), comma-separated for multiple"
            },
            "subject": {
                "type": "string",
                "description": "Email subject line"
            },
            "body": {
                "type": "string",
                "description": "Email body text (plain text)"
            },
            "cc": {
                "type": "string",
                "description": "CC recipients (comma-separated), optional"
            },
            "bcc": {
                "type": "string",
                "description": "BCC recipients (comma-separated), optional"
            },
            "reply_to_message_id": {
                "type": "string",
                "description": "If replying, the email_id of the message to reply to. This threads the reply in the same Gmail conversation."
            },
            "attachment_paths": {
                "type": "array",
                "description": "Optional list of file paths to attach (files in data/files/ directory)",
                "items": {
                    "type": "string"
                }
            }
        },
        "required": ["to", "subject", "body"]
    }
}

MANAGE_EMAIL_TOOL: Dict[str, Any] = {
    "name": "manage_email",
    "description": """Manage an email: mark as read/unread, move to trash, or download an attachment.

Use this when:
- The user wants to mark emails as read or unread
- The user wants to delete/trash an email
- You need to download an attachment from an email to the local file system

Actions:
  "mark_read" — Remove the unread label
  "mark_unread" — Add the unread label
  "trash" — Move to trash (reversible from Gmail's trash folder)
  "download_attachment" — Download a specific attachment to data/files/.
      Requires attachment_id and filename (both from read_email results).
      The file is saved to data/files/{filename}. After downloading, you may
      want to use the move_file tool to organize it into a subdirectory or
      rename it as needed.

For download_attachment: first use read_email to see the list of attachments
and their attachment_ids, then use this tool to download the one you need.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "email_id": {
                "type": "string",
                "description": "The email ID to manage (from search_emails or read_email results)"
            },
            "action": {
                "type": "string",
                "enum": ["mark_read", "mark_unread", "trash", "download_attachment"],
                "description": "The action to perform on the email"
            },
            "attachment_id": {
                "type": "string",
                "description": "Required for download_attachment: the attachment ID from read_email results"
            },
            "filename": {
                "type": "string",
                "description": "Required for download_attachment: the filename to save as (from read_email results)"
            }
        },
        "required": ["email_id", "action"]
    }
}
