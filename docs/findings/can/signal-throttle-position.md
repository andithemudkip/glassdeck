---
area: can
status: confirmed
established_by:
  - 2026-06-18-throttle-sweep-engine-off
references:
  - ktm-can-decoder
---

# Throttle position — `120` byte D2 (uint8, 0–254)

Throttle (rider grip) position on the 2020 Husqvarna Svartpilen 401 is broadcast in arbitration ID **`0x120`**, byte **D2**, as an unsigned 8-bit integer covering the grip travel.

**Which "throttle" this is.** The bike has two physically distinct throttle sensors (per repair manual wiring diagram pages 30.4 and 30.9):
- **B80 — throttle grip sensor** on the handlebar, 6-pin AP/6 connector, two redundant potentiometer channels (safety-critical for throttle-by-wire). Represents what the *rider* is asking for.
- **M60 — throttle valve position sensor** on the throttle body, measures the actual butterfly angle. Represents what the *ECU* is commanding via the ride-by-wire motor.

`120` D2 is **B80 (rider grip)**, not M60. Direct evidence: Phase A of [[2026-06-23-engine-driven-rear-spin]] held the bike in 1st gear with the clutch out and the rear wheel spinning at idle — drivetrain drag, ECU compensating by opening the butterfly to hold ~1700 RPM. `120` D2 read 0 throughout, matching the rider's grip (rider was not touching the throttle) rather than the butterfly (which was necessarily non-zero for the ECU to hold RPM). If `120` D2 were sourced from M60, it would have read the ECU's compensation. This distinction matters for the fuel-consumption model in [ADR 0017](../../decisions/0017-fuel-tracking-and-consumption-model.md) — grip is a rider-intent signal, not a load signal. A pure `RPM × grip` product will read fuel-idle-burn correctly (grip=0 → zero load term → idle-fuel term dominates) but will systematically under-model fuel during ECU load-compensation events (idle hold in gear, decel-cutoff transitions). Long-window auto-calibration against the sender absorbs most of this bias.

```
throttle = data[2]            # 0 = closed, 254 = wide-open
throttle_pct = throttle / 254.0
```

Update rate: 20 ms (the broadcast period of `120` — see [[always-on-broadcast-ids]]).

## Verified range

Across the engine-off slow-sweep capture of [`2026-06-19-throttle-sweep-engine-off`](../../../logs/2026-06-19-throttle-sweep-engine-off/):

| Phase | n (120 frames) | min | max | mean |
|---|---:|---:|---:|---:|
| slow sweep (open → hold → close → hold) | 1040 | 0 | 254 | 114.4 |
| step response (snap open / snap close) | 383 | 0 | 254 | 93.1 |
| reproducibility slow sweep | 1060 | 0 | 254 | 128.4 |

166 distinct values observed across the slow sweep — D2 sweeps cleanly through nearly every integer 0..254 as the rider drives the grip through its full travel.

**Max is 254, not 255.** Wide-open broadcasts `0xFE`, not `0xFF`. Whether this is a deliberate sentinel reservation at the top of the range (cf. some KTM dyno maps using `0xC8`/200 as full scale) or a calibration ceiling has not been characterised. Use 254 as full-scale for the dashboard's throttle gauge until contradicted.

Throttle-closed broadcasts exact `0x00`. No dead-band observed at the closed end — `0` is reached and held cleanly when the rider releases the grip.

The signal is meaningful **with the engine off** because the throttle on this bike is ride-by-wire — the ECU samples the grip-position sensor and broadcasts it from key-on regardless of combustion state.

## Cross-walk vs KTM

The ktm-can decoder ([reference](../../references/ktm-can-decoder.md)) places throttle at `120` D2 with a 0–255 range on the 2020 KTM 690 Enduro R. **Byte position and ID match exactly.** The Husqvarna observed maximum is 254, one count below KTM's stated 255 — close enough that this is probably the same encoding with a minor calibration difference, not a different scheme.

## Engine-off invariant cross-check

Across all 3 183 `120` frames in this capture, D0,D1 (RPM — see [[signal-rpm]]) read exact `0x00 0x00`. RPM is the engine-off zero, throttle byte sweeps cleanly — the throttle channel is fully decoupled from RPM in the broadcast layer.

## Refutations from the same capture

The throttle sweep also tested two adjacent hypotheses; both were rejected by this capture and should not propagate as assumptions:

- **`12A` D0 bit 1 ≠ throttle-open flag.** Zero transitions of this bit across 53 s spanning the full throttle range. Whatever this bit encodes, it is not "throttle off the stop". Re-derive: `python scripts/throttle_sweep.py`, see the "0→1 flips" / "1→0 flips" lines.
- **`120` D7 ≠ second throttle sensor (APP2).** D7 looked like a candidate from its range (32–223, 186 unique values), but a frame-by-frame Pearson correlation with D2 gives r = −0.012; D7's mean stays ~125–132 across every D2 bin. See [[byte-d7-cycle-hash]] for the leading interpretation.

## Open

- **Engine-on behaviour.** Encoding confirmed engine-off; engine-on confirmation pending in [`2026-06-18-engine-on-stationary-inputs`](../../experiments/2026-06-18-engine-on-stationary-inputs.md). Expectation: D2 behaves identically; the throttle channel is independent of engine state.
- **Map / RBW state bit (`12A` D1 bit 6).** Stuck at 0 across the engine-off sweep. Engine-off may suppress it — re-test engine-on per the experiment above.
- ~~**`541` D6 weak correlation.** r ≈ +0.26 vs D2 across this capture with range 20 counts.~~ **Resolved by [[2026-06-30-unknown-byte-corpus-sweep]]:** `541` D6 is the engine-OFF seconds counter ([[signal-engine-off-counter]]), not throttle-derived. Full-corpus r vs throttle peaked at +0.40 in the throttle-sweep session, dominated by D6's monotonic 1 Hz ramp coinciding with the rider's slow sweep. Closed.
- **Full-scale ceiling.** Verify whether 254 is a hard ceiling (sentinel) or a calibration knee by capturing a hard-to-the-stop snap; if the value briefly overshoots to 255 the ceiling is calibration, if it never does, 254 is likely a reserved sentinel.

## Evidence

- [`docs/experiments/2026-06-18-throttle-sweep-engine-off.md`](../../experiments/2026-06-18-throttle-sweep-engine-off.md) — hypothesis, procedure, result.
- [`logs/2026-06-19-throttle-sweep-engine-off/`](../../../logs/2026-06-19-throttle-sweep-engine-off/) — raw capture; `120_d2_timeseries.decoded.csv` written by the analysis script.
- [`scripts/throttle_sweep.py`](../../../scripts/throttle_sweep.py) — re-derives every number above from the capture.

See also: [[always-on-broadcast-ids]], [[signal-rpm]], [[byte-d7-cycle-hash]], [[ktm-can-decoder]].
