from dataclasses import replace
import unittest
from ppg_monitor.alarms import PulseAlarm
from ppg_monitor.communication import CommunicationEvent, ConnectionState
from ppg_monitor.controller import MonitorController, format_bpm
from ppg_monitor.demo import DemoSource
from ppg_monitor.protocol import Status


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.model = MonitorController(clock=lambda: self.now)
        self.model.begin()
        self.demo = DemoSource()
        self.model.handle(CommunicationEvent("state", ConnectionState.CONNECTED, self.now, 0))

    def stream(self, count=12):
        for _ in range(count):
            self.model.receive(self.demo.next_packet(), self.now)
            self.now += 1

    def test_graphical_history_and_one_decimal_text(self):
        self.stream()
        self.assertEqual(format_bpm(self.model.embedded_bpm), "72.4")
        self.assertEqual(format_bpm(70), "70.0")
        self.assertEqual(format_bpm(None), "--")
        self.assertEqual(len(self.model.trend), 12)
        self.assertAlmostEqual(self.model.latest_analysis.host_bpm, 72.4, delta=5)

    def test_alarm_transitions_log_once_including_limit_changes(self):
        self.model.set_limits(80, 120)
        self.stream(3)
        self.assertEqual(self.model.alarms.pulse, PulseAlarm.LOW)
        self.assertEqual(sum(entry.endswith(": Pulse Low") for entry in self.model.logger.entries), 1)
        self.model.set_limits(50, 60)
        self.assertEqual(self.model.alarms.pulse, PulseAlarm.HIGH)
        self.model.set_limits(50, 120)
        self.assertEqual(self.model.alarms.pulse, PulseAlarm.NORMAL)

    def test_five_second_communication_alarm_and_first_packet_recovery(self):
        self.now = 4.999
        self.model.tick()
        self.assertFalse(self.model.alarms.communication)
        self.now = 5
        self.model.tick()
        self.assertTrue(self.model.alarms.communication)
        self.model.receive(self.demo.next_packet(), self.now)
        self.assertFalse(self.model.alarms.communication)
        self.assertTrue(any("Communication Restored" in line for line in self.model.logger.entries))

    def test_timeout_clears_values_and_new_data_rebuilds_filter(self):
        self.stream()
        self.now = 16
        self.model.tick()
        self.assertIsNone(self.model.latest_analysis)
        self.assertIsNone(self.model.embedded_bpm)
        self.stream(1)
        self.assertEqual(len(self.model.latest_analysis.raw), 50)
        self.assertIsNone(self.model.latest_analysis.host_bpm)

    def test_reconnect_resets_sequence_and_retains_recordings(self):
        self.demo.recording = True
        self.stream(3)
        self.model.handle(CommunicationEvent("state", ConnectionState.RECONNECTING, self.now, 0))
        self.assertFalse(self.model.recorder.active)
        self.model.handle(CommunicationEvent("state", ConnectionState.CONNECTED, self.now, 0))
        self.demo.sequence = 0
        self.stream(1)
        self.assertEqual(self.model.latest_packet.sequence, 0)
        self.assertEqual(len(self.model.sessions), 2)
        self.assertEqual(self.model.sessions[0].summary().sample_count, 150)
        self.assertEqual(self.model.sessions[1].summary().sample_count, 50)

    def test_stopped_packets_and_duplicates_are_not_recorded(self):
        self.demo.recording = True
        self.stream(2)
        self.model.receive(self.model.latest_packet, self.now)
        self.demo.recording = False
        self.stream(1)
        self.assertEqual(self.model.recorder.summary().sample_count, 100)
        self.assertFalse(self.model.recording)

    def test_packet_loss_and_timestamp_discontinuity_clear_analysis_history(self):
        self.stream()
        self.demo.sequence += 1
        self.stream(1)
        self.assertEqual(len(self.model.latest_analysis.raw), 50)
        packet = replace(self.demo.next_packet(), block_start_ms=50000)
        self.model.receive(packet, self.now)
        self.assertEqual(len(self.model.latest_analysis.raw), 50)

    def test_explicit_disconnect_disables_timeout_and_ignores_late_packets(self):
        self.stream()
        self.model.disconnect()
        self.now = 100
        self.model.tick()
        self.model.receive(self.demo.next_packet(), self.now)
        self.assertIsNone(self.model.latest_analysis)
        self.assertFalse(self.model.alarms.communication)

    def test_timing_gap_withholds_embedded_and_host_bpm(self):
        self.stream()
        packet = self.demo.next_packet()
        self.model.receive(replace(packet, status=packet.status | Status.TIMING_GAP), self.now)
        self.assertIsNone(self.model.embedded_bpm)
        self.assertIsNone(self.model.latest_analysis.host_bpm)

    def test_flat_signal_with_lingering_sensor_flag_withholds_embedded_value(self):
        self.stream()
        packet = replace(self.demo.next_packet(), samples=(1800,) * 50)
        self.model.receive(packet, self.now)
        self.assertIsNone(self.model.embedded_bpm)
        self.assertEqual(self.model.alarms.pulse, PulseAlarm.UNAVAILABLE)


if __name__ == "__main__": unittest.main()
