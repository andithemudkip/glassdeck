---
area: can
status: provisional
established_by:
  - 2026-06-21-bit-transition-scan
---

# Candidate engine-on counter — `541` D4

`541` byte D4 is a strong candidate for a **slow engine-on counter** (or counter-like derived value). Originally tagged CRC-LIKE in [[2026-06-17-payload-diff-idle]] because it has ≥128 distinct values across an idle window; bit-level analysis ([[2026-06-21-bit-transition-scan]]) reveals the per-bit toggle counts form a clean binary-counter cascade rather than the uniform high-entropy distribution a checksum would produce.

## Observation

Per-bit toggle counts in each ~175-second engine-on idle window:

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

Each higher bit toggles at exactly half the rate of the bit below it — the textbook signature of a binary counter (bit 0 is the LSB and flips most often; bit 6 is the high bit and flips least). Bit 7 never toggles in the observed window; the counter looks 7-bit, value range `0..127`.

Engine-off toggle counts are zero in every session (cold-boot, throttle, kill, stand, clutch, gear). The counter only ticks with the engine running.

## Rate inference

Bit 0 toggled ~175 times over ~175 s of steady idle → bit 0 flip ~1 Hz → **counter increments approximately once per second**. At ~1 Hz, a 7-bit counter wraps every 128 s — consistent with the byte being a rolling seconds-of-engine-run modulo 128, or any other ~1 Hz tick (fuel-injection event group counter divided down, idle-air-control update tick, etc.).

## Why not a CRC

A standard checksum byte exhibits uniform high entropy: each bit toggles at roughly the same rate, near 50 %. `541` D4's bit rates differ by a factor of 88× from bit 0 to bit 6. That's not what a CRC produces. The byte-level CRC-LIKE tag in [[2026-06-17-payload-diff-idle]] was based on distinct-value count alone (≥128 distinct) without checking the structural pattern — bit-level analysis exposes the structure.

## Hypotheses

- **Engine-run seconds counter, 7-bit modulo 128.** Cleanest fit to the ~1 Hz rate.
- **Derived counter — fuel-injection events / N, ignition pulses / N.** Same observable pattern at any rate that averages to ~1 Hz over 175 s.
- **A coarse value other than a counter** (e.g., engine-load index, fuel-trim integrator) that happens to walk monotonically at ~1 Hz at idle. Less likely given the clean per-bit halving.

## Promote-to-confirmed criteria

- A longer engine-on capture (say 300+ s) shows bit 0 still toggling at ~1 Hz and bit 6 at ~1/64 Hz.
- An RPM excursion (engine blip from idle to 4000 RPM) either changes the rate (→ event-based counter) or doesn't (→ seconds counter). Either outcome is decisive.

If the rate is constant under RPM change, it's a seconds counter and can be read directly. If the rate scales with RPM, it's an event counter and can still be useful (e.g., trip-meter derivation).

## What this is NOT

- Not a flag-bit map: a flag would show toggle counts of 1–10 per session matching specific events, not a clean halving cascade.
- Not coolant-related: independent of `540` D5/D6.
- Not a checksum despite the original CRC-LIKE tag.

## Evidence

- [`docs/experiments/2026-06-21-bit-transition-scan.md`](../../experiments/2026-06-21-bit-transition-scan.md) — per-bit toggle table for `541` D4.
- [`docs/experiments/2026-06-17-payload-diff-idle.md`](../../experiments/2026-06-17-payload-diff-idle.md) — original byte-level CRC-LIKE tag (now superseded by the bit-level structural read).

See also: [[byte-d7-checksum-hypothesis]] (different ID, separate algorithm), [[always-on-broadcast-ids]].
