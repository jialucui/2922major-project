"""Deterministic 72.4 BPM source for a clearly labelled, hardware-free demo."""
import math
from .protocol import Packet, PacketParser, Status, encode_packet


class DemoSource:
    def __init__(self):
        self.sequence = 0
        self.recording = False
        self.parser = PacketParser()

    def next_packet(self) -> Packet:
        status = Status.BPM_VALID | Status.SENSOR_PRESENT
        if self.recording:
            status |= Status.RECORDING
        samples = tuple(round(1800 + 240 * max(0, math.sin(2 * math.pi * (72.4 / 60) * index / 50)))
                        for index in range(self.sequence * 50, (self.sequence + 1) * 50))
        packet = Packet(self.sequence & 0xFFFFFFFF, (self.sequence * 1000) & 0xFFFFFFFF, 72.4, status, samples)
        self.sequence += 1
        frame = encode_packet(packet)
        self.parser.feed(frame[:17])
        return self.parser.feed(frame[17:])[0]
