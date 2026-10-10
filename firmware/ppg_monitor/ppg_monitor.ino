// BMET2922: 50 Hz acquisition, embedded BPM, and Bluetooth Classic SPP.
// Contributor ownership should be entered by the team in the final report.
#include <Arduino.h>
#include <BluetoothSerial.h>
#include "config.h"
#include "button.h"
#include "bpm.h"
#include "packet.h"

#if !defined(CONFIG_BT_ENABLED) || !defined(CONFIG_BLUEDROID_ENABLED) || !defined(CONFIG_BT_SPP_ENABLED)
#error "This project requires an ESP32 with Bluetooth Classic SPP (not ESP32-S3/C3/S2)."
#endif

namespace {
BluetoothSerial serialBT;
ppg::DebouncedButton button;
ppg::BeatDetector detector(PPG_POLARITY);
QueueHandle_t transmitQueue = nullptr;
uint16_t samples[ppg::SAMPLE_COUNT]{};
uint8_t sampleCount = 0;
uint32_t sequence = 0, blockStartMs = 0, nextSampleUs = 0;
bool recording = false, timingGap = false;
bool expectingRecordingValue = false;
uint32_t controlPrefixMs = 0;

void setRecording(bool active) { recording = active; }

void serviceControls(uint32_t now) {
  if (!serialBT.hasClient() || (expectingRecordingValue && now - controlPrefixMs > 1000))
    expectingRecordingValue = false;
  // Bound work so incoming traffic cannot starve the sampling deadline.
  for (uint8_t n = 0; n < 16 && serialBT.available(); ++n) {
    uint8_t value = static_cast<uint8_t>(serialBT.read());
    if (expectingRecordingValue) {
      if (value <= 1) setRecording(value == 1);
      expectingRecordingValue = false;
    } else if (value == 1) {
      expectingRecordingValue = true;
      controlPrefixMs = now;
    }
  }
}

void updateLed(uint32_t now) {
  const bool warning = !serialBT.hasClient();
  const bool lit = warning ? (now % 1000 < 250) : recording;
  digitalWrite(LED_PIN, lit ? LED_ACTIVE_LEVEL : !LED_ACTIVE_LEVEL);
}

void transmitTask(void *) {
  ppg::Frame frame;
  while (true) {
    if (xQueueReceive(transmitQueue, &frame, portMAX_DELAY) == pdTRUE && serialBT.hasClient()) {
      // BluetoothSerial.write may wait for its internal queue. It never runs
      // in the acquisition loop; a full mailbox retains the newest frame.
      serialBT.write(frame.bytes, ppg::FRAME_LENGTH);
    }
  }
}

void printSample(uint32_t now, uint16_t raw, uint16_t bpm) {
  char line[150];
#ifdef SERIAL_CSV
  int length = snprintf(line, sizeof(line), "%lu,%u,%.1f,%u,%u,%.1f\n",
                        static_cast<unsigned long>(now), raw, detector.thresholdRaw(),
                        button.pressed(), recording, bpm == ppg::UNAVAILABLE_BPM ? 0.0 : bpm / 10.0);
#else
  int length = snprintf(line, sizeof(line), "ppg:%u\tthreshold:%.1f\tbutton:%u\tbpm:%.1f\trecording:%u\n",
                        raw, detector.thresholdRaw(), button.pressed(),
                        bpm == ppg::UNAVAILABLE_BPM ? 0.0 : bpm / 10.0, recording);
#endif
  // An unplugged/slow Serial Plotter must not delay ADC/button sampling.
  if (length > 0 && length < static_cast<int>(sizeof(line)) && Serial.availableForWrite() >= length)
    Serial.write(reinterpret_cast<const uint8_t *>(line), length);
}

void acquireSample(uint32_t now, uint32_t missed) {
  uint16_t raw = static_cast<uint16_t>(analogRead(PPG_PIN));
  if (button.update(digitalRead(BUTTON_PIN) == BUTTON_ACTIVE_LEVEL)) setRecording(!recording);
  if (missed) { timingGap = true; detector = ppg::BeatDetector(PPG_POLARITY); }
  detector.update(raw, now);
  const uint16_t bpm = detector.bpmTimesTen();
  if (sampleCount == 0) blockStartMs = now;
  samples[sampleCount++] = raw;
  printSample(now, raw, bpm);
  if (sampleCount == ppg::SAMPLE_COUNT) {
    uint8_t flags = (recording ? ppg::RECORDING : 0) |
                    (bpm != ppg::UNAVAILABLE_BPM ? ppg::BPM_VALID : 0) |
                    (button.pressed() ? ppg::BUTTON_PRESSED : 0) |
                    (detector.sensorPresent() ? ppg::SENSOR_PRESENT : 0) |
                    (timingGap ? ppg::TIMING_GAP : 0);
    ppg::Frame frame = ppg::makeFrame(sequence++, blockStartMs, bpm, flags, samples);
    xQueueOverwrite(transmitQueue, &frame);
    sampleCount = 0;
    timingGap = false;
  }
}
}  // namespace

void setup() {
  Serial.begin(SERIAL_BAUD);
  pinMode(PPG_PIN, INPUT);
  pinMode(BUTTON_PIN, BUTTON_INPUT_MODE);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, !LED_ACTIVE_LEVEL);
  analogReadResolution(12);
  // GPIO25 is ADC2. This project does not enable Wi-Fi.
  transmitQueue = xQueueCreate(1, sizeof(ppg::Frame));
  if (transmitQueue == nullptr || !serialBT.begin(DEVICE_NAME) ||
      xTaskCreate(transmitTask, "ppg-spp", 4096, nullptr, 1, nullptr) != pdPASS) {
    Serial.println("PPG startup failed: queue, Bluetooth SPP, or transmit task");
    abort();
  }
#ifdef SERIAL_CSV
  Serial.println("timestamp_ms,ppg_raw,threshold_raw,button_pressed,recording,embedded_bpm");
#endif
  nextSampleUs = micros() + SAMPLE_PERIOD_US;
}

void loop() {
  const uint32_t nowUs = micros();
  if (static_cast<int32_t>(nowUs - nextSampleUs) >= 0) {
    const uint32_t missed = (nowUs - nextSampleUs) / SAMPLE_PERIOD_US;
    nextSampleUs += (missed + 1) * SAMPLE_PERIOD_US;
    acquireSample(millis(), missed);
  }
  serviceControls(millis());
  updateLed(millis());
  // Yield to FreeRTOS without delaying an entire sample period.
  delay(1);
}
