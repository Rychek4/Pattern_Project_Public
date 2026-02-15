/**
 * ESP32-S3 Voice Terminal for Isaac (Pattern Project)
 *
 * Push-to-Talk → Record → POST /voice/talk → Play response
 *
 * Hardware:
 *   - ESP32-S3R8 (8MB PSRAM)
 *   - INMP441 I2S MEMS Microphone
 *   - MAX98357A I2S Amplifier + Speaker
 *   - Momentary push button (PTT)
 *   - Status LED
 */

#include <Arduino.h>
#include "config.h"
#include "audio.h"
#include "button.h"
#include "network.h"

// PSRAM buffers for audio data
static uint8_t* record_buffer = nullptr;
static uint8_t* response_buffer = nullptr;

// State machine
enum State {
    STATE_IDLE,
    STATE_RECORDING,
    STATE_SENDING,
    STATE_PLAYING,
    STATE_ERROR,
};

static State current_state = STATE_IDLE;
static size_t record_offset = 0;
static size_t response_len = 0;

// LED patterns
void led_set(bool on) {
    #ifdef PIN_STATUS_LED
    digitalWrite(PIN_STATUS_LED, on ? HIGH : LOW);
    #endif
}

void led_blink(int count, int on_ms, int off_ms) {
    for (int i = 0; i < count; i++) {
        led_set(true);
        delay(on_ms);
        led_set(false);
        if (i < count - 1) delay(off_ms);
    }
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n=== Isaac Voice Terminal ===");

    // Status LED
    #ifdef PIN_STATUS_LED
    pinMode(PIN_STATUS_LED, OUTPUT);
    #endif
    led_blink(2, 100, 100);

    // Allocate PSRAM buffers
    record_buffer = (uint8_t*)ps_malloc(RECORD_BUFFER_SIZE);
    response_buffer = (uint8_t*)ps_malloc(RECORD_BUFFER_SIZE);  // Reuse same size for response

    if (!record_buffer || !response_buffer) {
        Serial.println("FATAL: Failed to allocate PSRAM buffers!");
        led_blink(10, 50, 50);
        while (true) delay(1000);
    }
    Serial.printf("PSRAM buffers allocated: %d bytes each\n", RECORD_BUFFER_SIZE);

    // Initialize audio
    if (!audio_init_mic()) {
        Serial.println("FATAL: Mic I2S init failed!");
        while (true) delay(1000);
    }
    Serial.println("Mic I2S initialized");

    if (!audio_init_speaker()) {
        Serial.println("FATAL: Speaker I2S init failed!");
        while (true) delay(1000);
    }
    Serial.println("Speaker I2S initialized");

    // Initialize button
    button_init();
    Serial.println("PTT button initialized");

    // Connect to WiFi
    if (!network_connect_wifi()) {
        Serial.println("FATAL: WiFi connection failed!");
        led_blink(5, 200, 200);
        while (true) delay(1000);
    }

    // Check server health
    bool server_ok = false;
    for (int retry = 0; retry < 5; retry++) {
        if (network_check_server_health()) {
            server_ok = true;
            break;
        }
        Serial.printf("Server not ready, retrying in %ds...\n", (retry + 1) * 2);
        delay((retry + 1) * 2000);
    }

    if (!server_ok) {
        Serial.println("WARNING: Server not reachable — will retry on first PTT press");
    }

    led_blink(3, 100, 100);  // Ready signal
    Serial.println("\nReady! Hold the PTT button to speak.");
    current_state = STATE_IDLE;
}

void loop() {
    switch (current_state) {

    case STATE_IDLE:
        if (button_is_pressed()) {
            Serial.println("[REC] PTT pressed — recording...");
            led_set(true);
            record_offset = 0;
            current_state = STATE_RECORDING;

            // Flush any stale data from I2S DMA buffers
            uint8_t discard[1024];
            audio_read_mic(discard, sizeof(discard));
        }
        break;

    case STATE_RECORDING: {
        // Read audio from mic into PSRAM buffer
        size_t remaining = RECORD_BUFFER_SIZE - record_offset;
        if (remaining > 0) {
            size_t chunk = min(remaining, (size_t)4096);
            size_t got = audio_read_mic(record_buffer + record_offset, chunk);
            record_offset += got;
        }

        // Check if button released or buffer full
        if (!button_is_pressed() || record_offset >= RECORD_BUFFER_SIZE) {
            led_set(false);
            float seconds = (float)record_offset / (MIC_SAMPLE_RATE * MIC_CHANNELS * (MIC_BITS_PER_SAMPLE / 8));
            Serial.printf("[REC] Done: %zu bytes (%.1fs)\n", record_offset, seconds);

            if (record_offset < MIC_SAMPLE_RATE) {
                // Less than 0.5s of audio — too short, ignore
                Serial.println("[REC] Too short, ignoring");
                current_state = STATE_IDLE;
            } else {
                current_state = STATE_SENDING;
            }
        }
        break;
    }

    case STATE_SENDING: {
        Serial.println("[NET] Sending audio to server...");
        led_blink(1, 50, 0);

        response_len = 0;
        bool got_audio = network_voice_talk(
            record_buffer, record_offset,
            response_buffer, RECORD_BUFFER_SIZE,
            &response_len
        );

        if (got_audio && response_len > 0) {
            Serial.printf("[NET] Got audio response: %zu bytes\n", response_len);
            current_state = STATE_PLAYING;
        } else if (response_len > 0) {
            // Got JSON text response (TTS disabled or failed)
            Serial.println("[NET] Got text-only response (no audio)");
            current_state = STATE_IDLE;
        } else {
            Serial.println("[NET] Error — no response");
            current_state = STATE_ERROR;
        }
        break;
    }

    case STATE_PLAYING: {
        Serial.println("[SPK] Playing response...");
        led_set(true);

        // Feed response audio to I2S speaker in chunks
        size_t offset = 0;
        const size_t chunk_size = 4096;
        while (offset < response_len) {
            size_t to_write = min(chunk_size, response_len - offset);
            audio_write_speaker(response_buffer + offset, to_write);
            offset += to_write;
        }

        led_set(false);
        float play_secs = (float)response_len / (SPK_SAMPLE_RATE * SPK_CHANNELS * (SPK_BITS_PER_SAMPLE / 8));
        Serial.printf("[SPK] Done (%.1fs audio)\n", play_secs);
        current_state = STATE_IDLE;
        break;
    }

    case STATE_ERROR:
        led_blink(3, 100, 100);
        delay(2000);
        current_state = STATE_IDLE;
        break;
    }

    // Small yield to prevent watchdog
    delay(1);
}
