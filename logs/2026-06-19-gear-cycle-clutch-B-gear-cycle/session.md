# Session: 2026-06-19-gear-cycle-clutch-B-gear-cycle

**Firmware:** can-logger @ 61c64ae
**Bitrate:** 500 kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination [TODO: in / out]
**Capture start:** 2026-06-19T12:48:29+00:00
**Capture end:** 2026-06-19T12:49:53+00:00
**Total frames:** 29988
**Unique IDs:** 11
**Event marks:** 6  (see events.csv)

## Bike state

- Ignition: key on (position 1), kill switch in RUN.
- Engine: off throughout.
- Bike on paddock stand, **rear wheel free**.
- Gear at start: neutral (N). Clutch: pulled in at +25.7 s and not explicitly marked out after.
- Side stand: <TODO>
- Ambient temp: <TODO>

## Rider actions during session

Phase B of the gear-cycle-clutch experiment — engine-off gear cycle on a paddock stand. Attempted N → 1 → N → 2 → N → 2 sequence. Bike refused to engage 2nd: dash showed `"-"` instead of `2` on both attempts, suggesting the dogs weren't aligning without the input shaft turning (engine off).

Mark sequence:
- `c` @ +25.7 s — clutch in.
- `g` @ +34.2 s — down-shift to 1st (dash showed `1`).
- `n` @ +40.8 s — up to neutral (dash showed `N`).
- `g` @ +44.5 s — attempted up to 2nd (dash showed `"-"`).
- `g` @ +63.0 s — second attempt at 2nd (dash showed `"-"` again).

Gears reached: N and 1 only. 2–6 not achieved.

## Anomalies

The bike could not engage 2nd on the paddock stand with engine off — the dash flipped to `"-"` instead of `2`. This is a mechanical limitation (gearbox dogs don't align cleanly without the input shaft spinning), not a sensor anomaly. The `129` D0 hi-nibble gear value stayed at `0x0` (N) on the CAN bus during the "-" windows, confirming the gearbox sensor never registered 2nd. The "-" on the dash must be derived cluster-side from a separate shift-lever-position input not bridged to this CAN stub.
