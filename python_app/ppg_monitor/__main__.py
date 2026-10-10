"""Run the SPP monitor, or a labelled hardware-free demonstration."""
import argparse
from .gui import run


def main():
    parser = argparse.ArgumentParser(description="BMET2922 PPG monitor (Bluetooth Classic SPP)")
    parser.add_argument("--port", help="Paired SPP virtual serial port, e.g. COM5 or /dev/cu.BMET2922-PPG")
    parser.add_argument("--demo", action="store_true", help="Use explicitly labelled synthetic data")
    parser.add_argument("--language", choices=("en", "zh"), default="en", help="Initial UI language")
    parser.add_argument("--duration", type=float, help="Close after this many seconds (for smoke tests)")
    args = parser.parse_args()
    if args.duration is not None and args.duration <= 0:
        parser.error("--duration must be positive")
    if args.demo and args.port:
        parser.error("--demo and --port are mutually exclusive")
    return run(demo=args.demo, port=args.port, duration_seconds=args.duration,
               language="中文" if args.language == "zh" else "English")


if __name__ == "__main__":
    raise SystemExit(main())
