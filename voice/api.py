"""
Voice pipeline FastAPI routes.

Endpoints for ESP32-S3 Push-to-Talk integration:
  POST /voice/stt         - Transcribe raw PCM audio to text
  POST /voice/talk        - Full loop: audio → STT → Isaac → TTS → audio
  GET  /voice/health      - Pipeline status check
"""

import queue
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, Response

import config
from core.logger import log_info, log_warning, log_error
from core.user_settings import get_user_settings

voice_router = APIRouter(prefix="/voice", tags=["voice"])

# Thread-safe queue for GUI to pick up voice transcripts.
# The GUI polls this queue on a QTimer to display voice turns in the chat.
voice_event_queue = queue.Queue()


@voice_router.get("/health")
async def voice_health():
    """
    Voice pipeline health check.

    Returns status of STT model, TTS availability, and pipeline settings.
    """
    from stt.transcriber import is_stt_available, is_stt_loaded
    from tts.synthesizer import is_synthesizer_available

    settings = get_user_settings()

    status = {
        "pipeline_enabled": settings.voice_pipeline_enabled,
        "stt": {
            "available": is_stt_available(),
            "model_loaded": is_stt_loaded(),
            "enabled": settings.stt_enabled,
            "model_size": settings.stt_model_size,
        },
        "tts": {
            "available": is_synthesizer_available(),
            "enabled": settings.tts_enabled,
            "voice_id": settings.tts_voice_id,
        },
    }

    if not settings.voice_pipeline_enabled:
        status["status"] = "disabled"
        return JSONResponse(status, status_code=503)

    status["status"] = "ready" if is_stt_loaded() else "stt_not_loaded"
    code = 200 if is_stt_loaded() else 503
    return JSONResponse(status, status_code=code)


@voice_router.post("/stt")
async def voice_stt(request: Request):
    """
    Transcribe raw PCM audio to text.

    Request:
        Content-Type: application/octet-stream
        Body: Raw 16kHz 16-bit signed mono PCM bytes

    Response:
        {"text": "transcribed words", "success": true}
    """
    settings = get_user_settings()
    if not settings.voice_pipeline_enabled or not settings.stt_enabled:
        return JSONResponse({"error": "Voice pipeline or STT is disabled"}, status_code=503)

    audio_bytes = await request.body()
    if not audio_bytes:
        return JSONResponse({"error": "No audio data received"}, status_code=400)

    from stt.transcriber import transcribe, is_stt_loaded

    if not is_stt_loaded():
        return JSONResponse({"error": "STT model not loaded"}, status_code=503)

    text = transcribe(audio_bytes, sample_rate=config.VOICE_STT_SAMPLE_RATE)

    return {
        "text": text,
        "success": True,
        "audio_bytes": len(audio_bytes),
    }


@voice_router.post("/talk")
async def voice_talk(request: Request):
    """
    Full voice loop: audio → STT → Isaac → TTS → audio response.

    Request:
        Content-Type: application/octet-stream
        Body: Raw 16kHz 16-bit signed mono PCM bytes

    Response:
        Content-Type: audio/pcm (raw 24kHz 16-bit signed mono PCM)
        Headers:
            X-Transcription: what the user said
            X-Isaac-Text: what Isaac said
        Body: TTS audio bytes

    If TTS is disabled or fails, returns JSON with text response instead.
    """
    settings = get_user_settings()
    if not settings.voice_pipeline_enabled:
        return JSONResponse({"error": "Voice pipeline is disabled"}, status_code=503)

    audio_bytes = await request.body()
    if not audio_bytes:
        return JSONResponse({"error": "No audio data received"}, status_code=400)

    # Step 1: STT
    from stt.transcriber import transcribe, is_stt_loaded

    if not is_stt_loaded():
        return JSONResponse({"error": "STT model not loaded"}, status_code=503)

    user_text = transcribe(audio_bytes, sample_rate=config.VOICE_STT_SAMPLE_RATE)
    if not user_text:
        return {"error": "Could not transcribe audio", "text": ""}

    log_info(f"Voice input: {user_text}", prefix="[Voice]")

    # Step 2: Chat with Isaac
    try:
        from memory.conversation import get_conversation_manager
        from llm.router import get_llm_router, TaskType
        from core.temporal import strip_temporal_echoes

        conversation_mgr = get_conversation_manager()
        conversation_mgr.add_turn(role="user", content=user_text, input_type="voice")

        history = conversation_mgr.get_api_messages(limit=20)

        router = get_llm_router()
        response = router.chat(
            messages=history,
            task_type=TaskType.CONVERSATION,
            temperature=0.7,
            thinking_enabled=settings.thinking_enabled,
        )

        if not response.success:
            return JSONResponse({
                "error": f"LLM error: {response.error}",
                "transcription": user_text,
            }, status_code=500)

        isaac_text = strip_temporal_echoes(response.text)

        conversation_mgr.add_turn(role="assistant", content=isaac_text, input_type="text")
        log_info(f"Isaac response: {isaac_text[:80]}...", prefix="[Voice]")

    except Exception as e:
        log_error(f"Voice chat error: {e}", prefix="[Voice]")
        return JSONResponse({"error": str(e), "transcription": user_text}, status_code=500)

    # Notify GUI of the voice exchange (non-blocking)
    voice_event_queue.put({
        "user_text": user_text,
        "isaac_text": isaac_text,
        "timestamp": datetime.now().isoformat(),
    })

    # Step 3: TTS (if enabled)
    if settings.tts_enabled:
        try:
            from tts.synthesizer import synthesize_pcm

            tts_bytes = synthesize_pcm(
                isaac_text,
                voice=settings.tts_voice_id,
            )

            if tts_bytes:
                return Response(
                    content=tts_bytes,
                    media_type="audio/pcm",
                    headers={
                        "X-Transcription": user_text,
                        "X-Isaac-Text": isaac_text[:500],
                        "X-Sample-Rate": str(config.VOICE_TTS_SAMPLE_RATE),
                    },
                )

        except Exception as e:
            log_error(f"Voice TTS error: {e}", prefix="[Voice]")
            # Fall through to text-only response

    # Text-only response (TTS disabled or failed)
    return {
        "transcription": user_text,
        "response": isaac_text,
        "tts_available": False,
    }
