import unittest

from ppg_monitor.protocol import (
    FragmentAssembler,
    Packet,
    ProtocolError,
    SequenceTracker,
    Status,
    decode_packet,
    encode_packet,
    fragment_frame,
)


class PacketProtocolTests(unittest.TestCase):
    def packet(self, sequence=19):
        return Packet(sequence, 0x12345678, 72, Status.RECORDING | Status.BPM_VALID, tuple(range(50)))

    def test_packet_round_trip_preserves_field_order_and_byte_order(self):
        packet = self.packet()
        encoded = encode_packet(packet)
        self.assertEqual(len(encoded), 115)
        self.assertEqual(encoded[:5], b"PP\x01\x13\x00")
        self.assertEqual(encoded[5:9], b"\x78\x56\x34\x12")
        self.assertEqual(decode_packet(encoded), packet)

    def test_crc_rejects_corrupted_payload(self):
        encoded = bytearray(encode_packet(self.packet()))
        encoded[20] ^= 0x40
        with self.assertRaisesRegex(ProtocolError, "CRC"):
            decode_packet(bytes(encoded))

    def test_fragment_reassembly_survives_out_of_order_notifications(self):
        frame = encode_packet(self.packet())
        fragments = fragment_frame(frame)
        self.assertTrue(all(len(fragment) <= 20 for fragment in fragments))
        assembler = FragmentAssembler()
        reassembled = None
        for fragment in fragments[1:] + fragments[:1]:
            reassembled = assembler.feed(fragment, now=1.0)
        self.assertEqual(reassembled, frame)

    def test_sequence_tracker_counts_gaps_and_wraps(self):
        tracker = SequenceTracker()
        self.assertEqual(tracker.observe(0xFFFE).missing, 0)
        self.assertEqual(tracker.observe(0x0001).missing, 2)
        self.assertTrue(tracker.observe(0x0000).out_of_order)

    def test_unavailable_bpm_matches_status(self):
        packet = Packet(1, 1000, None, Status(0), (0,) * 50)
        self.assertIsNone(decode_packet(encode_packet(packet)).embedded_bpm)


if __name__ == "__main__":
    unittest.main()