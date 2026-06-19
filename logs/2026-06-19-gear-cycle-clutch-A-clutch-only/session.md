# Session: 2026-06-19-gear-cycle-clutch-A-clutch-only

**Firmware:** can-logger @ 61c64ae
**Bitrate:** 500 kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination [TODO: in / out]
**Capture start:** 2026-06-19T12:29:39+00:00
**Capture end:** 2026-06-19T12:31:21+00:00
**Total frames:** 37593
**Unique IDs:** 11
**Event marks:** 7  (see events.csv)

## Bike state

- Ignition: key on (position 1), kill switch in RUN.
- Engine: off throughout.
- Gear: neutral (N) throughout. Clutch lever started/ended at rest (released).
- Side stand: <TODO: down? up?>
- Ambient temp: <TODO>
- Anything odd at the bike: <TODO or "none">

## Rider actions during session

Phase A of the gear-cycle-clutch experiment — clutch-only baseline, no shifting. Five slow clutch pumps in neutral. Each pump: lever fully pulled to the bar, held ~2 s, released, then ~3 s rest before the next.

**Mark convention used:** `c` was pressed **once per pump, at the start of the pull-in** (lever motion beginning). Releases were not marked. So `events.csv` has 5 `c` marks = 5 clutch-in events; release timestamps must be inferred (~2 s after each `c` based on the held-duration target).

This differs from the experiment doc's "c on both edges" wording. The procedure was updated post-hoc to make the edge-each-press convention explicit for Phase B. The Phase A analysis (`scripts/clutch_scan.py`) does not depend on edge interpretation.

## Anomalies

None observed at the bike. The CAN-side null result (no clutch bit found in D0–D6 of any always-on ID) is documented in the experiment's Result section, not as an anomaly here.
