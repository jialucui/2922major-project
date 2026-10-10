"""SPP virtual serial-port receiver; all serial I/O stays off the GUI thread."""
from collections import deque
from dataclasses import dataclass
from enum import Enum
import queue
import threading
import time

import serial
from serial.tools import list_ports

from .config import (COMMUNICATION_TIMEOUT_S, RECONNECT_INTERVAL_S, SERIAL_BAUD,
                     SERIAL_READ_TIMEOUT_S, SERIAL_WRITE_TIMEOUT_S)
from .protocol import PacketParser, SequenceTracker, encode_set_recording


class ConnectionState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"


@dataclass(frozen=True)
class CommunicationEvent:
    kind: str
    value: object
    received_at: float
    generation: int


def available_ports() -> list[str]:
    return sorted(port.device for port in list_ports.comports())


class CommunicationManager:
    def __init__(self, serial_factory=serial.Serial, clock=time.monotonic):
        self._factory = serial_factory
        self._clock = clock
        self._lock = threading.Lock()
        self._target: str | None = None
        self._generation = 0
        self._active_generation = -1
        self._commands: deque[bytes] = deque(maxlen=8)
        self._events: queue.Queue[CommunicationEvent] = queue.Queue(maxsize=128)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._serial = None
        self._parser = PacketParser()
        self._sequence = SequenceTracker()
        self._state = ConnectionState.DISCONNECTED
        self._next_attempt = 0.0
        self._last_packet_at = 0.0
        self._attempted = False
        self._last_error = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="ppg-spp", daemon=True)
            self._thread.start()

    def connect(self, port: str) -> None:
        if not port.strip():
            raise ValueError("Select or enter the paired Bluetooth SPP serial port")
        with self._lock:
            self._target = port.strip()
            self._generation += 1
            self._commands.clear()
        self._wake.set()

    def disconnect(self) -> None:
        with self._lock:
            self._target = None
            self._generation += 1
            self._commands.clear()
        self._wake.set()

    def set_recording(self, enabled: bool) -> None:
        with self._lock:
            if self._target is None:
                raise ConnectionError("Connect before changing recording")
            self._commands.append(encode_set_recording(enabled))
        self._wake.set()

    def poll(self) -> list[CommunicationEvent]:
        with self._lock:
            generation = self._generation
        events = []
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            if event.generation == generation:
                events.append(event)
        return events

    def _emit(self, kind: str, value: object, now: float) -> None:
        event = CommunicationEvent(kind, value, now, self._active_generation)
        try:
            self._events.put_nowait(event)
        except queue.Full:
            try:
                self._events.get_nowait()
            except queue.Empty:
                pass
            self._events.put_nowait(event)

    def _set_state(self, state: ConnectionState, now: float) -> None:
        if self._state != state:
            self._state = state
            self._emit("state", state, now)

    def _close_serial(self) -> None:
        stream, self._serial = self._serial, None
        if stream is not None:
            try:
                stream.close()
            except (OSError, serial.SerialException):
                pass
        self._parser.reset()
        self._sequence.reset()

    def _lost(self, error: str, now: float) -> None:
        self._close_serial()
        with self._lock:
            self._commands.clear()
        if error != self._last_error:
            self._emit("error", error, now)
            self._last_error = error
        self._set_state(ConnectionState.RECONNECTING, now)
        self._next_attempt = now + RECONNECT_INTERVAL_S

    def _step(self) -> None:
        """One bounded serial operation cycle; also used by deterministic tests."""
        now = self._clock()
        with self._lock:
            target, generation = self._target, self._generation
        if generation != self._active_generation:
            self._close_serial()
            self._active_generation = generation
            self._attempted = False
            self._next_attempt = now
            self._last_error = None
            self._set_state(ConnectionState.DISCONNECTED, now)
        if target is None:
            return
        if self._serial is None:
            if now < self._next_attempt:
                return
            self._set_state(ConnectionState.RECONNECTING if self._attempted else ConnectionState.CONNECTING, now)
            self._attempted = True
            try:
                stream = self._factory(port=target, baudrate=SERIAL_BAUD,
                                       timeout=SERIAL_READ_TIMEOUT_S, write_timeout=SERIAL_WRITE_TIMEOUT_S)
                with self._lock:
                    obsolete = generation != self._generation
                if obsolete or self._stop.is_set():
                    stream.close()
                    return
                # Do not replay buffered data from before a reconnect.
                self._serial = stream
                stream.reset_input_buffer()
                self._last_packet_at = self._clock()
                self._set_state(ConnectionState.CONNECTED, self._last_packet_at)
                self._last_error = None
            except (OSError, serial.SerialException) as error:
                self._lost(str(error), self._clock())
                return
        try:
            with self._lock:
                commands = list(self._commands)
                self._commands.clear()
            for command in commands:
                if self._serial.write(command) != len(command):
                    raise serial.SerialTimeoutException("Incomplete recording command")
            data = self._serial.read(max(1, min(self._serial.in_waiting, 4096)))
            now = self._clock()
            invalid_before = self._parser.invalid_frames
            for packet in self._parser.feed(data):
                sequence = self._sequence.observe(packet.sequence)
                if sequence.out_of_order:
                    self._emit("error", f"Ignored duplicate/out-of-order packet {packet.sequence}", now)
                    continue
                self._last_packet_at = now
                self._emit("packet", packet, now)
            if self._parser.invalid_frames != invalid_before:
                self._emit("error", "Invalid packet discarded; serial stream resynchronized", now)
            if now - self._last_packet_at >= COMMUNICATION_TIMEOUT_S:
                self._lost("No valid new packet for 5 seconds", now)
        except (OSError, serial.SerialException) as error:
            self._lost(str(error), self._clock())

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._step()
                self._wake.wait(0.01)
                self._wake.clear()
        finally:
            self._close_serial()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        else:
            self._close_serial()
