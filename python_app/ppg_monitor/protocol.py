"""Versioned binary BLE protocol shared with the ESP32 firmware."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag
import time


MAGIC = b"PP"
PROTOCOL_VERSION = 1
SAMPLE_RATE_HZ = 50
SAMPLE_PERIOD_MS = 20
SAMPLES_PER_PACKET = 50
UNAVAILABLE_BPM = 0xFFFF
FRAME_LENGTH = 115
BLE_FRAGMENT_HEADER_LENGTH = 4
BLE_DEFAULT_PAYLOAD_LENGTH = 20

SERVICE_UUID = "a6210001-8f3c-4f72-a87c-04a21b292201"
DATA_CHARACTERISTIC_UUID = "a6210002-8f3c-4f72-a87c-04a21b292201"
CONTROL_CHARACTERISTIC_UUID = "a6210003-8f3c-4f72-a87c-04a21b292201"
DEVICE_NAME = "BMET2922-PPG"


class Status(IntFlag):
    RECORDING = 1 << 0
    BPM_VALID = 1 << 1
    BUTTON_PRESSED = 1 << 2
    SENSOR_PRESENT = 1 << 3
    TIMING_GAP = 1 << 4


class ProtocolError(ValueError):
    """Raised when a wire frame fails structural or integrity checks."""


@dataclass(frozen=True)
class Packet:
    sequence: int
    block_start_ms: int
    embedded_bpm: int | None
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


def encode_packet(packet: Packet) -> bytes:
    if not 0 <= packet.sequence <= 0xFFFF:
        raise ValueError("sequence must fit uint16")
    if not 0 <= packet.block_start_ms <= 0xFFFFFFFF:
        raise ValueError("block_start_ms must fit uint32")
    if len(packet.samples) != SAMPLES_PER_PACKET:
        raise ValueError(f"exactly {SAMPLES_PER_PACKET} samples are required")
    if any(not 0 <= sample <= 0xFFFF for sample in packet.samples):
        raise ValueError("samples must fit uint16")

    bpm = UNAVAILABLE_BPM if packet.embedded_bpm is None else packet.embedded_bpm
    if bpm != UNAVAILABLE_BPM and not 0 <= bpm <= 0xFFFE:
        raise ValueError("embedded BPM must fit uint16 or be unavailable")
    status = int(packet.status)
    if bool(status & Status.BPM_VALID) != (packet.embedded_bpm is not None):
        raise ValueError("BPM_VALID status must match embedded_bpm availability")

    frame = bytearray()
    frame.extend(MAGIC)
    frame.append(PROTOCOL_VERSION)
    frame.extend(packet.sequence.to_bytes(2, "little"))
    frame.extend(packet.block_start_ms.to_bytes(4, "little"))
    frame.extend(bpm.to_bytes(2, "little"))
    frame.append(status & 0xFF)
    frame.append(SAMPLES_PER_PACKET)
    for sample in packet.samples:
        frame.extend(sample.to_bytes(2, "little"))
    frame.extend(crc16_ccitt(frame).to_bytes(2, "little"))
    assert len(frame) == FRAME_LENGTH
    return bytes(frame)


def decode_packet(frame: bytes) -> Packet:
    if len(frame) != FRAME_LENGTH:
        raise ProtocolError(f"expected {FRAME_LENGTH} bytes, received {len(frame)}")
    if frame[:2] != MAGIC:
        raise ProtocolError("invalid frame magic")
    if frame[2] != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol version {frame[2]}")
    if frame[12] != SAMPLES_PER_PACKET:
        raise ProtocolError("unexpected sample count")
    expected_crc = int.from_bytes(frame[-2:], "little")
    if crc16_ccitt(frame[:-2]) != expected_crc:
        raise ProtocolError("CRC mismatch")

    bpm_value = int.from_bytes(frame[9:11], "little")
    status = Status(frame[11])
    bpm = None if bpm_value == UNAVAILABLE_BPM else bpm_value
    if bool(status & Status.BPM_VALID) != (bpm is not None):
        raise ProtocolError("BPM_VALID status does not match BPM field")
    samples = tuple(int.from_bytes(frame[index : index + 2], "little") for index in range(13, 113, 2))
    return Packet(
        sequence=int.from_bytes(frame[3:5], "little"),
        block_start_ms=int.from_bytes(frame[5:9], "little"),
        embedded_bpm=bpm,
        status=status,
        samples=samples,
    )


def fragment_frame(frame: bytes, payload_length: int = BLE_DEFAULT_PAYLOAD_LENGTH) -> list[bytes]:
    if len(frame) != FRAME_LENGTH:
        raise ProtocolError("cannot fragment a frame with an invalid length")
    if payload_length <= BLE_FRAGMENT_HEADER_LENGTH:
        raise ValueError("BLE payload must leave room for frame data")
    sequence = int.from_bytes(frame[3:5], "little")
    chunk_size = payload_length - BLE_FRAGMENT_HEADER_LENGTH
    chunks = [frame[index : index + chunk_size] for index in range(0, len(frame), chunk_size)]
    count = len(chunks)
    return [
        sequence.to_bytes(2, "little") + bytes((index, count)) + chunk
        for index, chunk in enumerate(chunks)
    ]


class FragmentAssembler:
    """Reassemble one notification-fragmented frame at a time."""

    def __init__(self, timeout_seconds: float = 2.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._sequence: int | None = None
        self._count = 0
        self._parts: dict[int, bytes] = {}
        self._last_fragment_at = 0.0

    def reset(self) -> None:
        self._sequence = None
        self._count = 0
        self._parts.clear()

    def feed(self, fragment: bytes, now: float | None = None) -> bytes | None:
        now = time.monotonic() if now is None else now
        if len(fragment) <= BLE_FRAGMENT_HEADER_LENGTH:
            raise ProtocolError("fragment has no frame data")
        sequence = int.from_bytes(fragment[:2], "little")
        index, count = fragment[2], fragment[3]
        if count == 0 or index >= count:
            raise ProtocolError("invalid fragment index/count")
        if now - self._last_fragment_at > self.timeout_seconds:
            self.reset()
        if self._sequence != sequence or self._count != count:
            self._sequence = sequence
            self._count = count
            self._parts = {}
        data = bytes(fragment[BLE_FRAGMENT_HEADER_LENGTH:])
        previous = self._parts.get(index)
        if previous is not None and previous != data:
            self.reset()
            raise ProtocolError("conflicting duplicate fragment")
        self._parts[index] = data
        self._last_fragment_at = now
        if len(self._parts) != self._count:
            return None
        frame = b"".join(self._parts[position] for position in range(self._count))
        self.reset()
        if len(frame) != FRAME_LENGTH:
            raise ProtocolError("reassembled frame has an invalid length")
        return frame


class SequenceTracker:
    def __init__(self) -> None:
        self.last_sequence: int | None = None

    def reset(self) -> None:
        self.last_sequence = None

    def observe(self, sequence: int) -> SequenceResult:
        if not 0 <= sequence <= 0xFFFF:
            raise ValueError("sequence must fit uint16")
        if self.last_sequence is None:
            self.last_sequence = sequence
            return SequenceResult()
        distance = (sequence - self.last_sequence) & 0xFFFF
        if distance == 0 or distance >= 0x8000:
            return SequenceResult(out_of_order=True)
        self.last_sequence = sequence
        return SequenceResult(missing=distance - 1)


def encode_set_recording(enabled: bool) -> bytes:
    return bytes((0x01, int(enabled)))
