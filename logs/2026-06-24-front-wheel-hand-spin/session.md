# Session: 2026-06-24-front-wheel-hand-spin

**Firmware:** can-logger @ 61c64ae
**Bitrate:** 500 kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination [TODO: in / out]
**Capture start:** 2026-06-24T15:08:47+00:00
**Capture end:** 2026-06-24T15:11:03+00:00
**Total frames:** 47573
**Unique IDs:** 11
**Event marks:** 0  (see events.csv)

## Bike state

- Ignition position 1 (key on), kill switch in RUN, neutral.
- **Engine off** throughout.
- Front of bike lifted with a hydraulic jack under the front engine guard; front wheel spinning freely, rear wheel resting on the ground.
- Rider spun the front wheel by hand. No marks — hand-driven, free-form (per [[experiment-design-hand-driven-marks]]).

## Rider actions during session

Free-form; the `12D` D0..D1 bytes self-delimit motion windows. Pushes done in order:

**Phase A — gentle pushes (4 reps):** dash peaks ≈ 4, 3, 3, 3 km/h. Settled to zero between each.

**Phase B — harder pushes (4 reps):** dash peaks ≈ 10, 7, 9, 11 km/h. Settled to zero between each.

**Phase C — sustained spin:** held the wheel at ~4–5 km/h shown on dash for a few seconds.

### Dash-lamp observations

- **Auto-headlight (low beam) did NOT come on at any point during the session.** Notably, Phase B peaks reached 11 km/h on the dash — well above the regime that triggered the headlight in the 2026-06-22 rear-only hand-spin session. This is a clean negative result: the auto-headlight is **not** front-wheel-keyed.
- **ABS warning lamp did NOT extinguish at any point.** Even at the Phase B peaks (well above the [[bike/dash-warning-lights]] ~6 km/h threshold) the lamp stayed lit. Working hypothesis: the ABS module needs the engine running (pump self-test) before it will clear the warning regardless of measured wheel speed.
- No dash display jumps or freezes observed.

## Anomalies

- None. Jack stable throughout; no wobble during pushes. Rear wheel stationary the whole session.
