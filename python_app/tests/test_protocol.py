import random
import unittest
from ppg_monitor.protocol import (
    FRAME_LENGTH, Packet, PacketParser, ProtocolError, SequenceTracker, Status,
    crc16_ccitt, decode_packet, encode_packet, encode_set_recording,
)


class PacketProtocolTests(unittest.TestCase):
    def packet(self, sequence=19):
        return Packet(sequence, 0x12345678, 72.4, Status.RECORDING | Status.BPM_VALID, tuple(range(50)))

    def test_wire_layout_and_decimal_bpm(self):
        packet = self.packet(0x01020304)
        frame = encode_packet(packet)
        self.assertEqual(len(frame), 117)
        self.assertEqual(frame[:15], b"PP\x02\x04\x03\x02\x01\x78\x56\x34\x12\xd4\x02\x03\x32")
        self.assertEqual(frame[15:19], b"\x00\x00\x01\x00")
        self.assertEqual(decode_packet(frame), packet)

    def test_crc_known_vector_and_corruption(self):
        self.assertEqual(crc16_ccitt(b"123456789"), 0x29B1)
        frame = bytearray(encode_packet(self.packet()))
        frame[60] ^= 1
        with self.assertRaisesRegex(ProtocolError, "CRC"):
            decode_packet(frame)

    def test_chunked_and_concatenated_stream(self):
        packets = [self.packet(index) for index in range(20)]
        data = b"".join(encode_packet(packet) for packet in packets)
        rng, parser, received = random.Random(2922), PacketParser(), []
        while data:
            size = rng.randint(1, 300)
            received.extend(parser.feed(data[:size]))
            data = data[size:]
        self.assertEqual(received, packets)

    def test_every_possible_split_boundary(self):
        packet = self.packet()
        frame = encode_packet(packet)
        for boundary in range(1, FRAME_LENGTH):
            with self.subTest(boundary=boundary):
                parser = PacketParser()
                self.assertEqual(parser.feed(frame[:boundary]), [])
                self.assertEqual(parser.feed(frame[boundary:]), [packet])

    def test_parser_recovers_from_noise_corruption_and_truncated_frame(self):
        packet = self.packet()
        good = encode_packet(packet)
        bad = bytearray(good)
        bad[42] ^= 0x55
        parser = PacketParser()
        stream = b"junkP" + bytes(bad) + good[:48] + good + b"garbage"
        self.assertEqual(parser.feed(stream), [packet])
        self.assertGreater(parser.invalid_frames, 0)
        self.assertLess(len(parser._buffer), FRAME_LENGTH)

    def test_large_noise_does_not_accumulate(self):
        parser = PacketParser()
        parser.feed(b"X" * 100000 + b"P")
        self.assertEqual(len(parser._buffer), 1)
        self.assertEqual(parser.feed(encode_packet(self.packet())[1:]), [self.packet()])

    def test_sequence_uint32_wrap_gaps_and_duplicates(self):
        tracker = SequenceTracker()
        tracker.observe(0xFFFFFFFE)
        self.assertEqual(tracker.observe(1).missing, 2)
        self.assertTrue(tracker.observe(1).out_of_order)
        self.assertTrue(tracker.observe(0).out_of_order)
        self.assertEqual(tracker.observe(2).missing, 0)
        tracker.reset()
        self.assertFalse(tracker.observe(0).out_of_order)

    def test_invalid_version_count_length_and_bpm_flags(self):
        frame = encode_packet(self.packet())
        for offset, value in ((2, 1), (14, 49), (13, 0)):
            corrupt = bytearray(frame)
            corrupt[offset] = value
            corrupt[-2:] = crc16_ccitt(corrupt[:-2]).to_bytes(2, "little")
            with self.subTest(offset=offset), self.assertRaises(ProtocolError):
                decode_packet(corrupt)
        with self.assertRaises(ProtocolError):
            decode_packet(frame[:-1])

    def test_invalid_values_and_unavailable_bpm(self):
        for bpm in (float("nan"), float("inf"), -1, 6553.5):
            with self.subTest(bpm=bpm), self.assertRaises(ValueError):
                encode_packet(Packet(0, 0, bpm, Status.BPM_VALID, (0,) * 50))
        for sample in (-1, 65536, 2.5):
            with self.subTest(sample=sample), self.assertRaises(ValueError):
                encode_packet(Packet(0, 0, None, Status(0), (sample,) * 50))
        packet = Packet(0, 0, None, Status(0), (0,) * 50)
        self.assertEqual(decode_packet(encode_packet(packet)), packet)
        self.assertEqual(encode_set_recording(True), b"\x01\x01")
        self.assertEqual(encode_set_recording(False), b"\x01\x00")


if __name__ == "__main__":
    unittest.main()
