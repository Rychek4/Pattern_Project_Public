"""
Simple TTS player using ElevenLabs.

No subprocess, no Flask server - just a background thread.
"""

import os
import threading
from typing import Optional

import config
from core.logger import log_info, log_warning, log_error


class TTSPlayer:
    """Threaded TTS player using ElevenLabs."""

    def __init__(self):
        self._client = None
        self._playback_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _get_client(self):
        """Lazy-load ElevenLabs client."""
        if self._client is None:
            api_key = os.getenv("Eleven_Labs_API")
            if api_key:
                try:
                    from elevenlabs.client import ElevenLabs
                    self._client = ElevenLabs(api_key=api_key)
                    log_info("ElevenLabs client initialized", prefix="🔊")
                except ImportError:
                    log_error("elevenlabs package not installed")
            else:
                log_warning("Eleven_Labs_API environment variable not set")
        return self._client

    def play(self, text: str, voice_id: Optional[str] = None) -> bool:
        """
        Play text as speech. Non-blocking.

        Args:
            text: Text to speak
            voice_id: Optional voice ID (uses default from config if not specified)

        Returns:
            True if playback started, False if failed
        """
        client = self._get_client()
        if not client:
            return False

        voice = voice_id or config.ELEVENLABS_DEFAULT_VOICE_ID

        # Run in background thread
        with self._lock:
            self._playback_thread = threading.Thread(
                target=self._play_audio,
                args=(text, voice),
                daemon=True
            )
            self._playback_thread.start()

        return True

    def _play_audio(self, text: str, voice_id: str):
        """Internal: Generate and stream audio."""
        try:
            from elevenlabs import stream

            preview = text[:50] + "..." if len(text) > 50 else text
            log_info(f"TTS playing: {preview}", prefix="🔊")

            audio = self._client.generate(
                text=text,
                voice=voice_id,
                model=config.ELEVENLABS_MODEL,
                stream=True
            )
            stream(audio)

            log_info("TTS playback complete", prefix="🔊")

        except Exception as e:
            log_error(f"TTS playback failed: {e}")

    def stop(self):
        """Stop current playback (best effort - clears state)."""
        with self._lock:
            self._playback_thread = None

    @staticmethod
    def is_available() -> bool:
        """Check if TTS dependencies are available."""
        # Check for elevenlabs
        try:
            from elevenlabs.client import ElevenLabs
            from elevenlabs import stream
        except ImportError:
            return False

        # Check for audio backend
        try:
            import sounddevice
        except ImportError:
            try:
                import pyaudio
            except ImportError:
                return False

        # Check for API key
        if not os.getenv("Eleven_Labs_API"):
            return False

        return True


# Global instance
_player: Optional[TTSPlayer] = None


def get_tts_player() -> TTSPlayer:
    """Get the global TTS player instance."""
    global _player
    if _player is None:
        _player = TTSPlayer()
    return _player


def play_tts(text: str, voice_id: Optional[str] = None) -> bool:
    """
    Play text as speech. Main entry point.

    Args:
        text: Text to speak
        voice_id: Optional voice ID

    Returns:
        True if playback started
    """
    return get_tts_player().play(text, voice_id)


def stop_tts():
    """Stop current TTS playback."""
    get_tts_player().stop()


def is_tts_available() -> bool:
    """Check if TTS is available (dependencies + API key)."""
    return TTSPlayer.is_available()
