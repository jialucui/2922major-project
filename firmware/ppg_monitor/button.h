#pragma once
#include <stdint.h>

namespace ppg {
class DebouncedButton {
 public:
  // Returns true exactly once for each debounced press, including a held
  // button at startup only after five actual sampled readings.
  bool update(bool rawPressed) {
    if (rawPressed != candidate_) { candidate_ = rawPressed; count_ = 1; }
    else if (count_ < 5) { ++count_; }
    if (count_ == 5 && pressed_ != candidate_) {
      pressed_ = candidate_;
      return pressed_;
    }
    return false;
  }
  bool pressed() const { return pressed_; }
 private:
  bool candidate_ = false;
  bool pressed_ = false;
  uint8_t count_ = 0;
};
}  // namespace ppg
