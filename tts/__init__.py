"""TTS (Text-to-Speech) module."""

from tts.player import play_tts, stop_tts, is_tts_available, get_tts_player, shutdown_tts

__all__ = ["play_tts", "stop_tts", "is_tts_available", "get_tts_player", "shutdown_tts"]
