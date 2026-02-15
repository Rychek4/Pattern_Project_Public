"""
Pattern Project - Email Gateway
SMTP-based email sending via Gmail.

This module provides the underlying email transport used by both
direct email sending and SMS-via-carrier-gateway functionality.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from core.logger import log_info, log_error, log_success, log_warning


@dataclass
class GatewayResult:
    """
    Result from a gateway send operation.

    Attributes:
        success: Whether the send succeeded
        message: Status message (success info or error description)
        recipient: The recipient address
        timestamp: When the operation occurred
    """
    success: bool
    message: str
    recipient: str
    timestamp: datetime

    def __str__(self) -> str:
        status = "Success" if self.success else "Failed"
        return f"{status}: {self.message}"


class EmailGateway:
    """
    Email gateway using Gmail SMTP.

    Sends emails via Gmail's SMTP server using app password authentication.
    This gateway is used both for direct email and as transport for SMS
    via carrier gateways.
    """

    def __init__(
        self,
        email_address: str,
        email_password: str,
        display_name: str = "Pattern Isaac",
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
    ):
        """
        Initialize the email gateway.

        Args:
            email_address: Gmail address to send from
            email_password: Gmail app password
            display_name: Display name for the From header
            smtp_host: SMTP server hostname
            smtp_port: SMTP server port (587 for TLS)
        """
        self.email_address = email_address
        self.email_password = email_password
        self.display_name = display_name
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port

    def is_available(self) -> bool:
        """
        Check if the gateway is properly configured.

        Returns:
            True if credentials are present, False otherwise
        """
        return bool(self.email_address and self.email_password)

    def send(
        self,
        recipient: str,
        subject: str,
        body: str,
        is_sms: bool = False,
    ) -> GatewayResult:
        """
        Send an email.

        Args:
            recipient: Recipient email address
            subject: Email subject (empty for SMS)
            body: Email body content
            is_sms: Whether this is an SMS-via-gateway message

        Returns:
            GatewayResult with success/failure info
        """
        timestamp = datetime.now()

        # Check configuration
        if not self.is_available():
            log_error("Email gateway not configured - missing credentials")
            return GatewayResult(
                success=False,
                message="Email gateway not configured. Check APP_EMAIL_ADDRESS and APP_EMAIL_PASS.",
                recipient=recipient,
                timestamp=timestamp
            )

        try:
            # Create message
            if is_sms:
                # SMS-via-gateway: plain text, no subject
                msg = MIMEText(body, 'plain')
                msg['Subject'] = ""
            else:
                # Regular email
                msg = MIMEMultipart('alternative')
                msg['Subject'] = subject
                msg.attach(MIMEText(body, 'plain'))

            # Set headers
            msg['From'] = f"{self.display_name} <{self.email_address}>"
            msg['To'] = recipient

            # Connect and send
            log_info(f"Connecting to SMTP server {self.smtp_host}:{self.smtp_port}")

            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.starttls()
                server.login(self.email_address, self.email_password)
                server.send_message(msg)

            msg_type = "SMS" if is_sms else "Email"
            log_success(f"{msg_type} sent to {recipient}")

            # Log to database
            self._log_to_database(
                msg_type="sms" if is_sms else "email",
                recipient=recipient,
                subject=subject if not is_sms else None,
                body=body,
                status="sent"
            )

            return GatewayResult(
                success=True,
                message=f"{msg_type} sent successfully",
                recipient=recipient,
                timestamp=timestamp
            )

        except smtplib.SMTPAuthenticationError as e:
            log_error(f"SMTP authentication failed: {e}")
            self._log_to_database(
                msg_type="sms" if is_sms else "email",
                recipient=recipient,
                subject=subject if not is_sms else None,
                body=body,
                status="failed",
                error_message=f"Authentication failed: {str(e)}"
            )
            return GatewayResult(
                success=False,
                message="Authentication failed. Check your Gmail app password.",
                recipient=recipient,
                timestamp=timestamp
            )

        except smtplib.SMTPRecipientsRefused as e:
            log_error(f"Recipient refused: {recipient}")
            self._log_to_database(
                msg_type="sms" if is_sms else "email",
                recipient=recipient,
                subject=subject if not is_sms else None,
                body=body,
                status="failed",
                error_message=f"Recipient refused: {str(e)}"
            )
            return GatewayResult(
                success=False,
                message=f"Recipient address rejected: {recipient}",
                recipient=recipient,
                timestamp=timestamp
            )

        except smtplib.SMTPException as e:
            log_error(f"SMTP error: {e}")
            self._log_to_database(
                msg_type="sms" if is_sms else "email",
                recipient=recipient,
                subject=subject if not is_sms else None,
                body=body,
                status="failed",
                error_message=f"SMTP error: {str(e)}"
            )
            return GatewayResult(
                success=False,
                message=f"SMTP error: {str(e)}",
                recipient=recipient,
                timestamp=timestamp
            )

        except Exception as e:
            log_error(f"Unexpected error sending email: {e}")
            self._log_to_database(
                msg_type="sms" if is_sms else "email",
                recipient=recipient,
                subject=subject if not is_sms else None,
                body=body,
                status="failed",
                error_message=f"Unexpected error: {str(e)}"
            )
            return GatewayResult(
                success=False,
                message=f"Failed to send: {str(e)}",
                recipient=recipient,
                timestamp=timestamp
            )

    def _log_to_database(
        self,
        msg_type: str,
        recipient: str,
        subject: Optional[str],
        body: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Log communication to database.

        Args:
            msg_type: 'email' or 'sms'
            recipient: Recipient address
            subject: Email subject (None for SMS)
            body: Message body
            status: 'sent' or 'failed'
            error_message: Error details if failed
        """
        try:
            from core.database import get_database

            db = get_database()
            db.execute(
                """
                INSERT INTO communication_log
                (type, recipient, subject, body, status, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg_type,
                    recipient,
                    subject,
                    body,
                    status,
                    error_message,
                    datetime.now().isoformat()
                )
            )
        except Exception as e:
            # Don't let logging failures break the send operation
            log_warning(f"Failed to log communication to database: {e}")


# Singleton instance
_gateway: Optional[EmailGateway] = None


def get_email_gateway() -> EmailGateway:
    """
    Get the global email gateway instance.

    Returns:
        The global EmailGateway instance

    Raises:
        RuntimeError: If gateway not initialized
    """
    if _gateway is None:
        raise RuntimeError("Email gateway not initialized. Call init_email_gateway() first.")
    return _gateway


def init_email_gateway(
    email_address: Optional[str] = None,
    email_password: Optional[str] = None,
    display_name: Optional[str] = None,
) -> EmailGateway:
    """
    Initialize the global email gateway instance.

    Args:
        email_address: Gmail address (defaults to config)
        email_password: Gmail app password (defaults to config)
        display_name: From display name (defaults to config)

    Returns:
        The initialized EmailGateway instance
    """
    global _gateway

    # Import config values as defaults
    from config import (
        EMAIL_ADDRESS,
        EMAIL_PASSWORD,
        EMAIL_DISPLAY_NAME,
        EMAIL_SMTP_HOST,
        EMAIL_SMTP_PORT,
    )

    _gateway = EmailGateway(
        email_address=email_address or EMAIL_ADDRESS,
        email_password=email_password or EMAIL_PASSWORD,
        display_name=display_name or EMAIL_DISPLAY_NAME,
        smtp_host=EMAIL_SMTP_HOST,
        smtp_port=EMAIL_SMTP_PORT,
    )

    if _gateway.is_available():
        log_info("Email gateway initialized")
    else:
        log_warning("Email gateway initialized but credentials not configured")

    return _gateway
