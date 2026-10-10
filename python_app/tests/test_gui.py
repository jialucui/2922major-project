"""GUI rendering/controller integration without requiring a desktop display."""
from collections import defaultdict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ppg_monitor.gui import PPGWindow
from ppg_monitor.protocol import Status


class Element:
    CanvasSize = (940, 150)
    def __init__(self):
        self.value = ""
        self.options = {}
        self.lines = []
    def update(self, value=None, **kwargs):
        if value is not None: self.value = value
        self.options.update(kwargs)
    def erase(self): self.lines.clear()
    def draw_line(self, *args, **kwargs): pass
    def draw_text(self, *args, **kwargs): pass
    def draw_lines(self, points, **kwargs): self.lines.append(points)
    def draw_circle(self, *args, **kwargs): pass


class Window(defaultdict):
    def __init__(self): super().__init__(Element)
    def close(self): pass


class GuiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        for patcher in (
            patch("ppg_monitor.gui.build_window", return_value=Window()),
            patch("ppg_monitor.gui.CommunicationManager.start"),
            patch("ppg_monitor.gui.available_ports", return_value=["SPP-test"]),
            patch("ppg_monitor.gui.DATA_DIRECTORY", Path(self.directory.name)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = PPGWindow(demo=True)
        self.addCleanup(self.app.close)

    def stream(self, count=12):
        for _ in range(count):
            self.app.controller.receive(self.app.demo.next_packet())
        self.app.render()

    def test_large_bpm_labels_trend_and_research_plots(self):
        self.stream()
        window = self.app.window
        self.assertEqual(window["-ESP-"].value, "72.4")
        self.assertRegex(window["-HOST-"].value, r"^\d+\.\d$")
        for graph in ("-WAVE-", "-TREND-", "-FILTER-", "-SPECTRUM-"):
            self.assertTrue(window[graph].lines, graph)
        self.assertIn("Hz", window["-FREQUENCY-"].value)

    def test_alarm_visual_and_validation_error_are_in_main_window(self):
        self.stream()
        self.app.handle_event("Apply limits", {"-LOW-": "80", "-HIGH-": "120"})
        self.app.render()
        self.assertEqual(self.app.window["-PULSE-"].value, "Pulse: LOW")
        self.app.handle_event("Apply limits", {"-LOW-": "180", "-HIGH-": "120"})
        self.app.render()
        self.assertIn("0 < low < high", self.app.window["-LOG-"].value)

    def test_five_second_alarm_and_recovery_render(self):
        model = self.app.controller
        now = model.alarms.monitoring_since + 5
        with patch.object(model, "clock", return_value=now):
            model.tick()
            self.app.render()
            self.assertIn("ALARM", self.app.window["-COMM-"].value)
            model.receive(self.app.demo.next_packet(), now)
            self.app.render()
        self.assertEqual(self.app.window["-COMM-"].value, "Communication: OK")

    def test_csv_export_includes_alarm_and_each_sample(self):
        self.app.handle_event("-RECORD-", {})
        self.stream(3)
        self.app.handle_event("-RECORD-", {})
        self.stream(1)
        destination = Path(self.directory.name) / "recorded.csv"
        self.app.handle_event("Save CSV", {"-CSV-PATH-": str(destination)})
        lines = destination.read_text().splitlines()
        self.assertEqual(len(lines), 151)
        self.assertIn("alarm", lines[0])
        self.assertIn("NORMAL", lines[1])

    def test_language_switch_preserves_recording_limits_and_data(self):
        self.app.demo.recording = True
        self.stream(3)
        model = self.app.controller
        self.app.handle_event("Apply limits", {"-LOW-": "80", "-HIGH-": "120"})
        self.app.handle_event("-LANGUAGE-", {"-LANGUAGE-": "中文", "-PORT-": "SPP-test",
                                               "-LOW-": "80", "-HIGH-": "120", "-CSV-PATH-": "test.csv"})
        self.assertIs(self.app.controller, model)
        self.assertEqual(self.app.window["-ESP-"].value, "72.4")
        self.assertEqual(self.app.window["-PULSE-"].value, "心率：偏低")
        self.assertEqual(self.app.window["-RECORD-"].value, "停止录制")
        self.assertEqual(model.recorder.summary().sample_count, 150)
        self.assertTrue(model.recorder.active)
        self.assertTrue(any(line.endswith(": Pulse Low") for line in model.logger.entries))
        self.app.handle_event("-LANGUAGE-", {"-LANGUAGE-": "English"})
        self.assertEqual(self.app.window["-PULSE-"].value, "Pulse: LOW")


if __name__ == "__main__": unittest.main()
