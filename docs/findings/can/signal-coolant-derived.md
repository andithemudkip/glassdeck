---
area: can
status: provisional
established_by:
  - 2026-06-21-cross-session-payload-diff
  - 2026-06-21-bit-transition-scan
references:
  - ktm-can-decoder
---

# Candidate derived-coolant byte — `540` D1

`540` byte D1 is a strong candidate for a **derived / binned coolant signal** — likely the dashboard gauge needle position, or coolant temperature in a coarser unit than the raw 0.1 °C encoding at [[signal-coolant-temp]].

## Observation

Across the three engine-idle baseline runs (cold / partial-warm / operating-temp), `540` D1's dominant value steps monotonically:

| Idle run                | dominant `540` D1 | observed [[signal-coolant-temp]] median |
|-------------------------|------------------:|----------------------------------------:|
| Run 1 (cold)            | `0x0E`            | 48.3 °C                                  |
| Run 2 (partial warm)    | `0x0F`            | 66.6 °C                                  |
| Run 3 (operating temp)  | `0x10`            | 85.5 °C                                  |

In all 6 engine-off sessions, `540` D1 dominant = `0x00` and is static within the session.

The three engine-on dominants `0x0E / 0x0F / 0x10` (14 / 15 / 16 decimal) increase strictly monotonically with coolant temperature, with very few intermediate values per session (idle-1 mostly `0x0E`, idle-2 mostly `0x0F`, idle-3 mostly `0x10`). The temperature step between Run 2 (66.6 °C) and Run 3 (85.5 °C) is ~19 °C and corresponds to a `0x0F → 0x10` step — *not* a 1 °C-per-bit encoding.

## Bit-level corroboration

[[2026-06-21-bit-transition-scan]] shows that the per-bit toggle profile of `540` D1 also shifts with temperature, in a way only a quantised thermal encoding would produce:

| bit | idle-1 (cold) | idle-2 (warm) | idle-3 (op-temp) | interpretation |
|----:|--------------:|--------------:|-----------------:|---------------|
| 0   | 80            | 81            | 80               | LSB, jitter-driven — toggles independent of temperature |
| 1   | 80            | 63            | **8**            | toggles **fall** as temp rises (settling) |
| 2   | active        | active        | inactive         | high bit, only flips during warm-up |
| 3   | active        | active        | inactive         | same |
| 4   | active        | active        | inactive         | same |

A coincident engine-state byte (just turning on at engine start, holding a stable value through idle) would not show this per-bit settling — its bits would be steady once engine-on. The bit-1-and-up settling as coolant approaches operating temperature is exactly the signature of a binned thermal encoding where the value is moving through fewer high-bit transitions as it stabilises.

## Hypotheses

Two natural readings, both untested:

1. **Dashboard gauge needle position.** The OEM coolant gauge has discrete bars/segments; D1 may encode the bar index (or a sub-bar position). The 14/15/16 spacing fits ~20 °C per bar in the lower-mid range.
2. **Coolant temperature on a non-linear lookup curve.** Bosch ECUs often expose a "gauge-side" or "warning-light-side" coolant value separately from the raw sensor reading. The curve is typically flat at the cold and hot extremes and steeper in the mid-range so the needle moves predictably.

Both hypotheses predict `540` D1 will track [[signal-coolant-temp]] (`540` D5,D6) but on a quantised scale. A finer-grained engine-on capture spanning a continuous warm-up (e.g., cold-start through to fan-cycle temperature) is needed to fit the function.

## Why `provisional`

- Only three data points across the thermal range (Runs 1/2/3 at 48 / 67 / 86 °C). Three points cannot distinguish "gauge bar index" from "derived non-linear lookup" from "coincidentally monotonic engine-state byte."
- The engine-off baseline at `0x00` is consistent with a coolant-derived signal but also consistent with any byte that simply latches to 0 engine-off.
- The 2026-06-19 per-input sessions (engine-off) all show `0x00`, so they add no thermal information.

## Promote-to-confirmed criteria

- A continuous engine-on warm-up capture shows `540` D1 stepping through more than 3 values as [[signal-coolant-temp]] climbs.
- The step boundaries are reproducible across two warm-up runs (i.e., the same temperature consistently produces the same D1 value, ruling out a session-local counter).

If both hold, the encoding can be promoted and the mapping table built.

## Evidence

- [`docs/experiments/2026-06-21-cross-session-payload-diff.md`](../../experiments/2026-06-21-cross-session-payload-diff.md) — candidate short list, `540` D1 row.
- [`docs/experiments/2026-06-17-payload-diff-idle.md`](../../experiments/2026-06-17-payload-diff-idle.md) — the original "ENGINE-STATE, thermal-corr" tag on `540` D1 (now interpreted as derived coolant).

See also: [[signal-coolant-temp]], [[always-on-broadcast-ids]].
