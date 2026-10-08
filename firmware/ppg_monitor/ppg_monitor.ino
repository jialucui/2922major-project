#include <Arduino.h>
#include <NimBLEDevice.h>

#ifndef PPG_PIN
#error "Define PPG_PIN as the confirmed ESP32 ADC GPIO."
#endif
#ifndef BUTTON_PIN
#error "Define BUTTON_PIN as the confirmed button GPIO."
#endif
#ifndef LED_PIN
#error "Define LED_PIN as the confirmed status LED GPIO."
#endif
#ifndef BUTTON_ACTIVE_LEVEL
#error "Define BUTTON_ACTIVE_LEVEL as LOW or HIGH for the wired button."
#endif
#ifndef LED_ACTIVE_LEVEL
#error "Define LED_ACTIVE_LEVEL as LOW or HIGH for the wired LED."
#endif
#ifndef PPG_POLARITY
#error "Define PPG_POLARITY as 1 or -1 after checking sensor pulse direction."
#endif

#if PPG_POLARITY != 1 && PPG_POLARITY != -1
#error "PPG_POLARITY must be 1 or -1."
#endif

namespace {
constexpr uint32_t SAMPLE_PERIOD_MS = 20;
constexpr uint32_t SERIAL_BAUD = 115200;
constexpr uint8_t SAMPLES_PER_PACKET = 50;
constexpr uint8_t PACKET_LENGTH = 115;
constexpr uint8_t FRAGMENT_DATA_LENGTH = 16;
constexpr uint8_t FRAGMENT_COUNT = (PACKET_LENGTH + FRAGMENT_DATA_LENGTH - 1) / FRAGMENT_DATA_LENGTH;
constexpr uint8_t MAX_IBI_COUNT = 4;
constexpr uint16_t UNAVAILABLE_BPM = 0xFFFF;
constexpr uint8_t STATUS_RECORDING = 1 << 0;
constexpr uint8_t STATUS_BPM_VALID = 1 << 1;
constexpr uint8_t STATUS_BUTTON_PRESSED = 1 << 2;
constexpr uint8_t STATUS_SENSOR_PRESENT = 1 << 3;
constexpr uint8_t STATUS_TIMING_GAP = 1 << 4;

constexpr char SERVICE_UUID[] = "a6210001-8f3c-4f72-a87c-04a21b292201";
constexpr char DATA_UUID[] = "a6210002-8f3c-4f72-a87c-04a21b292201";
constexpr char CONTROL_UUID[] = "a6210003-8f3c-4f72-a87c-04a21b292201";
constexpr char DEVICE_NAME[] = "BMET2922-PPG";

struct Sample {
  uint32_t timestampMs;
  uint16_t ppgRaw;
};

Sample sampleBlock[SAMPLES_PER_PACKET];
uint8_t sampleCount = 0;
uint32_t blockStartMs = 0;
uint32_t nextSampleDeadlineMs = 0;
bool blockHasTimingGap = false;
uint16_t packetSequence = 0;

NimBLEServer *bleServer = nullptr;
NimBLECharacteristic *dataCharacteristic = nullptr;
NimBLECharacteristic *controlCharacteristic = nullptr;
uint8_t pendingFrame[PACKET_LENGTH]{};
uint8_t nextFragment = 0;
bool framePending = false;
uint32_t nextFragmentAtMs = 0;

volatile bool recordingActive = false;
bool stableButtonPressed = false;
uint8_t candidateButtonLevel = HIGH;
uint8_t consistentButtonSamples = 0;

bool detectorInitialized = false;
float baseline = 0.0F;
float amplitudeEnvelope = 0.0F;
float previousAc = 0.0F;
float previousPreviousAc = 0.0F;
uint32_t previousAcTimestampMs = 0;
bool havePreviousAc = false;
bool haveLastBeat = false;
uint32_t lastBeatTimestampMs = 0;
uint32_t lastBeatCandidateMs = 0;
uint16_t ibiHistory[MAX_IBI_COUNT]{};
uint8_t ibiCount = 0;
uint8_t ibiWriteIndex = 0;
uint16_t embeddedBpm = UNAVAILABLE_BPM;

uint16_t clampAdc(float value) {
  if (value < 0.0F) return 0;
  if (value > 4095.0F) return 4095;
  return static_cast<uint16_t>(value + 0.5F);
}

float detectionThreshold() {
  const float amplitude = amplitudeEnvelope * 0.45F;
  return amplitude > 6.0F ? amplitude : 6.0F;
}

float thresholdInRawUnits() {
  return baseline + static_cast<float>(PPG_POLARITY) * detectionThreshold();
}

uint16_t calculateBpm() {
  if (!haveLastBeat || millis() - lastBeatTimestampMs > 3000 || ibiCount == 0) {
    embeddedBpm = UNAVAILABLE_BPM;
    return embeddedBpm;
  }
  uint32_t intervalTotal = 0;
  for (uint8_t index = 0; index < ibiCount; ++index) {
    intervalTotal += ibiHistory[index];
  }
  embeddedBpm = static_cast<uint16_t>(60000UL * ibiCount / intervalTotal);
  return embeddedBpm;
}

void registerPeak(uint32_t timestampMs) {
  if (timestampMs - lastBeatCandidateMs < 250) return;
  lastBeatCandidateMs = timestampMs;
  if (!haveLastBeat) {
    haveLastBeat = true;
    lastBeatTimestampMs = timestampMs;
    return;
  }

  const uint32_t intervalMs = timestampMs - lastBeatTimestampMs;
  if (intervalMs < 300) return;
  if (intervalMs > 2000) {
    ibiCount = 0;
    ibiWriteIndex = 0;
    lastBeatTimestampMs = timestampMs;
    embeddedBpm = UNAVAILABLE_BPM;
    return;
  }

  ibiHistory[ibiWriteIndex] = static_cast<uint16_t>(intervalMs);
  ibiWriteIndex = (ibiWriteIndex + 1) % MAX_IBI_COUNT;
  if (ibiCount < MAX_IBI_COUNT) ibiCount++;
  lastBeatTimestampMs = timestampMs;
}

void updateEmbeddedDetector(uint16_t raw, uint32_t timestampMs) {
  if (!detectorInitialized) {
    baseline = raw;
    detectorInitialized = true;
  }
  baseline += 0.02F * (static_cast<float>(raw) - baseline);
  const float ac = static_cast<float>(PPG_POLARITY) * (static_cast<float>(raw) - baseline);
  amplitudeEnvelope += 0.02F * (fabsf(ac) - amplitudeEnvelope);

  if (havePreviousAc && previousAc > previousPreviousAc && previousAc >= ac &&
      previousAc > detectionThreshold()) {
    registerPeak(previousAcTimestampMs);
  }
  previousPreviousAc = previousAc;
  previousAc = ac;
  previousAcTimestampMs = timestampMs;
  havePreviousAc = true;
  calculateBpm();
}

void updateButton(uint8_t rawLevel) {
  if (rawLevel != candidateButtonLevel) {
    candidateButtonLevel = rawLevel;
    consistentButtonSamples = 1;
  } else if (consistentButtonSamples < 5) {
    consistentButtonSamples++;
  }

  if (consistentButtonSamples == 5 && rawLevel != (stableButtonPressed ? BUTTON_ACTIVE_LEVEL : !BUTTON_ACTIVE_LEVEL)) {
    const bool newPressed = rawLevel == BUTTON_ACTIVE_LEVEL;
    stableButtonPressed = newPressed;
    if (newPressed) recordingActive = !recordingActive;
  }
  digitalWrite(LED_PIN, recordingActive ? LED_ACTIVE_LEVEL : !LED_ACTIVE_LEVEL);
}

uint16_t crc16Ccitt(const uint8_t *data, size_t length) {
  uint16_t crc = 0xFFFF;
  for (size_t index = 0; index < length; ++index) {
    crc ^= static_cast<uint16_t>(data[index]) << 8;
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc & 0x8000) ? static_cast<uint16_t>((crc << 1) ^ 0x1021) : static_cast<uint16_t>(crc << 1);
    }
  }
  return crc;
}

void writeU16(uint8_t *destination, uint16_t value) {
  destination[0] = static_cast<uint8_t>(value & 0xFF);
  destination[1] = static_cast<uint8_t>(value >> 8);
}

void writeU32(uint8_t *destination, uint32_t value) {
  destination[0] = static_cast<uint8_t>(value & 0xFF);
  destination[1] = static_cast<uint8_t>((value >> 8) & 0xFF);
  destination[2] = static_cast<uint8_t>((value >> 16) & 0xFF);
  destination[3] = static_cast<uint8_t>(value >> 24);
}

uint8_t makeStatus() {
  uint8_t status = 0;
  if (recordingActive) status |= STATUS_RECORDING;
  if (embeddedBpm != UNAVAILABLE_BPM) status |= STATUS_BPM_VALID;
  if (stableButtonPressed) status |= STATUS_BUTTON_PRESSED;
  if (amplitudeEnvelope >= 8.0F) status |= STATUS_SENSOR_PRESENT;
  if (blockHasTimingGap) status |= STATUS_TIMING_GAP;
  return status;
}

void buildFrame() {
  pendingFrame[0] = 'P';
  pendingFrame[1] = 'P';
  pendingFrame[2] = 1;
  writeU16(&pendingFrame[3], packetSequence++);
  writeU32(&pendingFrame[5], blockStartMs);
  writeU16(&pendingFrame[9], embeddedBpm);
  pendingFrame[11] = makeStatus();
  pendingFrame[12] = SAMPLES_PER_PACKET;
  for (uint8_t index = 0; index < SAMPLES_PER_PACKET; ++index) {
    writeU16(&pendingFrame[13 + index * 2], sampleBlock[index].ppgRaw);
  }
  writeU16(&pendingFrame[113], crc16Ccitt(pendingFrame, 113));
  framePending = true;
  nextFragment = 0;
  nextFragmentAtMs = millis();
  blockHasTimingGap = false;
}

void serviceBluetooth(uint32_t nowMs) {
  if (bleServer == nullptr || bleServer->getConnectedCount() == 0) {
    framePending = false;
    return;
  }
  if (!framePending || static_cast<int32_t>(nowMs - nextFragmentAtMs) < 0) return;

  const uint8_t offset = nextFragment * FRAGMENT_DATA_LENGTH;
  const uint8_t remaining = PACKET_LENGTH - offset;
  const uint8_t dataLength = remaining < FRAGMENT_DATA_LENGTH ? remaining : FRAGMENT_DATA_LENGTH;
  uint8_t fragment[20];
  writeU16(fragment, static_cast<uint16_t>(packetSequence - 1));
  fragment[2] = nextFragment;
  fragment[3] = FRAGMENT_COUNT;
  memcpy(&fragment[4], &pendingFrame[offset], dataLength);
  dataCharacteristic->setValue(fragment, dataLength + 4);
  if (dataCharacteristic->notify()) {
    nextFragment++;
    if (nextFragment == FRAGMENT_COUNT) framePending = false;
  }
  nextFragmentAtMs = nowMs + 20;
}

class ControlCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic *characteristic, NimBLEConnInfo &) override {
    const std::string command = characteristic->getValue();
    if (command.size() == 2 && static_cast<uint8_t>(command[0]) == 0x01 &&
        (command[1] == 0 || command[1] == 1)) {
      recordingActive = command[1] == 1;
      digitalWrite(LED_PIN, recordingActive ? LED_ACTIVE_LEVEL : !LED_ACTIVE_LEVEL);
    }
  }
};

void startBluetooth() {
  NimBLEDevice::init(DEVICE_NAME);
  bleServer = NimBLEDevice::createServer();
  NimBLEService *service = bleServer->createService(SERVICE_UUID);
  dataCharacteristic = service->createCharacteristic(DATA_UUID, NIMBLE_PROPERTY::NOTIFY);
  controlCharacteristic = service->createCharacteristic(
      CONTROL_UUID, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
  controlCharacteristic->setCallbacks(new ControlCallbacks());
  service->start();
  NimBLEAdvertising *advertising = NimBLEDevice::getAdvertising();
  advertising->addServiceUUID(SERVICE_UUID);
  advertising->start();
}

void printSample(const Sample &sample, float thresholdRaw) {
#if defined(SERIAL_CSV)
  Serial.printf("%lu,%u,%.1f,%u,%u,%u\n", static_cast<unsigned long>(sample.timestampMs),
                sample.ppgRaw, thresholdRaw, stableButtonPressed, recordingActive, embeddedBpm);
#else
  Serial.printf("ppg:%u\tthreshold:%.1f\tbutton:%u\tbpm:%u\trecording:%u\n",
                sample.ppgRaw, thresholdRaw, stableButtonPressed,
                embeddedBpm == UNAVAILABLE_BPM ? 0 : embeddedBpm, recordingActive);
#endif
}

void acquireSample(uint32_t timestampMs, uint32_t missedSlots) {
  const uint16_t raw = static_cast<uint16_t>(analogRead(PPG_PIN));
  updateButton(static_cast<uint8_t>(digitalRead(BUTTON_PIN)));
  updateEmbeddedDetector(raw, timestampMs);
  if (sampleCount == 0) blockStartMs = timestampMs;
  sampleBlock[sampleCount++] = {timestampMs, raw};
  if (missedSlots > 0) blockHasTimingGap = true;

  const Sample current{timestampMs, raw};
  printSample(current, thresholdInRawUnits());
  if (sampleCount == SAMPLES_PER_PACKET) {
    buildFrame();
    sampleCount = 0;
  }
}
}  // namespace

void setup() {
  Serial.begin(SERIAL_BAUD);
  pinMode(PPG_PIN, INPUT);
  pinMode(BUTTON_PIN, INPUT);
  pinMode(LED_PIN, OUTPUT);
  analogReadResolution(12);
  candidateButtonLevel = static_cast<uint8_t>(digitalRead(BUTTON_PIN));
  stableButtonPressed = candidateButtonLevel == BUTTON_ACTIVE_LEVEL;
  consistentButtonSamples = 5;
  digitalWrite(LED_PIN, recordingActive ? LED_ACTIVE_LEVEL : !LED_ACTIVE_LEVEL);
#if defined(SERIAL_CSV)
  Serial.println("timestamp_ms,ppg_raw,threshold_raw,button_pressed,recording,embedded_bpm");
#endif
  startBluetooth();
  nextSampleDeadlineMs = millis() + SAMPLE_PERIOD_MS;
}

void loop() {
  const uint32_t nowMs = millis();
  if (static_cast<int32_t>(nowMs - nextSampleDeadlineMs) >= 0) {
    const uint32_t lateByMs = nowMs - nextSampleDeadlineMs;
    const uint32_t missedSlots = lateByMs / SAMPLE_PERIOD_MS;
    nextSampleDeadlineMs += (missedSlots + 1) * SAMPLE_PERIOD_MS;
    acquireSample(nowMs, missedSlots);
  }
  serviceBluetooth(millis());
}