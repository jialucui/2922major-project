"""Testable monitor state shared by the single-window GUI and simulated demo."""
from collections import deque
import math
import time

from .alarms import AlarmManager, PulseAlarm
from .communication import CommunicationEvent, ConnectionState
from .logger import SystemLogger
from .protocol import Packet, SAMPLE_PERIOD_MS, SAMPLES_PER_PACKET, SequenceTracker, Status
from .recorder import SessionRecorder
from .signal_processing import PPGProcessor, SignalQuality


def format_bpm(value: float | None) -> str:
    return "--" if value is None or not math.isfinite(value) else f"{value:.1f}"


class MonitorController:
    def __init__(self, logger: SystemLogger | None = None, clock=time.monotonic):
        self.logger = logger if logger is not None else SystemLogger()
        self.clock = clock
        self.processor = PPGProcessor()
        self.sequence = SequenceTracker()
        self.alarms = AlarmManager()
        self.recorder = SessionRecorder()
        self.sessions: list[SessionRecorder] = [self.recorder]
        self.connection = ConnectionState.DISCONNECTED
        self.monitoring = False
        self.latest_packet = None
        self.latest_analysis = None
        self.recording = False
        self.has_connected = False
        self.trend: deque[tuple[float, float | None, float | None]] = deque(maxlen=120)
        self.started_at = self.clock()
        self.revision = 0
        self.last_processing_ms = 0.0

    @property
    def embedded_bpm(self) -> float | None:
        packet = self.latest_packet
        if packet is None or not packet.status & Status.SENSOR_PRESENT or packet.status & Status.TIMING_GAP:
            return None
        if self.latest_analysis is not None and self.latest_analysis.quality == SignalQuality.NO_SIGNAL:
            return None
        return packet.embedded_bpm

    def begin(self) -> None:
        self.monitoring = True
        self.has_connected = False
        self.alarms.begin(self.clock())
        self.clear_live(reset_sequence=True)
        self.connection = ConnectionState.CONNECTING
        self.logger.log("Bluetooth Connecting")

    def disconnect(self) -> None:
        self.monitoring = False
        self.connection = ConnectionState.DISCONNECTED
        self.alarms.stop()
        self.clear_live(reset_sequence=True)
        self.stop_recording()
        self.logger.log("Bluetooth Disconnected")

    def clear_live(self, reset_sequence=False) -> None:
        self.processor.reset()
        if reset_sequence:
            self.sequence.reset()
        self.latest_packet = None
        self.latest_analysis = None
        self.alarms.update_pulse(None)
        if self.trend and self.trend[-1][1:] != (None, None):
            self.trend.append((self.clock() - self.started_at, None, None))
        self.revision += 1

    def stop_recording(self) -> None:
        if self.recording:
            self.recorder.stop()
            self.recording = False
            self.logger.log("Recording Stopped")

    def handle(self, event: CommunicationEvent) -> None:
        if not self.monitoring:
            return
        if event.kind == "packet":
            self.receive(event.value, event.received_at)
        elif event.kind == "error":
            self.logger.log(str(event.value))
        elif event.kind == "state":
            previous = self.connection
            self.connection = event.value
            if self.connection == ConnectionState.CONNECTED:
                self.clear_live(reset_sequence=True)
                self.logger.log("Bluetooth Reconnected" if self.has_connected else "Bluetooth Connected")
                self.has_connected = True
            elif self.connection == ConnectionState.RECONNECTING:
                if previous == ConnectionState.CONNECTED:
                    self.logger.log("Bluetooth Lost")
                self.clear_live(reset_sequence=True)
                self.stop_recording()
                if previous != ConnectionState.RECONNECTING:
                    self.logger.log("Bluetooth Reconnecting")
            self.revision += 1

    def _pulse_update(self) -> None:
        previous = self.alarms.pulse
        current = self.alarms.update_pulse(self.embedded_bpm)
        if current != previous:
            self.logger.log({PulseAlarm.HIGH: "Pulse High", PulseAlarm.LOW: "Pulse Low",
                             PulseAlarm.NORMAL: "Pulse Normal", PulseAlarm.UNAVAILABLE: "Pulse Unavailable"}[current])

    def set_limits(self, low: float, high: float) -> None:
        self.alarms.set_limits(low, high)
        self._pulse_update()
        self.revision += 1
        self.logger.log(f"Alarm Limits Set: {low:.1f}–{high:.1f} BPM")

    def receive(self, packet: Packet, received_at: float | None = None) -> None:
        if not self.monitoring:
            return
        began = time.perf_counter()
        now = self.clock() if received_at is None else received_at
        result = self.sequence.observe(packet.sequence)
        if result.out_of_order:
            self.logger.log(f"Ignored duplicate/out-of-order packet {packet.sequence}")
            return
        if result.missing:
            self.logger.log(f"Packet Loss: {result.missing} block(s) before {packet.sequence}")
            self.processor.reset()
        elif self.latest_packet is not None:
            elapsed = (packet.block_start_ms - self.latest_packet.block_start_ms) & 0xFFFFFFFF
            if abs(elapsed - SAMPLES_PER_PACKET * SAMPLE_PERIOD_MS) > SAMPLE_PERIOD_MS:
                self.logger.log(f"Device Timestamp Gap before {packet.sequence}")
                self.processor.reset()
        timing_valid = not bool(packet.status & Status.TIMING_GAP)
        if not timing_valid:
            self.logger.log(f"Sampling Timing Gap in block {packet.sequence}")
        analysis = self.processor.process_block(packet.samples, bool(packet.status & Status.SENSOR_PRESENT), timing_valid)
        communication_was_lost = self.alarms.communication
        self.alarms.received(now)
        if communication_was_lost:
            self.logger.log("Communication Restored")
        self.latest_packet, self.latest_analysis = packet, analysis
        self._pulse_update()
        active = bool(packet.status & Status.RECORDING)
        if active and not self.recording:
            if self.recorder.summary().sample_count:
                self.recorder = SessionRecorder()
                self.sessions.append(self.recorder)
            self.recorder.start()
            self.recording = True
            self.logger.log("Recording Started")
        if active:
            self.recorder.add_packet(packet, analysis, self.alarms.pulse.value)
        else:
            self.stop_recording()
        self.trend.append((now - self.started_at, self.embedded_bpm, analysis.host_bpm))
        self.revision += 1
        self.last_processing_ms = (time.perf_counter() - began) * 1000

    def tick(self) -> None:
        previous = self.alarms.communication
        if self.alarms.tick(self.clock()) and not previous:
            self.clear_live()
            self.stop_recording()
            self.logger.log("Communication Lost: no packet for 5 seconds")
            self.revision += 1
