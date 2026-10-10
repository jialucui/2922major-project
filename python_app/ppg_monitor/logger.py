"""Course-format English timestamps and persistent, event-only logging."""
from collections import deque
from datetime import datetime
from pathlib import Path

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def format_event(message: str, when: datetime | None = None) -> str:
    when = datetime.now() if when is None else when
    return (f"{_DAYS[when.weekday()]} {_MONTHS[when.month - 1]} {when.day:02d} "
            f"{when:%H:%M:%S %Y}: {message}")


class SystemLogger:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else None
        self.entries: deque[str] = deque(maxlen=250)
        self.write_error: str | None = None
        self.revision = 0

    def log(self, message: str, when: datetime | None = None) -> str:
        entry = format_event(message, when)
        self.entries.append(entry)
        self.revision += 1
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as output:
                    output.write(entry + "\n")
            except OSError as error:
                self.write_error = str(error)
        return entry
