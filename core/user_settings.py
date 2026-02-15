"""
Pattern Project - User Settings Manager

Handles persistent user preferences that can be changed at runtime.
Settings are stored in a JSON file in the data directory.
"""

import json
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, asdict
import threading

import config
from core.logger import log_info, log_warning, log_error


@dataclass
class TTSSettings:
    """Text-to-speech settings."""
    enabled: bool = False
    voice_id: str = ""  # Empty means use default from config

    def get_voice_id(self) -> str:
        """Get voice ID, falling back to config default if not set."""
        return self.voice_id if self.voice_id else config.ELEVENLABS_DEFAULT_VOICE_ID


@dataclass
class UserSettings:
    """All user-configurable settings."""
    tts: TTSSettings = None
    font_size: int = 12
    conversation_model: str = "claude-sonnet-4-5-20250929"  # Default to Sonnet for first-time users
    thinking_enabled: bool = True  # Extended thinking on by default

    def __post_init__(self):
        if self.tts is None:
            self.tts = TTSSettings()


class UserSettingsManager:
    """
    Manages loading, saving, and accessing user settings.

    Thread-safe singleton that persists settings to JSON.
    """

    _instance: Optional["UserSettingsManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._settings_path: Path = config.USER_SETTINGS_PATH
        self._settings: UserSettings = UserSettings()
        self._file_lock = threading.Lock()

        # Ensure data directory exists
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing settings
        self._load()
        self._initialized = True

    def _load(self) -> None:
        """Load settings from disk."""
        try:
            if self._settings_path.exists():
                with open(self._settings_path, 'r') as f:
                    data = json.load(f)

                # Parse TTS settings
                tts_data = data.get('tts', {})
                self._settings.tts = TTSSettings(
                    enabled=tts_data.get('enabled', False),
                    voice_id=tts_data.get('voice_id', '')
                )

                # Parse other settings
                self._settings.font_size = data.get('font_size', 12)
                self._settings.conversation_model = data.get('conversation_model', 'claude-sonnet-4-5-20250929')
                self._settings.thinking_enabled = data.get('thinking_enabled', config.ANTHROPIC_THINKING_ENABLED)

                log_info("User settings loaded", prefix="⚙️")
        except json.JSONDecodeError as e:
            log_warning(f"Invalid settings file, using defaults: {e}")
        except Exception as e:
            log_error(f"Failed to load settings: {e}")

    def _save(self) -> None:
        """Save settings to disk."""
        with self._file_lock:
            try:
                data = {
                    'tts': {
                        'enabled': self._settings.tts.enabled,
                        'voice_id': self._settings.tts.voice_id
                    },
                    'font_size': self._settings.font_size,
                    'conversation_model': self._settings.conversation_model,
                    'thinking_enabled': self._settings.thinking_enabled
                }

                with open(self._settings_path, 'w') as f:
                    json.dump(data, f, indent=2)

            except Exception as e:
                log_error(f"Failed to save settings: {e}")

    @property
    def tts_enabled(self) -> bool:
        """Check if TTS is enabled."""
        return self._settings.tts.enabled

    @tts_enabled.setter
    def tts_enabled(self, value: bool) -> None:
        """Set TTS enabled state."""
        self._settings.tts.enabled = value
        self._save()

    @property
    def tts_voice_id(self) -> str:
        """Get the TTS voice ID."""
        return self._settings.tts.get_voice_id()

    @tts_voice_id.setter
    def tts_voice_id(self, value: str) -> None:
        """Set the TTS voice ID."""
        self._settings.tts.voice_id = value
        self._save()

    @property
    def font_size(self) -> int:
        """Get font size."""
        return self._settings.font_size

    @font_size.setter
    def font_size(self, value: int) -> None:
        """Set font size."""
        self._settings.font_size = value
        self._save()

    @property
    def conversation_model(self) -> str:
        """Get the conversation model."""
        return self._settings.conversation_model

    @conversation_model.setter
    def conversation_model(self, value: str) -> None:
        """Set the conversation model."""
        self._settings.conversation_model = value
        self._save()

    @property
    def thinking_enabled(self) -> bool:
        """Check if extended thinking is enabled."""
        return self._settings.thinking_enabled

    @thinking_enabled.setter
    def thinking_enabled(self, value: bool) -> None:
        """Set extended thinking enabled state."""
        self._settings.thinking_enabled = value
        self._save()

    def get_all(self) -> UserSettings:
        """Get a copy of all settings."""
        return UserSettings(
            tts=TTSSettings(
                enabled=self._settings.tts.enabled,
                voice_id=self._settings.tts.voice_id
            ),
            font_size=self._settings.font_size,
            conversation_model=self._settings.conversation_model,
            thinking_enabled=self._settings.thinking_enabled
        )


# Module-level convenience functions
_manager: Optional[UserSettingsManager] = None


def get_user_settings() -> UserSettingsManager:
    """Get the global user settings manager."""
    global _manager
    if _manager is None:
        _manager = UserSettingsManager()
    return _manager


def is_tts_enabled() -> bool:
    """Check if TTS is enabled."""
    return get_user_settings().tts_enabled


def get_tts_voice_id() -> str:
    """Get the current TTS voice ID."""
    return get_user_settings().tts_voice_id
