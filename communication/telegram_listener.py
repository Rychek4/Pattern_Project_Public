"""
Pattern Project - Telegram Listener
Background polling for inbound Telegram messages.

This module polls the Telegram Bot API for new messages from the user
and triggers AI responses when messages arrive.
"""

import asyncio
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable, List

from telegram import Bot, Update
from telegram.error import TelegramError

from core.logger import log_info, log_error, log_warning, log_success


@dataclass
class InboundMessage:
    """
    Represents an inbound message from Telegram.

    Attributes:
        text: The message text
        chat_id: The chat this message came from
        message_id: Telegram's message ID
        timestamp: When the message was received
        from_user: Username or first name of sender
    """
    text: str
    chat_id: str
    message_id: int
    timestamp: datetime
    from_user: str


class TelegramListener:
    """
    Background listener for inbound Telegram messages.

    Polls the Telegram Bot API for new messages and invokes
    a callback when messages are received. Also handles
    auto-detection of chat ID on first message.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str = "",
        poll_interval: float = 2.0,
    ):
        """
        Initialize the Telegram listener.

        Args:
            bot_token: Telegram Bot API token
            chat_id: Expected chat ID (for filtering)
            poll_interval: Seconds between polls
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.poll_interval = poll_interval

        self._bot: Optional[Bot] = None
        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._callback: Optional[Callable[[InboundMessage], None]] = None
        self._chat_id_callback: Optional[Callable[[str], None]] = None
        self._last_update_id: int = 0
        self._lock = threading.Lock()

    def _get_bot(self) -> Bot:
        """Get or create the Bot instance."""
        if self._bot is None:
            self._bot = Bot(token=self.bot_token)
        return self._bot

    def get_bot(self) -> Bot:
        """
        Get the shared Bot instance.

        Returns:
            The Bot instance used by this listener
        """
        return self._get_bot()

    def get_event_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """
        Get the listener's event loop.

        Returns:
            The event loop if running, None otherwise
        """
        return self._loop if self._running else None

    def run_coroutine(self, coro, timeout: float = 30.0):
        """
        Run a coroutine in the listener's event loop (thread-safe).

        This allows other threads (e.g., the main thread) to execute
        async operations using this listener's event loop and Bot.

        Args:
            coro: The coroutine to run
            timeout: Maximum seconds to wait for result

        Returns:
            The coroutine's result

        Raises:
            RuntimeError: If the listener is not running
            TimeoutError: If the operation times out
        """
        if not self._loop or not self._running:
            raise RuntimeError("Telegram listener is not running")

        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def set_callback(self, callback: Callable[[InboundMessage], None]) -> None:
        """
        Set the callback for inbound messages.

        Args:
            callback: Function to call with InboundMessage when received
        """
        self._callback = callback

    def set_chat_id_callback(self, callback: Callable[[str], None]) -> None:
        """
        Set the callback for chat ID auto-detection.

        Args:
            callback: Function to call with chat_id when detected
        """
        self._chat_id_callback = callback

    def set_chat_id(self, chat_id: str) -> None:
        """
        Update the expected chat ID.

        Args:
            chat_id: The chat ID to accept messages from
        """
        with self._lock:
            self.chat_id = str(chat_id)

    async def _poll_once(self) -> List[InboundMessage]:
        """
        Poll for new messages once.

        Returns:
            List of new InboundMessage objects
        """
        messages = []

        try:
            bot = self._get_bot()

            # Get updates since last check
            updates = await bot.get_updates(
                offset=self._last_update_id + 1,
                timeout=1,
                allowed_updates=["message"]
            )

            for update in updates:
                # Update the offset to acknowledge this update
                self._last_update_id = update.update_id

                # Skip if no message
                if not update.message or not update.message.text:
                    continue

                msg = update.message
                chat_id = str(msg.chat.id)

                # Auto-detect chat ID if not set
                if not self.chat_id:
                    log_info(f"Auto-detected Telegram chat ID: {chat_id}")
                    with self._lock:
                        self.chat_id = chat_id

                    # Notify via callback
                    if self._chat_id_callback:
                        self._chat_id_callback(chat_id)

                    # Save to config/state
                    self._save_chat_id(chat_id)

                # Filter to only accept messages from expected chat
                if self.chat_id and chat_id != self.chat_id:
                    log_warning(f"Ignoring message from unexpected chat: {chat_id}")
                    continue

                # Get sender info
                from_user = ""
                if msg.from_user:
                    from_user = msg.from_user.username or msg.from_user.first_name or ""

                inbound = InboundMessage(
                    text=msg.text,
                    chat_id=chat_id,
                    message_id=msg.message_id,
                    timestamp=msg.date or datetime.now(),
                    from_user=from_user
                )
                messages.append(inbound)

        except TelegramError as e:
            log_error(f"Telegram polling error: {e}")
        except Exception as e:
            log_error(f"Unexpected error polling Telegram: {e}")

        return messages

    def _save_chat_id(self, chat_id: str) -> None:
        """
        Save the auto-detected chat ID to database state.

        Args:
            chat_id: The detected chat ID
        """
        try:
            from core.database import get_database
            db = get_database()
            db.set_state("telegram_chat_id", chat_id)
            log_success(f"Saved Telegram chat ID to database: {chat_id}")
        except Exception as e:
            log_warning(f"Failed to save chat ID to database: {e}")

    def _poll_loop(self) -> None:
        """Background polling loop with persistent event loop."""
        # Create ONE persistent event loop for this thread
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        log_info("Telegram listener started")

        try:
            while self._running:
                if self._paused:
                    time.sleep(0.5)
                    continue

                try:
                    # Use the persistent loop instead of asyncio.run()
                    messages = self._loop.run_until_complete(self._poll_once())

                    # Process each message
                    for msg in messages:
                        log_info(f"Received Telegram message from {msg.from_user}: {msg.text[:50]}...")

                        if self._callback:
                            try:
                                self._callback(msg)
                            except Exception as e:
                                log_error(f"Error in message callback: {e}")

                except Exception as e:
                    log_error(f"Error in poll loop: {e}")

                # Wait before next poll
                time.sleep(self.poll_interval)
        finally:
            # Clean up the Bot's HTTP session
            if self._bot:
                try:
                    self._loop.run_until_complete(self._bot.shutdown())
                except Exception as e:
                    log_warning(f"Error shutting down Telegram bot: {e}")

            # Close the event loop
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None

        log_info("Telegram listener stopped")

    def start(self) -> None:
        """Start the background polling thread."""
        if self._running:
            return

        if not self.bot_token:
            log_warning("Cannot start Telegram listener - no bot token configured")
            return

        self._running = True
        self._paused = False
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background polling thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def pause(self) -> None:
        """Pause polling (listener stays running but doesn't poll)."""
        self._paused = True

    def resume(self) -> None:
        """Resume polling after pause."""
        self._paused = False

    def is_running(self) -> bool:
        """Check if the listener is running."""
        return self._running and self._thread is not None and self._thread.is_alive()

    def get_stats(self) -> dict:
        """
        Get listener statistics.

        Returns:
            Dict with current status
        """
        return {
            "running": self._running,
            "paused": self._paused,
            "chat_id": self.chat_id,
            "poll_interval": self.poll_interval,
            "last_update_id": self._last_update_id,
            "has_callback": self._callback is not None,
        }


# Singleton instance
_listener: Optional[TelegramListener] = None


def get_telegram_listener() -> TelegramListener:
    """
    Get the global Telegram listener instance.

    Returns:
        The global TelegramListener instance
    """
    global _listener
    if _listener is None:
        _listener = init_telegram_listener()
    return _listener


def init_telegram_listener(
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    poll_interval: Optional[float] = None,
) -> TelegramListener:
    """
    Initialize the global Telegram listener instance.

    Args:
        bot_token: Bot API token (defaults to config)
        chat_id: Target chat ID (defaults to config or database)
        poll_interval: Seconds between polls (defaults to config)

    Returns:
        The initialized TelegramListener instance
    """
    global _listener

    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_POLL_INTERVAL

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

    _listener = TelegramListener(
        bot_token=bot_token or TELEGRAM_BOT_TOKEN,
        chat_id=effective_chat_id,
        poll_interval=poll_interval or TELEGRAM_POLL_INTERVAL,
    )

    return _listener
