"""In-memory session recording and CSV export."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import time

from .protocol import Packet, SAMPLE_PERIOD_MS, Status
from .signal_processing import AnalysisResult


CSV_FIELDS = (
    "received_at_utc",
    "sequence",
    "device_timestamp_ms",
    "sample_index",
    "ppg_raw",
    "ppg_filtered",
    "embedded_bpm",
    "host_bpm",
    "fft_bpm",
    "signal_quality",
    "status_flags",
    "recording",
    "session_duration_s",
    "session_average_bpm",
    "session_min_bpm",
    "session_max_bpm",
)


@dataclass(frozen=True)
class SessionSummary:
    duration_seconds: float
    average_bpm: float | None
    minimum_bpm: float | None
    maximum_bpm: float | None
    valid_measurements: int
    sample_count: int


class SessionRecorder:
    def __init__(self) -> None:
        self.active = False
        self._started_at = 0.0
        self._stopped_at: float | None = None
        self._rows: list[dict[str, object]] = []
        self._valid_bpm: list[float] = []

    def start(self) -> None:
        if self.active:
            return
        self._rows.clear()
        self._valid_bpm.clear()
        self._started_at = time.monotonic()
        self._stopped_at = None
        self.active = True

    def stop(self) -> None:
        if self.active:
            self._stopped_at = time.monotonic()
            self.active = False

    def add_packet(self, packet: Packet, analysis: AnalysisResult) -> None:
        if not self.active:
            return
        if analysis.host_bpm is not None:
            self._valid_bpm.append(analysis.host_bpm)
        received_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        recording = bool(packet.status & Status.RECORDING)
        for index, raw in enumerate(packet.samples):
            self._rows.append(
                {
                    "received_at_utc": received_at,
                    "sequence": packet.sequence,
                    "device_timestamp_ms": (packet.block_start_ms + index * SAMPLE_PERIOD_MS) & 0xFFFFFFFF,
                    "sample_index": index,
                    "ppg_raw": raw,
                    "ppg_filtered": analysis.filtered[-len(packet.samples) + index],
                    "embedded_bpm": packet.embedded_bpm,
                    "host_bpm": analysis.host_bpm,
                    "fft_bpm": analysis.fft_bpm,
                    "signal_quality": analysis.quality.value,
                    "status_flags": int(packet.status),
                    "recording": recording,
                }
            )

    def summary(self) -> SessionSummary:
        stopped_at = self._stopped_at if self._stopped_at is not None else time.monotonic()
        duration = max(0.0, stopped_at - self._started_at) if self._started_at else 0.0
        if not self._valid_bpm:
            return SessionSummary(duration, None, None, None, 0, len(self._rows))
        values = self._valid_bpm
        return SessionSummary(
            duration_seconds=duration,
            average_bpm=sum(values) / len(values),
            minimum_bpm=min(values),
            maximum_bpm=max(values),
            valid_measurements=len(values),
            sample_count=len(self._rows),
        )

    def export_csv(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        summary = self.summary()
        summary_fields: dict[str, object] = {
            "session_duration_s": round(summary.duration_seconds, 3),
            "session_average_bpm": _rounded(summary.average_bpm),
            "session_min_bpm": _rounded(summary.minimum_bpm),
            "session_max_bpm": _rounded(summary.maximum_bpm),
        }
        with destination.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for row in self._rows:
                writer.writerow({**row, **summary_fields})
        return destination


def _rounded(value: float | None) -> float | str:
    return "" if value is None else round(value, 2)