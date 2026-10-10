"""Independent pulse and five-second communication alarm state."""
from enum import Enum
import math
from .config import COMMUNICATION_TIMEOUT_S, DEFAULT_LOW_BPM, DEFAULT_HIGH_BPM


class PulseAlarm(str, Enum):
    UNAVAILABLE = "UNAVAILABLE"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    LOW = "LOW"


class AlarmManager:
    def __init__(self, low=DEFAULT_LOW_BPM, high=DEFAULT_HIGH_BPM):
        self.set_limits(low, high)
        self.pulse = PulseAlarm.UNAVAILABLE
        self.communication = False
        self.monitoring_since = None
        self.last_packet_at = None

    def set_limits(self, low: float, high: float) -> None:
        if not math.isfinite(low) or not math.isfinite(high) or not 0 < low < high:
            raise ValueError("Alarm limits must satisfy 0 < low < high")
        self.low, self.high = float(low), float(high)

    def begin(self, now: float) -> None:
        self.monitoring_since = now
        self.last_packet_at = None
        self.communication = False
        self.pulse = PulseAlarm.UNAVAILABLE

    def stop(self) -> None:
        self.monitoring_since = None
        self.last_packet_at = None
        self.communication = False
        self.pulse = PulseAlarm.UNAVAILABLE

    def received(self, now: float) -> None:
        self.last_packet_at = now
        self.communication = False

    def tick(self, now: float) -> bool:
        reference = self.last_packet_at if self.last_packet_at is not None else self.monitoring_since
        self.communication = reference is not None and now - reference >= COMMUNICATION_TIMEOUT_S
        if self.communication:
            self.pulse = PulseAlarm.UNAVAILABLE
        return self.communication

    def update_pulse(self, bpm: float | None) -> PulseAlarm:
        if bpm is None or not math.isfinite(bpm):
            self.pulse = PulseAlarm.UNAVAILABLE
        elif bpm < self.low:
            self.pulse = PulseAlarm.LOW
        elif bpm > self.high:
            self.pulse = PulseAlarm.HIGH
        else:
            self.pulse = PulseAlarm.NORMAL
        return self.pulse
