#pragma once
#include <stdint.h>
#include <stddef.h>

namespace ppg {
constexpr uint8_t SAMPLE_COUNT = 50;
constexpr uint8_t FRAME_LENGTH = 117;
constexpr uint16_t UNAVAILABLE_BPM = 0xFFFF;
constexpr uint8_t RECORDING = 1 << 0;
constexpr uint8_t BPM_VALID = 1 << 1;
constexpr uint8_t BUTTON_PRESSED = 1 << 2;
constexpr uint8_t SENSOR_PRESENT = 1 << 3;
constexpr uint8_t TIMING_GAP = 1 << 4;

struct Frame { uint8_t bytes[FRAME_LENGTH]; };

inline uint16_t crc16(const uint8_t *data, size_t length) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < length; ++i) {
    crc ^= static_cast<uint16_t>(data[i]) << 8;
    for (uint8_t bit = 0; bit < 8; ++bit)
      crc = crc & 0x8000 ? static_cast<uint16_t>((crc << 1) ^ 0x1021) : static_cast<uint16_t>(crc << 1);
  }
  return crc;
}

inline void write16(uint8_t *out, uint16_t value) {
  out[0] = value & 0xFF;
  out[1] = value >> 8;
}

inline void write32(uint8_t *out, uint32_t value) {
  for (uint8_t i = 0; i < 4; ++i) out[i] = (value >> (8 * i)) & 0xFF;
}

inline Frame makeFrame(uint32_t sequence, uint32_t timestamp, uint16_t bpmTimesTen,
                       uint8_t status, const uint16_t *samples) {
  Frame frame{};
  frame.bytes[0] = 'P'; frame.bytes[1] = 'P'; frame.bytes[2] = 2;
  write32(&frame.bytes[3], sequence);
  write32(&frame.bytes[7], timestamp);
  write16(&frame.bytes[11], bpmTimesTen);
  frame.bytes[13] = status;
  frame.bytes[14] = SAMPLE_COUNT;
  for (uint8_t i = 0; i < SAMPLE_COUNT; ++i) write16(&frame.bytes[15 + 2 * i], samples[i]);
  write16(&frame.bytes[115], crc16(frame.bytes, 115));
  return frame;
}
}  // namespace ppg
