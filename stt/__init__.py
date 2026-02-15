"""STT (Speech-to-Text) module using faster-whisper."""

from stt.transcriber import (
    load_stt_model,
    unload_stt_model,
    transcribe,
    is_stt_available,
    is_stt_loaded,
)

__all__ = [
    "load_stt_model",
    "unload_stt_model",
    "transcribe",
    "is_stt_available",
    "is_stt_loaded",
]
