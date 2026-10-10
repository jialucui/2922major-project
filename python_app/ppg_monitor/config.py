"""Host configuration; acquisition constants live in protocol.py."""
from pathlib import Path

SERIAL_BAUD = 115200
SERIAL_READ_TIMEOUT_S = 0.1
SERIAL_WRITE_TIMEOUT_S = 0.3
RECONNECT_INTERVAL_S = 1.0
COMMUNICATION_TIMEOUT_S = 5.0
GUI_POLL_MS = 50
DEFAULT_LOW_BPM = 50.0
DEFAULT_HIGH_BPM = 120.0
DATA_DIRECTORY = Path(__file__).resolve().parents[2] / "data"
