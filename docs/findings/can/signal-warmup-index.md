---
area: can
status: provisional
established_by:
  - 2026-06-17-engine-idle-baseline-x3
  - 2026-06-21-cross-session-payload-diff
  - 2026-06-21-bit-transition-scan
references:
  - ktm-can-decoder
---

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
