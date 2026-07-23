---
area: can
status: provisional
established_by:
  - 2026-06-17-engine-idle-baseline-x3
  - 2026-06-21-cross-session-payload-diff
  - 2026-06-21-bit-transition-scan
contradicted_by:
  - 2026-06-23-engine-driven-rear-spin
  - 2026-07-22-first-moving-ride
references:
  - ktm-can-decoder
---

> **2026-07-22 cold-walkup cross-check + overrun anomaly.** `scripts/first_moving_ride_warmup_index_check.py` extracted D1 vs coolant from moving-1's fresh cold walk-up (26 → 87 °C over ~ 5 min while riding), filtered to strict-idle conditions (throttle < 8 raw AND RPM < 2200), and compared against the existing table below. **Match is exact within ±1 LSB at every temperature bin the moving-1 data covers**: 27-30 °C → 0x13-0x14 (existing: 0x14 at 28°C ✓), 33-42 °C → 0x11 (existing: 0x11 at 40°C ✓), 84-87 °C → 0x0E (existing: 0x0E at 85°C ✓). The idle-regime coolant→D1 lookup is corroborated independently.
>
> **Overrun anomaly (new).** At near-idle throttle (throttle < 8 raw) but higher RPM (2200-5000 range — the bike is coasting with throttle closed but wheels driving the engine), D1 does NOT stay at its idle-coolant lookup value. It spikes to 60-140 for individual frames. Aggregate across coolant bins 54-72 °C shows D1 means of 32-112 (vs. the strict-idle expectation of 15-16 at those temps). This is *engine-off* — no fuel injection — yet D1 is elevated. If D1 were a fuel-injection-quantity proxy it should be zero during overrun (ECU decel fuel-cut). It isn't. Reinforces the interpretation that D1 is some **broader engine-management-state index** (leading candidates: idle-air-bypass position anticipating re-engagement; a load estimate the ECU uses for fuelling-table indexing; or an air-mass-flow estimate). Not fuel injection. This also independently supports the [[fuel-consumption-derivation-from-torque]] finding's decision to use `121_A` × RPM rather than `540 D1` as the fuel-rate proxy.
>
> **2026-07-22 rolling-load update — the paddock ruling "engine-load ≠ driver" is retracted.** The [`scripts/first_moving_ride_load_scan.py`](../../../scripts/first_moving_ride_load_scan.py) sweep across the 2026-07-22 corpus shows real-riding D1 running dramatically higher than the paddock formula `D1 ≈ 14 + 0.8 × throttle%` predicts, at every off-idle (RPM, throttle) bin:
>
> | RPM bin | throttle bin | throttle % | D1 mean (rolling) | D1 predicted (paddock formula) | Δ |
> |--------:|-------------:|-----------:|------------------:|-------------------------------:|---:|
> | 1500-2000 | 0-8    |  0-3 %  | 14.8 | 14 | +0.8 (matches — idle regime) |
> | 4500-5000 | 48-56  | 19-22 % | 56.9 | 30 | +27 |
> | 4500-5000 | 88-96  | 35-38 % | 58.6 | 42 | +17 |
> | 5000-5500 | 96-104 | 38-41 % | 77.7 | 45 | +33 |
> | 5500-6000 | 112-120| 44-47 % | 107.2 | 50 | +57 |
>
> The paddock formula holds *at idle* and diverges more strongly as RPM/throttle climb. The Phase A "MAP ruled out" test used ~ 21 s of paddock-stand drivetrain drag at idle — a very small load — and got Δ = -0.10 (inside σ = 0.61). That measurement was correct on its own terms but the load range it tested was too narrow to rule anything out. On real ride load (wind resistance at highway speed, acceleration inertia, gradient loads) the discrepancy is 10-50 LSB, obvious.
>
> **The current best model — throttle-derived with a coolant-keyed idle offset — needs at minimum an additive load term** to explain the rolling-ride data. Under real load at fixed (RPM, throttle, coolant) the byte reads meaningfully higher than under paddock-stand load. Whether that extra term is best modelled as (a) a MAP-like intake-pressure signal, (b) a real engine-load or fuel-injection-quantity signal, or (c) an ignition-map correction index sensitive to real cylinder charge, needs a cleaner discriminator than this pass provides. The rolling-ride corpus mixes coolant walk-up (26 → 92 °C) with speed / gear variation, and coolant explains part but demonstrably not all of the within-bin σ.
>
> **The channel 121 D0-D3 rolling-load analysis pointed toward signed engine torque** ([[byte-121-twin-int16]] 2026-07-22 update). If confirmed, `540` D1 might be a related throttle-and-load-derived quantity — possibly the **absolute** magnitude that the signed torque channels split into signed drive/overrun.
>
> **Rewrite still deferred** — the 2026-07-22 data is enough to retract the paddock ruling but not enough to lock in the correct semantic. Phase E of [[2026-07-12-neutral-rpm-sweep]] still provides the cleaner RPM-vs-throttle discriminator; the missing piece is a controlled load capture (rolling ride with coolant held fixed at operating temperature, or short paired segments at same RPM/throttle in different gears). See Follow-ups below.
>
> Older 2026-06-23 review block preserved below for historical continuity.

> **2026-06-23 — interpretation under review.** Two pieces of new evidence from [[2026-06-23-engine-driven-rear-spin]] (analysed with [`scripts/engine_load_scan.py`](../../../scripts/engine_load_scan.py) and [`scripts/idle_load_compare.py`](../../../scripts/idle_load_compare.py)):
>
> 1. **Off-idle, D1 tracks throttle.** Across the 5 RPM setpoints D1 climbs from 17.5 (2000 RPM / 2 % throttle) to 35.1 (5000 RPM / 24 % throttle) at **constant operating-temp coolant**. A simple `D1 ≈ 14 + 0.8 × throttle%` model fits to within ~+1.7 LSB across all 5 points (small constant residual, suggests a minor RPM term on top). The dominant off-idle input is throttle, not coolant.
> 2. **~~Engine load alone does not move D1.~~ ⚠ Retracted 2026-07-22.** Phase A of the same capture spent ~21 s in 1st gear with the clutch fully out and the rear wheel spinning on the paddock stand — genuine drivetrain drag, ECU holding idle RPM against it. At matched RPM (1704 vs 1709) and matched throttle (0 % vs 0 %), D1 in-gear = 15.57 vs neutral 15.67, Δ = -0.10 (inside σ = 0.61). At the time this was read as "MAP / engine-load ruled out as the primary interpretation" — but the paddock's Δ = -0.10 was on a *very small* load excursion. Real riding load produces a Δ of +10 to +50 LSB against the same formula (see 2026-07-22 update above). Load is back on the table.
>
> **Revised reading:** D1 is most likely a **throttle-position-derived quantity** (or a fuelling-table index keyed off throttle) with a **coolant-keyed offset at idle**. The cold→warm walk (0x19 → 0x0E) the original finding documented is real and reflects coolant-keyed idle corrections; the warm-up framing is wrong because off-idle the byte stops tracking coolant and starts tracking throttle. If D1 is just a re-derivation of `120` D2 (the throttle byte we already have) plus a coolant offset, it's of limited interest for the dashboard but worth documenting cleanly.
>
> **Open discriminator:** Phase E of [[2026-07-12-neutral-rpm-sweep]] (matched-RPM neutral setpoints) decides throttle-derived vs RPM-derived. In neutral the same RPM is reached with much less throttle, so D1(neutral) at e.g. 4500 RPM should read **lower** than D1(in-gear) at 4500 RPM if throttle-derived; **equal** if RPM-derived.
>
> **Rewrite deferred** until Phase E. The text below is preserved as-is — it remains a correct description of D1 *at idle*, only the projection to "warm-up index" overall is wrong. If Phase E confirms the throttle-derived reading, this file gets renamed (probably `signal-throttle-fuel-index` or similar) and rewritten.

# Warm-up index — `540` D1

`540` D1 is an **engine-on-gated, coolant-temperature-driven** value that **decreases** monotonically as the engine warms and asymptotes to a stable warm floor. Most consistent with an ECU-internal warm-up correction (cold-start fuelling enrichment, or fast-idle / idle-air-bypass position) — not the dashboard coolant-gauge needle.

## Encoding

- Static `0x00` whenever the engine is not running (verified in all 6 engine-off sessions and in the pre-start window of all 3 idle sessions).
- After engine start, jumps to a temperature-dependent non-zero value.
- Decreases monotonically as coolant temp rises; floor ≈ `0x0E` (14) at operating temperature.

## Observed mapping (`540` D1 vs `coolant_temp` °C)

Pieced together from the three engine-idle baseline captures: Run 1 is a true overnight cold start (so its timeline walks the cold→warm range), Runs 2 and 3 are hot restarts a few minutes after the prior session.

| coolant °C (approx) | `540` D1 | source              |
|--------------------:|---------:|---------------------|
| 26 (engine just lit) | 0x19 (25), brief | Run 1, t≈30 s |
| 28                  | 0x14 (20) | Run 1, t≈40 s        |
| 31                  | 0x13 (19) | Run 1, t≈50 s        |
| 35 – 47             | 0x11 (17) | Run 1, t≈60-110 s    |
| 49 – 63             | 0x10 (16) | Run 1, t≈120-210 s   |
| 50 – 78             | 0x0F (15) | Run 2 steady         |
| 78 – 92             | 0x0E (14) | Run 3 steady         |

Step boundaries are roughly 5-10 °C wide in the mid range and wider at the cold extreme. No 1-°C-per-bit linear encoding fits.

## Hot-restart discriminator

The three sessions accidentally give a clean test of time-based vs temperature-based behaviour:

- **Run 1 (true cold, 26 °C):** D1 spends ~90 s walking 25 → 20 → 19 → 17 → 16 as coolant climbs from 26 → 50 °C.
- **Run 2 (hot restart, 51 °C):** D1 ramps 18 → 17 → 15 within ~10 s of engine-on, then holds.
- **Run 3 (hot restart, 75 °C):** D1 goes straight to 14 the moment the engine fires — **no transient**.

A time-based cold-start counter (one that resets on every key-cycle and decays regardless of temperature) would briefly read a high value on every restart. Run 3 jumping immediately to 14 rules that out. The value is a **stateless lookup of (current thermal state)** computed only while the engine is running.

The ~10 s Run-2 transient (18 → 17 → 15) is consistent with the ECU's fuelling/idle tables ramping in over the first few combustion cycles, not a time decay.

## Bit-level corroboration

[[2026-06-21-bit-transition-scan]] (which predates the rewrite, when this byte was still labelled "coolant_derived") shows the per-bit toggle profile of `540` D1 settling as temperature rises:

| bit | idle-1 (cold) | idle-2 (warm) | idle-3 (op-temp) |
|----:|--------------:|--------------:|-----------------:|
| 0   | 80            | 81            | 80               |
| 1   | 80            | 63            | **8**            |
| 2   | active        | active        | inactive         |
| 3   | active        | active        | inactive         |
| 4   | active        | active        | inactive         |

High bits flip during warm-up and stabilise at operating temperature; bit 0 keeps jittering. That settling pattern is what a quantised thermally-driven encoding produces — it is direction-agnostic, so the bit-scan evidence holds whether D1 rises or falls with temperature.

## Hypotheses

Both remain untested at the physical-quantity level. Both fit the shape:

1. **Cold-start / warm-up fuelling enrichment factor.** ECU looks up a richness multiplier from coolant temp; engine-only; falls as engine warms; stable non-zero floor at operating temperature because some baseline trim is always present.
2. **Fast-idle / idle-air-bypass valve position.** Cold engines need more bypass air to hold idle (cold idle ~1900 RPM on this bike, warm idle ~1700); the value would close down as warm-up progresses but never reach zero.

Both are coolant-driven lookups computed only while running, both have stable warm floors, both would read 0 when the ECU has no engine running to fuel/idle. The hot-restart behaviour matches either.

A residual ~1-unit offset between equal-coolant-temperature points in different sessions (Run 1 reads 16 at 50 °C; Run 2 starts at 50 °C and settles at 15) suggests one of: lookup-table granularity at boundaries, a small secondary thermal input (head temp, oil temp, intake air temp — all warmer in a hot restart), or a small hysteresis in the lookup.

## What was refuted

- **Dashboard coolant-gauge needle index.** Original hypothesis. Required `540` D1 to *increase* with temperature; it does the opposite. Also: the OEM gauge typically keeps reading briefly after key-off, but D1 latches to `0x00` engine-off, which fits an engine-management quantity rather than a display value.
- **Linear / scaled coolant temp in different units.** No simple `a + b·temp` mapping reproduces the table above; steps are non-uniform and inverted.
- **Time-based cold-start enrichment timer.** Hot restart at 75 °C reading 14 immediately, with no high-value transient, rules this out.

## Why `provisional`

- The thermal-derived character is well-established (engine-gating, monotonic inverse relationship, hot-restart insensitivity, bit-level settling).
- The **physical quantity** is not yet identified — could be enrichment factor, fast-idle target, idle-bypass duty, or another coolant-temp-keyed correction. The data shape alone can't separate these.
- The Run-1-vs-Run-2 ~1-unit offset is unexplained.

## Promote-to-confirmed criteria

- A continuous warm-up capture from a true overnight cold start through fan-cycle temperature, showing the value walking through the full table above without gaps, and stable across two such runs.
- Either a positive ID against ECU documentation (Bosch ME17 / KE-Jetronic class engine-management tables for warm-up enrichment) **or** a discriminating experiment that separates the candidate physical quantities (e.g., correlation with RPM idle offset during cold idle would point at idle-bypass; correlation with injector pulse-width — if a duty-related signal is found elsewhere on the bus — would point at enrichment).

## Evidence

- [`docs/experiments/2026-06-17-engine-idle-baseline-x3.md`](../../experiments/2026-06-17-engine-idle-baseline-x3.md) — the three idle captures that span the thermal range, plus the accidental hot-restart structure.
- [`docs/experiments/2026-06-21-cross-session-payload-diff.md`](../../experiments/2026-06-21-cross-session-payload-diff.md) — original cross-session candidate that surfaced `540` D1 (labelled "coolant_derived" at the time).
- [`docs/experiments/2026-06-21-bit-transition-scan.md`](../../experiments/2026-06-21-bit-transition-scan.md) — per-bit settling pattern (direction-agnostic, still corroborates the thermal-derived character).

See also: [[signal-coolant-temp]] (`540` D5,D6 — the raw thermal input this byte is computed from), [[always-on-broadcast-ids]].
