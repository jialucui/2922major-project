#pragma once
#include <Arduino.h>

// User-specified wiring. Override using build flags if the hardware changes.
#ifndef PPG_PIN
#define PPG_PIN 25
#endif
#ifndef BUTTON_PIN
#define BUTTON_PIN 33
#endif
#ifndef LED_PIN
#define LED_PIN 32
#endif
// Assumptions to verify: switch shorts GPIO33 to GND; LED lights when HIGH.
#ifndef BUTTON_ACTIVE_LEVEL
#define BUTTON_ACTIVE_LEVEL LOW
#endif
#ifndef BUTTON_INPUT_MODE
#define BUTTON_INPUT_MODE INPUT_PULLUP
#endif
#ifndef LED_ACTIVE_LEVEL
#define LED_ACTIVE_LEVEL HIGH
#endif
#ifndef PPG_POLARITY
#define PPG_POLARITY 1
#endif
#if PPG_POLARITY != 1 && PPG_POLARITY != -1
#error "PPG_POLARITY must be 1 or -1."
#endif
#if BUTTON_ACTIVE_LEVEL != LOW && BUTTON_ACTIVE_LEVEL != HIGH
#error "BUTTON_ACTIVE_LEVEL must be LOW or HIGH."
#endif
#if LED_ACTIVE_LEVEL != LOW && LED_ACTIVE_LEVEL != HIGH
#error "LED_ACTIVE_LEVEL must be LOW or HIGH."
#endif

constexpr uint32_t SAMPLE_PERIOD_US = 20000;
constexpr uint32_t SERIAL_BAUD = 115200;
constexpr char DEVICE_NAME[] = "BMET2922-PPG";
