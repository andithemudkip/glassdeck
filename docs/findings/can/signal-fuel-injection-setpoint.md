---
area: can
status: provisional
established_by:
  - 2026-06-17-engine-idle-baseline-x3
  - 2026-06-21-cross-session-payload-diff
  - 2026-06-21-bit-transition-scan
  - 2026-07-22-first-moving-ride
references:
  - ktm-can-decoder
---

# Fuel-injection setpoint — `540` D1

`540` D1 is an **ECU-internal fuel-adjacent scalar, best read as the base fuel-injection setpoint**. Broadcast at the 20 ms cadence of `540` but recomputed by the ECU at ~1 Hz — the value on the bus latches for ~1 second between recomputes. Under normal running the setpoint is applied to injection; under decel-fuel-cut the injector is zeroed while the ECU continues to compute and broadcast the setpoint on its own cadence.

```
setpoint = data[1]    # 0 engine-off; nonzero engine-on
```

## Shape at a glance

- **Engine off:** `0x00`. Latches to zero within one frame of key-off.
- **Post-start (both cold and hot):** identical 3-stage pattern in discrete ~1 s steps. Cold-start 25.8 °C: `0 → 6 → 29 → 26 → 25`. Hot-start 75.8 °C: `0 → 8 → 16 → 14 → 13-15`. Stage 2 overshoots the settled value — classic cold-start enrichment shape.
- **Warm idle floor:** ~14 at coolant ≥ 84 °C. σ = 1.2 across n = 1688 hot-idle frames.
- **Under drive:** OLS `setpoint ≈ 5.92 + 0.4055·grip + 0.00921·RPM − 0.1375·coolant` fits with r² = 0.73 over the moving corpus. Nothing else on the bus (torque, gear, speed) adds information once (grip, RPM, coolant) are fixed.
- **Gear-invariant.** At fixed (grip, RPM), setpoint matches across gears despite very different actual load at the wheel — rules out any measured-load quantity.
- **Overrun:** setpoint stays elevated relative to actual injection (which is zero under decel-fuel-cut) and decays stepwise toward the coolant-keyed idle floor over 1–2 s. Elevation scales with `121_A` magnitude (engine-braking severity).

## Encoding scale

Ride-integrated calibration: mean(setpoint) × engine-on-seconds ≈ rider's fuel used implies **1 LSB·s ≈ 8.18 μL** of fuel. Under that scaling:

| Regime | typical D1 | predicted rate | plausibility |
|--------|-----------:|---------------:|--------------|
| Warm idle | 14 | 0.41 L/hr | matches typical 390 cc idle |
| 5000 RPM cruise | 55 | 1.6 L/hr | close to rider's ~2 L/hr estimate |
| WOT sustained | 150 | 4.4 L/hr | plausible for the platform |

Consistent enough that this signal can serve as an **orthogonal cross-check** for the `RPM × 121_A` torque-based fuel model in [[fuel-consumption-derivation-from-torque]]. It smooths over transients (the ~1 s ECU recompute cadence loses spikes), but its nonzero idle floor removes the need for a separate `f_idle` term.

## Cold-start transient (Run 1 vs Run 3)

Both true-cold and hot restarts show the same 3-stage pattern updated on a ~1 s cadence:

```
Run 1 — true cold, 25.8 °C:
  t <  0.0s:  D1 = 0                  engine off
  +0.05..+0.95:  D1 =  6              stage 1
  +1.04..+1.94:  D1 = 29              stage 2 — cold-start enrichment peak
  +2.05..+2.94:  D1 = 26              tapering
  +3.05+:     D1 = 25                 settled to coolant-keyed floor

Run 3 — hot restart, 75.8 °C:
  t <  0.0s:  D1 = 0
  +0.18..+1.08:  D1 =  8              stage 1
  +1.17..+2.07:  D1 = 16              stage 2 — small enrichment even hot
  +2.17+:     D1 = 14                 settled floor
```

Two decisive features:

1. **Discrete ~1 s steps, not a smooth ramp.** Rules out any running-average / integrator interpretation. The "~1 s time constant" observed in cross-correlation with grip on the moving corpus was actually the ECU's recompute cadence, not filter smoothing.
2. **Stage 2 overshoots the settled value.** Peak-then-decay is a classic cold-start fuel enrichment profile. Ignition timing wouldn't overshoot; measured air-mass wouldn't; butterfly position wouldn't. Fuel injection setpoint does.

## Idle-band coolant lookup

Rebuilt from the 2026-07-22 moving corpus at strict idle (grip < 5, 800 < RPM < 2200), n = 7 602 frames:

| coolant °C | setpoint mode | n |
|-----------:|--------------:|---:|
| 24-27 | 20 | 36 |
| 27-30 | 19 | 162 |
| 30-42 | 17 | 728 |
| 42-51 | 17 | 472 |
| 51-57 | 16-17 | 91 |
| 78-84 | 13-15 | 438 |
| 84-93 | 14 | 4 542 |
| 93-96 | 13 | 685 |

Matches the earlier bike-stationary idle table from [[2026-06-17-engine-idle-baseline-x3]] Run 1 within ±1 LSB across every bin. The coolant response is preserved from what the finding was originally attributed to (fast-idle correction) — the reason the reading held up cleanly at idle even after everything else was overturned.

## Cross-session bit-level corroboration

[[2026-06-21-bit-transition-scan]] (originally labelled this byte `coolant_derived`) shows the per-bit toggle profile settling as temperature rises:

| bit | idle-1 (cold) | idle-2 (warm) | idle-3 (op-temp) |
|----:|--------------:|--------------:|-----------------:|
| 0   | 80            | 81            | 80               |
| 1   | 80            | 63            | **8**            |
| 2   | active        | active        | inactive         |
| 3   | active        | active        | inactive         |
| 4   | active        | active        | inactive         |

Direction-agnostic — corroborates the byte carries a thermally-varying quantity.

## What was ruled out

- **Dashboard coolant-gauge needle index.** Would need to *rise* with temperature; setpoint falls.
- **Time-based cold-start enrichment counter.** A time counter would reset on every key-cycle and produce a transient on hot restart independent of coolant. Run 3 at 75 °C settles to 14 within 3 s with no anomalous excursion — no time-only counter fits.
- **Any measured-load quantity** (MAP, MAF, air-mass, cylinder charge, calculated engine torque). Gear-invariance at fixed (grip, RPM) kills all of these — real load varies wildly across gears at fixed engine state, setpoint doesn't.
- **Ride-by-wire butterfly command angle.** Would respond within tens of ms to grip changes; setpoint latches for ~1 s. Also would sit near zero during overrun, not elevated.
- **Ignition-timing map output.** Fits the (grip, RPM, coolant) dependency but the post-start peak-then-decay shape does not match spark advance behaviour, which typically walks monotonically toward warm-idle setpoint after start. Also, values > 150 during overrun are outside typical advance ranges.

## Why `provisional`

Setpoint interpretation fits every observation. What remains open is the **exact scaling** — the 8.18 μL·LSB⁻¹·s⁻¹ conversion is anchored to one ride's rider-reported baseline and could be off by 20-30 %. Nailing it down needs a tank-fill delta over a ride with logged D1 integration.

Confirmation-strength discriminators still available:

- **Prolonged closed-throttle coast-down (>5 s)** — see [[2026-07-23-coast-down]]. Setpoint should decay fully to the coolant floor rather than latch at an intermediate step.
- **Direct comparison with an OBD-II PID scan** while running. Match by shape to a known fuel-rate or injection-quantity PID would pin the semantic and the units simultaneously.

## Evidence

- [`docs/experiments/2026-06-17-engine-idle-baseline-x3.md`](../../experiments/2026-06-17-engine-idle-baseline-x3.md) — three idle captures spanning the thermal range and the cold-start 3-stage transient.
- [`docs/experiments/2026-06-21-cross-session-payload-diff.md`](../../experiments/2026-06-21-cross-session-payload-diff.md) — original cross-session candidate surface (labelled `coolant_derived`).
- [`docs/experiments/2026-06-21-bit-transition-scan.md`](../../experiments/2026-06-21-bit-transition-scan.md) — per-bit settling pattern.
- [`docs/experiments/2026-06-23-engine-driven-rear-spin.md`](../../experiments/2026-06-23-engine-driven-rear-spin.md) — first evidence that the byte tracks throttle off-idle.
- [`docs/experiments/2026-07-22-first-moving-ride.md`](../../experiments/2026-07-22-first-moving-ride.md) sub-analyses 7, 16, 17 — rolling-load discrimination, moving-corpus cold-walkup cross-check, and the full 7-discriminator scan that pinned (grip, RPM, coolant) as the sole predictors and demonstrated gear-invariance.
- [`scripts/cold_start_d1_transient.py`](../../../scripts/cold_start_d1_transient.py) — post-start 3-stage transient extraction.
- [`scripts/first_moving_ride_d1_full_scan.py`](../../../scripts/first_moving_ride_d1_full_scan.py) — 7-discriminator scan.
- [`scripts/first_moving_ride_d1_step_response.py`](../../../scripts/first_moving_ride_d1_step_response.py) — step-response and idle-lookup cross-check.

## Naming history

Originally surfaced as `coolant_derived` ([[2026-06-21-bit-transition-scan]]), then renamed `warmup_index` on the reading that the byte was a warm-up enrichment factor decreasing with temperature. That name was retracted after the 2026-06-23 rear-spin capture showed off-idle throttle response, and the 2026-07-22 rolling corpus showed load response and gear-invariance. Renamed to `fuel_injection_setpoint` on 2026-07-23 after the cold-start 3-stage transient in Runs 1 & 3 decided integrator-vs-lookup and revealed the enrichment overshoot.

See also: [[signal-coolant-temp]] (`540` D5,D6 — the coolant reading the setpoint's idle floor is keyed on), [[fuel-consumption-derivation-from-torque]] (primary fuel model; this signal is the cross-check), [[signal-engine-torque]] (signed engine torque — the parallel load-responsive quantity), [[always-on-broadcast-ids]].
