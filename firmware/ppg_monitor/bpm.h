#pragma once
#include <math.h>
#include <stdint.h>
#include "packet.h"

namespace ppg {
class BeatDetector {
 public:
  explicit BeatDetector(int polarity) : polarity_(polarity) {}
  void update(uint16_t raw, uint32_t now) {
    if (!initialized_) { baseline_ = raw; initialized_ = true; }
    baseline_ += 0.02F * (static_cast<float>(raw) - baseline_);
    float ac = polarity_ * (static_cast<float>(raw) - baseline_);
    envelope_ += 0.02F * (fabsf(ac) - envelope_);
    float threshold = fmaxf(6.0F, envelope_ * 0.45F);
    // Rearm only after the pulse has fallen below half the threshold.
    if (ac < threshold * 0.5F) armed_ = true;
    if (armed_ && previous_ > beforePrevious_ && previous_ >= ac && previous_ > threshold) {
      if (!haveBeat_ || previousTime_ - lastBeat_ >= 300) {
        registerBeat(previousTime_);
        armed_ = false;
      }
    }
    beforePrevious_ = previous_;
    previous_ = ac;
    previousTime_ = now;
    if (haveBeat_ && now - lastBeat_ > 3000) {
      count_ = 0; writeIndex_ = 0; haveBeat_ = false;
    }
  }
  uint16_t bpmTimesTen() const {
    if (!haveBeat_ || count_ == 0 || envelope_ < 8.0F) return UNAVAILABLE_BPM;
    uint32_t total = 0;
    for (uint8_t i = 0; i < count_; ++i) total += intervals_[i];
    return static_cast<uint16_t>((600000UL * count_ + total / 2) / total);
  }
  float thresholdRaw() const { return baseline_ + polarity_ * fmaxf(6.0F, envelope_ * 0.45F); }
  bool sensorPresent() const { return envelope_ >= 8.0F; }
 private:
  void registerBeat(uint32_t now) {
    if (haveBeat_) {
      uint32_t interval = now - lastBeat_;
      if (interval < 300) return;
      if (interval <= 2000) {
        intervals_[writeIndex_] = static_cast<uint16_t>(interval);
        writeIndex_ = (writeIndex_ + 1) % 4;
        if (count_ < 4) ++count_;
      } else { count_ = 0; writeIndex_ = 0; }
    }
    haveBeat_ = true; lastBeat_ = now;
  }
  int polarity_;
  bool initialized_ = false, armed_ = true, haveBeat_ = false;
  float baseline_ = 0, envelope_ = 0, previous_ = 0, beforePrevious_ = 0;
  uint32_t previousTime_ = 0, lastBeat_ = 0;
  uint16_t intervals_[4]{};
  uint8_t count_ = 0, writeIndex_ = 0;
};
}  // namespace ppg
