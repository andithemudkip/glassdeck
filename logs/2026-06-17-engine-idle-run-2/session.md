# Session: 2026-06-17-engine-idle-run-2

**Firmware:** can-logger @ a9f53db
**Bitrate:** 500 kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination **in place** (not desoldered)
**Capture start:** 2026-06-17T16:13:19+00:00
**Capture end:** 2026-06-17T16:17:04+00:00
**Total frames:** 88872
**Unique IDs:** 11
**Event marks:** 4  (see events.csv)

## Bike state

Engine **partially warm** at session start. Run 1 ran for ~3 min of engine-on, then bike sat key-off for ~13 min — enough to soak some heat back into the head but the engine had not returned to cold. Rider-reported coolant gauge: above cold-zone, well below half. Bike in neutral, side stand down, no rider on the seat. Ambient ~30 °C, fuel ~50 % (no refuel between runs). Adapter wiring unchanged. Dash post-self-test: check engine + ABS lit; check-engine extinguished ~1 s after engine catch; ABS stayed lit through idle (stationary).

## Rider actions during session

Capture started 16:13:19; ~7 s silent head. Key on at 16:13:26.92 (`key_on` mark). Held key-on engine-off for 29.5 s. Starter pressed at 16:13:56.38 (`s` hotkey → `starter button`). Engine settled to idle ~2.85 s later; spacebar pressed at 16:13:59.24 (`idle_settled`, second `generic mark` — recorded properly this run, no proxy needed). Held idle for 176.4 s untouched. Kill switch pressed at 16:16:55.64 (`k` hotkey → `kill switch`). Engine decayed, key off after silence, capture stopped at 16:17:04 (~7 s decay tail).

## Anomalies

- WS2812 activity LED still dark despite continuous frame arrival — known issue, see Run 1 session.md.
- No `bus_err` / status-line cross-check — known limitation (`capture.py` discards `# …` lines). Frame count is within ~1 % of Run 1's idle window, which is the indirect signal of consistency.
- Spacing from Run 1 was ~13 min key-off — comfortably above the ≥60 s floor, close to the ~10 min ideal. **Engine thermal state is not identical to Run 1**, see Bike state above.
