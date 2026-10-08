"""Independent host-side PPG filtering, beat analysis, and spectrum estimation."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum

import numpy as np
from scipy.signal import butter, find_peaks, sosfiltfilt

from .protocol import SAMPLE_RATE_HZ, SAMPLES_PER_PACKET


class SignalQuality(str, Enum):
    GOOD = "GOOD"
    POOR = "POOR"
    NO_SIGNAL = "NO SIGNAL"


@dataclass(frozen=True)
class AnalysisResult:
    raw: tuple[float, ...]
    filtered: tuple[float, ...]
    times_s: tuple[float, ...]
    frequencies_hz: tuple[float, ...]
    spectrum_magnitude: tuple[float, ...]
    host_bpm: float | None
    dominant_frequency_hz: float | None
    fft_bpm: float | None
    quality: SignalQuality
    quality_reason: str
    valid_interval_count: int
    signal_amplitude: float


class PPGProcessor:
    def __init__(
        self,
        sample_rate_hz: int = SAMPLE_RATE_HZ,
        history_seconds: int = 12,
        minimum_signal_range: float = 8.0,
    ) -> None:
        if sample_rate_hz <= 0 or history_seconds < 5:
            raise ValueError("sample rate must be positive and history must be at least 5 seconds")
        self.sample_rate_hz = sample_rate_hz
        self.minimum_signal_range = minimum_signal_range
        self.history_size = sample_rate_hz * history_seconds
        self._raw: deque[float] = deque(maxlen=self.history_size)
        self._sample_count = 0
        self._sos = butter(3, (0.5, 4.0), btype="bandpass", fs=sample_rate_hz, output="sos")

    def reset(self) -> None:
        self._raw.clear()
        self._sample_count = 0

    def process_block(
        self,
        samples: tuple[int, ...] | list[int],
        sensor_present: bool | None = None,
        timing_valid: bool = True,
    ) -> AnalysisResult:
        if len(samples) != SAMPLES_PER_PACKET:
            raise ValueError(f"exactly {SAMPLES_PER_PACKET} samples are required")
        if any(not 0 <= int(sample) <= 0xFFFF for sample in samples):
            raise ValueError("samples must be unsigned 16-bit values")
        self._raw.extend(float(sample) for sample in samples)
        self._sample_count += len(samples)

        raw_array = np.asarray(self._raw, dtype=np.float64)
        count = len(raw_array)
        times = np.arange(count, dtype=np.float64) / self.sample_rate_hz
        if count >= 20:
            filtered = sosfiltfilt(self._sos, raw_array)
        else:
            filtered = raw_array - np.mean(raw_array)
        intervals = self._beat_intervals(filtered) if count >= 100 else []

        raw_range = float(np.ptp(raw_array)) if count else 0.0
        raw_std = float(np.std(raw_array)) if count else 0.0
        filtered_range = float(np.ptp(filtered)) if count else 0.0
        near_rails = float(np.mean((raw_array <= 1) | (raw_array >= 4094))) if count else 0.0
        quality, reason = self._classify_quality(
            count, raw_range, raw_std, filtered_range, near_rails, sensor_present, timing_valid, intervals
        )

        host_bpm: float | None = None
        valid_intervals = len(intervals)
        if quality != SignalQuality.NO_SIGNAL and intervals:
            host_bpm = 60.0 / float(np.median(intervals))

        frequencies: np.ndarray = np.empty(0, dtype=np.float64)
        magnitude: np.ndarray = np.empty(0, dtype=np.float64)
        dominant_frequency: float | None = None
        fft_bpm: float | None = None
        if count >= self.sample_rate_hz * 5:
            frequencies, magnitude = self._spectrum(filtered)
            if quality == SignalQuality.GOOD and host_bpm is not None and len(frequencies):
                band = (frequencies >= 0.5) & (frequencies <= 4.0)
                band_indices = np.flatnonzero(band)
                if len(band_indices):
                    peak_index = band_indices[int(np.argmax(magnitude[band]))]
                    candidate_hz = float(frequencies[peak_index])
                    candidate_bpm = candidate_hz * 60.0
                    tolerance_hz = max(0.2, host_bpm / 60.0 * 0.2)
                    if abs(candidate_bpm - host_bpm) <= tolerance_hz * 60.0:
                        dominant_frequency = candidate_hz
                        fft_bpm = candidate_bpm

        return AnalysisResult(
            raw=tuple(float(value) for value in raw_array),
            filtered=tuple(float(value) for value in filtered),
            times_s=tuple(float(value) for value in times),
            frequencies_hz=tuple(float(value) for value in frequencies),
            spectrum_magnitude=tuple(float(value) for value in magnitude),
            host_bpm=host_bpm if quality == SignalQuality.GOOD else None,
            dominant_frequency_hz=dominant_frequency,
            fft_bpm=fft_bpm,
            quality=quality,
            quality_reason=reason,
            valid_interval_count=valid_intervals,
            signal_amplitude=filtered_range,
        )

    def _classify_quality(
        self,
        count: int,
        raw_range: float,
        raw_std: float,
        filtered_range: float,
        near_rails: float,
        sensor_present: bool | None,
        timing_valid: bool,
        intervals: list[float],
    ) -> tuple[SignalQuality, str]:
        if sensor_present is False or raw_range < self.minimum_signal_range or raw_std < 2.0:
            return SignalQuality.NO_SIGNAL, "No usable pulse variation detected"
        if not timing_valid:
            return SignalQuality.POOR, "Sampling timing gap; rebuilding a uniform-rate analysis window"
        if near_rails > 0.05:
            return SignalQuality.POOR, "Signal is clipped at the ADC input range"
        if count < self.sample_rate_hz * 5:
            return SignalQuality.POOR, "Collecting at least 5 seconds of signal"
        if filtered_range < 4.0:
            return SignalQuality.POOR, "Filtered pulse amplitude is too small"
        if len(intervals) < 2:
            return SignalQuality.POOR, "Too few reliable beat intervals"
        interval_values = np.asarray(intervals, dtype=np.float64)
        variability = float(np.std(interval_values) / np.mean(interval_values))
        if variability > 0.25:
            return SignalQuality.POOR, "Beat intervals are unstable"
        return SignalQuality.GOOD, "Pulse intervals are stable"

    def _beat_intervals(self, filtered: np.ndarray) -> list[float]:
        if len(filtered) < 100:
            return []
        robust_noise = float(np.median(np.abs(filtered - np.median(filtered))) * 1.4826)
        prominence = max(1.0, robust_noise * 1.2, float(np.ptp(filtered)) * 0.08)
        minimum_distance = max(1, round(self.sample_rate_hz * 60.0 / 200.0))
        candidate_sets = []
        for polarity in (1.0, -1.0):
            peaks, _ = find_peaks(
                filtered * polarity,
                distance=minimum_distance,
                prominence=prominence,
            )
            intervals = np.diff(peaks) / self.sample_rate_hz
            valid = intervals[(intervals >= 0.3) & (intervals <= 2.0)]
            if len(valid):
                variability = float(np.std(valid) / np.mean(valid))
                candidate_sets.append((len(valid), -variability, valid.tolist()))
        if not candidate_sets:
            return []
        return max(candidate_sets, key=lambda item: (item[0], item[1]))[2]

    def _spectrum(self, filtered: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        window = np.hanning(len(filtered))
        centered = filtered - np.mean(filtered)
        spectrum = np.abs(np.fft.rfft(centered * window)) * (2.0 / np.sum(window))
        frequencies = np.fft.rfftfreq(len(filtered), d=1.0 / self.sample_rate_hz)
        mask = (frequencies >= 0.0) & (frequencies <= 10.0)
        return frequencies[mask], spectrum[mask]