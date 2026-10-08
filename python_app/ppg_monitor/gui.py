"""Desktop real-time monitor and researcher views."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .bluetooth_worker import BluetoothWorker
from .protocol import DEVICE_NAME, Packet, SequenceTracker, Status
from .recorder import SessionRecorder
from .signal_processing import AnalysisResult, PPGProcessor, SignalQuality


APP_STYLE = """
QMainWindow, QWidget { background: #f1f5f2; color: #172622; font-family: 'Noto Sans'; font-size: 13px; }
QLabel#title { font-size: 23px; font-weight: 700; color: #102f2c; }
QLabel#eyebrow { color: #58706a; font-size: 11px; }
QLabel#metric { font-size: 36px; font-weight: 700; color: #123c38; }
QLabel#metricCaption { color: #52665f; font-size: 12px; }
QLabel#connection, QLabel#quality { padding: 6px 10px; border: 1px solid #c7d4ce; border-radius: 3px; font-weight: 700; }
QPushButton { background: #e4ece8; border: 1px solid #bccdc5; border-radius: 3px; padding: 7px 12px; color: #173b35; }
QPushButton:hover { background: #d6e5de; }
QPushButton:disabled { color: #8c9a94; background: #edf1ef; }
QPushButton#primary { background: #087c70; border-color: #087c70; color: white; font-weight: 700; }
QPushButton#primary:hover { background: #06685f; }
QComboBox, QDoubleSpinBox { background: #ffffff; border: 1px solid #c7d4ce; border-radius: 3px; padding: 6px; min-height: 20px; }
QTabWidget::pane { border: 1px solid #d4dfda; background: #f8faf8; }
QTabBar::tab { padding: 9px 18px; background: #e7eeea; border: 1px solid #d4dfda; }
QTabBar::tab:selected { background: #087c70; color: white; }
QListWidget { background: #fbfcfb; border: 1px solid #d4dfda; }
"""


def _metric(caption: str) -> tuple[QWidget, QLabel]:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(10, 8, 10, 8)
    title = QLabel(caption)
    title.setObjectName("metricCaption")
    value = QLabel("--")
    value.setObjectName("metric")
    layout.addWidget(title)
    layout.addWidget(value)
    return widget, value


class PPGWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BMET2922 | PPG Research Monitor")
        self.resize(1280, 850)
        self.setMinimumSize(920, 680)
        self.worker = BluetoothWorker()
        self.processor = PPGProcessor()
        self.sequence_tracker = SequenceTracker()
        self.recorder = SessionRecorder()
        self.latest_analysis: AnalysisResult | None = None
        self.latest_packet: Packet | None = None
        self.connected = False
        self.recording = False
        self._build_ui()
        self._connect_signals()
        self.worker.start()

        self.plot_timer = QTimer(self)
        self.plot_timer.timeout.connect(self._refresh_plots)
        self.plot_timer.start(100)
        self.session_timer = QTimer(self)
        self.session_timer.timeout.connect(self._refresh_summary)
        self.session_timer.start(1000)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(20, 16, 20, 16)
        main.setSpacing(12)

        heading = QHBoxLayout()
        title_column = QVBoxLayout()
        title = QLabel("PPG / Heart Rate Monitor")
        title.setObjectName("title")
        subtitle = QLabel("50 Hz · independent embedded and host analysis · educational use")
        subtitle.setObjectName("eyebrow")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        heading.addLayout(title_column)
        heading.addStretch(1)
        self.connection_label = QLabel("DISCONNECTED")
        self.connection_label.setObjectName("connection")
        heading.addWidget(self.connection_label)
        main.addLayout(heading)

        connection_row = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(290)
        self.device_combo.addItem("Scan for BMET2922-PPG", userData=None)
        self.scan_button = QPushButton("Scan")
        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("primary")
        connection_row.addWidget(QLabel("Bluetooth device"))
        connection_row.addWidget(self.device_combo, 1)
        connection_row.addWidget(self.scan_button)
        connection_row.addWidget(self.connect_button)
        main.addLayout(connection_row)

        self.tabs = QTabWidget()
        self.monitor_tab = self._build_monitor_tab()
        self.research_tab = self._build_research_tab()
        self.session_tab = self._build_session_tab()
        self.tabs.addTab(self.monitor_tab, "Monitor")
        self.tabs.addTab(self.research_tab, "Researcher")
        self.tabs.addTab(self.session_tab, "Session")
        main.addWidget(self.tabs, 1)

    def _build_monitor_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)

        metrics = QGridLayout()
        embedded_widget, self.embedded_value = _metric("ESP32 BPM")
        host_widget, self.host_value = _metric("Host BPM")
        delta_widget, self.delta_value = _metric("Host − ESP32")
        self.quality_label = QLabel("NO SIGNAL")
        self.quality_label.setObjectName("quality")
        self.quality_reason = QLabel("Waiting for samples")
        self.quality_reason.setWordWrap(True)
        quality_box = QWidget()
        quality_layout = QVBoxLayout(quality_box)
        quality_layout.setContentsMargins(10, 8, 10, 8)
        quality_layout.addWidget(QLabel("SIGNAL QUALITY"))
        quality_layout.addWidget(self.quality_label)
        quality_layout.addWidget(self.quality_reason)
        metrics.addWidget(embedded_widget, 0, 0)
        metrics.addWidget(host_widget, 0, 1)
        metrics.addWidget(delta_widget, 0, 2)
        metrics.addWidget(quality_box, 0, 3)
        layout.addLayout(metrics)

        self.live_plot = pg.PlotWidget()
        self.live_plot.setBackground("#fbfdfb")
        self.live_plot.showGrid(x=True, y=True, alpha=0.18)
        self.live_plot.setLabel("left", "ADC counts")
        self.live_plot.setLabel("bottom", "Time", units="s")
        self.live_plot.setTitle("Live PPG")
        self.live_curve = self.live_plot.plot(pen=pg.mkPen("#087c70", width=2))
        layout.addWidget(self.live_plot, 1)

        controls = QHBoxLayout()
        self.record_button = QPushButton("Start recording")
        self.save_button = QPushButton("Save CSV")
        self.save_button.setEnabled(False)
        self.alarm_label = QLabel("HEART RATE: --")
        self.alarm_label.setMinimumWidth(220)
        thresholds = QFormLayout()
        self.low_threshold = QDoubleSpinBox()
        self.low_threshold.setRange(30, 180)
        self.low_threshold.setSingleStep(5)
        self.low_threshold.setValue(50)
        self.low_threshold.setSuffix(" bpm")
        self.high_threshold = QDoubleSpinBox()
        self.high_threshold.setRange(40, 220)
        self.high_threshold.setSingleStep(5)
        self.high_threshold.setValue(120)
        self.high_threshold.setSuffix(" bpm")
        thresholds.addRow("Low alarm", self.low_threshold)
        thresholds.addRow("High alarm", self.high_threshold)
        controls.addWidget(self.record_button)
        controls.addWidget(self.save_button)
        controls.addWidget(self.alarm_label, 1)
        controls.addLayout(thresholds)
        layout.addLayout(controls)

        self.event_log = QListWidget()
        self.event_log.setMaximumHeight(110)
        layout.addWidget(self.event_log)
        return page

    def _build_research_tab(self) -> QWidget:
        page = QWidget()
        layout = QGridLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)

        self.raw_plot = pg.PlotWidget()
        self.filtered_plot = pg.PlotWidget()
        for plot, label in ((self.raw_plot, "Raw PPG · ADC counts"), (self.filtered_plot, "Filtered PPG · 0.5–4 Hz")):
            plot.setBackground("#fbfdfb")
            plot.showGrid(x=True, y=True, alpha=0.18)
            plot.setLabel("left", label)
            plot.setLabel("bottom", "Time", units="s")
        self.filtered_plot.setXLink(self.raw_plot)
        self.raw_curve = self.raw_plot.plot(pen=pg.mkPen("#087c70", width=2))
        self.filtered_curve = self.filtered_plot.plot(pen=pg.mkPen("#c45129", width=2))
        self.raw_plot.setTitle("Raw waveform")
        self.filtered_plot.setTitle("Band-pass output")
        layout.addWidget(self.raw_plot, 0, 0)
        layout.addWidget(self.filtered_plot, 1, 0)

        spectrum_column = QVBoxLayout()
        self.spectrum_plot = pg.PlotWidget()
        self.spectrum_plot.setBackground("#fbfdfb")
        self.spectrum_plot.showGrid(x=True, y=True, alpha=0.18)
        self.spectrum_plot.setLabel("left", "Magnitude")
        self.spectrum_plot.setLabel("bottom", "Frequency", units="Hz")
        self.spectrum_plot.setTitle("Windowed real-time spectrum")
        self.spectrum_curve = self.spectrum_plot.plot(pen=pg.mkPen("#3056a3", width=2))
        self.spectrum_peak = pg.ScatterPlotItem(size=11, pen=pg.mkPen("#c45129"), brush="#f1a35e")
        self.spectrum_plot.addItem(self.spectrum_peak)
        self.frequency_label = QLabel("Dominant pulse frequency: --")
        self.frequency_label.setWordWrap(True)
        self.frequency_label.setObjectName("quality")
        spectrum_column.addWidget(self.spectrum_plot, 1)
        spectrum_column.addWidget(self.frequency_label)
        layout.addLayout(spectrum_column, 0, 1, 2, 1)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        return page

    def _build_session_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(QLabel("Session summary"))
        self.session_duration = QLabel("Duration: 00:00")
        self.session_average = QLabel("Average valid host BPM: --")
        self.session_minimum = QLabel("Minimum valid host BPM: --")
        self.session_maximum = QLabel("Maximum valid host BPM: --")
        self.session_count = QLabel("Valid measurements: 0")
        for label in (self.session_duration, self.session_average, self.session_minimum, self.session_maximum, self.session_count):
            layout.addWidget(label)
        self.session_save_button = QPushButton("Save recorded data as CSV")
        self.session_save_button.setEnabled(False)
        self.session_save_button.setObjectName("primary")
        self.session_save_button.clicked.connect(self._save_csv)
        layout.addWidget(self.session_save_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return page

    def _connect_signals(self) -> None:
        self.worker.devices_found.connect(self._devices_found)
        self.worker.connection_changed.connect(self._connection_changed)
        self.worker.packet_received.connect(self._packet_received)
        self.worker.error_occurred.connect(self._log_event)
        self.scan_button.clicked.connect(self._scan)
        self.connect_button.clicked.connect(self._toggle_connection)
        self.record_button.clicked.connect(self._toggle_recording)
        self.save_button.clicked.connect(self._save_csv)
        self.low_threshold.valueChanged.connect(self._low_threshold_changed)
        self.high_threshold.valueChanged.connect(self._high_threshold_changed)

    def _scan(self) -> None:
        self.device_combo.clear()
        self.device_combo.addItem("Scanning…", userData=None)
        self.scan_button.setEnabled(False)
        QTimer.singleShot(5500, lambda: self.scan_button.setEnabled(True))
        self.worker.scan()

    def _devices_found(self, devices: list) -> None:
        self.device_combo.clear()
        self.device_combo.addItem("Select ESP32 device", userData=None)
        devices.sort(key=lambda item: (item["name"] != DEVICE_NAME, item["name"].lower()))
        for device in devices:
            self.device_combo.addItem(f"{device['name']}  ·  {device['address']}", userData=device["address"])
        if not devices:
            self._log_event("No BLE devices found")

    def _toggle_connection(self) -> None:
        if self.connected:
            self.worker.disconnect()
            return
        address = self.device_combo.currentData()
        if not address:
            self._log_event("Scan and select a BLE device first")
            return
        self.connection_label.setText("CONNECTING…")
        self.worker.connect_to(address)

    def _connection_changed(self, connected: bool, address: str) -> None:
        changed = connected != self.connected
        self.connected = connected
        self.connection_label.setText("CONNECTED" if connected else "DISCONNECTED")
        self.connect_button.setText("Disconnect" if connected else "Connect")
        self.record_button.setEnabled(connected)
        if changed:
            self._log_event(f"Bluetooth connected: {address}" if connected else "Bluetooth disconnected")
        if not connected and self.recording:
            self.recorder.stop()
            self.recording = False
            self.record_button.setText("Start recording")
            self._refresh_summary()

    def _toggle_recording(self) -> None:
        if not self.connected:
            self._log_event("Connect to the ESP32 before recording")
            return
        self.worker.set_recording(not self.recording)

    def _packet_received(self, packet: Packet) -> None:
        sequence = self.sequence_tracker.observe(packet.sequence)
        if sequence.out_of_order:
            self._log_event(f"Ignored duplicate/out-of-order packet {packet.sequence}")
            return
        if sequence.missing:
            self._log_event(f"Packet loss: {sequence.missing} block(s) before {packet.sequence}")
            self.processor.reset()
        timing_valid = not bool(packet.status & Status.TIMING_GAP)
        if not timing_valid:
            self._log_event(f"Sampling timing gap in block {packet.sequence}")
            self.processor.reset()

        sensor_present = bool(packet.status & Status.SENSOR_PRESENT)
        analysis = self.processor.process_block(
            packet.samples, sensor_present=sensor_present, timing_valid=timing_valid
        )
        if not timing_valid:
            self.processor.reset()
        self.latest_analysis = analysis
        self.latest_packet = packet
        current_recording = bool(packet.status & Status.RECORDING)
        if current_recording and not self.recording:
            self.recorder.start()
            self._log_event("Recording started")
        if self.recording:
            self.recorder.add_packet(packet, analysis)
        elif current_recording:
            self.recorder.add_packet(packet, analysis)
        if self.recording and not current_recording:
            self.recorder.stop()
            self._log_event("Recording stopped")
        self.recording = current_recording
        self.record_button.setText("Stop recording" if self.recording else "Start recording")

        self.embedded_value.setText("--" if packet.embedded_bpm is None else str(packet.embedded_bpm))
        self.host_value.setText("--" if analysis.host_bpm is None else f"{analysis.host_bpm:.0f}")
        if analysis.host_bpm is None or packet.embedded_bpm is None:
            self.delta_value.setText("--")
        else:
            self.delta_value.setText(f"{analysis.host_bpm - packet.embedded_bpm:+.0f}")
        self.quality_label.setText(analysis.quality.value)
        quality_color = {
            SignalQuality.GOOD: ("#d7efe2", "#12633e"),
            SignalQuality.POOR: ("#fff0cf", "#8a5800"),
            SignalQuality.NO_SIGNAL: ("#f8dddd", "#982e2e"),
        }[analysis.quality]
        background, foreground = quality_color
        self.quality_label.setStyleSheet(f"background:{background}; color:{foreground};")
        self.quality_reason.setText(analysis.quality_reason)
        self._refresh_alarm()
        self.save_button.setEnabled(bool(self.recorder.summary().sample_count))
        self.session_save_button.setEnabled(bool(self.recorder.summary().sample_count))
        self._refresh_summary()

    def _refresh_alarm(self) -> None:
        analysis = self.latest_analysis
        if analysis is None or analysis.host_bpm is None or analysis.quality != SignalQuality.GOOD:
            self.alarm_label.setText("HEART RATE: UNAVAILABLE")
            self.alarm_label.setStyleSheet("color:#596a64; font-weight:700;")
            return
        bpm = analysis.host_bpm
        if bpm > self.high_threshold.value():
            self.alarm_label.setText(f"HIGH HEART RATE · {bpm:.0f} BPM")
            self.alarm_label.setStyleSheet("background:#f8dddd; color:#982e2e; font-weight:700; padding:7px;")
        elif bpm < self.low_threshold.value():
            self.alarm_label.setText(f"LOW HEART RATE · {bpm:.0f} BPM")
            self.alarm_label.setStyleSheet("background:#fff0cf; color:#8a5800; font-weight:700; padding:7px;")
        else:
            self.alarm_label.setText(f"HEART RATE IN RANGE · {bpm:.0f} BPM")
            self.alarm_label.setStyleSheet("background:#d7efe2; color:#12633e; font-weight:700; padding:7px;")

    def _low_threshold_changed(self, value: float) -> None:
        if value >= self.high_threshold.value():
            self.high_threshold.setValue(min(self.high_threshold.maximum(), value + 5))
        self._refresh_alarm()

    def _high_threshold_changed(self, value: float) -> None:
        if value <= self.low_threshold.value():
            self.low_threshold.setValue(max(self.low_threshold.minimum(), value - 5))
        self._refresh_alarm()

    def _refresh_plots(self) -> None:
        analysis = self.latest_analysis
        if analysis is None:
            return
        self.live_curve.setData(analysis.times_s, analysis.raw)
        self.raw_curve.setData(analysis.times_s, analysis.raw)
        self.filtered_curve.setData(analysis.times_s, analysis.filtered)
        if analysis.times_s:
            end = analysis.times_s[-1]
            self.live_plot.setXRange(max(0.0, end - 10), max(10.0, end), padding=0)
            self.raw_plot.setXRange(max(0.0, end - 10), max(10.0, end), padding=0)
        self.spectrum_curve.setData(analysis.frequencies_hz, analysis.spectrum_magnitude)
        if analysis.dominant_frequency_hz is not None and analysis.fft_bpm is not None:
            self.spectrum_peak.setData([{"pos": (analysis.dominant_frequency_hz, max(analysis.spectrum_magnitude)), "data": 1}])
            self.frequency_label.setText(
                f"Dominant pulse: {analysis.dominant_frequency_hz:.2f} Hz  ·  {analysis.fft_bpm:.0f} BPM"
            )
        else:
            self.spectrum_peak.setData([])
            self.frequency_label.setText("Dominant pulse frequency: unavailable until signal quality is GOOD")

    def _refresh_summary(self) -> None:
        summary = self.recorder.summary()
        seconds = int(summary.duration_seconds)
        self.session_duration.setText(f"Duration: {seconds // 60:02d}:{seconds % 60:02d}")
        self.session_average.setText(
            "Average valid host BPM: --" if summary.average_bpm is None else f"Average valid host BPM: {summary.average_bpm:.1f}"
        )
        self.session_minimum.setText(
            "Minimum valid host BPM: --" if summary.minimum_bpm is None else f"Minimum valid host BPM: {summary.minimum_bpm:.0f}"
        )
        self.session_maximum.setText(
            "Maximum valid host BPM: --" if summary.maximum_bpm is None else f"Maximum valid host BPM: {summary.maximum_bpm:.0f}"
        )
        self.session_count.setText(f"Valid measurements: {summary.valid_measurements} · Samples: {summary.sample_count}")

    def _save_csv(self) -> None:
        if not self.recorder.summary().sample_count:
            QMessageBox.information(self, "No session data", "There are no recorded samples to save yet.")
            return
        filename = f"ppg_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Save PPG session", str(Path.home() / filename), "CSV files (*.csv)")
        if not path:
            return
        try:
            saved = self.recorder.export_csv(path)
            self._log_event(f"Saved {self.recorder.summary().sample_count} samples to {saved}")
        except OSError as error:
            QMessageBox.critical(self, "Save failed", str(error))

    def _log_event(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.event_log.insertItem(0, f"{timestamp}  {message}")
        while self.event_log.count() > 250:
            self.event_log.takeItem(self.event_log.count() - 1)

    def closeEvent(self, event) -> None:
        self.worker.stop()
        event.accept()


def run() -> int:
    application = QApplication(sys.argv)
    application.setStyleSheet(APP_STYLE)
    pg.setConfigOptions(antialias=True)
    window = PPGWindow()
    window.show()
    return application.exec()
