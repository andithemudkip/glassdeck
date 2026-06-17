# Session: 2026-06-17-key-off-baseline

**Firmware:** can-logger @ a9f53db
**Bitrate:** 500 kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination **in place** (not desoldered)
**Capture start:** 2026-06-17T15:31:54+00:00
**Capture end:** 2026-06-17T15:32:56+00:00
**Total frames:** 0
**Unique IDs:** 0
**Event marks:** 0  (see events.csv)

## Bike state

Ignition fully off (position 0). Engine cold, in neutral, side stand down. Battery connected, nothing else touched. Adapter plugged into the diagnostic connector — pin 2 → CANH, pin 5 → CANL, pin 3 → GND; pin 4 (12 V switched) intentionally unwired per ADR 0001. Adapter powered from laptop USB only. Ambient temperature not recorded.

## Rider actions during session

None — no key turn, no controls touched. Capture was started, allowed to run ~62 s of bus silence, then stopped with `q`. `events.csv` is empty beyond the header, consistent with no rider activity.

## Anomalies

None. Capture exited cleanly via `q` (no `disconnect` events logged). Firmware `# ...` status comment lines were not explicitly inspected during the run — `capture.py` discards them — but the absence of any `disconnect` event in `events.csv` is consistent with the driver staying in `state=running` for the full window.
