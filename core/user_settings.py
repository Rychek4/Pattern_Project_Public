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
class VoiceSettings:
    """Consolidated voice pipeline settings (TTS + STT + ESP32)."""
    pipeline_enabled: bool = False   # Master on/off for entire voice system
    tts_enabled: bool = True         # TTS output (sub-toggle under master)
    stt_enabled: bool = True         # STT input  (sub-toggle under master)
    voice_id: str = ""               # ElevenLabs voice ID (empty = default)
    stt_model_size: str = "small"    # faster-whisper model: tiny, base, small

    def get_voice_id(self) -> str:
        """Get voice ID, falling back to config default if not set."""
        return self.voice_id if self.voice_id else config.ELEVENLABS_DEFAULT_VOICE_ID


# Keep old name as alias for any external code that references it directly
TTSSettings = VoiceSettings


@dataclass
class UserSettings:
    """All user-configurable settings."""
    voice: VoiceSettings = None
    font_size: int = 12
    conversation_model: str = "claude-sonnet-4-5-20250929"  # Default to Sonnet for first-time users
    thinking_enabled: bool = True  # Extended thinking on by default

    def __post_init__(self):
        if self.voice is None:
            self.voice = VoiceSettings()

    # Backward-compat alias so old code referencing settings.tts still works
    @property
    def tts(self) -> VoiceSettings:
        return self.voice

    @tts.setter
    def tts(self, value):
        if isinstance(value, VoiceSettings):
            self.voice = value


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
        """Load settings from disk, migrating old format if needed."""
        try:
            if self._settings_path.exists():
                with open(self._settings_path, 'r') as f:
                    data = json.load(f)

                migrated = False

                # ----------------------------------------------------------
                # Migration: old "tts" key → new "voice" key
                # Old format:  {"tts": {"enabled": true, "voice_id": "..."}}
                # New format:  {"voice": {"pipeline_enabled": true, ...}}
                # ----------------------------------------------------------
                if 'tts' in data and 'voice' not in data:
                    old_tts = data.pop('tts', {})
                    data['voice'] = {
                        'pipeline_enabled': old_tts.get('enabled', False),
                        'tts_enabled': old_tts.get('enabled', False),
                        'stt_enabled': True,
                        'voice_id': old_tts.get('voice_id', ''),
                        'stt_model_size': config.WHISPER_MODEL_DEFAULT,
                    }
                    migrated = True
                    log_info("Migrated legacy TTS settings → voice pipeline settings", prefix="⚙️")

                # Parse voice settings
                voice_data = data.get('voice', {})
                self._settings.voice = VoiceSettings(
                    pipeline_enabled=voice_data.get('pipeline_enabled', False),
                    tts_enabled=voice_data.get('tts_enabled', True),
                    stt_enabled=voice_data.get('stt_enabled', True),
                    voice_id=voice_data.get('voice_id', ''),
                    stt_model_size=voice_data.get('stt_model_size', config.WHISPER_MODEL_DEFAULT),
                )

                # Parse other settings
                self._settings.font_size = data.get('font_size', 12)
                self._settings.conversation_model = data.get('conversation_model', 'claude-sonnet-4-5-20250929')
                self._settings.thinking_enabled = data.get('thinking_enabled', config.ANTHROPIC_THINKING_ENABLED)

                log_info("User settings loaded", prefix="⚙️")

                # Persist migration immediately
                if migrated:
                    self._save()

        except json.JSONDecodeError as e:
            log_warning(f"Invalid settings file, using defaults: {e}")
        except Exception as e:
            log_error(f"Failed to load settings: {e}")

    def _save(self) -> None:
        """Save settings to disk."""
        with self._file_lock:
            try:
                data = {
                    'voice': {
                        'pipeline_enabled': self._settings.voice.pipeline_enabled,
                        'tts_enabled': self._settings.voice.tts_enabled,
                        'stt_enabled': self._settings.voice.stt_enabled,
                        'voice_id': self._settings.voice.voice_id,
                        'stt_model_size': self._settings.voice.stt_model_size,
                    },
                    'font_size': self._settings.font_size,
                    'conversation_model': self._settings.conversation_model,
                    'thinking_enabled': self._settings.thinking_enabled
                }

                with open(self._settings_path, 'w') as f:
                    json.dump(data, f, indent=2)

            except Exception as e:
                log_error(f"Failed to save settings: {e}")

    # -----------------------------------------------------------------
    # Voice pipeline properties
    # -----------------------------------------------------------------
    @property
    def voice_pipeline_enabled(self) -> bool:
        """Master toggle for the entire voice pipeline."""
        return self._settings.voice.pipeline_enabled

    @voice_pipeline_enabled.setter
    def voice_pipeline_enabled(self, value: bool) -> None:
        self._settings.voice.pipeline_enabled = value
        self._save()

    @property
    def tts_enabled(self) -> bool:
        """Check if TTS is enabled (requires pipeline_enabled)."""
        return self._settings.voice.pipeline_enabled and self._settings.voice.tts_enabled

    @tts_enabled.setter
    def tts_enabled(self, value: bool) -> None:
        """Set TTS sub-toggle (independent of master)."""
        self._settings.voice.tts_enabled = value
        self._save()

    @property
    def stt_enabled(self) -> bool:
        """Check if STT is enabled (requires pipeline_enabled)."""
        return self._settings.voice.pipeline_enabled and self._settings.voice.stt_enabled

    @stt_enabled.setter
    def stt_enabled(self, value: bool) -> None:
        """Set STT sub-toggle."""
        self._settings.voice.stt_enabled = value
        self._save()

    @property
    def tts_voice_id(self) -> str:
        """Get the TTS voice ID."""
        return self._settings.voice.get_voice_id()

    @tts_voice_id.setter
    def tts_voice_id(self, value: str) -> None:
        """Set the TTS voice ID."""
        self._settings.voice.voice_id = value
        self._save()

    @property
    def stt_model_size(self) -> str:
        """Get the STT model size."""
        return self._settings.voice.stt_model_size

    @stt_model_size.setter
    def stt_model_size(self, value: str) -> None:
        """Set the STT model size."""
        if value in ('tiny', 'base', 'small'):
            self._settings.voice.stt_model_size = value
            self._save()

    # -----------------------------------------------------------------
    # Other settings properties (unchanged)
    # -----------------------------------------------------------------
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
            voice=VoiceSettings(
                pipeline_enabled=self._settings.voice.pipeline_enabled,
                tts_enabled=self._settings.voice.tts_enabled,
                stt_enabled=self._settings.voice.stt_enabled,
                voice_id=self._settings.voice.voice_id,
                stt_model_size=self._settings.voice.stt_model_size,
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
    """Check if TTS is enabled (pipeline master + TTS sub-toggle)."""
    return get_user_settings().tts_enabled


def get_tts_voice_id() -> str:
    """Get the current TTS voice ID."""
    return get_user_settings().tts_voice_id
