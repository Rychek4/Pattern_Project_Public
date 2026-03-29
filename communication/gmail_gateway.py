"""
Pattern Project - Gmail Gateway
OAuth2-based Gmail API integration for sending, receiving, and managing emails.

This module provides the underlying Gmail service used by the gmail
tool handlers. On first use, it triggers a browser-based OAuth consent flow.
After consent, tokens are saved locally and auto-refresh.
"""

import os
import base64
from dataclasses import dataclass
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional, List, Dict, Any

from core.logger import log_info, log_error, log_success, log_warning


@dataclass
class GmailResult:
    """
    Result from a Gmail gateway operation.

    Attributes:
        success: Whether the operation succeeded
        message: Status message (success info or error description)
        data: Structured result data (email dict, list of emails, etc.)
        timestamp: When the operation occurred
    """
    success: bool
    message: str
    data: Optional[Any] = None
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def __str__(self) -> str:
        status = "Success" if self.success else "Failed"
        return f"{status}: {self.message}"


class GmailGateway:
    """
    Gmail gateway using the Gmail API v1.

    Handles OAuth2 authentication with automatic token refresh.
    On first use, opens a browser for user consent. After consent,
    the token is stored locally and refreshed automatically.
    """

    # Read, send, and modify (label changes) but not permanent delete
    SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

    def __init__(
        self,
        credentials_path: str,
        token_path: str,
    ):
        """
        Initialize the Gmail gateway.

        Args:
            credentials_path: Path to the OAuth2 credentials JSON from Google Cloud Console
            token_path: Path where the OAuth2 token will be saved/loaded
        """
        self.credentials_path = credentials_path
        self.token_path = token_path
        self._service = None

    def is_available(self) -> bool:
        """
        Check if the gateway is properly configured.

        Returns:
            True if the credentials file exists, False otherwise
        """
        return os.path.exists(self.credentials_path)

    def _get_service(self):
        """
        Get or create the authenticated Gmail API service.

        On first call (no token file), opens a browser for OAuth consent.
        On subsequent calls, loads the saved token and refreshes if needed.

        Returns:
            Authenticated Gmail API service object

        Raises:
            RuntimeError: If credentials file is missing or auth fails
        """
        if self._service is not None:
            return self._service

        if not self.is_available():
            raise RuntimeError(
                f"Gmail credentials not found at {self.credentials_path}. "
                "Download OAuth2 credentials from Google Cloud Console."
            )

        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = None

        # Load existing token if available
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(
                    self.token_path, self.SCOPES
                )
                log_info("Loaded existing Gmail token")
            except Exception as e:
                log_warning(f"Failed to load Gmail token, will re-authenticate: {e}")
                creds = None

        # Refresh or obtain new credentials
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                log_info("Refreshed Gmail token")
            except Exception as e:
                log_warning(f"Gmail token refresh failed, will re-authenticate: {e}")
                creds = None

        if not creds or not creds.valid:
            log_info("Starting Gmail OAuth consent flow (browser will open)...")
            flow = InstalledAppFlow.from_client_secrets_file(
                self.credentials_path, self.SCOPES
            )
            creds = flow.run_local_server(port=0)
            log_success("Gmail OAuth consent completed")

            # Save token for future use
            with open(self.token_path, "w") as token_file:
                token_file.write(creds.to_json())
            log_info(f"Saved Gmail token to {self.token_path}")

        self._service = build("gmail", "v1", credentials=creds)
        log_success("Gmail API service initialized")
        return self._service

    def list_emails(
        self,
        query: str = "",
        max_results: int = 10,
    ) -> GmailResult:
        """
        Search/list emails from the user's Gmail inbox.

        Args:
            query: Gmail search query (e.g., "from:alice is:unread", "subject:invoice")
                   Empty string returns recent emails.
            max_results: Maximum number of emails to return (default 10)

        Returns:
            GmailResult with list of email summary dicts in data field
        """
        try:
            service = self._get_service()

            results = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=max_results,
            ).execute()

            messages = results.get("messages", [])

            if not messages:
                return GmailResult(
                    success=True,
                    message="No emails found matching the query",
                    data=[],
                )

            # Fetch summary info for each message
            summaries = []
            for msg_ref in messages:
                msg = service.users().messages().get(
                    userId="me",
                    id=msg_ref["id"],
                    format="metadata",
                    metadataHeaders=["Subject", "From", "To", "Date"],
                ).execute()
                summaries.append(self._simplify_email_summary(msg))

            log_info(f"Retrieved {len(summaries)} email summaries")

            return GmailResult(
                success=True,
                message=f"Found {len(summaries)} email(s)",
                data=summaries,
            )

        except RuntimeError as e:
            log_error(f"Gmail gateway error: {e}")
            return GmailResult(success=False, message=str(e))
        except Exception as e:
            log_error(f"Failed to list emails: {e}")
            return GmailResult(success=False, message=f"Failed to list emails: {str(e)}")

    def read_email(self, email_id: str) -> GmailResult:
        """
        Read the full content of an email by ID.

        Args:
            email_id: The Gmail message ID (from list_emails results)

        Returns:
            GmailResult with full email content dict in data field
        """
        try:
            service = self._get_service()

            msg = service.users().messages().get(
                userId="me",
                id=email_id,
                format="full",
            ).execute()

            email_data = self._parse_full_email(msg)
            log_info(f"Read email: {email_data.get('subject', '(no subject)')}")

            return GmailResult(
                success=True,
                message=f"Read email: {email_data.get('subject', '(no subject)')}",
                data=email_data,
            )

        except RuntimeError as e:
            log_error(f"Gmail gateway error: {e}")
            return GmailResult(success=False, message=str(e))
        except Exception as e:
            log_error(f"Failed to read email: {e}")
            return GmailResult(success=False, message=f"Failed to read email: {str(e)}")

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
        reply_to_message_id: str = "",
        attachment_paths: Optional[List[str]] = None,
    ) -> GmailResult:
        """
        Send a new email or reply to an existing thread.

        Args:
            to: Recipient email address(es), comma-separated for multiple
            subject: Email subject line
            body: Email body text (plain text)
            cc: CC recipients (comma-separated), optional
            bcc: BCC recipients (comma-separated), optional
            reply_to_message_id: If provided, sends as a reply in the same thread.
                                 The message ID must be from a previous read_email result.
            attachment_paths: Optional list of file paths to attach (from data/files/)

        Returns:
            GmailResult with sent message data
        """
        try:
            service = self._get_service()

            # Build the MIME message
            if attachment_paths:
                from config import FILE_STORAGE_DIR

                message = MIMEMultipart()
                message.attach(MIMEText(body, "plain"))

                for file_path in attachment_paths:
                    # Resolve sandbox-relative paths (e.g. "specs/report.md" → data/files/specs/report.md)
                    if not os.path.isabs(file_path):
                        resolved = os.path.join(str(FILE_STORAGE_DIR), file_path)
                    else:
                        resolved = file_path
                    if not os.path.exists(resolved):
                        return GmailResult(
                            success=False,
                            message=f"Attachment not found: {file_path}",
                        )
                    part = self._create_attachment(resolved)
                    message.attach(part)
            else:
                message = MIMEText(body, "plain")

            message["to"] = to
            message["subject"] = subject
            if cc:
                message["cc"] = cc
            if bcc:
                message["bcc"] = bcc

            # Handle reply threading
            thread_id = None
            if reply_to_message_id:
                # Fetch the original message to get thread ID and headers
                original = service.users().messages().get(
                    userId="me",
                    id=reply_to_message_id,
                    format="metadata",
                    metadataHeaders=["Message-ID", "Subject"],
                ).execute()

                thread_id = original.get("threadId")

                # Set threading headers
                original_message_id = self._get_header(original, "Message-ID")
                if original_message_id:
                    message["In-Reply-To"] = original_message_id
                    message["References"] = original_message_id

                # Ensure subject has Re: prefix for replies
                if not subject.lower().startswith("re:"):
                    original_subject = self._get_header(original, "Subject")
                    if original_subject:
                        message.replace_header("subject", f"Re: {original_subject}")

            # Encode and send
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

            send_body: Dict[str, Any] = {"raw": raw}
            if thread_id:
                send_body["threadId"] = thread_id

            sent = service.users().messages().send(
                userId="me",
                body=send_body,
            ).execute()

            action = "Reply sent" if reply_to_message_id else "Email sent"
            log_success(f"{action} to {to}: {subject}")

            return GmailResult(
                success=True,
                message=f"{action} to {to}",
                data={
                    "message_id": sent.get("id", ""),
                    "thread_id": sent.get("threadId", ""),
                    "to": to,
                    "subject": subject,
                },
            )

        except RuntimeError as e:
            log_error(f"Gmail gateway error: {e}")
            return GmailResult(success=False, message=str(e))
        except Exception as e:
            log_error(f"Failed to send email: {e}")
            return GmailResult(success=False, message=f"Failed to send email: {str(e)}")

    def download_attachment(
        self,
        email_id: str,
        attachment_id: str,
        filename: str,
    ) -> GmailResult:
        """
        Download an email attachment and save it to the file storage directory.

        Args:
            email_id: The Gmail message ID containing the attachment
            attachment_id: The attachment ID (from read_email results)
            filename: Filename to save as (within data/files/)

        Returns:
            GmailResult with the saved file path
        """
        try:
            service = self._get_service()

            from config import FILE_STORAGE_DIR

            attachment = service.users().messages().attachments().get(
                userId="me",
                messageId=email_id,
                id=attachment_id,
            ).execute()

            file_data = base64.urlsafe_b64decode(attachment["data"])

            # Save to the sandboxed file storage directory
            save_path = os.path.join(str(FILE_STORAGE_DIR), filename)

            # Ensure parent directory exists
            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            with open(save_path, "wb") as f:
                f.write(file_data)

            file_size = len(file_data)
            log_success(f"Downloaded attachment: {filename} ({file_size} bytes)")

            return GmailResult(
                success=True,
                message=f"Saved attachment: {filename} ({file_size} bytes) to {save_path}",
                data={
                    "filename": filename,
                    "path": save_path,
                    "size_bytes": file_size,
                },
            )

        except RuntimeError as e:
            log_error(f"Gmail gateway error: {e}")
            return GmailResult(success=False, message=str(e))
        except Exception as e:
            log_error(f"Failed to download attachment: {e}")
            return GmailResult(
                success=False,
                message=f"Failed to download attachment: {str(e)}",
            )

    def manage_email(
        self,
        email_id: str,
        action: str,
    ) -> GmailResult:
        """
        Manage an email: mark read/unread or trash.

        Args:
            email_id: The Gmail message ID
            action: One of "mark_read", "mark_unread", "trash"

        Returns:
            GmailResult with confirmation
        """
        try:
            service = self._get_service()

            if action == "mark_read":
                service.users().messages().modify(
                    userId="me",
                    id=email_id,
                    body={"removeLabelIds": ["UNREAD"]},
                ).execute()
                log_info(f"Marked email as read: {email_id}")
                return GmailResult(
                    success=True,
                    message=f"Marked email as read",
                    data={"email_id": email_id, "action": action},
                )

            elif action == "mark_unread":
                service.users().messages().modify(
                    userId="me",
                    id=email_id,
                    body={"addLabelIds": ["UNREAD"]},
                ).execute()
                log_info(f"Marked email as unread: {email_id}")
                return GmailResult(
                    success=True,
                    message=f"Marked email as unread",
                    data={"email_id": email_id, "action": action},
                )

            elif action == "trash":
                service.users().messages().trash(
                    userId="me",
                    id=email_id,
                ).execute()
                log_info(f"Trashed email: {email_id}")
                return GmailResult(
                    success=True,
                    message=f"Moved email to trash",
                    data={"email_id": email_id, "action": action},
                )

            else:
                return GmailResult(
                    success=False,
                    message=f"Unknown action: {action}. Must be one of: mark_read, mark_unread, trash",
                )

        except RuntimeError as e:
            log_error(f"Gmail gateway error: {e}")
            return GmailResult(success=False, message=str(e))
        except Exception as e:
            log_error(f"Failed to manage email: {e}")
            return GmailResult(
                success=False,
                message=f"Failed to {action} email: {str(e)}",
            )

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _simplify_email_summary(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """
        Simplify a Gmail message metadata response into a summary dict.

        Args:
            msg: Raw message dict from Gmail API (metadata format)

        Returns:
            Simplified summary dict
        """
        labels = msg.get("labelIds", [])

        summary = {
            "email_id": msg.get("id", ""),
            "thread_id": msg.get("threadId", ""),
            "subject": self._get_header(msg, "Subject") or "(no subject)",
            "from": self._get_header(msg, "From") or "",
            "to": self._get_header(msg, "To") or "",
            "date": self._get_header(msg, "Date") or "",
            "snippet": msg.get("snippet", ""),
            "is_unread": "UNREAD" in labels,
        }

        return summary

    def _parse_full_email(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse a full Gmail message into a structured dict.

        Extracts headers, body text, and attachment metadata.

        Args:
            msg: Raw message dict from Gmail API (full format)

        Returns:
            Parsed email dict with body text and attachment list
        """
        labels = msg.get("labelIds", [])
        payload = msg.get("payload", {})

        email_data = {
            "email_id": msg.get("id", ""),
            "thread_id": msg.get("threadId", ""),
            "subject": self._get_header(msg, "Subject") or "(no subject)",
            "from": self._get_header(msg, "From") or "",
            "to": self._get_header(msg, "To") or "",
            "cc": self._get_header(msg, "Cc") or "",
            "date": self._get_header(msg, "Date") or "",
            "is_unread": "UNREAD" in labels,
            "body": "",
            "attachments": [],
        }

        # Extract body and attachments from MIME structure
        body_text = self._extract_body(payload)
        email_data["body"] = body_text

        attachments = self._extract_attachments(payload)
        email_data["attachments"] = attachments

        return email_data

    def _extract_body(self, payload: Dict[str, Any]) -> str:
        """
        Extract plain text body from a MIME payload, recursively.

        Prefers text/plain over text/html. Falls back to HTML with
        basic tag stripping if no plain text part exists.

        Args:
            payload: The message payload dict from Gmail API

        Returns:
            Extracted body text string
        """
        mime_type = payload.get("mimeType", "")
        parts = payload.get("parts", [])

        # Simple single-part message
        if not parts:
            if mime_type == "text/plain":
                data = payload.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            elif mime_type == "text/html":
                data = payload.get("body", {}).get("data", "")
                if data:
                    html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                    return self._strip_html(html)
            return ""

        # Multipart message — look for text/plain first, then text/html
        plain_text = ""
        html_text = ""

        for part in parts:
            part_mime = part.get("mimeType", "")

            if part_mime == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    plain_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            elif part_mime == "text/html":
                data = part.get("body", {}).get("data", "")
                if data:
                    html_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            elif part_mime.startswith("multipart/"):
                # Recurse into nested multipart
                nested = self._extract_body(part)
                if nested:
                    if not plain_text:
                        plain_text = nested

        if plain_text:
            return plain_text
        if html_text:
            return self._strip_html(html_text)
        return ""

    def _extract_attachments(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract attachment metadata from a MIME payload.

        Args:
            payload: The message payload dict from Gmail API

        Returns:
            List of attachment info dicts (filename, id, size, mime_type)
        """
        attachments = []
        parts = payload.get("parts", [])

        for part in parts:
            filename = part.get("filename", "")
            body = part.get("body", {})
            attachment_id = body.get("attachmentId")

            if filename and attachment_id:
                attachments.append({
                    "filename": filename,
                    "attachment_id": attachment_id,
                    "size_bytes": body.get("size", 0),
                    "mime_type": part.get("mimeType", ""),
                })

            # Recurse into nested parts
            if part.get("parts"):
                attachments.extend(self._extract_attachments(part))

        return attachments

    def _create_attachment(self, file_path: str) -> MIMEBase:
        """
        Create a MIME attachment from a file path.

        Args:
            file_path: Path to the file to attach

        Returns:
            MIMEBase object ready to be attached to a message
        """
        import mimetypes

        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            mime_type = "application/octet-stream"

        main_type, sub_type = mime_type.split("/", 1)

        with open(file_path, "rb") as f:
            part = MIMEBase(main_type, sub_type)
            part.set_payload(f.read())

        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=os.path.basename(file_path),
        )
        return part

    @staticmethod
    def _get_header(msg: Dict[str, Any], header_name: str) -> str:
        """
        Get a header value from a Gmail message dict.

        Args:
            msg: Message dict from Gmail API
            header_name: Header name (e.g., "Subject", "From")

        Returns:
            Header value string, or empty string if not found
        """
        headers = msg.get("payload", {}).get("headers", [])
        for h in headers:
            if h.get("name", "").lower() == header_name.lower():
                return h.get("value", "")
        return ""

    @staticmethod
    def _strip_html(html: str) -> str:
        """
        Basic HTML tag stripping for email body fallback.

        Not a full HTML parser — just removes tags and decodes common entities
        to make HTML emails readable as plain text.

        Args:
            html: HTML string

        Returns:
            Text with HTML tags removed
        """
        import re

        # Remove style and script blocks entirely
        text = re.sub(r"<(style|script)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        # Replace <br> and <p> with newlines
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
        # Remove all remaining tags
        text = re.sub(r"<[^>]+>", "", text)
        # Decode common HTML entities
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
        # Collapse multiple newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


# Singleton instance
_gateway: Optional[GmailGateway] = None


def get_gmail_gateway() -> GmailGateway:
    """
    Get the global Gmail gateway instance.

    Returns:
        The global GmailGateway instance

    Raises:
        RuntimeError: If gateway not initialized
    """
    if _gateway is None:
        raise RuntimeError(
            "Gmail gateway not initialized. Call init_gmail_gateway() first."
        )
    return _gateway


def init_gmail_gateway(
    credentials_path: Optional[str] = None,
    token_path: Optional[str] = None,
) -> GmailGateway:
    """
    Initialize the global Gmail gateway instance.

    Args:
        credentials_path: Path to OAuth2 credentials JSON (defaults to config)
        token_path: Path to save/load OAuth2 token (defaults to config)

    Returns:
        The initialized GmailGateway instance
    """
    global _gateway

    from config import (
        GMAIL_CREDENTIALS_PATH,
        GMAIL_TOKEN_PATH,
    )

    _gateway = GmailGateway(
        credentials_path=credentials_path or GMAIL_CREDENTIALS_PATH,
        token_path=token_path or GMAIL_TOKEN_PATH,
    )

    if _gateway.is_available():
        log_info("Gmail gateway initialized")
    else:
        log_warning(
            "Gmail gateway initialized but credentials not found at "
            f"{_gateway.credentials_path}"
        )

    return _gateway
