# BMET2922 Wearable PPG Monitor

An educational ESP32 PPG monitoring prototype with independent embedded and
host heart-rate estimates, BLE transport, live signal analysis, researcher
plots, signal-quality feedback, alarms, and CSV session recording. It is not a
clinical diagnostic device.

## Repository Layout

- `firmware/ppg_monitor/ppg_monitor.ino`: ESP32 sampler, button/LED state,
  embedded beat detector, BLE peripheral, and Serial Plotter output.
- `python_app/ppg_monitor/protocol.py`: versioned packet codec and BLE fragment
  assembly shared with the firmware layout.
- `python_app/ppg_monitor/signal_processing.py`: host filtering, beat/FFT
  estimates, and signal-quality classification.
- `python_app/ppg_monitor/bluetooth_worker.py`: asynchronous BLE scanner/client
  running outside the GUI thread.
- `python_app/ppg_monitor/gui.py`: Monitor, Researcher, and Session tabs.
- `python_app/ppg_monitor/recorder.py`: sample-level CSV export and summaries.
- `python_app/tests/`: protocol, DSP, quality, and recording tests.

## Hardware Decisions To Confirm

The board model, sensor model/output, and GPIO assignments were not provided.
Confirm these against the exact board and sensor documentation before wiring or
uploading; this project deliberately does not select pins for you.

- `PPG_PIN`: analog-capable ESP32 GPIO connected to the sensor analog output.
- `BUTTON_PIN`: GPIO for the push button. Firmware uses `INPUT`; wire a stable
  external pull-up or pull-down and set the active level accordingly.
- `LED_PIN`: status LED GPIO with suitable current limiting; set its active
  level for the actual LED wiring.
- `PPG_POLARITY`: `1` if a pulse rises above baseline, `-1` if it falls.
- Confirm the sensor output voltage is safe for the selected ESP32 ADC input.

The firmware requires `PPG_PIN`, `BUTTON_PIN`, `LED_PIN`,
`BUTTON_ACTIVE_LEVEL`, `LED_ACTIVE_LEVEL`, and `PPG_POLARITY` build macros.
`LOW`/`HIGH` use the Arduino definitions. One example command, after replacing
all placeholders with confirmed values, is:

```sh
arduino-cli core install esp32:esp32
arduino-cli lib install NimBLE-Arduino
arduino-cli compile --fqbn <your-esp32-board-fqbn> \
  --build-property 'compiler.cpp.extra_flags=-DPPG_PIN=<adc-gpio> -DBUTTON_PIN=<button-gpio> -DLED_PIN=<led-gpio> -DBUTTON_ACTIVE_LEVEL=<LOW-or-HIGH> -DLED_ACTIVE_LEVEL=<LOW-or-HIGH> -DPPG_POLARITY=<1-or-minus-1>' \
  firmware/ppg_monitor
```

For a CSV timing/debug stream instead of the default Serial Plotter format, add
`-DSERIAL_CSV` to the extra flags. Upload using the board and port selected for
the actual hardware. Serial runs at 115200 baud. The default Serial Plotter
series are `ppg`, adaptive `threshold`, debounced `button`, `bpm` (zero means
unavailable), and `recording`.

The sampler uses 20 ms `millis()` deadlines and does not use `delay(20)`. It
skips an expired deadline rather than taking late samples in a burst and marks
the affected 50-sample block with `TIMING_GAP`. The button toggles recording
after five identical 20 ms samples; the LED follows recording state. BLE
commands can also set recording state. The embedded peak detector maintains an
adaptive baseline/threshold, accepts 300–2000 ms IBIs, and averages up to four
valid intervals; until a valid interval exists it sends unavailable BPM.

## BLE Wire Protocol

The ESP32 advertises as `BMET2922-PPG` with service UUID
`a6210001-8f3c-4f72-a87c-04a21b292201`. Data notifications use characteristic
`a6210002-8f3c-4f72-a87c-04a21b292201`; recording commands are written to
`a6210003-8f3c-4f72-a87c-04a21b292201`.

Every data frame is exactly 115 bytes. Multi-byte fields are little-endian.
The CRC is CRC-16/CCITT (initial value `0xFFFF`, polynomial `0x1021`) over
bytes 0–112, with the CRC stored little-endian.

| Offset | Size | Field |
|---:|---:|---|
| 0 | 2 | ASCII magic `PP` |
| 2 | 1 | Protocol version (`1`) |
| 3 | 2 | Packet sequence (`uint16`, wraps) |
| 5 | 4 | First sample timestamp in ESP32 `millis()` (`uint32`) |
| 9 | 2 | Embedded BPM (`uint16`; `0xFFFF` means unavailable) |
| 11 | 1 | Status bits below |
| 12 | 1 | Sample count (`50`) |
| 13 | 100 | Fifty raw ADC values (`uint16` each) |
| 113 | 2 | CRC-16/CCITT |

Samples are nominally 20 ms apart. The first sample timestamp plus that rate
reconstructs individual sample times; `TIMING_GAP` warns that one or more
deadlines were missed in that block.

| Bit | Meaning |
|---:|---|
| 0 | Recording active |
| 1 | Embedded BPM is valid |
| 2 | Debounced button is pressed |
| 3 | Embedded detector sees pulse amplitude |
| 4 | Sampling timing gap occurred in this block |

Each BLE notification contains a four-byte fragment header followed by up to
16 frame bytes: frame sequence (`uint16` little-endian), fragment index
(`uint8`, zero-based), fragment count (`uint8`), payload. This stays within the
default 20-byte ATT notification limit. The host reassembles and CRC-checks a
full frame before analysis. Control writes are exactly `[0x01, 0x00]` for stop
and `[0x01, 0x01]` for start.

## Python Desktop App

Install and start from `python_app/` using Python 3.11 or newer:

```sh
cd python_app
python -m pip install -r requirements.txt
python -m ppg_monitor
```

The app scans for nearby BLE devices; select the ESP32, connect, and then use
the Monitor, Researcher, and Session tabs. Bluetooth scan, connect, and receive
operations run on a dedicated asyncio thread. After an interruption, the app
shows disconnection; scan and reconnect to resume. The packet sequence tracker
reports missing/out-of-order blocks, and the signal history is reset across a
detected gap so BPM is not computed across missing data.

Host processing uses the actual 50 Hz sample rate and a third-order
0.5–4 Hz Butterworth band-pass filter. A 12-second rolling window supports
peak detection and Hann-window FFT analysis. Host BPM is only presented when
quality is GOOD: at least five seconds of data, usable non-clipped amplitude,
at least two valid beat intervals, and interval coefficient of variation no
greater than 0.25. Flat/no-contact-like input is NO SIGNAL; warm-up, clipping,
or unreliable peaks are POOR. FFT-derived BPM is shown only when its frequency
agrees with the independently detected host BPM. These are prototype signal
quality heuristics, not clinical thresholds.

The default alarm limits are 50 and 120 BPM and can be adjusted in Monitor.
Recording can be toggled in the app or with the device button. CSV export
includes per-sample device timestamps, raw and filtered PPG, embedded/host/FFT
BPM, quality, status flags, and session summary fields. The summary average,
minimum, and maximum include only valid host BPM measurements.

## Verification

Run the host test suite with dependencies installed:

```sh
cd python_app
python -m unittest discover -s tests -v
```

The suite covers packet byte order/CRC, BLE fragmentation, sequence gaps and
wraparound, synthetic 72 BPM host estimates, unstable/no-signal quality, and
CSV sample counts/session statistics. Hardware verification still requires the
chosen ESP32 and sensor:

1. Build and upload with the confirmed board/GPIO settings; record 10 seconds
	of `SERIAL_CSV` output and check normal timestamp deltas are 20 ms.
2. Check five-sample button debounce, LED behavior, embedded BPM, and the
	Serial Plotter threshold on a stable finger contact and with no contact.
3. Compare host and embedded BPM against a reference pulse source; report
	packet gaps and any timing-gap status rather than hiding them.
4. Disconnect/reconnect BLE, verify connection status and sequence-gap log,
	then confirm analysis recovers after fresh samples arrive.
5. Trigger high/low alarm limits, record and stop a session, export CSV, and
	verify sample rows and valid-only summary statistics.

For the 4–6 minute demonstration, show acquisition/Serial Plotter first, then
BLE packet delivery and embedded BPM, Monitor alarms/recording, and finally
Researcher filtering, FFT, and signal quality. Each team member should explain
their actual module inputs, outputs, and failure handling.

## Suggested Team Split

- Member 1: confirm sensor/board wiring and own the ESP32 sampler, five-sample
  debounce, LED/recording behavior, embedded BPM, and Serial Plotter checks.
- Member 2: own the documented BLE frame, packet-loss/reconnect checks, host
  filtering, independent BPM, FFT, and signal-quality criteria.
- Member 3: own the Qt GUI, live views and alarms, session controls, CSV export,
  and end-to-end integration. All members should participate in validation.