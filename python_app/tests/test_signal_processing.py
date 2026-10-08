import math
import unittest

from ppg_monitor.signal_processing import PPGProcessor, SignalQuality


class SignalProcessingTests(unittest.TestCase):
    @staticmethod
    def _stream(signal):
        processor = PPGProcessor()
        result = None
        for offset in range(0, len(signal), 50):
            result = processor.process_block(signal[offset : offset + 50], sensor_present=True)
        return result

    def test_synthetic_72_bpm_has_good_quality_and_independent_estimates(self):
        signal = [
            int(1800 + 240 * max(0.0, math.sin(2 * math.pi * 1.2 * index / 50)))
            for index in range(600)
        ]
        result = self._stream(signal)
        self.assertEqual(result.quality, SignalQuality.GOOD)
        self.assertAlmostEqual(result.host_bpm, 72, delta=5)
        self.assertAlmostEqual(result.fft_bpm, 72, delta=6)
        self.assertEqual(len(result.raw), 600)
        self.assertEqual(len(result.filtered), 600)

    def test_flat_input_is_no_signal_and_has_no_bpm(self):
        result = PPGProcessor().process_block([2000] * 50, sensor_present=False)
        self.assertEqual(result.quality, SignalQuality.NO_SIGNAL)
        self.assertIsNone(result.host_bpm)
        self.assertIsNone(result.fft_bpm)

    def test_timing_gap_withholds_bpm_and_requires_new_history(self):
        processor = PPGProcessor()
        pulse = [int(1800 + 240 * max(0.0, math.sin(2 * math.pi * 1.2 * index / 50))) for index in range(50)]
        result = None
        for _ in range(10):
            result = processor.process_block(pulse, sensor_present=True)
        self.assertEqual(result.quality, SignalQuality.GOOD)
        gap_result = processor.process_block(pulse, sensor_present=True, timing_valid=False)
        self.assertEqual(gap_result.quality, SignalQuality.POOR)
        self.assertIsNone(gap_result.host_bpm)

    def test_irregular_pulse_intervals_are_not_reported_as_good(self):
        beat_times = []
        beat_time = 0.35
        intervals = (0.45, 1.2)
        while beat_time < 11.5:
            beat_times.append(beat_time)
            beat_time += intervals[len(beat_times) % 2]
        signal = []
        for index in range(600):
            current_time = index / 50
            pulse = sum(300 * math.exp(-((current_time - beat) / 0.075) ** 2) for beat in beat_times)
            signal.append(int(1800 + 150 * current_time / 12 + pulse))
        result = self._stream(signal)
        self.assertEqual(result.quality, SignalQuality.POOR)
        self.assertIsNone(result.host_bpm)


if __name__ == "__main__":
    unittest.main()