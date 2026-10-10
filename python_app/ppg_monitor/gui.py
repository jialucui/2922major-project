"""One FreeSimpleGUI window for monitoring, research plots, and CSV sessions."""
from datetime import datetime
from pathlib import Path
import math
import time

import FreeSimpleGUI as sg

from .alarms import PulseAlarm
from .communication import CommunicationEvent, CommunicationManager, ConnectionState, available_ports
from .config import DATA_DIRECTORY, GUI_POLL_MS
from .controller import MonitorController, format_bpm
from .demo import DemoSource
from .logger import SystemLogger
from .i18n import LANGUAGES, translate

BACKGROUND = "#f1f5f2"
INK = "#172622"
TEAL = "#087c70"
GRAPH_SIZE = (940, 150)


def _graph(key, height=150):
    return sg.Graph((940, height), (0, 0), (940, height), key=key, background_color="#ffffff")


def build_window(demo=False, language="English"):
    def t(message, **values):
        return translate(message, language, **values)

    def text(message, **kwargs):
        return sg.Text(t(message), **kwargs)

    def button(message, **kwargs):
        kwargs.setdefault("key", message)
        return sg.Button(t(message), **kwargs)

    sg.theme("LightGrey1")
    monitor = [
        [text("ESP32 BPM", size=(22, 1)), text("Host BPM", size=(22, 1)), text("Signal quality")],
        [text("--", key="-ESP-", font=("Helvetica", 36, "bold"), size=(9, 1), text_color=TEAL),
         text("--", key="-HOST-", font=("Helvetica", 36, "bold"), size=(9, 1)),
         text("NO SIGNAL", key="-QUALITY-", size=(25, 2))],
        [text("Pulse: UNAVAILABLE", key="-PULSE-", size=(32, 1), font=("Helvetica", 14, "bold")),
         text("Communication: IDLE", key="-COMM-", size=(44, 1), font=("Helvetica", 13, "bold"))],
        [text("Raw PPG · ADC counts")], [_graph("-WAVE-")],
        [text("BPM trend · ESP32 (green) / Host (orange)")], [_graph("-TREND-", 130)],
        [text("Low BPM"), sg.Input("50.0", key="-LOW-", size=(7, 1)),
         text("High BPM"), sg.Input("120.0", key="-HIGH-", size=(7, 1)), button("Apply limits"),
         button("Start recording", key="-RECORD-", disabled=True),
         text("", key="-PROCESSING-", size=(28, 1))],
    ]
    research = [
        [text("Stateful Butterworth band-pass · 0.5–4 Hz · 50 Hz sampling")],
        [_graph("-FILTER-")],
        [text("Hann-window FFT · frequency (Hz)")], [_graph("-SPECTRUM-", 210)],
        [text("Dominant pulse frequency: --", key="-FREQUENCY-", size=(75, 1))],
        [text("Waiting for data", key="-REASON-", size=(95, 2))],
    ]
    sessions = [
        [text("Recording"), sg.Combo([t("Session {number}", number=1)], default_value=t("Session {number}", number=1), readonly=True,
                                       enable_events=True, key="-SESSION-", size=(20, 1))],
        [text("", key="-SUMMARY-", size=(80, 8), font=("Helvetica", 15))],
        [text("CSV destination")],
        [sg.Input(str(_csv_path()), key="-CSV-PATH-", size=(80, 1)),
         sg.FileSaveAs(t("Browse"), target="-CSV-PATH-", file_types=(("CSV", "*.csv"),), default_extension=".csv")],
        [button("Save CSV")],
        [text("Stopped sessions are retained here until the app closes. Save each session before exiting.", size=(92, 2))],
    ]
    layout = [
        [text("BMET2922 / PPG Monitor", font=("Helvetica", 22, "bold"), text_color=TEAL),
         text("SIMULATED DATA" if demo else "Bluetooth Classic SPP", text_color="#a94718" if demo else INK),
         text("DISCONNECTED", key="-CONNECTION-", size=(18, 1)), sg.Combo(LANGUAGES, default_value=language, key="-LANGUAGE-", readonly=True, enable_events=True, size=(9, 1))],
        [text("SPP serial port"), sg.Combo([], key="-PORT-", size=(43, 1)),
         button("Refresh ports"), button("Connect", key="-CONNECT-"),
         text("Pair BMET2922-PPG in OS Bluetooth settings first.", size=(43, 1))],
        [sg.TabGroup([[sg.Tab(t("Monitor"), monitor), sg.Tab(t("Researcher"), research), sg.Tab(t("Sessions / CSV"), sessions)]])],
        [text("System log")],
        [sg.Multiline("", key="-LOG-", size=(122, 5), disabled=True, autoscroll=True)],
        [text("Educational prototype · local times in log / UTC in CSV", key="-NOTICE-", size=(110, 1))],
    ]
    return sg.Window("BMET2922 PPG Monitor", layout, finalize=True, resizable=True,
                     background_color=BACKGROUND, font=("Helvetica", 11), margins=(12, 10))


def _csv_path():
    return DATA_DIRECTORY / "recordings" / f"ppg_{datetime.now():%Y%m%d_%H%M%S_%f}.csv"


def draw_plot(graph, series, x_label="Time (s)", y_limits=None, guides=()):
    """Each series is (x values, y values, color); None splits a lost-signal line."""
    graph.erase()
    width, height = graph.CanvasSize
    left, right, bottom, top = 48, width - 14, 28, height - 14
    all_points = [(float(x), float(y)) for xs, ys, _ in series for x, y in zip(xs, ys)
                  if y is not None and math.isfinite(y) and math.isfinite(x)]
    if all_points:
        x_min, x_max = min(x for x, _ in all_points), max(x for x, _ in all_points)
        y_min, y_max = y_limits or (min(y for _, y in all_points), max(y for _, y in all_points))
        if y_limits is None:
            padding = max(1.0, (y_max - y_min) * 0.1)
            y_min, y_max = y_min - padding, y_max + padding
    else:
        x_min, x_max = 0.0, 10.0
        y_min, y_max = y_limits or (0.0, 1.0)
    x_max = max(x_max, x_min + 0.1)
    y_max = max(y_max, y_min + 1.0)

    def point(x, y):
        return (left + (x - x_min) / (x_max - x_min) * (right - left),
                bottom + (y - y_min) / (y_max - y_min) * (top - bottom))

    for fraction in (0, 0.5, 1):
        y = y_min + fraction * (y_max - y_min)
        graph.draw_line((left, point(x_min, y)[1]), (right, point(x_min, y)[1]), color="#d9e4de")
        graph.draw_text(f"{y:.1f}", (23, point(x_min, y)[1]), color=INK, font=("Helvetica", 9))
    graph.draw_text(f"{x_min:.1f}", (left, 12), color=INK, font=("Helvetica", 9))
    graph.draw_text(f"{x_max:.1f}", (right - 10, 12), color=INK, font=("Helvetica", 9))
    graph.draw_text(x_label, ((left + right) / 2, 12), color=INK, font=("Helvetica", 9))
    for y in guides:
        if y_min <= y <= y_max:
            graph.draw_line(point(x_min, y), point(x_max, y), color="#b66a49")
    for xs, ys, color in series:
        segment = []
        for x, y in zip(xs, ys):
            if y is None or not math.isfinite(y):
                if len(segment) > 1:
                    graph.draw_lines(segment, color=color, width=2)
                segment = []
            else:
                segment.append(point(x, y))
        if len(segment) > 1:
            graph.draw_lines(segment, color=color, width=2)
        elif segment:
            graph.draw_circle(segment[0], 2, fill_color=color, line_color=color)


class PPGWindow:
    def __init__(self, demo=False, port=None, language="English"):
        self.language = language
        self.demo = DemoSource() if demo else None
        log_path = DATA_DIRECTORY / "logs" / f"system_{datetime.now():%Y%m%d_%H%M%S_%f}.log"
        self.controller = MonitorController(SystemLogger(log_path))
        self.worker = CommunicationManager()
        self.window = build_window(demo, language)
        self._last_revision = -1
        self._last_log_revision = -1
        self._session_count = 1
        self._session_index = 0
        self._next_demo_at = time.monotonic()
        self._closed = False
        self.worker.start()
        self.refresh_ports()
        if demo:
            self.window["-PORT-"].update(self.t("SIMULATED"), disabled=True)
            self.controller.begin()
            self.controller.handle(CommunicationEvent("state", ConnectionState.CONNECTED, time.monotonic(), 0))
            self.controller.logger.log("Demo Mode: Simulated Data")
        elif port:
            self.window["-PORT-"].update(port)
            self.controller.begin()
            self.worker.connect(port)
        self.render()

    def t(self, message, **values):
        return translate(message, self.language, **values)

    def change_language(self, language, values):
        if language not in LANGUAGES or language == self.language:
            return
        self.language = language
        self.window.close()
        self.window = build_window(self.demo is not None, language)
        self.refresh_ports()
        for key in ("-PORT-", "-LOW-", "-HIGH-", "-CSV-PATH-"):
            if key in values:
                self.window[key].update(values[key])
        if self.demo:
            self.window["-PORT-"].update(self.t("SIMULATED"), disabled=True)
        self.window["-SESSION-"].update(
            values=[self.t("Session {number}", number=i + 1) for i in range(len(self.controller.sessions))],
            value=self.t("Session {number}", number=self._session_index + 1))
        self._last_revision = self._last_log_revision = -1
        self.render()

    def refresh_ports(self):
        try:
            self.window["-PORT-"].update(values=available_ports())
        except OSError as error:
            self.controller.logger.log(f"Port Scan Failed: {error}")

    def handle_event(self, event, values):
        model = self.controller
        try:
            if event == "-LANGUAGE-":
                self.change_language(values["-LANGUAGE-"], values)
            elif event == "Refresh ports":
                self.refresh_ports()
            elif event == "-CONNECT-":
                if model.monitoring:
                    self.worker.disconnect()
                    model.disconnect()
                else:
                    if self.demo:
                        self.demo = DemoSource()
                        model.begin()
                        model.handle(CommunicationEvent("state", ConnectionState.CONNECTED, time.monotonic(), 0))
                        self._next_demo_at = time.monotonic()
                    else:
                        port = str(values["-PORT-"] or "").strip()
                        if not port:
                            raise ValueError("Select or enter the paired SPP serial port")
                        model.begin()
                        self.worker.connect(port)
            elif event == "Apply limits":
                model.set_limits(float(values["-LOW-"]), float(values["-HIGH-"]))
            elif event == "-RECORD-":
                if self.demo:
                    self.demo.recording = not model.recording
                else:
                    self.worker.set_recording(not model.recording)
            elif event == "-SESSION-":
                self._session_index = int(values["-SESSION-"].split()[-1]) - 1
                self.window["-CSV-PATH-"].update(str(_csv_path()))
            elif event == "Save CSV":
                session = model.sessions[self._session_index]
                if not session.summary().sample_count:
                    raise ValueError("No recorded samples in the selected session")
                path = str(values["-CSV-PATH-"]).strip()
                if not path:
                    raise ValueError("Choose a CSV destination")
                saved = session.export_csv(Path(path).with_suffix(".csv"))
                model.logger.log(f"CSV Saved: {saved}")
        except (ValueError, OSError, ConnectionError) as error:
            model.logger.log(str(error))

    def tick(self):
        model = self.controller
        for event in self.worker.poll():
            model.handle(event)
        now = time.monotonic()
        if self.demo and model.monitoring and now >= self._next_demo_at:
            model.receive(self.demo.next_packet(), now)
            self._next_demo_at = now + 1.0
        model.tick()
        self.render()

    def render(self):
        model, window = self.controller, self.window
        t = self.t
        if model.revision != self._last_revision:
            self._last_revision = model.revision
            analysis = model.latest_analysis
            window["-ESP-"].update(format_bpm(model.embedded_bpm))
            window["-HOST-"].update(format_bpm(analysis.host_bpm if analysis else None))
            window["-CONNECTION-"].update(t(model.connection.value))
            window["-CONNECT-"].update(t("Disconnect" if model.monitoring else "Connect"))
            window["-RECORD-"].update(t("Stop recording" if model.recording else "Start recording"),
                                    disabled=model.connection != ConnectionState.CONNECTED or model.alarms.communication)
            window["-QUALITY-"].update(t(analysis.quality.value if analysis else "NO SIGNAL"))
            alarm = model.alarms.pulse
            color = {PulseAlarm.HIGH: "#b62030", PulseAlarm.LOW: "#a05a00",
                     PulseAlarm.NORMAL: TEAL, PulseAlarm.UNAVAILABLE: "#596a64"}[alarm]
            window["-PULSE-"].update(t("Pulse: {state}", state=t(alarm.value)), text_color=color)
            comm = "ALARM — no packet for 5 s" if model.alarms.communication else ("OK" if model.alarms.last_packet_at is not None else "WAITING" if model.monitoring else "IDLE")
            window["-COMM-"].update(t("Communication: {state}", state=t(comm)), text_color="#b62030" if model.alarms.communication else INK)
            window["-REASON-"].update(t(analysis.quality_reason if analysis else "Waiting for fresh samples"))
            window["-PROCESSING-"].update(t("Host processing: {ms:.1f} ms", ms=model.last_processing_ms))
            window["-FREQUENCY-"].update(t("Dominant pulse frequency: --") if not analysis or analysis.fft_bpm is None
                                        else t("Dominant pulse: {hz:.2f} Hz / {bpm:.1f} BPM", hz=analysis.dominant_frequency_hz, bpm=analysis.fft_bpm))
            draw_plot(window["-WAVE-"], [(analysis.times_s, analysis.raw, TEAL)] if analysis else [], x_label=t("Time (s)"))
            draw_plot(window["-FILTER-"], [(analysis.times_s, analysis.filtered, "#c45129")] if analysis else [], x_label=t("Time (s)"))
            draw_plot(window["-SPECTRUM-"], [(analysis.frequencies_hz, analysis.spectrum_magnitude, "#3056a3")] if analysis else [], x_label=t("Frequency (Hz)"))
            xs = [row[0] for row in model.trend]
            draw_plot(window["-TREND-"], [(xs, [row[1] for row in model.trend], TEAL),
                                         (xs, [row[2] for row in model.trend], "#c45129")],
                      y_limits=(0, max(220, model.alarms.high + 10, max((row[1] or 0 for row in model.trend), default=0) + 10)),
                      guides=(model.alarms.low, model.alarms.high), x_label=t("Time (s)"))
        if len(model.sessions) != self._session_count:
            self._session_count = len(model.sessions)
            self._session_index = self._session_count - 1
            window["-SESSION-"].update(values=[t("Session {number}", number=i + 1) for i in range(self._session_count)], value=t("Session {number}", number=self._session_count))
            window["-CSV-PATH-"].update(str(_csv_path()))
        summary = model.sessions[self._session_index].summary()
        seconds = int(summary.duration_seconds)
        window["-SUMMARY-"].update(f"{t('Duration')}: {seconds // 60:02d}:{seconds % 60:02d}\n"
                                  f"{t('Average valid host BPM')}: {format_bpm(summary.average_bpm)}\n"
                                  f"{t('Minimum valid host BPM')}: {format_bpm(summary.minimum_bpm)}\n"
                                  f"{t('Maximum valid host BPM')}: {format_bpm(summary.maximum_bpm)}\n"
                                  f"{t('Valid measurements')}: {summary.valid_measurements}\n{t('Samples')}: {summary.sample_count}")
        if model.logger.revision != self._last_log_revision:
            self._last_log_revision = model.logger.revision
            window["-LOG-"].update("\n".join(model.logger.entries), autoscroll=True)
        if model.logger.write_error:
            window["-NOTICE-"].update(t("Log file could not be written: {error}", error=model.logger.write_error), text_color="#b62030")

    def run(self, duration_seconds=None):
        deadline = None if duration_seconds is None else time.monotonic() + duration_seconds
        try:
            while deadline is None or time.monotonic() < deadline:
                event, values = self.window.read(timeout=GUI_POLL_MS)
                if event == sg.WIN_CLOSED:
                    break
                self.handle_event(event, values)
                self.tick()
        finally:
            self.close()
        return 0

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.controller.stop_recording()
        self.worker.stop()
        self.window.close()


def run(demo=False, port=None, duration_seconds=None, language="English") -> int:
    return PPGWindow(demo=demo, port=port, language=language).run(duration_seconds)
