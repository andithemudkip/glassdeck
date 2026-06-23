# Session: 2026-06-23-shift-lever-vs-clutch

**Firmware:** can-logger @ 61c64ae
**Bitrate:** 500 kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination in
**Capture start:** 2026-06-23T18:09:00+00:00
**Capture end:** 2026-06-23T18:09:52+00:00
**Total frames:** 21848
**Unique IDs:** 11
**Event marks:** 7  (4 clutch + 3 gear; see events.csv)

## Bike state

- Engine off
- Key on, kill switch in run
- Neutral throughout the session
- Bike on rear paddock stand
- Ambient: indoor garage, ~room temp

## Rider actions during session

Disambiguating `129` D0 bit 3 — clutch lever vs shift-lever-displaced. See [`docs/experiments/2026-06-23-shift-lever-vs-clutch.md`](../../docs/experiments/2026-06-23-shift-lever-vs-clutch.md) for hypothesis and analysis.

Phase 1 — clutch only, no shifter input:
- Mark `clutch` pressed *before* each clutch pull (mark precedes action).
- 4 clutch pulls. First was a brief tap (~0.1 s) followed by a sustained pull a couple seconds later; the other three were clean 2.4–2.9 s holds.

Phase 2 — shifter only, no clutch input:
- Mark `gear` pressed *before* each shift-lever press.
- 3 light shift-lever presses (preload, no through-shift, no actual gear engagement).

## Anomalies

- Clutch-lever sensor on this physical bike is mechanically finicky: only trips when the lever is pulled upward past a threshold (well into the pull, not at the start of travel). Shallow / partial pulls — like the gentle pumps used in the Phase A clutch-only capture from 2026-06-19 — may not actuate the switch and would produce a false null. Documented in [`docs/findings/can/signal-clutch.md`](../../docs/findings/can/signal-clutch.md).
