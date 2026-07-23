---
area: can
status: provisional
established_by:
  - 2026-07-22-first-moving-ride
references:
  - fuel-consumption-absent-from-broadcasts
  - byte-121-twin-int16
  - project-fuel-consumption-derivation
---

# Fuel-consumption estimate from `121 A` × RPM (torque-based)

Fuel consumption is not broadcast on this bike's CAN bus ([[fuel-consumption-absent-from-broadcasts]]). The **derivation model** the replacement dashboard uses is what we get to choose. The previous plan (from [[project-fuel-consumption-derivation]] memory) was `fuel_rate ∝ a·RPM + b·RPM·throttle`. The 2026-07-22 corpus supports a physically-grounded upgrade:

```
fuel_rate_mL_per_s ≈ k · RPM · max(0, 121_A)
```

where `121_A` is the signed int16 channel `121 D0:D1` (leading hypothesis: engine torque, see [[byte-121-twin-int16]]). The `max(0, ...)` clip encodes the well-known ECU behaviour that fuel is cut on decel — during overrun the engine is being spun by the wheels rather than driving them, so no fuel is being injected.

Working calibration constant against the 2026-07-22 ride: **k ≈ 2.83 × 10⁻⁶ mL / (RPM · LSB · s)**, anchored to the rider's 3.4 L/100km typical-riding baseline ([[project-fuel-consumption-baseline]]).

## Why this beats the previous plan

The `a·RPM + b·RPM·throttle` model has a structural flaw: it can't distinguish "throttle 0, RPM 5000 while coasting downhill" (zero fuel — decel cutoff) from "throttle 0, RPM 5000 while idling in neutral" (idle fuel). The rider's throttle-hand tells you nothing about whether the engine is doing work or being spun by inertia.

`121_A` tells you exactly this. During overrun in the 2026-07-22 corpus, `121_A` averaged **-19.5 LSB** (clearly negative — engine being driven by wheels). During drive, it averaged **+51.6 LSB** (clearly positive — engine driving wheels). The sign is the fuel-cut indicator; the magnitude is roughly the fuel demand.

## Ride-integrated corroboration

`scripts/first_moving_ride_fuel_model.py` merged the 5-file moving corpus into a single 100-ms-resampled timeline and computed:

| Metric | Value |
|--------|------:|
| Total engine-on time | 952 s (15.9 min) |
| Total distance | 9.58 km |
| Avg speed | 36.2 km/h |
| Expected fuel used (at 3.4 L/100km rider baseline) | 326 mL |
| Time in overrun (throttle < 3 %, RPM > 2000, `121_A` < -3) | 99.3 s (10.4 %) |
| Distance in overrun (fuel cut) | 1.50 km (15.6 %) |
| Time at idle stop | 312.8 s (32.9 %) |

Model integrals:

| Model | Integrated quantity | Value |
|-------|--------------------|-------|
| **Torque × RPM (this model)** | `∫(RPM × max(0, 121_A)) dt` | 1.15 × 10⁸ RPM·LSB·s |
| RPM × throttle (old plan) | `∫(RPM × throttle_frac) dt` | 6.92 × 10⁵ RPM·s |
| 540 D1 warm-up minus baseline × RPM | `∫((D1 - 14) × RPM) dt` | 1.41 × 10⁸ LSB·RPM·s |

Sanity check on the torque model against the physical picture — if `121_A` carries torque at 0.25 N·m/LSB (half the 0.5 N·m/LSB earlier guess, which would put peak observed torque at ~ 19 N·m, comfortably inside the Svartpilen 401's 37 N·m spec peak), then:

- Integrated positive mechanical power over the ride = k × ∫(RPM × A) × 0.25 × 2π/60 W·s
- Divide by (specific energy of gasoline × combustion efficiency) to get fuel volume
- With rider's 326 mL baseline, implied thermal efficiency = **27 %**  — right in the range for a small gasoline single at real-world duty cycle.

At LSB = 0.5 N·m/LSB, implied efficiency = 54 % (physically impossible for a spark-ignition engine, so likely wrong). At LSB = 0.125 N·m/LSB, implied efficiency = 13 % (too low). The middle number matches — so if `121_A` is torque-related, LSB ≈ 0.25 N·m is the working estimate. **Not confirmed** — needs a coast-down capture to nail down.

## Numerical spot-checks

At `k = 2.83 × 10⁻⁶`:

| Regime | Predicted fuel rate | Fuel efficiency |
|--------|--------------------|-----------------|
| Cruise 80 km/h, 5000 RPM, `121_A` ≈ +40 | 0.57 mL/s (2.0 L/h) | 2.5 L/100km |
| Spirited 100 km/h, 6000 RPM, `121_A` ≈ +65 | 1.10 mL/s (4.0 L/h) | 4.0 L/100km |
| Overrun (any RPM, any speed, `121_A` < 0) | 0 mL/s | — |
| Idle (1700 RPM, `121_A` ≈ 0) | 0 mL/s (**wrong — see below**) |

The last row is a **model limitation**: at idle, `121_A ≈ 0` (near-zero net torque; engine is just holding itself), so `k · RPM · A ≈ 0`. But the engine is burning fuel at idle (~ 0.3-0.5 L/hour on a bike this size). The current model under-predicts idle consumption.

**Fix** — add a small idle-fuel constant `f_idle`:

```
fuel_rate_mL_per_s = f_idle_mL_per_s + k · RPM · max(0, 121_A)
```

Rider's OEM-dash cruise numbers of 3.3-3.5 L/100km are for typical riding that includes idle stops. Untangling `f_idle` from `k` needs one of:

- A dedicated idle-only capture with a rider-noted "how long did I idle" clock and a tank-fill delta (impractical).
- A model fit against 2+ rides with widely differing idle-fractions — the intercept isolates `f_idle`.

Working estimate for `f_idle`: use published Svartpilen 401 idle consumption if available; failing that, 0.3 L/hour ≈ 0.083 mL/s.

## Model 3 (540 D1) doesn't work as a fuel proxy

The [[signal-warmup-index]] byte's rolling-load response looked promising for a fuel-injection-quantity signal, but the integrated-ride model produces implausibly low fuel numbers at moderate load (predicts ~0.7 L/hour at 5000 RPM cruise where reality is ~2 L/hour). D1's nonlinear/saturating relationship with load means it doesn't scale like fuel injection does. Keep D1 as an "engine state" indicator, not as a fuel proxy.

## What this means for the firmware / ADR

Update the fuel-consumption derivation model in [[project-fuel-consumption-derivation]] memory from `a·RPM + b·RPM·throttle` to:

```
fuel_rate_mL_per_s = f_idle_mL_per_s + k · RPM · max(0, decode_121_A(frame))

k        ≈ 2.83e-6  mL/(RPM · LSB · s)     [ride-anchored 2026-07-22]
f_idle   ≈ 0.083    mL/s (0.3 L/hour)        [nominal; refine per tank-fill]
```

Both constants tank-fill-calibrated in normal operation. Per [[project-fuel-consumption-derivation]], the calibration approach was already "constants refined against tank-fill deltas over time" — this just changes the model shape from two-term (idle-fuel + load-fuel-from-throttle) to two-term (idle-fuel + load-fuel-from-torque). Structurally similar, physically better.

Decision on adopting this is not made — write it as a proposed ADR revision when firmware Phase 3 lands.

## Open

- **Verify signed-torque interpretation** with a coast-down capture (throttle closed, RPM drops from say 5000 to idle across ~ 10 s in a fixed gear). Expected: `121_A` walks smoothly from strongly-negative back to ~ zero as engine reaches idle; no discontinuities. This is what [[byte-121-twin-int16]]'s Open list already calls out.
- **Nail the LSB of `121_A`**. Currently no direct measurement; the "0.25 N·m/LSB gives 27 % thermal eff" argument above is suggestive but circular (assumes rider baseline is exactly 3.4 L/100km on this ride). A GPS-tracked ride with a tank-fill delta anchor would isolate the LSB.
- **`f_idle` calibration**. Needs either a manufacturer-published number or a stopped-engine-running experiment with fuel-flow measurement. For now, 0.3 L/hour is a reasonable placeholder.
- **Does the model handle transient WOT correctly?** During hard acceleration, `121_A` can spike briefly; the model may over-predict on those spikes if the actual injection-quantity limit trails torque demand. Only observable via tank-fill delta over rides with varying aggression.

## Evidence

- [[2026-07-22-first-moving-ride]] moving-1..5 — 9.6 km ride with mixed regimes; `121_A` sign correlates with drive/overrun cleanly.
- [`scripts/first_moving_ride_fuel_model.py`](../../../scripts/first_moving_ride_fuel_model.py) — ride-integrated calibration.
- [`scripts/first_moving_ride_load_scan.py`](../../../scripts/first_moving_ride_load_scan.py) — earlier analysis that first surfaced `121_A` as signed-torque-shaped.

See also: [[byte-121-twin-int16]] (encoding + signed-torque hypothesis), [[fuel-consumption-absent-from-broadcasts]] (why we derive rather than read), [[signal-warmup-index]] (parallel load-responsive byte that turned out not to be a good fuel proxy), [[signal-rpm]], [[project-fuel-consumption-derivation]] (memory — model plan).
