---
area: can
status: confirmed
established_by:
  - 2026-06-18-throttle-sweep-engine-off
---

# Byte D7 on always-on IDs looks like a checksum / counter, not a data signal

On at least 9 of the 11 always-on broadcast IDs, byte **D7** behaves like a derived byte (checksum, rolling counter, or hash) rather than a data signal. This is an *observation* about the value distribution; the CRC interpretation is the leading hypothesis but has not been verified by reproducing the algorithm.

## Observation

During the engine-off throttle sweep ([`2026-06-19-throttle-sweep-engine-off`](../../../logs/2026-06-19-throttle-sweep-engine-off/)), bytes D7 across IDs split into two cleanly defined groups by value cardinality (counted across the ~20 s slow-sweep phase):

| ID  | Other-byte payload movement during phase | D7 range | D7 unique values |
|-----|------------------------------------------|---------:|-----------------:|
| `120` | D2 sweeps 0–254 (throttle); D0,D1 = 0    | 32–223   | **186** |
| `541` | D6 drifts in range 20 counts             | 32–223   | **102** |
| `121` | D0 alternates 0 / 255; D1 = 2 values     | 52–217   | 12      |
| `129` | mostly static                            | 49–208   | **6**   |
| `12A` | mostly static                            | 61–220   | **6**   |
| `12D` | mostly static                            | 53–212   | **6**   |
| `12E` | mostly static                            | 46–207   | **6**   |
| `5A0` | mostly static                            | 59–218   | **6**   |
| `5B0` | mostly static                            | 52–213   | **6**   |

The cardinality of D7's value set scales with how much the rest of the payload moves. IDs whose other bytes are mostly static cycle through exactly **six** D7 values; the two IDs with the most-active payloads (`120`, `541`) show one to two orders of magnitude more.

That pattern is consistent with a checksum or hash byte: D7 is determined by D0..D6, so it varies only when D0..D6 vary, and the value space it explores is bounded by the input space it actually sees. A pure data signal would not show this dependency.

## Why this is more than a coincidence

The leading alternative hypothesis is a rolling sequence counter (independent of payload). That can be ruled out for the mostly-static IDs by the cardinality: a free-running counter over ~400 frames would visit far more than 6 values unless the counter wraps at 6, which would be unusual.

The pattern also retroactively explains [`120` D7's weak negative correlation with `120` D2](signal-throttle-position.md#refutations-from-the-same-capture) (Pearson r = −0.012): D7's value distribution is shaped by the *checksum function*, not by the throttle channel.

## What this is *not* claiming

- It is not claiming D7 is a CAN-bus-layer CRC. Classic CAN has its own 15-bit CRC on every frame and the payload is not the place for it.
- It is not claiming the specific algorithm (CRC-8 variant, simple XOR, Bosch's J1939-style checksum, a manufacturer-proprietary hash, etc.). Identifying the algorithm requires reproducing it from D0..D6 against D7 across a wider corpus.
- It says nothing about `540` and `450`. Both are 100 ms-cohort IDs whose payloads are mostly static across our captures so far — they did not surface in the bus-wide range scan with threshold 20. A dedicated check is needed.
- It does not yet exclude that D7 on `120` and `541` is *partly* checksum and *partly* data — a checksum nibble in the high four bits and a counter in the low four, for example.

## Why this matters

Three downstream consequences:

1. **Discount D7 as a candidate decode target on the 7 IDs flagged above.** Time spent hunting for "which signal lives at D7" on those IDs is likely wasted; the byte is structural, not informational.
2. **Active TX will need D7 right.** If the project ever transmits a synthesised frame back to the bike (well beyond Phase 4, see CLAUDE.md golden rule 1), the ECU is likely to reject frames whose D7 doesn't match the expected checksum over D0..D6. Reproducing the algorithm is a prerequisite for closed-loop write.
3. **It quietly explains why payload-diff classified D7 on many IDs as UNKNOWN.** A static payload + a deterministic checksum function = a small set of values that look pseudo-random to a classifier without context.

## Open

- **Reproduce the algorithm.** Iterate over candidate CRC-8 polynomials / J1939-style checksums against D0..D6 → D7 across a corpus that spans multiple payload states (idle + throttle sweep + kill toggle + future per-input captures). If one polynomial scores >99 % across all three captures simultaneously, that is the algorithm.
- **Check `540` and `450`.** Capture-cohort coverage is currently driven by which IDs have non-static payload bytes. A future capture with engine running + several inputs varied will exercise `540` and `450` payloads enough to surface their D7 distributions.
- **Counter vs checksum**, even for the static-payload group: 6 unique values is consistent with both a checksum over a 6-state payload *and* a mod-6 sequence counter. Recording the time series of D7 alongside the frame index would disambiguate.

## Evidence

- [`docs/experiments/2026-06-18-throttle-sweep-engine-off.md`](../../experiments/2026-06-18-throttle-sweep-engine-off.md) — Result section, "Bus-wide scan" subsection.
- [`scripts/throttle_sweep.py`](../../../scripts/throttle_sweep.py) — bus-wide range scan that surfaced this pattern (`--range-threshold` controls the cutoff).

See also: [[always-on-broadcast-ids]], [[signal-throttle-position]].
