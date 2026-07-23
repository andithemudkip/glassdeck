---
area: can
status: provisional
established_by:
  - 2026-07-22-first-moving-ride
---

# `541` D3 — 3-state monotonic counter, ~ 5 min per state, resets on key-cycle

`541` D3 takes exactly three observed values (0, 1, 2) across the 2026-07-22 moving corpus, walking monotonically 0 → 1 → 2 at roughly 5-minute intervals after engine start, and resetting to 0 on every fresh key-cycle. Semantic meaning open — this is a "confirmed active byte, semantics untested" finding, one of several signals that fell out of the first real ride.

```python
d3_value = data[3]           # observed: {0, 1, 2}; higher values plausible on longer rides
```

`541` D3 was previously classified as an `?` byte in the 2026-06-30 corpus sweep (moved in some sessions, no known-signal correlation passed |r| ≥ 0.9). The 2026-07-22 corpus is the first to observe both transitions cleanly and correlate them to time-since-engine-start.

## Observation

Across the 5 captures — moving-1 is a separate ESP boot (= fresh key-on cycle), moving-2..5 share a second ESP boot:

| Capture | D3 at start | D3 transition (t+s in file) | D3 at end |
|---------|:-----------:|-----------------------------|:---------:|
| moving-1 | 0 | 0 → 1 at t+236.7 s (~ 5.0 min from ESP boot) | 1 |
| moving-2 | 0 (fresh boot, resets) | — | 0 |
| moving-3 | 0 | 0 → 1 at t+112.5 s (~ 4.4 min after moving-2 engine start) | 1 |
| moving-4 | 1 | — | 1 |
| moving-5 | 2 | — | 2 |

Between moving-4 (D3=1 throughout, boot-relative 363-535 s) and moving-5 (D3=2 from start, boot-relative 601 s), there's a gap of ~ 66 s where the transition 1 → 2 must have happened. Rough timeline: transition 1 → 2 sometime between engine-start + 8.8 min and engine-start + 10.0 min. Consistent with the same ~ 5 min-per-state cadence: 0 for 0-5 min, 1 for 5-10 min, 2 for 10+ min.

## Context at each transition

`scripts/first_moving_ride_qs_bit_probe.py` printed the concurrent RPM / coolant / speed state at each transition moment:

| Transition | RPM | coolant | speed | interpretation |
|------------|----:|--------:|------:|----------------|
| moving-1 0 → 1 | 6089 | 80.1 °C | 90.7 km/h | mid-acceleration, hot engine |
| moving-3 0 → 1 | 4825 | 85.5 °C | 60.5 km/h | steady cruise, hot engine |

RPM and speed differ by ~ 30-50 % between the two transitions; coolant is similar but not tight. If the byte were speed-triggered or RPM-triggered, we'd expect these to line up. Time is the only variable that matches to within a minute across both transitions.

## Candidate meanings

Not enough data to distinguish; ranked by plausibility given the pattern:

1. **Post-start warmup-stage counter.** ECU's internal "how much longer in cold-map / normal-map / hot-map" bin. Would fit the ~ 5 min-per-step cadence and the reset-on-key-cycle behaviour. Consistent with real ECU warm-up scheduling, which typically ramps in stages rather than continuously.
2. **Trip-timer or "minutes since engine start" 3-state bin.** Some ECUs broadcast an internal "elapsed run time" quantised into coarse bins. If bin width is ~ 5 min and rolls into higher states over longer rides, a 12+ min ride would eventually show D3 = 3, 4, 5.
3. **Some cumulative event counter that happens to accrete on a ~ 5 min timescale.** Less likely because the observed values are strictly monotonic; a random-event counter would show more variance.

The 3-state observation is a **lower bound** — longer rides would exercise D3 = 3+ and either extend the sequence (supports (2)) or saturate at 2 (supports a fixed warmup schedule per (1)).

## What the byte is NOT

- **Not coolant-triggered.** moving-2 stayed at D3 = 0 for 124 s with coolant already above 80 °C throughout; if coolant crossed a threshold, D3 would have stepped. And the two 0 → 1 transitions occurred at 80.1 and 85.5 °C — a 5 °C gap that a threshold model doesn't explain.
- **Not RPM-triggered.** Transitions at 6089 and 4825 RPM.
- **Not gear-triggered.** Rider was in different gears at the two transitions.
- **Not persistent across key-cycles.** moving-2 starts fresh at 0 after the key-cycle from moving-1.
- **Not the ABS ROAD/SUPERMOTO mode broadcast** ([[2026-07-12-dash-inputs]] Phase A open question). ROAD/SUPERMOTO would toggle 2-state on button-press, not walk monotonically with time.

## Open

- **Confirm the ~ 5 min-per-state cadence** with a single-boot capture ≥ 30 min. Should see D3 walk 0 → 1 at ~ 5 min, 1 → 2 at ~ 10 min, and if this is a running counter, 2 → 3 at ~ 15 min.
- **Semantic identification** via a scenario that exercises a specific ECU-mode transition: a cold engine ride to full warm; a controlled short vs long ride; possibly cross-reference to any owner's-manual mention of ECU "warmup phases".
- **Cross-check against `540 D1` (warmup index).** Both are engine-management bytes on adjacent IDs and both engine-on-gated. If they track together during warmup, this reinforces the warmup-stage hypothesis.

## Evidence

- [[2026-07-22-first-moving-ride]] — moving-1 and moving-3 provided the two transitions; moving-2/4/5 provided the plateau boundaries.
- One-liner byte-transition analysis embedded in the whole-corpus sweep of remaining `?` bytes.

See also: [[signal-warmup-index]] (`540` D1 — the parallel warmup-related byte, throttle+load-derived; also engine-on-gated), [[signal-engine-on-counter]] (`541` D4 — the *continuous* second-resolution engine-on counter, contrast to this coarse 5-min-bin byte).
