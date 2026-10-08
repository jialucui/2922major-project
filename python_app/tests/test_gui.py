import math
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    from ppg_monitor.gui import PPGWindow
    from ppg_monitor.protocol import Packet, Status

    GUI_IMPORT_ERROR = None
except (ImportError, OSError) as error:
    GUI_IMPORT_ERROR = str(error)


@unittest.skipIf(GUI_IMPORT_ERROR is not None, f"Qt GUI runtime unavailable: {GUI_IMPORT_ERROR}")
class GuiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_alarm_states_update_from_valid_live_analysis(self):
        window = PPGWindow()
        window.low_threshold.setValue(80)
        samples = [
            int(1800 + 240 * max(0.0, math.sin(2 * math.pi * 1.2 * index / 50)))
            for index in range(600)
        ]
        status = Status.BPM_VALID | Status.SENSOR_PRESENT
        for sequence in range(12):
            packet = Packet(sequence, sequence * 1000, 72, status, tuple(samples[sequence * 50 : (sequence + 1) * 50]))
            window._packet_received(packet)
            self.application.processEvents()

        self.assertEqual(window.quality_label.text(), "GOOD")
        self.assertIn("LOW HEART RATE", window.alarm_label.text())
        window.low_threshold.setValue(50)
        self.assertIn("IN RANGE", window.alarm_label.text())
        window.high_threshold.setValue(60)
        self.assertIn("HIGH HEART RATE", window.alarm_label.text())
        window.close()


if __name__ == "__main__":
    unittest.main()