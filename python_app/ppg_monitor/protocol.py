"""Version 2, fixed-length Bluetooth SPP frames shared with the ESP32."""

from dataclasses import dataclass
from enum import IntFlag
import math
from numbers import Integral
import struct

MAGIC = b"PP"
PROTOCOL_VERSION = 2
SAMPLE_RATE_HZ = 50
SAMPLE_PERIOD_MS = 20
SAMPLES_PER_PACKET = 50
UNAVAILABLE_BPM = 0xFFFF
FRAME_LENGTH = 117
DEVICE_NAME = "BMET2922-PPG"
_HEADER = struct.Struct("<2sBIIHBB")
_SAMPLES = struct.Struct("<50H")


class Status(IntFlag):
    RECORDING = 1 << 0
    BPM_VALID = 1 << 1
    BUTTON_PRESSED = 1 << 2
    SENSOR_PRESENT = 1 << 3
    TIMING_GAP = 1 << 4


class ProtocolError(ValueError):
    """The frame failed a structural or integrity check."""


@dataclass(frozen=True)
class Packet:
    sequence: int
    block_start_ms: int
    embedded_bpm: float | None
    status: Status
    samples: tuple[int, ...]


@dataclass(frozen=True)
class SequenceResult:
    missing: int = 0
    out_of_order: bool = False


def crc16_ccitt(data: bytes, initial: int = 0xFFFF) -> int:
    crc = initial
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _uint(value: int, maximum: int, name: str) -> None:
    if not isinstance(value, Integral) or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be an integer between 0 and {maximum}")


def encode_packet(packet: Packet) -> bytes:
    _uint(packet.sequence, 0xFFFFFFFF, "sequence")
    _uint(packet.block_start_ms, 0xFFFFFFFF, "block_start_ms")
    _uint(packet.status, 0xFF, "status")
    if len(packet.samples) != SAMPLES_PER_PACKET:
        raise ValueError(f"exactly {SAMPLES_PER_PACKET} samples are required")
    for sample in packet.samples:
        _uint(sample, 0xFFFF, "sample")
    bpm = UNAVAILABLE_BPM
    if packet.embedded_bpm is not None:
        if not math.isfinite(packet.embedded_bpm) or not 0 <= packet.embedded_bpm <= 6553.4:
            raise ValueError("embedded BPM must be finite and fit the BPM-times-ten field")
        bpm = round(packet.embedded_bpm * 10)
    if bool(packet.status & Status.BPM_VALID) != (packet.embedded_bpm is not None):
        raise ValueError("BPM_VALID status must match embedded_bpm availability")
    payload = _HEADER.pack(MAGIC, PROTOCOL_VERSION, packet.sequence, packet.block_start_ms,
                           bpm, int(packet.status), SAMPLES_PER_PACKET) + _SAMPLES.pack(*packet.samples)
    return payload + struct.pack("<H", crc16_ccitt(payload))


def decode_packet(frame: bytes) -> Packet:
    if len(frame) != FRAME_LENGTH:
        raise ProtocolError(f"expected {FRAME_LENGTH} bytes, received {len(frame)}")
    magic, version, sequence, timestamp, bpm, flags, count = _HEADER.unpack_from(frame)
    if magic != MAGIC:
        raise ProtocolError("invalid frame magic")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol version {version}")
    if count != SAMPLES_PER_PACKET:
        raise ProtocolError("unexpected sample count")
    if crc16_ccitt(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
        raise ProtocolError("CRC mismatch")
    status = Status(flags)
    embedded_bpm = None if bpm == UNAVAILABLE_BPM else bpm / 10.0
    if bool(status & Status.BPM_VALID) != (embedded_bpm is not None):
        raise ProtocolError("BPM_VALID status does not match BPM field")
    return Packet(sequence, timestamp, embedded_bpm, status, _SAMPLES.unpack_from(frame, _HEADER.size))


class PacketParser:
    """Recover frames from arbitrary serial chunks, noise, and corrupt bytes."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.invalid_frames = 0
        self.discarded_bytes = 0

    def reset(self) -> None:
        self._buffer.clear()
        self.invalid_frames = 0
        self.discarded_bytes = 0

    def feed(self, data: bytes) -> list[Packet]:
        self._buffer.extend(data)
        packets = []
        while self._buffer:
            start = self._buffer.find(MAGIC)
            if start < 0:
                keep = 1 if self._buffer[-1:] == MAGIC[:1] else 0
                self.discarded_bytes += len(self._buffer) - keep
                self._buffer[:] = self._buffer[-1:] if keep else b""
                break
            if start:
                self.discarded_bytes += start
                del self._buffer[:start]
            if len(self._buffer) < FRAME_LENGTH:
                break
            try:
                packet = decode_packet(bytes(self._buffer[:FRAME_LENGTH]))
            except ProtocolError:
                self.invalid_frames += 1
                self.discarded_bytes += 1
                del self._buffer[0]
            else:
                packets.append(packet)
                del self._buffer[:FRAME_LENGTH]
        return packets


class SequenceTracker:
    def __init__(self) -> None:
        self.last_sequence: int | None = None

    def reset(self) -> None:
        self.last_sequence = None

    def observe(self, sequence: int) -> SequenceResult:
        _uint(sequence, 0xFFFFFFFF, "sequence")
        if self.last_sequence is None:
            self.last_sequence = sequence
            return SequenceResult()
        distance = (sequence - self.last_sequence) & 0xFFFFFFFF
        if distance == 0 or distance >= 0x80000000:
            return SequenceResult(out_of_order=True)
        self.last_sequence = sequence
        return SequenceResult(missing=distance - 1)


def encode_set_recording(enabled: bool) -> bytes:
    return bytes((0x01, int(enabled)))
