---
area: can
status: provisional
established_by:
  - 2026-06-17-engine-idle-baseline-x3
  - 2026-06-23-engine-driven-rear-spin
  - 2026-07-22-first-moving-ride
references:
  - ktm-can-decoder
---

# `121` D0:D1 and D2:D3 — twin signed int16 channels

> **2026-07-22 rolling-load update — leading hypothesis is now signed engine torque (or a signed torque-derived correction).** The paddock-stand data made these channels look like a bounded engine-on wobble peaking around 3500 RPM at +7 LSB. Real riding shows a much bigger, cleaner shape that the paddock stand couldn't produce:
>
> - **Overrun (throttle 0 %, RPM > idle) → strongly negative**, magnitude grows with RPM: -16 at 3500 RPM, -18 at 4000 RPM, -20 at 4500 RPM, -23 at 5000 RPM. Engine being spun by the wheels through a closed throttle — negative net engine torque.
> - **Idle → near zero** (unchanged from the earlier finding: A μ ≈ +0.7, σ ≈ 1.4 in 1500-2000 RPM 0-8-throttle bin across 3699 rolling-ride frames).
> - **Drive → positive, monotonic with throttle at fixed RPM**. Example, 4500-5000 RPM bin: -20 at 0 % throttle → 0 near ~7 % → +59 at ~38 % throttle. Zero-crossing throttle grows with RPM (7 % at 4500, higher at 5500) — the "throttle needed to balance zero net torque" moves with RPM.
> - **A and B track within ~1 LSB across every rolling-ride bin.** Almost identical, unlike the r=0.6-0.96 disparity in the paddock corpus. Under real load they're either the same quantity broadcast twice or two views of the same computation.
> - **Peak observed magnitude ~ 75** at 5500-6000 RPM, ~ 47 % throttle. Svartpilen 401 spec peak torque ≈ 37 N·m — so if these are torque at 0.5 N·m/LSB the peak matches the physical spec. Provisional but suggestive.
>
> **Hypotheses re-ranked:**
> 1. **Signed engine torque / brake mean effective pressure** (was not on the original list). Fits every rolling-ride observation. Sign flip on drive/overrun is the strongest evidence; a bounded fuel-trim or ignition-advance signal doesn't naturally sign-flip on overrun.
> 2. Ignition advance corrections (originally #1). Still possible but doesn't naturally produce the sign-flip pattern under overrun.
> 3. Short-term + long-term fuel trim (originally #2). Downweight — fuel cutoff on decel would produce specific overrun behaviour but not the smooth signed continuum we see.
> 4. Closed-loop control feedback (originally #3). Not obviously torque-shaped.
>
> **The "not load-driven" claim below (paddock-stand Phase A rear-spin) is retracted.** Paddock-stand drivetrain drag is a tiny load compared to real riding (no wind, no acceleration inertia, no gradient); a "load ruled out" verdict on that data was inadequate. This finding's ninth section preserves the original claim for historical continuity — read with the retraction in mind. The rolling-ride analysis is in `scripts/first_moving_ride_load_scan.py`.
>
> **New promote-to-confirmed criterion:** if the two channels really are signed torque, a controlled coast-down capture (throttle closed, bike coasting from high RPM to idle) should produce a smooth monotonic curve from a strongly-negative value at high-RPM overrun through zero at idle. Also plausibly correlates with instantaneous fuel-injection duration if that ever surfaces on the bus.
>
> ---
>
> **Second independent corroboration (2026-07-22 shift-cut analysis).** During the ~ 60 ms quickshifter ignition cut ([[signal-quickshifter]] `121 D6 bit 0`), the ECU stops combustion. If `121_A` is torque, that instantaneous absence of combustion should produce a sharp drop in the channel — combustion was producing positive torque, remove combustion, only drivetrain drag / pumping losses remain (negative). Test on the 2026-07-22 corpus, partitioned by rider intensity at the shift moment (`scripts/first_moving_ride_torque_during_cut.py`):
>
> | Shift group | n | Pre-cut `121_A` μ | In-cut min `121_A` μ | Δ |
> |-------------|---:|-------------------:|---------------------:|---:|
> | **Aggressive** (rider ON throttle through cut, pre-cut A > +30) | 3 | +88 | -38 | **-126 LSB** |
> | Neutral (rider between, -10 < pre-cut < +30) | 5 | +8 | +9 | +1 LSB |
> | All 31 upshifts (rider intent varies) | 31 | -17 | -28 (min per shift) | -12 LSB |
>
> Individual aggressive shifts: pre +94 → cut -39 (moving-1 3→4, drop 133); pre +90 → cut -38 (moving-1 4→5, drop 128); pre +79 → cut -37 (moving-2 2→3, drop 116).
>
> **The correlation with rider intensity is the discriminator, not just the magnitude.** If `121_A` were RPM-derived, ignition-derived, or throttle-derived, the ~60 ms cut wouldn't produce a 130 LSB dip conditioned on the pre-cut throttle-on state — RPM barely moves in 60 ms, ignition is a pulse-timing signal not a bulk value, and the rider's throttle grip doesn't change *during* the cut. Only a signal that responds to instantaneous combustion (torque, MAP, or fuel-injection quantity) would show this pattern. Torque is the cleanest fit because it goes NEGATIVE during the cut (drag, no combustion) — MAP and injection quantity would go to zero but not below.
>
> Physical spot-check: at LSB ~ 0.25 N·m/LSB (the working hypothesis), the +90 → -38 swing is +22.5 N·m → -9.5 N·m = 32 N·m delta. Svartpilen 401 spec peak torque is 37 N·m. The magnitude of instantaneous drive torque interrupted by the cut lands right in the expected physical range.

# `121` D0:D1 and D2:D3 — twin signed int16 channels

`121` carries **two correlated signed 16-bit big-endian channels** at D0:D1 and D2:D3 — small wobbling values at engine-on idle, climbing to a mid-RPM peak under the engine-driven sweep, with a sharply different "bias" value when the engine is off. Encoding is confirmed (100% sign-byte agreement across ~37,000 engine-on frames in 4 sessions); physical quantity is not.

## Observation — encoding

For any signed int16 BE in two's complement, **D0 == 0xFF iff D1 ≥ 0x80** (the high byte is the sign extension of the low byte's high bit) when the value's magnitude fits in int8. The test holds at 100.0% across the engine-on windows of all four sessions analysed:

| session | engine-on frames | D0:D1 sign-agree | D2:D3 sign-agree |
|---|---:|---:|---:|
| 2026-06-17-engine-idle-run-1 | 7,997 | 100.0 % | 100.0 % |
| 2026-06-17-engine-idle-run-2 | 7,962 | 100.0 % | 100.0 % |
| 2026-06-17-engine-idle-run-3 | 7,998 | 100.0 % | 100.0 % |
| 2026-06-23-engine-driven-rear-spin | 11,155 | 100.0 % | 100.0 % |

Zero counterexamples across 35,112 engine-on frames. The byte-distribution scan ([`scripts/id121_byte_scan.py`](../../../scripts/id121_byte_scan.py)) had already flagged D0 and D2 as bimodal {0x00, 0xFF} — exactly the sign-extension signature.

The earlier non-monotonic byte means for D0..D3 ([`scripts/engine_load_scan.py`](../../../scripts/engine_load_scan.py)) were an artifact of taking byte-level statistics across the sign discontinuity: a sequence wobbling between -1, 0, +1, +2 reads as raw bytes 0xFF, 0x00, 0x01, 0x02 with byte-mean ~64, not ~0. Decoded as int16, the shape is clean.

## Observation — engine-on values

Per-setpoint signed int16 BE means from the rear-spin RPM sweep (`scripts/id121_int16_verify.py`):

| window | RPM | D0:D1 mean ± std | D0:D1 range | D2:D3 mean ± std | D2:D3 range |
|---|---:|---:|---|---:|---|
| idle-neutral (pre-sweep) | 1709 | -0.36 ± 0.54 | -2..+2 | -0.85 ± 1.00 | -3..+4 |
| idle 1st (Phase A) | 1704 | +0.24 ± 0.50 | -1..+2 | +0.12 ± 0.94 | -2..+3 |
| B1 — ~2000 RPM | 1975 | +1.83 ± 2.03 | -2..+13 | +1.78 ± 2.05 | -3..+11 |
| B2 — ~2500 RPM | 2131 | +3.72 ± 3.41 | -7..+15 | +3.56 ± 3.28 | -7..+14 |
| **B3 — ~3500 RPM** | **3017** | **+7.17 ± 2.67** | +0..+16 | **+7.36 ± 2.80** | -1..+16 |
| B4 — ~4500 RPM | 3944 | +4.26 ± 2.21 | +0..+14 | +4.21 ± 2.26 | -1..+14 |
| B5 — ~5500 RPM | 4966 | +3.93 ± 4.35 | -7..+19 | +3.89 ± 4.06 | -7..+18 |
| idle 1st (Phase C post-sweep) | 1706 | +1.62 ± 0.53 | +0..+3 | +1.60 ± 0.74 | -1..+3 |
| idle-neutral (return) | 1662 | +1.34 ± 0.67 | -2..+3 | +1.28 ± 0.85 | -2..+3 |

The shape:

- **At idle, both channels wobble around 0** with std ~0.5–1.0 LSB. Tight, mostly within ±2.
- **They climb roughly monotonically B1 → B3** as RPM/throttle rise, peaking at B3 (~3500 RPM, ~7.8 % throttle) at +7 LSB.
- **They drop back B3 → B5** even though RPM and throttle keep climbing. The mid-RPM peak is robust — present in both channels, in both means and ranges.
- **Variance grows with RPM** (std ~0.5 idle → ~4 at B5). High-RPM operating points carry more frame-to-frame jitter.

Cross-session, the engine-on idle wobble holds across all three baseline captures: D0:D1 idle mean +0.43..+1.15, std 0.6..1.1 — narrow, near zero, never sign-extended into the larger-magnitude regime engine-off uses.

## Observation — channel relationship

The two channels track the same shape but are not identical:

| window | Pearson r (D0:D1 vs D2:D3) | mean diff | equal-frame fraction |
|---|---:|---:|---:|
| idle (pre-sweep) | +0.713 | +0.496 | 40.0 % |
| idle 1st (Phase A) | +0.669 | +0.125 | 55.5 % |
| B1 | +0.823 | +0.048 | 37.2 % |
| B2 | +0.920 | +0.163 | 31.0 % |
| B3 | +0.936 | -0.190 | 53.5 % |
| B4 | +0.932 | +0.048 | 58.0 % |
| B5 | +0.963 | +0.045 | 58.2 % |
| idle 1st (Phase C) | +0.642 | +0.013 | 67.5 % |
| idle (return) | +0.749 | +0.054 | 69.3 % |

Correlation **rises with RPM** (idle ~0.7, B5 ~0.96). Equal-frame fractions are 31–69 % — so even when r is high the per-frame values differ by ±1 LSB the majority of the time. Means are within 0.2 LSB of each other across the whole RPM sweep. Read: **two related quantities computed from similar inputs**, not the same quantity broadcast twice.

## Observation — engine-off bias

Engine-off pre-start windows in all 4 sessions show the bytes holding a stable non-zero positive bias rather than the engine-on small wobble:

| session | engine-off D0:D1 mean ± std | D2:D3 mean ± std | r |
|---|---:|---:|---:|
| 2026-06-17-engine-idle-run-1 | +165.81 ± 6.16 | +462.41 ± 17.14 | +0.999 |
| 2026-06-17-engine-idle-run-2 | +168.78 ± 6.37 | +466.36 ± 17.58 | +1.000 |
| 2026-06-17-engine-idle-run-3 | +171.78 ± 6.20 | +468.40 ± 16.90 | +1.000 |
| 2026-06-23-engine-driven-rear-spin | +168.78 ± 6.33 | +465.37 ± 17.46 | +1.000 |

Two things:

1. **r between channels is essentially 1.0 in engine-off** — the two channels move in perfect lockstep when the engine isn't running. They are not in lockstep engine-on (r 0.6–0.96).
2. **D2:D3 / D0:D1 ratio ≈ 2.75** across all four sessions (462/166, 466/169, 468/172, 465/169). Suspiciously close to 11/4. Two scaled views of the same underlying engine-off quantity, or two raw values that happen to share a near-constant ratio in this operating regime.

The encoding is still int16 BE — positive values in the 100–500 range are perfectly valid int16 — but the values are dramatically different in engine-off vs engine-on. So either:

- Different ECU computation paths run in the two states (most plausible — many ECU corrections are zero/undefined when the engine isn't running, and the bytes get reused for diagnostic or sensor-raw values), or
- A single computation that produces small values when the engine is running and large positive values otherwise (e.g., a closed-loop integrator that has nothing to lock onto and parks at a default).

## Hypotheses (semantic, not encoding)

Encoding is settled; physical quantity is open. Candidates that fit *the engine-on shape* (small signed wobble, mid-RPM peak, two correlated channels):

1. **Ignition advance corrections.** Engine ignition maps often run more aggressive base advance at low and high RPM and more conservative advance at mid-RPM (the torque peak region, where knock margin is smallest). A real-time correction byte would dip more positive (more retard from base) around the torque-peak RPM. Two channels could be "instantaneous correction" + "rolling-average correction" or "applied" + "requested."
2. **Short-term + long-term fuel trim.** OBD-II diagnostic pattern of two correlated trim percentages. But standard fuel trims usually move with load not RPM, and ours peaks at mid-RPM at modest throttle — fits less cleanly than ignition advance.
3. **Closed-loop control feedback values** (idle-controller output integrator + derivative, or torque-controller targets). Would be near zero at idle (system in lock) and grow when the controller has to work harder.
4. **Knock retard counters.** Refuted by the data — knock retard fires on detected knock events, not as a steady-state value, and our data shows broad smooth distributions at every operating point.

The two-channels-correlated-but-not-identical pattern is the strongest evidence for "two related ECU corrections" rather than "one signal mirrored" or "one signal + its checksum."

## What this is NOT

- **Not a counter.** D0:D1 and D2:D3 take signed-int16 values in a small bounded range (-22..+36 across the whole rear-spin sweep), not the monotone-then-wrap pattern of `541` D4 ([[signal-engine-on-counter]]).
- **Not engine-state flags.** No bit on D0..D3 holds a stable {0,1} pattern across windows — the bytes wobble continuously.
- **Not the D7 cycle hash.** D7 is computed independently from D0..D6 per the universal algorithm ([[byte-d7-cycle-hash]]); D0:D1 / D2:D3 are payload, not checksum.
- **Not load-driven.** The rear-spin Phase A test (idle in 1st, clutch out, drivetrain spinning) showed both channels matching neutral-idle to within noise at matched RPM/throttle. Genuine drivetrain drag didn't move them. Same negative result that ruled MAP/load out for `540` D1 — but here documented as part of the encoding finding rather than a separate experiment.

## Promote-to-confirmed criteria

The encoding (twin int16 BE) is essentially confirmed; the **physical quantity** is what needs more work. Promotion path:

1. **Phase E of [[2026-07-12-neutral-rpm-sweep]]** — matched-RPM neutral setpoints will show whether the B3 peak survives without load. If the peak is RPM-keyed it reproduces in neutral; if throttle/load-keyed it shifts or disappears.
2. **Throttle-blip transient analysis** from Phase D of the same experiment — fast throttle transitions show whether the channels lead/lag throttle vs RPM, which discriminates between ignition-correction and fuel-trim-style hypotheses (ignition advance updates per ignition event, ~fast; fuel trims have integrator delay, ~slow).
3. **External documentation** — Bosch ME17 / motorcycle-ECU service tool data parameter lists would settle the semantic interpretation in one shot if a public source can be found.

## Evidence

- [`docs/experiments/2026-06-23-engine-driven-rear-spin.md`](../../experiments/2026-06-23-engine-driven-rear-spin.md) — engine-on RPM sweep that surfaced the non-monotonic shape and gave the cleanest setpoint stats.
- [`docs/experiments/2026-06-17-engine-idle-baseline-x3.md`](../../experiments/2026-06-17-engine-idle-baseline-x3.md) — three engine-on idle captures used for cross-session generalisation.
- [`scripts/engine_load_scan.py`](../../../scripts/engine_load_scan.py) — original per-setpoint byte-mean scan that flagged D0..D3 as RPM-correlated.
- [`scripts/id121_byte_scan.py`](../../../scripts/id121_byte_scan.py) — value-distribution scan that revealed D0/D2 as bimodal {0x00, 0xFF}.
- [`scripts/id121_int16_verify.py`](../../../scripts/id121_int16_verify.py) — sign-byte consistency check + int16 mean/std per window + channel correlation.
- [`scripts/id121_int16_crosssession.py`](../../../scripts/id121_int16_crosssession.py) — cross-session generalisation check.

See also: [[byte-d7-cycle-hash]] (different ID, separate algorithm — note D7 is excluded from the int16 channels here), [[signal-engine-on-counter]] (different ID `541` D4 — counter not int16), [[signal-warmup-index]] (the parallel re-attribution story for `540` D1, currently also under review), [[always-on-broadcast-ids]].
