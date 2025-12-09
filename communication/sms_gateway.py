"""
Pattern Project - SMS Gateway
SMS sending via carrier email gateway (Email-to-SMS).

This module sends SMS messages by routing them through carrier-specific
email gateways (e.g., 1234567890@txt.att.net for AT&T).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from core.logger import log_info, log_error, log_warning
from communication.email_gateway import EmailGateway, GatewayResult


# Carrier gateway domain mappings
# These are the email domains used by carriers for SMS delivery
CARRIER_GATEWAYS = {
    "att": "txt.att.net",
    "verizon": "vtext.com",
    "tmobile": "tmomail.net",
    "sprint": "messaging.sprintpcs.com",
    "uscellular": "email.uscc.net",
    "virgin": "vmobl.com",
    "metro": "mymetropcs.com",
    "boost": "sms.myboostmobile.com",
    "cricket": "sms.cricketwireless.net",
}


class SMSGateway:
    """
    SMS gateway using carrier email-to-SMS functionality.

    Sends SMS messages by converting them to emails addressed to
    carrier-specific gateway domains (e.g., phonenumber@txt.att.net).
    """

    def __init__(
        self,
        email_gateway: EmailGateway,
        recipient_phone: str,
        carrier_gateway: str = "txt.att.net",
        max_length: int = 160,
    ):
        """
        Initialize the SMS gateway.

        Args:
            email_gateway: EmailGateway instance for transport
            recipient_phone: Whitelisted phone number (10 digits, no formatting)
            carrier_gateway: Carrier's SMS gateway domain
            max_length: Maximum SMS length before truncation
        """
        self.email_gateway = email_gateway
        self.recipient_phone = self._normalize_phone(recipient_phone)
        self.carrier_gateway = carrier_gateway
        self.max_length = max_length

    def _normalize_phone(self, phone: str) -> str:
        """
        Normalize phone number to 10 digits.

        Args:
            phone: Phone number (may include formatting)

        Returns:
            10-digit phone number string
        """
        # Strip everything except digits
        digits = ''.join(c for c in phone if c.isdigit())

        # Handle 11-digit numbers starting with 1 (US country code)
        if len(digits) == 11 and digits.startswith('1'):
            digits = digits[1:]

        return digits

    def is_available(self) -> bool:
        """
        Check if the gateway is properly configured.

        Returns:
            True if email gateway is available and phone is configured
        """
        return (
            self.email_gateway.is_available() and
            bool(self.recipient_phone) and
            len(self.recipient_phone) == 10
        )

    def send(self, message: str) -> GatewayResult:
        """
        Send an SMS message to the whitelisted recipient.

        Args:
            message: Text message content

        Returns:
            GatewayResult with success/failure info
        """
        timestamp = datetime.now()

        # Check configuration
        if not self.email_gateway.is_available():
            log_error("SMS gateway unavailable - email gateway not configured")
            return GatewayResult(
                success=False,
                message="SMS gateway not configured. Check email credentials.",
                recipient=self.recipient_phone,
                timestamp=timestamp
            )

        if not self.recipient_phone:
            log_error("SMS gateway unavailable - no recipient phone configured")
            return GatewayResult(
                success=False,
                message="No SMS recipient configured. Check APP_SMS_RECIPIENT_PHONE.",
                recipient="",
                timestamp=timestamp
            )

        if len(self.recipient_phone) != 10:
            log_error(f"Invalid phone number length: {len(self.recipient_phone)}")
            return GatewayResult(
                success=False,
                message=f"Invalid phone number: must be 10 digits, got {len(self.recipient_phone)}",
                recipient=self.recipient_phone,
                timestamp=timestamp
            )

        # Check and handle message length
        original_length = len(message)
        truncated = False

        if original_length > self.max_length:
            message = message[:self.max_length - 3] + "..."
            truncated = True
            log_warning(
                f"SMS truncated from {original_length} to {self.max_length} chars"
            )

        # Construct the carrier gateway email address
        sms_email = f"{self.recipient_phone}@{self.carrier_gateway}"

        log_info(f"Sending SMS via {sms_email}")

        # Send via email gateway (empty subject for SMS)
        result = self.email_gateway.send(
            recipient=sms_email,
            subject="",
            body=message,
            is_sms=True
        )

        # Enhance result message if truncated
        if result.success and truncated:
            result.message = f"SMS sent (truncated from {original_length} to {self.max_length} chars)"

        return result


# Singleton instance
_gateway: Optional[SMSGateway] = None


def get_sms_gateway() -> SMSGateway:
    """
    Get the global SMS gateway instance.

    Lazily initializes the gateway if not already initialized.

    Returns:
        The global SMSGateway instance
    """
    global _gateway
    if _gateway is None:
        # Lazy initialization - same pattern as other gateway getters
        _gateway = init_sms_gateway()
    return _gateway


def init_sms_gateway(
    email_gateway: Optional[EmailGateway] = None,
    recipient_phone: Optional[str] = None,
    carrier_gateway: Optional[str] = None,
) -> SMSGateway:
    """
    Initialize the global SMS gateway instance.

    Args:
        email_gateway: EmailGateway instance (defaults to global)
        recipient_phone: Recipient phone number (defaults to config)
        carrier_gateway: Carrier gateway domain (defaults to config)

    Returns:
        The initialized SMSGateway instance
    """
    global _gateway

    # Import config values as defaults
    from config import (
        SMS_RECIPIENT_PHONE,
        SMS_CARRIER_GATEWAY,
        SMS_MAX_LENGTH,
    )

    # Get email gateway if not provided
    if email_gateway is None:
        from communication.email_gateway import get_email_gateway
        try:
            email_gateway = get_email_gateway()
        except RuntimeError:
            # Email gateway not initialized yet - this will be handled later
            from communication.email_gateway import init_email_gateway
            email_gateway = init_email_gateway()

    _gateway = SMSGateway(
        email_gateway=email_gateway,
        recipient_phone=recipient_phone or SMS_RECIPIENT_PHONE,
        carrier_gateway=carrier_gateway or SMS_CARRIER_GATEWAY,
        max_length=SMS_MAX_LENGTH,
    )

    if _gateway.is_available():
        log_info(f"SMS gateway initialized (recipient: {_gateway.recipient_phone})")
    else:
        log_warning("SMS gateway initialized but not fully configured")

    return _gateway
