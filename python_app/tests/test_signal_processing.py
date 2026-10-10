import math
import unittest
import numpy as np

from ppg_monitor.signal_processing import PPGProcessor, SignalQuality


class SignalProcessingTests(unittest.TestCase):
    def test_streaming_filter_preserves_previously_emitted_samples(self):
        processor = PPGProcessor()
        pulse = [int(1800 + 240 * math.sin(2 * math.pi * 1.2 * index / 50)) for index in range(100)]
        first = processor.process_block(pulse[:50], sensor_present=True)
        second = processor.process_block(pulse[50:], sensor_present=True)
        self.assertEqual(first.filtered, second.filtered[:50])

    def test_low_frequency_drift_is_attenuated_while_pulse_is_preserved(self):
        processor = PPGProcessor()
        times = np.arange(1500) / 50
        signal = np.rint(1800 + 200 * np.sin(2 * np.pi * 0.1 * times)
                         + 100 * np.sin(2 * np.pi * 1.2 * times)).astype(int)
        for offset in range(0, len(signal), 50):
            result = processor.process_block(signal[offset:offset + 50], sensor_present=True)
        t = times[-len(result.filtered):]
        basis = np.column_stack([np.sin(2 * np.pi * 0.1 * t), np.cos(2 * np.pi * 0.1 * t),
                                 np.sin(2 * np.pi * 1.2 * t), np.cos(2 * np.pi * 1.2 * t), np.ones(len(t))])
        coefficients = np.linalg.lstsq(basis, result.filtered, rcond=None)[0]
        self.assertLess(np.hypot(*coefficients[:2]), 10)
        self.assertGreater(np.hypot(*coefficients[2:4]), 80)
        self.assertAlmostEqual(result.host_bpm, 72, delta=5)

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
        recovered = processor.process_block(pulse, sensor_present=True)
        self.assertEqual(len(recovered.raw), 50)
        self.assertIsNone(recovered.host_bpm)

    def test_flat_block_invalidates_old_beats_even_if_sensor_flag_lingers(self):
        processor = PPGProcessor()
        pulse = [int(1800 + 240 * max(0.0, math.sin(2 * math.pi * 1.2 * index / 50))) for index in range(50)]
        for _ in range(10):
            processor.process_block(pulse, sensor_present=True)
        result = processor.process_block([2000] * 50, sensor_present=True)
        self.assertEqual(result.quality, SignalQuality.NO_SIGNAL)
        self.assertIsNone(result.host_bpm)
        recovered = processor.process_block(pulse, sensor_present=True)
        self.assertEqual(len(recovered.raw), 50)
        self.assertIsNone(recovered.host_bpm)

    def test_invalid_samples_are_rejected_before_changing_history(self):
        processor = PPGProcessor()
        for sample in (-0.1, 2.5, float("nan"), float("inf"), -1, 65536):
            with self.subTest(sample=sample), self.assertRaises(ValueError):
                processor.process_block([sample] * 50)
        self.assertEqual(len(processor.process_block([2000] * 50).raw), 50)

    def test_clipping_withholds_host_and_fft_bpm(self):
        signal = [4095 if (index % 42) < 21 else 0 for index in range(600)]
        result = self._stream(signal)
        self.assertEqual(result.quality, SignalQuality.POOR)
        self.assertIsNone(result.host_bpm)
        self.assertIsNone(result.fft_bpm)

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
