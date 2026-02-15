# Implementation Plan: OpenAI TTS Swap + Legacy Playback Removal

## Context

Phases 1-3 of the ESP32 voice pipeline are already complete (settings consolidation, STT/Whisper, voice API endpoints). This plan covers the remaining server-side work: removing the legacy local playback system, swapping ElevenLabs for OpenAI TTS, and surfacing voice transcripts in the GUI.

---

## Step 1: Swap ElevenLabs → OpenAI TTS in `tts/synthesizer.py`

Rewrite the synthesizer internals. The public API stays the same (`synthesize_pcm()`, `synthesize_mp3()`, `sanitize_for_tts()`, `is_synthesizer_available()`), but the guts switch from the `elevenlabs` SDK to the `openai` SDK.

**Key changes:**
- `_get_client()` → lazy-load `openai.OpenAI(api_key=...)` instead of `ElevenLabs(api_key=...)`
- `synthesize_pcm()` → call `client.audio.speech.create(model=..., voice=..., input=text, response_format="pcm")`. OpenAI's PCM output is 24kHz 16-bit mono — identical to what we send to the ESP32 today. No audio format change.
- `synthesize_mp3()` → same call with `response_format="mp3"` (used by GUI path)
- `is_synthesizer_available()` → check for `openai` package + `OPENAI_API_KEY` env var
- Remove all `elevenlabs` imports (`ElevenLabs`, `VoiceSettings`)
- `voice_id` parameter becomes `voice` — one of OpenAI's 6 named voices (`alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`) instead of an ElevenLabs UUID
- No more `VoiceSettings(stability=0.5, ...)` — OpenAI's API doesn't have these knobs

**Audio format contract — unchanged:**
- ESP32 → Server: 16kHz 16-bit mono PCM (Whisper input)
- Server → ESP32: 24kHz 16-bit mono PCM (OpenAI `response_format="pcm"` default)

---

## Step 2: Update `config.py` — Replace ElevenLabs config with OpenAI TTS config

**Remove** (lines 341-351):
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_DEFAULT_VOICE_ID`
- `ELEVENLABS_MODEL`
- `ELEVENLABS_AUDIO_PORT` (legacy)

**Add:**
- `OPENAI_TTS_API_KEY = os.getenv("OPENAI_API_KEY", "")` — reuse standard OpenAI env var
- `OPENAI_TTS_MODEL = "tts-1"` — faster/cheaper; `"tts-1-hd"` for higher quality
- `OPENAI_TTS_DEFAULT_VOICE = "nova"` — default voice (pick one that sounds good)
- `OPENAI_TTS_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"]` — all valid voices for settings UI validation

Also update the comment on `VOICE_TTS_SAMPLE_RATE = 24000` to reference OpenAI instead of ElevenLabs.

Also remove `SUBPROCESS_AUDIO_ENABLED = False` (dead config).

---

## Step 3: Update `core/user_settings.py` — Voice ID → Voice Name

**`VoiceSettings` dataclass:**
- `voice_id: str = ""` comment changes from "ElevenLabs voice ID" to "OpenAI TTS voice name"
- `get_voice_id()` fallback changes from `config.ELEVENLABS_DEFAULT_VOICE_ID` to `config.OPENAI_TTS_DEFAULT_VOICE`

**Migration:** Add a migration path in `_load()` for existing `user_settings.json` files that have an ElevenLabs UUID as `voice_id`. If the stored value looks like a UUID (not in the valid OpenAI voice list), reset it to empty string so the default kicks in.

---

## Step 4: Remove `tts/player.py` — Delete Legacy Local Playback

Delete the entire 780-line file. It contains:
- Multiprocessing pygame worker
- WorkerWatchdog class
- TTSPlayer class with queue management
- All pygame-based audio playback

None of this is needed anymore. The ESP32 handles all audio I/O. The GUI's `_trigger_tts()` path needs to be updated (see Step 6).

---

## Step 5: Update `tts/__init__.py` — New Exports

Replace the player-based exports with synthesizer-based exports:

```python
from tts.synthesizer import (
    synthesize_pcm,
    synthesize_mp3,
    sanitize_for_tts,
    is_synthesizer_available,
)
```

Remove: `play_tts`, `stop_tts`, `get_tts_player`, `shutdown_tts` (all from deleted player.py).

---

## Step 6: Update `interface/gui.py` — Remove Player References, Keep TTS for GUI

Three spots reference `tts/player.py`:

1. **Line 1319**: `from tts.player import play_tts` in `_trigger_tts()` — Remove the local playback call entirely. The GUI no longer plays audio through PC speakers. If TTS is enabled, the ESP32 handles audio. The GUI's job is just displaying text.

2. **Line 1663**: `from tts.player import queue_tts_sentence` in `_process_message()` — Remove the sentence-by-sentence TTS queuing during streaming. Same reason: no local playback.

3. **Line 3378**: `from tts.player import shutdown_tts` in shutdown — Remove the cleanup call. Nothing to shut down.

**Net effect:** Remove the `_trigger_tts()` method body (or make it a no-op), remove `queue_tts_sentence` calls from the streaming path, remove `shutdown_tts` from cleanup. The TTS trigger code in `_process_message` that builds the `SentenceBuffer` for TTS queuing also gets simplified — the sentence buffer was only there to feed chunks to the player.

---

## Step 7: Show Voice Transcripts in GUI

When the ESP32 sends audio via `POST /voice/talk`, the voice API already writes turns to the conversation manager:
- `conversation_mgr.add_turn(role="user", content=user_text, input_type="voice")`
- `conversation_mgr.add_turn(role="assistant", content=isaac_text, input_type="text")`

But the GUI doesn't currently know about these turns because it only displays messages from its own `_process_message` flow.

**Approach:** Add a lightweight polling mechanism or signal so the GUI picks up voice-originated turns:

- Add a `voice_message_received` signal to `ChatWindow`
- In `voice/api.py` after a successful `/voice/talk`, emit a signal (or write to a thread-safe queue) with the user transcription and Isaac's response
- The GUI's event loop picks it up and calls `_append_message()` with a visual indicator that this was a voice message (e.g., a small microphone icon prefix or a distinct bubble color)
- Voice user messages get styled slightly differently — same right-aligned bubble but with a "🎙" prefix to distinguish typed vs spoken input

**Implementation detail:** Since Flask runs in a separate thread from Qt, use a `QTimer`-based poll (every 500ms) checking a `queue.Queue` that the voice endpoint writes to. This is the same pattern used by the process event bus already in the codebase.

---

## Step 8: Update `requirements.txt` — Dependencies

**Remove:**
- `elevenlabs>=1.0.0`
- `pygame>=2.5.0`

**Add:**
- `openai>=1.0.0` (for TTS API)
- `faster-whisper>=0.9.0` (was missing — already in use by STT)

---

## Step 9: Update `voice/api.py` — Wire Voice Queue for GUI

Add a module-level thread-safe queue that the GUI can poll:

```python
import queue
voice_event_queue = queue.Queue()
```

After a successful `/voice/talk` response, push a dict:
```python
voice_event_queue.put({
    "user_text": user_text,
    "isaac_text": isaac_text,
    "timestamp": datetime.now().isoformat(),
})
```

The GUI imports `voice_event_queue` and drains it on a timer.

---

## Step 10: Clean up `main.py` — Remove TTS Shutdown

Remove any `shutdown_tts()` calls from the cleanup/shutdown path. The OpenAI client doesn't need explicit shutdown (it's just an HTTP client).

---

## File Change Summary

| File | Action | What |
|------|--------|------|
| `tts/synthesizer.py` | **Rewrite** | ElevenLabs → OpenAI TTS |
| `tts/player.py` | **Delete** | Legacy pygame playback |
| `tts/__init__.py` | **Edit** | New exports from synthesizer |
| `config.py` | **Edit** | Remove ElevenLabs config, add OpenAI TTS config |
| `core/user_settings.py` | **Edit** | Voice ID fallback + migration |
| `interface/gui.py` | **Edit** | Remove player imports, add voice transcript display |
| `voice/api.py` | **Edit** | Add voice event queue for GUI |
| `requirements.txt` | **Edit** | Swap elevenlabs/pygame for openai, add faster-whisper |
| `main.py` | **Edit** | Remove shutdown_tts cleanup |

**No changes to:** `stt/`, `voice/api.py` endpoints (just adding the queue), ESP32 firmware, database schema, conversation manager, prompt builder.

---

## Implementation Order

```
Step 1 (synthesizer rewrite) ─┐
Step 2 (config)               ├─► Can be done together (core TTS swap)
Step 3 (user settings)        ─┘
Step 4 (delete player.py)     ─┐
Step 5 (tts/__init__.py)      ├─► Depends on Step 1 (synthesizer must exist first)
Step 6 (gui.py player refs)   ─┘
Step 7 (voice transcripts)    ─┐
Step 9 (voice event queue)    ├─► Independent of TTS swap, can parallel
Step 8 (requirements.txt)     ─── Last (after all code changes)
Step 10 (main.py cleanup)     ─── Last
```
