# Session: 2026-06-23-engine-driven-rear-spin

**Firmware:** can-logger @ 61c64ae
**Bitrate:** 500 kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination [TODO: in / out]
**Capture start:** 2026-06-23T18:49:48+00:00
**Capture end:** 2026-06-23T18:54:50+00:00
**Total frames:** 118416
**Unique IDs:** 11  (same set as [[always-on-broadcast-ids]] — no new fault-state traffic)
**Event marks:** 12  (see events.csv)

## Bike state

2020 Husqvarna Svartpilen 401, rear paddock stand, front wheel parked straight. Engine ON from t+45 s (after `idle settled (neutral)` mark). Ignition ON throughout. Kill switch RUN. Side stand UP. Gear: NEUTRAL until Phase A engagement to 1st gear, returned to NEUTRAL at session end.

Nothing unusual about the ambient environment.

## Rider actions during session

Driven by `procedure.yaml.snapshot` — see events.csv for mark timestamps. Sequence:

1. Key on, dash boot.
2. Engine start, idle settle in neutral (30 s).
3. **Phase A:** clutch in, shift to 1st, clutch slowly out — rear wheel turning at idle through 1st gear (~15 s steady-state read).
4. **Phase B:** RPM setpoint sweep — 2000, 2500, 3500, 4500, 5500 RPM held ~12 s each, with idle-in-gear rests between.
5. **Phase C:** re-baseline idle-in-gear (post-sweep drift check).
6. Clutch in, neutral, idle settle, kill switch, key off, tail silence.

RPM held within ~140 RPM of target on most setpoints. B2 (~2500 target) was held lower at ~2130 — irrelevant since analysis reads RPM from CAN frame-by-frame.

None. The ABS warning lamp stayed on throughout the session, but this is the **normal key-on state, not a fault** — per [[dash-warning-lights]], ABS extinguishes once speed exceeds ~6 km/h, and that threshold reads the **front wheel / OEM speedo** (which stayed at 0 throughout this rear-only spin). The lamp had no opportunity to extinguish. Independently corroborates the speedo-reads-front model from [[signal-wheel-speed-rear]] § "Why the OEM speedometer reads 0 during a rear-only spin".

No other dash glyph or warning lamp anomalies. Coolant temp uneventful.
