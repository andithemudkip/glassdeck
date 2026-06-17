# Session: 2026-06-17-key-on-cold-boot

**Firmware:** can-logger @ a9f53db
**Bitrate:** 500 kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination **in place** (not desoldered)
**Capture start:** 2026-06-17T15:39:19+00:00
**Capture end:** 2026-06-17T15:42:20+00:00
**Total frames:** 72916
**Unique IDs:** 11
**Event marks:** 1  (see events.csv)

## Bike state

Engine cold (had not run today). Ignition turned to position 1 (key-on, engine off); starter never pressed. Neutral, side stand down. Adapter wiring unchanged from `2026-06-17-key-off-baseline` (pin 2 → CANH, pin 5 → CANL, pin 3 → GND, pin 4 unwired). Ambient temperature ~30 °C, fuel ~50%.

Dash readout after self-test settled: **check engine** and **ABS** warning lights both lit and held for the duration of the capture. Per rider knowledge of this bike, that's the expected key-on engine-off state — check engine extinguishes ~1 s after the engine actually starts, and ABS extinguishes once vehicle speed crosses ~6 km/h. Captured behavior is documented as a finding in [`docs/findings/bike/dash-warning-lights.md`](../../docs/findings/bike/dash-warning-lights.md) and constrains the interpretation of the broadcast IDs collected here: any signal that means "engine running" or "ABS active" must be in its *inactive / not-yet-ok* state across this entire capture.

## Rider actions during session

Pre-key-on silent head: capture started at 15:39:19, key remained off for ~7 s. At 15:39:26.39 the key was turned to position 1 and the spacebar pressed simultaneously to drop the `generic mark` event (the t=0 anchor for analysis). The bike then sat untouched at key-on through to the end of capture at 15:42:20, ~174 s of bus activity. No other controls were touched.

## Anomalies

- **WS2812 activity LED stayed dark** the entire session despite ~419 frames/s arriving on the bus. Capture itself was unaffected (frames recorded, `events.csv` clean, no `disconnect` rows). Most likely cause per `firmware/can-logger/README.md`: this DevKitC-1 board revision routes the LED to GPIO48, not GPIO38. Resolution deferred to a tooling-side experiment — rebuild with `-DLED_GPIO=48` and re-bench, or scope GPIO38 to confirm the firmware is writing pulses to an unconnected pin. Capture path is not blocked on this.
- No `bus_err` / status-line cross-check during the session (capture.py discards `# …` comment lines and we didn't shadow-monitor on a second port). The clean 11-ID inventory with stable median periods is the indirect signal that the bitrate is right and the driver was healthy.

## Derived artifacts

ID inventory + period analysis: run `python scripts/inventory_ids.py logs/2026-06-17-key-on-cold-boot/`. Summary lives in [`docs/experiments/2026-06-17-key-on-cold-boot.md`](../../docs/experiments/2026-06-17-key-on-cold-boot.md) and was promoted to [`docs/findings/can/bitrate.md`](../../docs/findings/can/bitrate.md) and [`docs/findings/can/always-on-broadcast-ids.md`](../../docs/findings/can/always-on-broadcast-ids.md).
