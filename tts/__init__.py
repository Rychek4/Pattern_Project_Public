"""TTS (Text-to-Speech) module — OpenAI TTS synthesis."""

from tts.synthesizer import (
    synthesize_pcm,
    synthesize_mp3,
    sanitize_for_tts,
    is_synthesizer_available,
)

__all__ = [
    "synthesize_pcm",
    "synthesize_mp3",
    "sanitize_for_tts",
    "is_synthesizer_available",
]
