"""
Pattern Project - Telegram Gateway
Telegram Bot API for bidirectional messaging.

This module sends messages via the Telegram Bot API, replacing
the legacy SMS-via-carrier-gateway approach.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from telegram import Bot
from telegram.error import TelegramError

from core.logger import log_info, log_error, log_warning, log_success


@dataclass
class TelegramResult:
    """
    Result from a Telegram send operation.

    Attributes:
        success: Whether the send succeeded
        message: Status message (success info or error description)
        chat_id: The chat ID the message was sent to
        message_id: Telegram's message ID (for replies/edits)
        timestamp: When the operation occurred
    """
    success: bool
    message: str
    chat_id: str
    message_id: Optional[int] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def __str__(self) -> str:
        status = "Success" if self.success else "Failed"
        return f"{status}: {self.message}"


class TelegramGateway:
    """
    Telegram gateway using the Bot API.

    Sends messages to a specific chat via the Telegram Bot API.
    Supports plain text messages with optional markdown formatting.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str = "",
    ):
        """
        Initialize the Telegram gateway.

        Args:
            bot_token: Telegram Bot API token from @BotFather
            chat_id: Target chat ID (can be set later via auto-detection)
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._bot: Optional[Bot] = None

    def _get_bot(self) -> Bot:
        """Get or create the Bot instance."""
        if self._bot is None:
            self._bot = Bot(token=self.bot_token)
        return self._bot

    def is_available(self) -> bool:
        """
        Check if the gateway is properly configured.

        Returns:
            True if token and chat_id are present
        """
        return bool(self.bot_token and self.chat_id)

    def set_chat_id(self, chat_id: str) -> None:
        """
        Set or update the target chat ID.

        Args:
            chat_id: The Telegram chat ID to send messages to
        """
        self.chat_id = str(chat_id)
        log_info(f"Telegram chat ID set to: {self.chat_id}")

    async def _send_async(
        self,
        message: str,
        parse_mode: Optional[str] = None,
        bot: Optional[Bot] = None
    ) -> TelegramResult:
        """
        Send a message asynchronously.

        Args:
            message: Text message content
            parse_mode: Optional parse mode ('Markdown' or 'HTML')
            bot: Optional Bot instance to use (if None, uses self._get_bot())

        Returns:
            TelegramResult with send status
        """
        timestamp = datetime.now()

        if not self.bot_token:
            log_error("Telegram gateway unavailable - no bot token configured")
            return TelegramResult(
                success=False,
                message="Telegram bot token not configured. Check telegram_bot env var.",
                chat_id="",
                timestamp=timestamp
            )

        if not self.chat_id:
            log_error("Telegram gateway unavailable - no chat ID configured")
            return TelegramResult(
                success=False,
                message="Telegram chat ID not configured. Send a message to your bot first.",
                chat_id="",
                timestamp=timestamp
            )

        try:
            # Use provided bot or get/create our own
            send_bot = bot if bot is not None else self._get_bot()
            result = await send_bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=parse_mode
            )

            log_success(f"Telegram message sent to {self.chat_id}")

            # Log to database
            self._log_to_database(
                recipient=self.chat_id,
                body=message,
                status="sent"
            )

            return TelegramResult(
                success=True,
                message="Message sent successfully",
                chat_id=self.chat_id,
                message_id=result.message_id,
                timestamp=timestamp
            )

        except TelegramError as e:
            log_error(f"Telegram API error: {e}")
            self._log_to_database(
                recipient=self.chat_id,
                body=message,
                status="failed",
                error_message=f"Telegram API error: {str(e)}"
            )
            return TelegramResult(
                success=False,
                message=f"Telegram API error: {str(e)}",
                chat_id=self.chat_id,
                timestamp=timestamp
            )

        except Exception as e:
            log_error(f"Unexpected error sending Telegram message: {e}")
            self._log_to_database(
                recipient=self.chat_id,
                body=message,
                status="failed",
                error_message=f"Unexpected error: {str(e)}"
            )
            return TelegramResult(
                success=False,
                message=f"Failed to send: {str(e)}",
                chat_id=self.chat_id,
                timestamp=timestamp
            )

    def send(self, message: str, parse_mode: Optional[str] = None) -> TelegramResult:
        """
        Send a message to the configured chat.

        Uses the TelegramListener's shared event loop and Bot instance
        when available to avoid connection pool exhaustion.

        Args:
            message: Text message content
            parse_mode: Optional parse mode ('Markdown' or 'HTML')

        Returns:
            TelegramResult with send status
        """
        # Try to use the listener's shared event loop and Bot
        future = None
        listener_loop = None
        shared_bot = None

        try:
            from communication.telegram_listener import get_telegram_listener
            listener = get_telegram_listener()

            if listener.is_running():
                # Get the listener's bot and loop - don't store in self._bot yet
                # to avoid event loop mismatch if we need to fall back
                shared_bot = listener.get_bot()
                listener_loop = listener.get_event_loop()

                if listener_loop and not listener_loop.is_closed():
                    # Schedule the coroutine on the listener's event loop
                    # Pass the bot directly to avoid storing it in self._bot
                    future = asyncio.run_coroutine_threadsafe(
                        self._send_async(message, parse_mode, bot=shared_bot),
                        listener_loop
                    )

                    # Wait for result with timeout
                    return future.result(timeout=30.0)

        except Exception as e:
            # If we scheduled a coroutine but waiting for result failed,
            # cancel it to prevent duplicate sends when we fall back
            if future is not None:
                future.cancel()
                # Give it a moment to cancel
                try:
                    future.result(timeout=0.5)
                except Exception:
                    pass  # Expected - either cancelled or already done
            log_warning(f"Could not use shared Telegram listener: {e}")

        # Fallback: create a temporary event loop with proper cleanup
        # This handles the case where the listener isn't running yet
        #
        # CRITICAL: Use a local Bot instance to avoid race conditions.
        # Multiple threads could enter this fallback simultaneously, and
        # sharing self._bot would cause them to clobber each other's instances.

        loop = asyncio.new_event_loop()
        local_bot = None
        try:
            asyncio.set_event_loop(loop)

            # Create a local Bot instance for this event loop only
            local_bot = Bot(token=self.bot_token)

            # Use asyncio.wait_for to enforce a timeout and prevent indefinite blocking
            result = loop.run_until_complete(
                asyncio.wait_for(
                    self._send_async(message, parse_mode, bot=local_bot),
                    timeout=30.0
                )
            )

            # Properly shut down the local bot to avoid "Event loop is closed" errors
            if local_bot:
                try:
                    loop.run_until_complete(local_bot.shutdown())
                except Exception:
                    pass  # Ignore shutdown errors

            return result
        finally:
            try:
                loop.close()
            except Exception:
                pass

    def _log_to_database(
        self,
        recipient: str,
        body: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Log communication to database.

        Args:
            recipient: Chat ID
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
                    "telegram",
                    recipient,
                    None,  # No subject for Telegram
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
_gateway: Optional[TelegramGateway] = None


def get_telegram_gateway() -> TelegramGateway:
    """
    Get the global Telegram gateway instance.

    Lazily initializes the gateway if not already initialized.

    Returns:
        The global TelegramGateway instance
    """
    global _gateway
    if _gateway is None:
        _gateway = init_telegram_gateway()
    return _gateway


def init_telegram_gateway(
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> TelegramGateway:
    """
    Initialize the global Telegram gateway instance.

    Args:
        bot_token: Bot API token (defaults to config)
        chat_id: Target chat ID (defaults to config or database)

    Returns:
        The initialized TelegramGateway instance
    """
    global _gateway

    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

    # Try to load chat_id from database if not in config
    effective_chat_id = chat_id or TELEGRAM_CHAT_ID
    if not effective_chat_id:
        try:
            from core.database import get_database
            db = get_database()
            saved_id = db.get_state("telegram_chat_id")
            if saved_id:
                effective_chat_id = saved_id
                log_info(f"Loaded Telegram chat ID from database: {effective_chat_id}")
        except Exception:
            pass  # Database might not be initialized yet

    _gateway = TelegramGateway(
        bot_token=bot_token or TELEGRAM_BOT_TOKEN,
        chat_id=effective_chat_id,
    )

    if _gateway.is_available():
        log_info(f"Telegram gateway initialized (chat: {_gateway.chat_id})")
    elif _gateway.bot_token:
        log_warning("Telegram gateway initialized - waiting for chat ID (send a message to the bot)")
    else:
        log_warning("Telegram gateway initialized but not configured (missing bot token)")

    return _gateway
