# Session: 2026-06-24-front-wheel-decay-mark

**Firmware:** can-logger @ 61c64ae
**Bitrate:** 500 kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination [TODO: in / out]
**Capture start:** 2026-06-24T15:39:14+00:00
**Capture end:** 2026-06-24T15:40:56+00:00
**Total frames:** 40655
**Unique IDs:** 11
**Event marks:** 6 (5 push marks after collapsing the one mis-press; see events.csv)

## Bike state

- Ignition position 1 (key on), kill switch in RUN, neutral. **Engine off.**
- Front of bike lifted on a hydraulic jack under the engine guard; front wheel spinning freely, rear stationary.
- Same physical setup as [[2026-06-24-front-wheel-hand-spin]] (earlier same day).

## Rider actions during session

Follow-up to the morning hand-spin: 5 harder pushes (aiming for ~10 km/h on the dash) with one `b` press per push at the moment the dash flipped from low single digits to 0 on the decay tail. Goal was to anchor the LSB at the dash 3→0 transition.

Mis-press on the 5th push: pressed `b` once early, then pressed again when the dash actually flipped. Analysis collapses any two `b` marks within 2 s to the later one.

Rider noted dash **briefly showed "2"** km/h (never "1") on at least one decay tail before flipping to 0 — corroborated the round-to-nearest dash quantisation rule and the ECU broadcast floor (~2.33 km/h).

`b` is mapped to `(beam, high beam toggle)` in `capture.py` HOTKEYS, so the events.csv labels read "high beam toggle" — purely a naming artifact, no high beam was actually toggled.

## Anomalies

None. Jack stable throughout.
