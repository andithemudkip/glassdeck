# Session: 2026-07-10-brakes-stationary

**Firmware:** can-logger @ 4855deb
**Bitrate:** 500 kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination (wifi-bridge firmware, WebSocket to laptop via `bin/experiment-wifi-bridge`)
**Termination:** [TODO: in / out]
**Capture start:** 2026-07-10T15:27:55+00:00
**Capture end:** 2026-07-10T15:32:06+00:00
**Total frames:** 101752
**Unique IDs:** 11
**Event marks:** 21  (see events.csv)
**Clock:** wifi-bridge `(sec.us)` prefixes normalized to host wall-clock (added +1783696824.723811 s to every frame; capture.log frames and events.csv marks share one time base)

**Firmware note:** capture.py's `--firmware-rev` auto-detect reads `firmware/can-logger/` and reports `4855deb`; the actual firmware on the ESP32 was **wifi-bridge**, not can-logger — auto-detect bug worth fixing separately.

## Bike state
Key ON, engine OFF, kill switch RUN, neutral, side stand down. Bike stationary on both wheels. Indoor/driveway ambient. No throttle work throughout — right hand and foot exclusively on front lever / rear pedal.

## Rider actions during session
Driven by `procedure.yaml.snapshot` (byte-identical copy of `docs/experiments/2026-07-10-brakes-stationary.procedure.yaml`). 21 auto-marks in `events.csv` correspond 1:1 to the procedure's mark-emitting steps.

## Anomalies
None during capture. The `541` D5 01→02 latch at t=+55.76 s post-key-on is expected behavior (see [[battery-voltage-absent-from-always-on-broadcasts]]) and analyzed in the experiment writeup.

