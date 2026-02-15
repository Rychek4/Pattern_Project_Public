# Streaming LLM & TTS Pipeline

This document describes the streaming pipeline implementation that reduces latency from "press send" to "audio plays" by approximately 73-75%.

## Overview

The streaming pipeline parallelizes LLM response generation with TTS audio generation, allowing audio to start playing while the LLM is still generating text.

### Before (Sequential)
```
User sends → LLM (3s) → TTS (1.5s) → Audio plays
Total: ~4.5 seconds to first audio
```

### After (Streaming)
```
User sends → LLM streams ──────────────────────►
                │
                ├─ First tokens (~500ms)
                │   └─► GUI updates
                │
                ├─ First sentence (~900ms)
                │   └─► TTS starts ──► Audio plays (~1.2s)
                │
                └─ Response complete (~3s)

Total: ~1.2 seconds to first audio
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         GUI Thread                               │
│  ┌────────────────┐    ┌──────────────────────────────────────┐ │
│  │ Chat Display   │◄───│ MessageSignals                       │ │
│  │ (QTextBrowser) │    │  - stream_start(timestamp)           │ │
│  └────────────────┘    │  - stream_chunk(text)                │ │
│                        │  - stream_complete(full_text)        │ │
│                        └──────────────────────────────────────┘ │
└────────────────────────────────▲────────────────────────────────┘
                                 │
                                 │ Signals (thread-safe)
                                 │
┌────────────────────────────────┴────────────────────────────────┐
│                    Background Thread                             │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ _process_message()                                         │ │
│  │                                                            │ │
│  │  1. Build prompt (PromptBuilder)                          │ │
│  │  2. Get conversation history                              │ │
│  │  3. Start streaming: chat_stream()                        │ │
│  │     │                                                     │ │
│  │     ├─► For each chunk:                                   │ │
│  │     │     ├─► Emit stream_chunk signal                    │ │
│  │     │     └─► Feed to SentenceBuffer                      │ │
│  │     │           │                                         │ │
│  │     │           └─► If sentence complete:                 │ │
│  │     │                 └─► queue_tts_sentence()            │ │
│  │     │                                                     │ │
│  │     └─► On stream complete:                               │ │
│  │           ├─► Handle tool calls (if any)                  │ │
│  │           ├─► Flush remaining TTS                         │ │
│  │           └─► Emit stream_complete signal                 │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
                    ▼                         ▼
         ┌──────────────────┐      ┌──────────────────┐
         │ Anthropic API    │      │ ElevenLabs API   │
         │ (Streaming SSE)  │      │ (PCM 24kHz)      │
         └──────────────────┘      └────────┬─────────┘
                                            │
                                            ▼
                                   ┌──────────────────┐
                                   │ Audio Queue      │
                                   │ (multiprocessing)│
                                   └────────┬─────────┘
                                            │
                                            ▼
                                   ┌──────────────────┐
                                   │ pygame Worker    │
                                   │ (separate proc)  │
                                   └──────────────────┘
```

## Components

### 1. LLM Streaming (`llm/anthropic_client.py`)

#### StreamingState Class
Tracks accumulated state during streaming:
```python
@dataclass
class StreamingState:
    text: str = ""                    # Accumulated response text
    input_tokens: int = 0             # Token usage
    output_tokens: int = 0
    tool_calls: List[ToolCall] = ...  # Detected tool calls
    raw_content: List[Any] = ...      # For continuation messages
    stop_reason: Optional[str] = None # "end_turn", "tool_use", "error"
    web_searches_used: int = 0
    citations: List[WebSearchCitation] = ...
```

#### chat_stream() Method
```python
def chat_stream(
    self,
    messages: List[Dict[str, Any]],
    system_prompt: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: float = 0.7,
    tools: Optional[List[Dict[str, Any]]] = None,
    ...
) -> Generator[tuple[str, StreamingState], None, None]:
    """
    Yields (text_chunk, state) tuples as tokens arrive.

    The state accumulates the full response and can be used
    to detect tool calls after streaming completes.
    """
```

**Event Types Handled:**
- `message_start` - Extract input token count
- `content_block_start` - Track block type (text vs tool_use)
- `content_block_delta` - Yield text chunks, accumulate tool JSON
- `content_block_stop` - Finalize tool calls
- `message_delta` - Get stop_reason and output tokens
- `message_stop` - Stream complete

### 2. Sentence Detection (`core/sentence_splitter.py`)

#### SentenceBuffer Class
Buffers streaming text and extracts complete sentences for TTS.

```python
class SentenceBuffer:
    def add_chunk(self, chunk: str) -> List[Tuple[str, bool]]:
        """
        Add text chunk, return list of (sentence, is_speakable).

        is_speakable=False for code blocks (skipped for TTS).
        """

    def flush(self) -> List[Tuple[str, bool]]:
        """Return any remaining buffered content."""
```

**Features:**
- Detects sentence boundaries (`.` `!` `?`)
- Handles code blocks (``` markers) - marks as non-speakable
- Handles abbreviations: "Dr.", "Mr.", "etc."
- Handles decimals: "3.14", "$99.99"
- Handles ellipsis: "..."

**Example:**
```python
buffer = SentenceBuffer()

# Streaming chunks arrive
buffer.add_chunk("Hello, I am ")     # Returns: []
buffer.add_chunk("Claude. How ")     # Returns: [("Hello, I am Claude.", True)]
buffer.add_chunk("are you?")         # Returns: []
buffer.flush()                        # Returns: [("How are you?", True)]
```

### 3. TTS Streaming (`tts/player.py`)

#### queue_sentence() Method
```python
def queue_sentence(self, sentence: str, voice_id: Optional[str] = None) -> bool:
    """
    Queue a single sentence for TTS using PCM format.

    Uses pcm_24000 format for lower latency than MP3.
    Non-blocking - fetches audio in background thread.
    """
```

#### Audio Format
- **Format:** PCM 24kHz, 16-bit signed
- **Why PCM:** Allows chunk-by-chunk playback without waiting for complete file
- **Normalization:** DC offset removal, -16 dBFS normalization, fade in/out

#### Worker Process
The pygame worker process handles both formats:
```python
if audio_type == AUDIO_TYPE_PCM:
    # Use pygame.mixer.Sound for PCM (supports streaming)
    sound = pygame.mixer.Sound(wav_buffer)
    sound.play()
else:
    # Use pygame.mixer.music for MP3 (legacy)
    pygame.mixer.music.load(mp3_buffer)
    pygame.mixer.music.play()
```

### 4. GUI Integration (`interface/gui.py`)

#### New Signals
```python
class MessageSignals(QObject):
    # ... existing signals ...

    # Streaming signals
    stream_start = pyqtSignal(str)     # timestamp
    stream_chunk = pyqtSignal(str)     # text chunk
    stream_complete = pyqtSignal(str)  # full_text
```

#### Signal Handlers

**_on_stream_start(timestamp)**
- Creates message placeholder in chat display
- Initializes streaming state variables

**_on_stream_chunk(chunk)**
- Appends chunk to accumulated text
- Updates chat display (simple HTML escape during streaming)
- Note: Full markdown rendering happens at stream_complete

**_on_stream_complete(full_text)**
- Applies full markdown rendering
- Stores message in search index
- Clears streaming state

## Configuration

### ElevenLabs Settings (`config.py`)
```python
ELEVENLABS_MODEL = "eleven_turbo_v2_5"
ELEVENLABS_DEFAULT_VOICE_ID = "your_voice_id"
```

### TTS Player Settings (`tts/player.py`)
```python
ELEVENLABS_PCM_24K_SAMPLE_RATE = 24000  # For streaming
PYGAME_SAMPLE_RATE = 44100              # Mixer frequency
MASTER_VOLUME = 0.4                      # Output volume
```

### Streaming Behavior
The streaming implementation has no configuration toggles - it's the default behavior. To revert to non-streaming, you would need to roll back the git changes.

## Tool Call Handling

When the LLM response includes tool calls:

1. **During Streaming:** Text is streamed normally, tool call JSON is accumulated
2. **After Streaming:** `final_state.has_tool_calls()` returns True
3. **Tool Processing:** Uses existing `process_with_tools()` (non-streaming continuations)
4. **Additional Text:** Any text from tool continuations is also sent to TTS

```python
if final_state.has_tool_calls():
    # Convert streaming state to LLMResponse for tool processor
    response = LLMResponse(
        text=final_state.text,
        tool_calls=final_state.tool_calls,
        raw_content=final_state.raw_content,
        ...
    )

    # Process tools (uses non-streaming for continuations)
    result = process_with_tools(llm_router, response, history, ...)

    # Queue any additional text for TTS
    if result.final_text != streamed_text:
        additional = result.final_text[len(streamed_text):]
        # ... queue for TTS
```

## Error Handling

### LLM Streaming Errors
- Connection drops: Stream terminates, partial text is preserved
- API errors: `stop_reason` set to "error", error state yielded

### TTS Errors
- API failures: Logged, sentence skipped, playback continues
- Empty audio: Logged as warning, continues to next sentence

### GUI Errors
- All exceptions caught in `_process_message()`
- `stream_complete("")` emitted on error to clean up UI state
- `response_complete` always emitted in `finally` block

## Latency Breakdown

| Phase | Before | After | Notes |
|-------|--------|-------|-------|
| Prompt assembly | 300ms | 300ms | Unchanged |
| First LLM tokens | 3000ms | 500ms | Streaming starts early |
| First sentence | 3000ms | 900ms | ~15 words |
| TTS API call | +1500ms | +300ms | Per sentence, parallel |
| First audio | 4500ms | 1200ms | **73% reduction** |

## Troubleshooting

### Audio not playing
1. Check ElevenLabs API key: `echo $Eleven_Labs_API`
2. Verify TTS enabled: User Settings > TTS toggle
3. Check logs for `[TTS]` prefixed messages

### Text not streaming
1. Check Anthropic API key
2. Look for `[Stream]` errors in logs
3. Verify model supports streaming (all Claude models do)

### Sentences not detected
1. Check for missing punctuation in LLM output
2. Code blocks are intentionally skipped
3. Use `split_for_tts()` to test sentence detection:
   ```python
   from core.sentence_splitter import split_for_tts
   result = split_for_tts("Hello. World.")
   print(result)  # [("Hello.", True), ("World.", True)]
   ```

### Audio gaps between sentences
This is expected behavior - each sentence is a separate TTS call. The gaps are typically 100-300ms and provide natural pacing.

## Future Improvements

Potential enhancements not implemented:
1. **True audio streaming:** Use ElevenLabs WebSocket API for sub-sentence audio chunks
2. **Speculative generation:** Start TTS before sentence is complete
3. **Audio crossfade:** Smooth transitions between sentences
4. **Streaming for tool continuations:** Currently uses non-streaming for tool follow-ups
