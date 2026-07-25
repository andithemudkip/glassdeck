# Session: 2026-07-24-abs-mode-toggle

**Firmware:** can-logger @ 4855deb
**Bitrate:** 500 kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination [TODO: in / out]
**Capture start:** 2026-07-24T15:08:57+00:00
**Capture end:** 2026-07-24T15:11:32+00:00
**Total frames:** 3448
**Unique IDs:** 11
**Event marks:** 5  (see events.csv)
**Clock:** wifi-bridge `(sec.us)` prefixes normalized to host wall-clock (added +1784905639.382138 s to every frame; capture.log frames and events.csv marks share one time base)

## Bike state

Key ON, engine OFF, kill RUN, neutral, side stand up, rider seated (see `2026-07-24-abs-mode-toggle-3/session.md` for why the planned stand-down setup was abandoned).

## Rider actions during session

Rider followed the procedure YAML in full — all 4 toggles performed.

## Anomalies

**Capture failed silently after ~13 s.** Only 3448 frames captured (~250 fps × 13 s), all with timestamps between 15:08:58 and 15:09:11 UTC. All 4 mode-toggle marks (15:10:06–15:11:00 UTC) landed with no frame data underneath. Best guess: wifi-bridge websocket dropped, `capture.py` kept running (marks + procedure completed normally) but no more frames streamed through. Not usable for analysis — session re-run as `2026-07-24-abs-mode-toggle-3/` (attempt 2 was 0 frames, connection setup problem). Kept as evidence of the failure mode; do not delete.
