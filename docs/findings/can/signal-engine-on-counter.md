---
area: can
status: confirmed
established_by:
  - 2026-06-21-bit-transition-scan
  - 2026-06-23-engine-driven-rear-spin
  - 2026-07-22-first-moving-ride
---

# Engine-running seconds counter — `541` D4 (uint8)

`541` byte D4 is a **full 8-bit uint8 modulo-256 engine-running seconds counter**. It ticks at ~1 Hz whenever the engine is running and is frozen engine-off.

```
seconds_mod_256 = data[4]             # 0..255, wraps every 256 s
```

> **2026-07-22 update — bit 7 is not reserved.** Original finding claimed 7-bit modulo-128 because bit 7 never toggled in any pre-2026-07-22 session. That was because every previous engine-on session was shorter than ~ 128 s from engine-start. The moving-ride corpus caught D4 crossing 128 four times: moving-1 at t+108.7 s (D4 = 128), moving-3 starts at D4 = 143 (bit 7 already high mid-count), moving-4 first bit-7 at t+50.4 s, moving-5 first bit-7 at t+68.3 s. Peak observed D4 = 255 with natural wrap-through to 0 — a full uint8 counter, not a 7-bit one. See [`scripts/first_moving_ride_qs_bit_probe.py`](../../../scripts/first_moving_ride_qs_bit_probe.py) tail output (the byte was surfaced en passant during the fan-status hunt in [[fan-status-absent-from-broadcasts]]).

Update rate (of the broadcast): 100 ms (the period of `541` — see [[always-on-broadcast-ids]]). The counter's *value* only increments once a second; the byte is rebroadcast at the ID's period in between.

## Engine-time, not engine-events

The decisive test was whether the tick rate is constant under wall-clock time (seconds counter) or scales with RPM (an engine-cycle / fuel-injection event counter). The 2026-06-23 engine-driven rear-spin capture holds steady RPM setpoints from idle to ~5500; the rate is essentially flat:

| RPM bin     | duration (s) | ticks | rate (Hz) | ticks/rev |
|-------------|-------------:|------:|----------:|----------:|
| idle (~1700) | 205.6        | 202   | 0.98      | 0.0349    |
| ~2000       | 11.1         | 12    | 1.09      | 0.0318    |
| ~2500       | 5.9          | 6     | 1.02      | 0.0244    |
| ~3000       | 6.0          | 6     | 1.00      | 0.0202    |
| ~3500       | 8.5          | 8     | 0.94      | 0.0157    |
| ~5500       | 6.4          | 6     | 0.94      | 0.0112    |

If the byte were an engine-cycle counter, `ticks/rev` would be roughly constant and the rate would climb ~3× from idle to 5500. The opposite happens — rate stays clustered around 1 Hz and `ticks/rev` falls inversely with RPM. The 4000 / 4500 RPM bins are noisier (each only held 4–7 s, 5–7 ticks; one bad sample shifts the rate visibly) but neither breaks the pattern.

The three steady-idle baselines independently land at 0.983 / 0.989 / 0.991 Hz over ~180 s each — close to 1.00 Hz but slightly under, consistent with a true ~1 Hz tick and small bin-edge truncation in the analysis rather than a non-unit rate.

Re-derive with `python scripts/id541_d4_tick_rate.py`.

## Per-bit toggle cascade (engine-on idle)

The clean halving cascade that originally flagged this byte as a counter — bits 0..6 each toggle at half the rate of the bit below — over ~175 s of steady idle:

| bit | idle-1 | idle-2 | idle-3 | ratio vs bit 0 |
|----:|-------:|-------:|-------:|---------------:|
| 0   | 177    | 176    | 175    | 1.00 (reference) |
| 1   | 88     | 88     | 87     | 0.50            |
| 2   | 44     | 44     | 44     | 0.25            |
| 3   | 22     | 22     | 22     | 0.125           |
| 4   | 11     | 11     | 11     | 0.0625          |
| 5   | 5      | 5      | 5      | 0.031           |
| 6   | 2      | 2      | 2      | 0.016           |
| 7   | 0      | 0      | 0      | —               |

Bit 0 is the LSB. Engine-off toggle counts are zero in every off session (cold-boot, throttle, kill, stand, clutch, gear).

## Why this isn't fuel consumption

The byte was on the candidate list for fuel-consumption derivation. It isn't — the rate is decoupled from RPM, so it can't be an injection-event count and it can't be an integrated-fuel-mass quantity. Useful only as engine-hours (modulo 128 s, so usable for short windows or once dewrapped across captures), not for L/h. See the analysis in `scripts/id541_d4_tick_rate.py` and the broader fuel-rate hunt notes in [[byte-121-twin-int16]] and the planned fuel-level walkdown.

## What this is NOT

- Not a CRC despite the original byte-level CRC-LIKE tag — that was based on distinct-value count alone (≥128). A real CRC's per-bit toggle rates would cluster near 50 % at every bit, not halve cleanly.
- Not a fuel / engine-event counter (ruled out by the RPM-excursion test above).
- Not a flag-bit map.

## Open

- **Wrap dewrapping.** Across a session longer than 128 s the byte rolls. Consumers need to integrate `(curr - prev) mod 128` per frame (the `id541_d4_tick_rate.py` analyzer does this). Worth wrapping in a small helper if more callers materialise.
- **Sub-second jitter.** Median rate at idle reads 0.98–0.99 Hz, not exactly 1.00. Within the precision of the analysis (bin-edge truncation, ~1 LSB per ~180 s window) this is consistent with a true 1 Hz tick; an independent stopwatch-anchored capture could pin it tighter if it ever matters.

## Evidence

- [`docs/experiments/2026-06-21-bit-transition-scan.md`](../../experiments/2026-06-21-bit-transition-scan.md) — per-bit toggle table establishing the counter structure.
- [`docs/experiments/2026-06-23-engine-driven-rear-spin.md`](../../experiments/2026-06-23-engine-driven-rear-spin.md) — RPM setpoint capture that supplied the rate-vs-RPM test.
- [`scripts/id541_d4_tick_rate.py`](../../../scripts/id541_d4_tick_rate.py) — re-derives the table above.
- [`docs/experiments/2026-06-17-payload-diff-idle.md`](../../experiments/2026-06-17-payload-diff-idle.md) — original byte-level CRC-LIKE tag (superseded).

See also: [[byte-d7-cycle-hash]] (different ID, separate algorithm), [[always-on-broadcast-ids]], [[byte-121-twin-int16]].
