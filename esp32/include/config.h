/**
 * ESP32-S3 Voice Terminal - Configuration
 *
 * Edit these values for your network and server setup.
 */
#ifndef CONFIG_H
#define CONFIG_H

// ---- WiFi ----
#define WIFI_SSID     "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define WIFI_TIMEOUT_MS 10000

// ---- Pattern Project Server ----
#define SERVER_HOST "192.168.1.100"  // IP of the machine running Pattern Project
#define SERVER_PORT 5000             // Must match config.py HTTP_PORT

// ---- Audio Format (must match config.py VOICE_* constants) ----
#define MIC_SAMPLE_RATE    16000   // 16kHz for Whisper
#define MIC_BITS_PER_SAMPLE 16
#define MIC_CHANNELS        1

#define SPK_SAMPLE_RATE    24000   // 24kHz from ElevenLabs pcm_24000
#define SPK_BITS_PER_SAMPLE 16
#define SPK_CHANNELS        1

// ---- Recording Limits ----
#define MAX_RECORD_SECONDS  30     // Max PTT hold duration
#define RECORD_BUFFER_SIZE  (MIC_SAMPLE_RATE * MIC_CHANNELS * (MIC_BITS_PER_SAMPLE / 8) * MAX_RECORD_SECONDS)

// ---- Pins (can also be set via build_flags in platformio.ini) ----
#ifndef PIN_PTT_BUTTON
#define PIN_PTT_BUTTON  0   // BOOT button on most dev boards
#endif

#ifndef PIN_STATUS_LED
#define PIN_STATUS_LED  48  // Onboard RGB LED (ESP32-S3-DevKitC)
#endif

// I2S Microphone (INMP441 / SPH0645)
#ifndef PIN_I2S_MIC_SCK
#define PIN_I2S_MIC_SCK  42
#endif
#ifndef PIN_I2S_MIC_WS
#define PIN_I2S_MIC_WS   41
#endif
#ifndef PIN_I2S_MIC_SD
#define PIN_I2S_MIC_SD   2
#endif

// I2S Speaker Amplifier (MAX98357A)
#ifndef PIN_I2S_SPK_BCK
#define PIN_I2S_SPK_BCK   17
#endif
#ifndef PIN_I2S_SPK_WS
#define PIN_I2S_SPK_WS    18
#endif
#ifndef PIN_I2S_SPK_DATA
#define PIN_I2S_SPK_DATA  8
#endif

#endif // CONFIG_H
