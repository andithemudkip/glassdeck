---
area: can
status: provisional
established_by:
  - 2026-06-23-engine-driven-rear-spin
  - 2026-06-17-engine-idle-baseline-x3
  - 2026-06-24-front-wheel-hand-spin
  - 2026-06-24-front-wheel-decay-mark
---

# `12D` D1 bit 0 — rear-wheel-speed threshold flag (27 km/h), low nibble of the front-wheel-speed slot

`12D` D1's low nibble carries fields independent of the front wheel speed (which uses bits 15:4 of the D0:D1 BE u16, see [[signal-wheel-speed-front]]). Bit 0 is the only one observed to take both values; bits 1-3 are always 0.

| Bit | Behaviour | Status |
|----:|-----------|--------|
| D1 b0 | Set whenever rear wheel speed ≥ ~27 km/h (engine on); clear below | speed-threshold flag, **provisional** |
| D1 b1-3 | Always 0 across every observed frame | reserved / unused |

The flag tracks rear-wheel speed (`12D` D5:D6 BE / 16 per [[signal-wheel-speed-rear]]) with a **single mixed transition bin**:

| Rear km/h bin | bit=1 / total `12D` frames | % bit=1 |
|---------------|---------------------------:|--------:|
| 0-26 km/h (all bins) | 0 / ~26 700 | **0.000%** |
| 26-27 | 0 / 56 | 0.000% |
| 27-28 | 44 / 52 | 84.6% (transition) |
| 28-29 | 217 / 217 | **100.0%** |
| 29-30 | 400 / 400 | **100.0%** |
| 30-33 (all bins) | 331 / 331 | **100.0%** |

The same data binned by RPM also looked clean at first pass, but on closer inspection rear km/h is the cleaner predictor:

| Joint check across 28 820 `12D` frames | Result |
|---|---|
| Frames with rear_kmh < 27 AND bit = 1 | **0** |
| Frames with RPM < 4500 AND bit = 1 | 7 (RPM 4291..4489, **rear km/h 27.31..28.31** in every case) |
| Frames with rear_kmh ≥ 27 AND bit = 0 | (only the 8 transition frames in the 27-28 km/h bin) |
| Frames with RPM ≥ 4500 AND bit = 0 | 31 |

The 7 "RPM-below-4500 yet bit-on" frames are exactly the moments when RPM dipped briefly (engine transient) while wheel inertia kept rear speed above 27 km/h. They make sense as a rear-speed-keyed flag with a momentary RPM dip; they make no sense as an RPM-keyed flag. Combined with rear km/h being a perfect predictor (0 false positives in 1 002 bit=1 frames), the within-capture data **favours speed-keyed**. The flag was previously documented as "RPM-threshold (~4500 RPM)"; that's the projection of a 27 km/h threshold through the 1st-gear ratio used during the sweep.

Semantic meaning is still open. 27 km/h doesn't match any obvious dashboard cue on this bike. Plausible candidates: a body-controller / ABS-module high-speed regime marker, a transmission-cooling or fuel-map switchpoint, or a sound-control / emissions trigger. None is verifiable from CAN alone.

## Evidence base

| Capture | Engine | bit=1 frames | RPM range |
|---------|:------:|-------------:|-----------|
| [[2026-06-17-engine-idle-baseline-x3]] (3 captures) | on | 0 / 64 745 | idle ~1700 |
| [[2026-06-22-wheel-spin-paddock-stand]] | off | 0 / 18 556 | (engine off) |
| [[2026-06-24-front-wheel-hand-spin]] | off | 0 / 47 573 | (engine off) |
| [[2026-06-24-front-wheel-decay-mark]] | off | 0 / ~56 000 | (engine off) |
| [[2026-06-23-engine-driven-rear-spin]] | on | 1 002 / 28 820 (~3.5%) | idle → 5500 RPM sweep |

The ~3.5 % overall duty in the rear-spin capture is *not* a heartbeat — bit=1 frames are concentrated in 5 runs (lengths 1, 18, 54, 58, 871 frames; 87 % of bit=1 frames inside the single 871-frame run, corresponding to the B5 5500 RPM hold = ~30 km/h rear). 936 of the 1 002 bit=1 frames fall in a single 10-s window (t+210-220 s = B5 setpoint). At B4 (~4500 RPM held within ±140 RPM = rear km/h hovering around 27 km/h) the bit oscillates as rear speed crosses the threshold — short on/off cycles with inter-run intervals 0.19, 0.20, 0.61, 0.73 s, consistent with speed transients across the threshold rather than a periodic broadcast.

## Cross-checks

- **Throttle:** bit=1 occurs almost entirely in the throttle ≥ 20 (raw) bin (880/948 bit=1 frames). In 1st gear at sustained 4500+ RPM the throttle is necessarily high to hold the setpoint, so this is a derived correlation, not an independent cause.
- **541 D4 (engine-on seconds counter, [[signal-engine-on-counter]]):** the 5 run-starts coincide with 3 distinct counter values, one repeated — no 1-per-tick pattern, so the flag is not gated by the seconds counter.
- **Front wheel speed (the other field in the same byte slot):** during the rear-spin capture the front wheel was stationary, so the high-12-bit speed field stayed at 0 throughout. The two fields don't co-occur in this capture but there's no encoding reason they can't — the decoder must always mask `D1 & 0xF0` for wheel speed and read `D1 & 0x01` separately for this flag.

Analysis: [`scripts/id12d_d1_bit0_duty.py`](../../../scripts/id12d_d1_bit0_duty.py).

## Open

- **Speed-keyed confirmation in neutral.** The within-capture data favours rear-speed-keyed (rear km/h is a perfect predictor, RPM isn't) but the rear-spin capture is 1st-gear-only, so RPM and rear km/h are tightly coupled. Phase E of [[2026-06-18-engine-on-stationary-inputs]] (RPM setpoints in neutral with vehicle speed = 0) is the clean discriminator — if the bit fires at 5500 RPM in neutral, it's RPM-keyed; if it doesn't, the 27 km/h speed threshold is confirmed.
- **Engine-on precondition vs raw speed threshold.** All bit=1 frames are engine-on; no engine-off capture has crossed 27 km/h rear speed. Whether the bit fires at engine-off rear spin above 27 km/h (e.g. a future engine-off paddock-stand session that hits higher speeds) is open — a "rear km/h ≥ 27 km/h regardless of engine" vs "rear km/h ≥ 27 km/h AND engine on" distinction.
- **Exact threshold and hysteresis.** Best current estimate is "between 26 and 28 km/h" — the 27-28 km/h bin shows 84.6 % bit=1 (8 zero frames inside it) and every bin above is 100 %. A slow rear-spin ramp through 26-29 km/h would pin the threshold to better than 0.1 km/h and reveal whether ON and OFF thresholds differ (hysteresis band).
- **Semantic meaning.** 27 km/h doesn't match any obvious dashboard cue. Plausible candidates: ABS-module high-speed regime marker, body-controller motion-mode boundary, transmission/lubrication switchpoint, sound-control trigger. Useful comparison: the auto-headlight rear-keyed threshold is much lower (~6 km/h, [[bike/dash-warning-lights]]), so this isn't the same body-controller line.
- **Whether D1 bits 1-3 are truly reserved or just unused at current operating points.** Holding higher rear speeds (above ~33 km/h, requires higher RPM or higher gear) might exercise them — none of the existing captures crosses that band.

## Notes

Surfaced by a `(raw_u16 & 0x000F) != 0` scan against the engine-on session, while verifying the front-wheel 12-bit-in-16-bit encoding for [[signal-wheel-speed-front]]. The scan was added explicitly to test that the "12-bit packing" claim was universal, not session-specific — it isn't. The wheel-speed field still uses bits 15:4 cleanly; the low nibble carries this separate signal.

See also: [[signal-wheel-speed-front]], [[byte-encoding-12-in-16]], [[signal-engine-on-counter]], [[byte-121-twin-int16]] (different engine-correlated signal, peak at ~3500 RPM rather than a threshold flag — different shape, different source likely).
