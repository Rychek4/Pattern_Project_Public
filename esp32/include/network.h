/**
 * ESP32-S3 Voice Terminal - Network Helpers
 *
 * WiFi connection and HTTP client wrappers for the Pattern Project server.
 */
#ifndef NETWORK_H
#define NETWORK_H

#include <WiFi.h>
#include <HTTPClient.h>
#include "config.h"

/**
 * Connect to WiFi. Blocks until connected or timeout.
 * Returns true on success.
 */
inline bool network_connect_wifi() {
    Serial.printf("Connecting to WiFi '%s'...\n", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start > WIFI_TIMEOUT_MS) {
            Serial.println("WiFi connection timeout!");
            return false;
        }
        delay(250);
        Serial.print(".");
    }
    Serial.printf("\nWiFi connected! IP: %s\n", WiFi.localIP().toString().c_str());
    return true;
}

/**
 * Check if the Pattern Project server voice endpoint is healthy.
 */
inline bool network_check_server_health() {
    HTTPClient http;
    String url = String("http://") + SERVER_HOST + ":" + SERVER_PORT + "/voice/health";

    http.begin(url);
    int code = http.GET();
    http.end();

    if (code == 200) {
        Serial.println("Server voice pipeline: READY");
        return true;
    } else {
        Serial.printf("Server health check failed (HTTP %d)\n", code);
        return false;
    }
}

/**
 * POST raw PCM audio to /voice/talk and receive audio response.
 *
 * response_buffer: Pre-allocated PSRAM buffer for the response audio
 * response_max: Size of response_buffer
 * response_len: [out] Actual bytes received
 *
 * Returns true if the response is audio/pcm, false if JSON or error.
 */
inline bool network_voice_talk(
    const uint8_t* audio_data,
    size_t audio_len,
    uint8_t* response_buffer,
    size_t response_max,
    size_t* response_len
) {
    HTTPClient http;
    String url = String("http://") + SERVER_HOST + ":" + SERVER_PORT + "/voice/talk";

    http.begin(url);
    http.addHeader("Content-Type", "application/octet-stream");
    http.setTimeout(30000);  // 30s timeout for STT + LLM + TTS

    int code = http.POST(const_cast<uint8_t*>(audio_data), audio_len);

    if (code != 200) {
        Serial.printf("voice/talk failed: HTTP %d\n", code);
        http.end();
        *response_len = 0;
        return false;
    }

    // Check content type
    String content_type = http.header("Content-Type");
    bool is_audio = content_type.startsWith("audio/pcm");

    // Read response body
    WiFiClient* stream = http.getStreamPtr();
    size_t total = 0;
    while (stream->available() && total < response_max) {
        int avail = stream->available();
        if (avail <= 0) break;
        size_t to_read = min((size_t)avail, response_max - total);
        size_t got = stream->readBytes(response_buffer + total, to_read);
        total += got;
    }

    *response_len = total;
    http.end();

    Serial.printf("Received %zu bytes (%s)\n", total, is_audio ? "audio" : "json");
    return is_audio;
}

#endif // NETWORK_H
