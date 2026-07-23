# Session: 2026-07-22-first-moving-ride

**Firmware:** wifi-bridge @ 58a5d95
**Bitrate:** 500 kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination (bike-powered)
**Capture start (wall-clock, from filenames):** 2026-07-22T15:50:48 local (moving-1)
**Capture end (wall-clock, from filenames):** ~2026-07-22T16:09:10 local (moving-5)
**Ride length (5 runs, cumulative):** ~16.6 minutes of frames

## Captures

| File | Boot-relative start (s) | Duration (s) | Frames | Notes |
|------|------------------------:|-------------:|-------:|-------|
| moving-1.log | 63.5 | 360.8 | 136 543 | Started cold-ish. 2 GAP markers, ~39 621 frames dropped (phone sleep). |
| moving-2.log | 24.5 | 123.8 |  51 930 | Clean. Time base restarts — ESP was power-cycled or re-booted between moving-1 and moving-2. |
| moving-3.log | 173.1 | 177.0 |  74 233 | Clean. **OEM dash max reached 101 km/h — calibration endpoint for wheel-speed LSB.** |
| moving-4.log | 363.2 | 171.7 |  72 041 | Clean. |
| moving-5.log | 601.4 | 122.7 |  51 524 | Clean. **Cooling fan on at start, cycled off at 90 °C → back on at 95 °C → off at 90 °C.** |

Time-base note: moving-2..5 look continuous on a single ESP boot (boot-relative timestamps advance 24 s → 148 s → 173 s → 350 s → 363 s → 535 s → 601 s → 724 s). moving-1 is a separate boot (timestamps restart). No wifi-bridge normalization has been applied yet — every file still carries raw `(sec.us)` boot-relative prefixes; normalization to a common wall-clock is deferred until an analysis needs it.

## Bike state

- Ambient ~22 °C. First real moving session on this bike with our capture rig.
- moving-1 started from a cold-ish engine; engine warms through the ride. Coolant walk-up is visible in moving-1 and provides material for the [`541` D1 candidate coolant-derived byte](../../docs/findings/can/) probe.
- Engine ON throughout all five captures (rider was riding).
- All 11 always-on broadcast IDs present in every capture (moving-1 through moving-5).
- No dash warnings called out by the rider.

## Rider actions

Freeform ride, no scripted procedure. Rider was riding normally (throttle work, gear changes, braking, clutch). The 5 files are not one continuous timeline — they are 5 separate `wifi-bridge` capture sessions on the rider's phone, chunked to work around iOS backgrounding the WebSocket connection when the phone went to sleep. Moving-1 hit the sleep issue mid-ride (hence the two gaps); moving-2..5 were manually started/stopped by the rider to avoid recurrence.

## Rider-observed calibration points

Captured verbally by the rider immediately after the ride, not synchronized to any specific frame:

- **~60 km/h steady on the OEM dash** ⇒ our decoded rear wheel speed sat at **~66 km/h**, our decoded front wheel speed at **~45 km/h**. Directions are consistent across the ride (rear reads high, front reads low).
- **moving-3 peak on the OEM dash: 101 km/h.** Use as an endpoint calibration point vs decoded wheel-speed max in that file.
- **moving-5 fan hysteresis: fan on at start, off at 90 °C, on again at 95 °C, off again at 90 °C.** Coolant appears twice-cycled around the 90–95 °C band. Useful both for (a) sanity-checking the `540` D5:D6 coolant decode against a known physical event, and (b) hunting for a cooling-fan status bit correlated with the on/off transitions.

## Anomalies

- moving-1 gap markers: 2 markers, 39 621 dropped frames total, over a 361 s span (~22 % loss). Cause: phone WiFi backgrounded when the screen slept. Frames captured before and after the gap are still valid; timeline within the gap is missing.
- Boot-relative timestamps discontinuity between moving-1 and moving-2..5 — ESP was rebooted or power-cycled somewhere between the two.

## Related experiment

[`docs/experiments/2026-07-22-first-moving-ride.md`](../../docs/experiments/2026-07-22-first-moving-ride.md).
