from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from ppg_monitor.alarms import AlarmManager, PulseAlarm
from ppg_monitor.logger import SystemLogger, format_event


class AlarmTests(unittest.TestCase):
    def test_threshold_boundaries_and_invalid_values(self):
        alarms = AlarmManager(50, 120)
        for bpm, expected in ((49.9, PulseAlarm.LOW), (50, PulseAlarm.NORMAL),
                              (120, PulseAlarm.NORMAL), (120.1, PulseAlarm.HIGH),
                              (None, PulseAlarm.UNAVAILABLE), (float("nan"), PulseAlarm.UNAVAILABLE)):
            self.assertEqual(alarms.update_pulse(bpm), expected)
        for low, high in ((120, 50), (50, 50), (0, 120), (50, float("inf"))):
            with self.assertRaises(ValueError): alarms.set_limits(low, high)

    def test_five_second_deadline_and_recovery(self):
        alarms = AlarmManager()
        alarms.begin(0)
        self.assertFalse(alarms.tick(4.999))
        self.assertTrue(alarms.tick(5))
        alarms.received(5.5)
        self.assertFalse(alarms.communication)
        self.assertFalse(alarms.tick(10.499))
        self.assertTrue(alarms.tick(10.5))
        alarms.stop()
        self.assertFalse(alarms.tick(100))


class LoggerTests(unittest.TestCase):
    def test_exact_required_timestamp_and_persistent_log(self):
        when = datetime(2024, 9, 19, 17, 46, 50)
        expected = "Thu Sep 19 17:46:50 2024: Pulse Low"
        self.assertEqual(format_event("Pulse Low", when), expected)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "logs" / "system.log"
            logger = SystemLogger(path)
            logger.log("Pulse Low", when)
            self.assertEqual(path.read_text(), expected + "\n")
            self.assertEqual(list(logger.entries), [expected])

    def test_file_error_preserves_visible_log(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = SystemLogger(directory)
            logger.log("Bluetooth Lost")
            self.assertIsNotNone(logger.write_error)
            self.assertTrue(logger.entries[-1].endswith(": Bluetooth Lost"))


if __name__ == "__main__": unittest.main()
