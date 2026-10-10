from collections import deque
import time
import unittest
from ppg_monitor.communication import CommunicationManager, ConnectionState
from ppg_monitor.demo import DemoSource
from ppg_monitor.protocol import encode_packet


class FakeClock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now


class FakeSerial:
    def __init__(self):
        self.data = bytearray()
        self.closed = False
        self.writes = []
        self.read_error = None
        self.short_write = False
        self.reset_error = None
    @property
    def in_waiting(self): return len(self.data)
    def reset_input_buffer(self):
        if self.reset_error: raise self.reset_error
        self.data.clear()
    def read(self, count):
        if self.read_error: raise self.read_error
        result = bytes(self.data[:count])
        del self.data[:count]
        return result
    def write(self, data):
        self.writes.append(data)
        return 1 if self.short_write else len(data)
    def close(self): self.closed = True


class CommunicationTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.streams, self.opens = [], []
        self.unavailable = False
        def factory(**kwargs):
            self.opens.append((self.clock(), kwargs))
            if self.unavailable: raise OSError("SPP unavailable")
            stream = FakeSerial()
            self.streams.append(stream)
            return stream
        self.manager = CommunicationManager(factory, self.clock)
        self.addCleanup(self.manager.stop)
        self.manager.connect("SPP-PORT")
        self.manager._step()
        self.demo = DemoSource()

    def send(self):
        packet = self.demo.next_packet()
        self.streams[-1].data.extend(encode_packet(packet))
        self.manager._step()
        return packet

    def test_read_delivers_packet_with_receive_time(self):
        self.clock.now = 1.0
        packet = self.send()
        events = self.manager.poll()
        received = [event for event in events if event.kind == "packet"]
        self.assertEqual(received[0].value, packet)
        self.assertEqual(received[0].received_at, 1.0)
        self.assertEqual(self.opens[0][1]["timeout"], 0.1)
        self.assertEqual(self.opens[0][1]["write_timeout"], 0.3)

    def test_timeout_occurs_at_five_seconds_and_retries_after_one_second(self):
        self.manager.poll()
        self.clock.now = 4.999
        self.manager._step()
        self.assertFalse(self.streams[0].closed)
        self.clock.now = 5
        self.manager._step()
        self.assertTrue(self.streams[0].closed)
        self.assertIn(ConnectionState.RECONNECTING, [e.value for e in self.manager.poll() if e.kind == "state"])
        self.clock.now = 5.999
        self.manager._step()
        self.assertEqual(len(self.streams), 1)
        self.clock.now = 6
        self.manager._step()
        self.assertEqual(len(self.streams), 2)
        self.assertEqual(self.opens[-1][0], 6)

    def test_continuous_retry_and_recovery_within_ten_seconds(self):
        self.streams[0].read_error = OSError("lost")
        self.manager._step()
        self.unavailable = True
        for second in range(1, 15):
            self.clock.now = second
            self.manager._step()
        self.assertEqual(len(self.opens), 15)
        available_at = 14.2
        self.unavailable = False
        self.clock.now = 15
        self.manager._step()
        self.demo.sequence = 0
        self.send()
        received = [e for e in self.manager.poll() if e.kind == "packet"]
        self.assertEqual(received[-1].value.sequence, 0)
        self.assertLess(received[-1].received_at - available_at, 10)

    def test_duplicate_and_corrupt_frames_do_not_reset_watchdog(self):
        packet = self.send()
        self.clock.now = 4
        self.streams[0].data.extend(encode_packet(packet))
        corrupt = bytearray(encode_packet(self.demo.next_packet()))
        corrupt[70] ^= 1
        self.streams[0].data.extend(corrupt)
        self.manager._step()
        self.clock.now = 5
        self.manager._step()
        self.assertTrue(self.streams[0].closed)

    def test_explicit_disconnect_stops_retry_and_discards_queued_events(self):
        self.send()
        self.manager.disconnect()
        self.manager._step()
        self.clock.now = 100
        self.manager._step()
        self.assertEqual(len(self.opens), 1)
        self.assertTrue(self.streams[0].closed)
        self.assertFalse(any(e.kind == "packet" for e in self.manager.poll()))

    def test_recording_command_and_partial_write_failure(self):
        self.manager.set_recording(True)
        self.manager._step()
        self.assertEqual(self.streams[0].writes, [b"\x01\x01"])
        self.streams[0].short_write = True
        self.manager.set_recording(False)
        self.manager._step()
        self.assertTrue(self.streams[0].closed)

    def test_reconnect_resets_sequence_and_partial_frame(self):
        packet = self.send()
        self.streams[0].data.extend(encode_packet(packet)[:30])
        self.manager._step()
        self.streams[0].read_error = OSError("lost")
        self.manager._step()
        self.clock.now = 1
        self.manager._step()
        self.demo.sequence = 0
        self.send()
        packets = [e.value.sequence for e in self.manager.poll() if e.kind == "packet"]
        self.assertEqual(packets, [0, 0])

    def test_background_io_does_not_block_connect_caller(self):
        self.manager.start()
        start = time.perf_counter()
        self.manager.connect("new-port")
        self.assertLess(time.perf_counter() - start, 0.1)
        self.manager.stop()
        self.assertFalse(self.manager._thread.is_alive())


if __name__ == "__main__": unittest.main()
