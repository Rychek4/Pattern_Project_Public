/**
 * ESP32-S3 Voice Terminal - I2S Audio Setup
 *
 * Configures two I2S peripherals:
 *   I2S_NUM_0 — Microphone input  (INMP441 or SPH0645)
 *   I2S_NUM_1 — Speaker output    (MAX98357A)
 */
#ifndef AUDIO_H
#define AUDIO_H

#include <driver/i2s.h>
#include "config.h"

/**
 * Initialize I2S microphone (I2S_NUM_0).
 * Returns true on success.
 */
inline bool audio_init_mic() {
    i2s_config_t mic_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
        .sample_rate = MIC_SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 8,
        .dma_buf_len = 1024,
        .use_apll = false,
        .tx_desc_auto_clear = false,
        .fixed_mclk = 0,
    };

    i2s_pin_config_t mic_pins = {
        .bck_io_num   = PIN_I2S_MIC_SCK,
        .ws_io_num    = PIN_I2S_MIC_WS,
        .data_out_num = I2S_PIN_NO_CHANGE,
        .data_in_num  = PIN_I2S_MIC_SD,
    };

    esp_err_t err = i2s_driver_install(I2S_NUM_0, &mic_config, 0, NULL);
    if (err != ESP_OK) return false;

    err = i2s_set_pin(I2S_NUM_0, &mic_pins);
    return err == ESP_OK;
}

/**
 * Initialize I2S speaker (I2S_NUM_1).
 * Returns true on success.
 */
inline bool audio_init_speaker() {
    i2s_config_t spk_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
        .sample_rate = SPK_SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 8,
        .dma_buf_len = 1024,
        .use_apll = false,
        .tx_desc_auto_clear = true,
        .fixed_mclk = 0,
    };

    i2s_pin_config_t spk_pins = {
        .bck_io_num   = PIN_I2S_SPK_BCK,
        .ws_io_num    = PIN_I2S_SPK_WS,
        .data_out_num = PIN_I2S_SPK_DATA,
        .data_in_num  = I2S_PIN_NO_CHANGE,
    };

    esp_err_t err = i2s_driver_install(I2S_NUM_1, &spk_config, 0, NULL);
    if (err != ESP_OK) return false;

    err = i2s_set_pin(I2S_NUM_1, &spk_pins);
    return err == ESP_OK;
}

/**
 * Read audio samples from microphone into buffer.
 * Returns number of bytes read.
 */
inline size_t audio_read_mic(uint8_t* buffer, size_t max_bytes) {
    size_t bytes_read = 0;
    i2s_read(I2S_NUM_0, buffer, max_bytes, &bytes_read, portMAX_DELAY);
    return bytes_read;
}

/**
 * Write audio samples to speaker.
 * Returns number of bytes written.
 */
inline size_t audio_write_speaker(const uint8_t* buffer, size_t num_bytes) {
    size_t bytes_written = 0;
    i2s_write(I2S_NUM_1, buffer, num_bytes, &bytes_written, portMAX_DELAY);
    return bytes_written;
}

#endif // AUDIO_H
