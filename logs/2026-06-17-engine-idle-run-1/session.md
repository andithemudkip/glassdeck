# Session: 2026-06-17-engine-idle-run-1

**Firmware:** can-logger @ a9f53db
**Bitrate:** 500 kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination **in place** (not desoldered)
**Capture start:** 2026-06-17T15:56:23+00:00
**Capture end:** 2026-06-17T16:00:10+00:00
**Total frames:** 89803
**Unique IDs:** 11
**Event marks:** 3  (see events.csv)

## Bike state

Engine cold at session start (no run today prior to the cold-boot session ~15 min earlier; cooled through key-off-baseline + key-on-cold-boot). Bike in neutral, side stand down, no rider on the seat. Ambient ~30 °C, fuel ~50 %. Adapter wiring unchanged from previous sessions: pin 2 → CANH, pin 5 → CANL, pin 3 → GND, pin 4 unwired. Dash post-self-test: check engine + ABS lit (per [`docs/findings/bike/dash-warning-lights.md`](../../docs/findings/bike/dash-warning-lights.md)). Check-engine extinguished ~1 s after the engine caught; ABS remained lit through the idle window (vehicle stationary).

## Rider actions during session

Pre-key-on silent head: capture started at 15:56:23, key off for ~7 s. At 15:56:30.15 the key was turned to position 1 and the spacebar pressed simultaneously (first `generic mark` = `key_on` anchor). Held key-on, engine off, for 30.1 s through the dash self-test and into steady key-on-no-engine state — no controls touched. At 15:57:00.29 the starter button was pressed (`s` hotkey at the same moment → `starter button` row). Engine caught and settled to idle within ~1 s of the starter press — the planned second spacebar for `idle_settled` was **missed**; rider notes the moment was ≤1 s after the starter press, so analysis uses `starter + 1 s` as an `idle_settled` proxy throughout (an approximation, not an event mark). Held idle for 179.9 s untouched. Kill switch pressed at 16:00:00.25 (`k` hotkey at the press → `kill switch` row). Engine decayed, key off after silence, capture stopped at 16:00:10 (~10 s of decay tail).

## Anomalies

- **`idle_settled` mark was missed.** Worked around with the `starter + 1 s` proxy. Acceptable for ID inventory and period analysis; not acceptable if precise sub-100 ms timing of the start transient ever matters. Document the proxy if cited downstream.
- **WS2812 activity LED still dark** despite continuous frame arrival (same as the cold-boot session). Cause not yet investigated — see follow-up listed in the experiment file.
- **No `bus_err` / status-line cross-check.** As before, `capture.py` discards the firmware `# …` comment lines. The clean 11-ID inventory with stable periods is the indirect signal.
- **Post-kill behaviour mildly interesting** (not anomalous, just noted): `540` and `5B0` stop broadcasting within ~0.3 s of the kill press, while `12A` and `450` keep going through the full 6 s of post-kill capture. Suggests these IDs come from different modules that power down at different rates. Recorded in the experiment file's Result section.

## Derived artifacts

- Per-window ID inventory and period analysis in [`docs/experiments/2026-06-17-engine-idle-baseline-x3.md`](../../docs/experiments/2026-06-17-engine-idle-baseline-x3.md).
- Re-run inventory with: `python scripts/inventory_ids.py logs/2026-06-17-engine-idle-run-1 --anchor-label "starter button"`.
- Findings updated: [`docs/findings/can/always-on-broadcast-ids.md`](../../docs/findings/can/always-on-broadcast-ids.md).
