/**
 * ESP32-S3 Voice Terminal - PTT Button Handler
 *
 * Debounced push-to-talk button with press/release detection.
 */
#ifndef BUTTON_H
#define BUTTON_H

#include <Arduino.h>
#include "config.h"

#define DEBOUNCE_MS 50

static volatile bool _button_pressed = false;
static volatile unsigned long _button_last_change = 0;

/**
 * ISR for button state change.
 */
void IRAM_ATTR _button_isr() {
    unsigned long now = millis();
    if (now - _button_last_change > DEBOUNCE_MS) {
        _button_pressed = (digitalRead(PIN_PTT_BUTTON) == LOW);  // Active low
        _button_last_change = now;
    }
}

/**
 * Initialize the PTT button with interrupt.
 */
inline void button_init() {
    pinMode(PIN_PTT_BUTTON, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(PIN_PTT_BUTTON), _button_isr, CHANGE);
}

/**
 * Check if the button is currently held down.
 */
inline bool button_is_pressed() {
    return _button_pressed;
}

#endif // BUTTON_H
