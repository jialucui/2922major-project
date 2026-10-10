import csv
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from ppg_monitor.protocol import Packet, Status
from ppg_monitor.recorder import SessionRecorder
from ppg_monitor.signal_processing import AnalysisResult, SignalQuality


def analysis(host_bpm):
    return AnalysisResult(
        raw=(100.0,) * 50,
        filtered=(1.0,) * 50,
        times_s=tuple(index / 50 for index in range(50)),
        frequencies_hz=(),
        spectrum_magnitude=(),
        host_bpm=host_bpm,
        dominant_frequency_hz=None,
        fft_bpm=None,
        quality=SignalQuality.GOOD if host_bpm is not None else SignalQuality.POOR,
        quality_reason="test",
        valid_interval_count=3 if host_bpm is not None else 0,
        signal_amplitude=10.0,
    )


class RecorderTests(unittest.TestCase):
    def test_duration_is_frozen_after_stop_even_when_clock_starts_at_zero(self):
        recorder = SessionRecorder()
        with patch("ppg_monitor.recorder.time.monotonic", return_value=0):
            recorder.start()
        with patch("ppg_monitor.recorder.time.monotonic", return_value=10):
            recorder.stop()
        self.assertEqual(recorder.summary().duration_seconds, 10)

    def test_summary_ignores_poor_quality_and_nonfinite_measurements(self):
        recorder = SessionRecorder()
        recorder.start()
        packet = Packet(0, 0, None, Status.RECORDING, (0,) * 50)
        recorder.add_packet(packet, replace(analysis(70), quality=SignalQuality.POOR))
        recorder.add_packet(packet, analysis(float("nan")))
        recorder.add_packet(packet, analysis(80))
        self.assertEqual(recorder.summary().valid_measurements, 1)
        self.assertEqual(recorder.summary().average_bpm, 80)

    def test_unrecorded_blocks_are_not_exported(self):
        recorder = SessionRecorder()
        recorder.start()
        recorder.add_packet(Packet(0, 0, None, Status(0), (0,) * 50), analysis(70))
        self.assertEqual(recorder.summary().sample_count, 0)

    def test_csv_exports_samples_and_summary_excludes_unavailable_bpm(self):
        recorder = SessionRecorder()
        recorder.start()
        for sequence, bpm in enumerate((70.0, None, 80.0)):
            packet = Packet(sequence, sequence * 1000, 75, Status.RECORDING | Status.BPM_VALID, tuple(range(50)))
            recorder.add_packet(packet, analysis(bpm))
        recorder.stop()
        summary = recorder.summary()
        self.assertEqual(summary.valid_measurements, 2)
        self.assertEqual(summary.minimum_bpm, 70)
        self.assertEqual(summary.maximum_bpm, 80)
        self.assertEqual(summary.average_bpm, 75)
        self.assertEqual(summary.sample_count, 150)

        with tempfile.TemporaryDirectory() as directory:
            path = recorder.export_csv(Path(directory) / "session.csv")
            with path.open(newline="", encoding="utf-8") as source:
                rows = list(csv.DictReader(source))
            self.assertEqual(len(rows), 150)
            self.assertEqual(rows[0]["ppg_raw"], "0")
            self.assertEqual(rows[0]["session_average_bpm"], "75.0")
            self.assertEqual(rows[50]["host_bpm"], "")


if __name__ == "__main__":
    unittest.main()
