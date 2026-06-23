---
date: 2026-06-23
status: failure
phase: 2
related:
  findings: [byte-d7-cycle-hash]
  decisions: []
  logs: []
---

# D7 per-ID offset — search for `g(canID) → offset`

## Hypothesis

The 9 per-ID D7-cycle XOR offsets cataloged in `byte-d7-cycle-hash`
all fall in `0x00..0x1B` — well below the entropy of a randomly drawn 8-bit
per-ID secret. Probability of all 9 below 0x20 if drawn uniformly is
`(32/256)^9 ≈ 10⁻⁸`. We hypothesised the offset is not a stored per-ID
secret but a deterministic function `g(canID)` with a low-bit-width output.
If `g` exists, the two offset collisions (`120`/`12D` at 0x00,
`121`/`12A` at 0x08) become deterministic, not coincidences — and the
"per-ID secret seed" story in the finding is wrong.

## Setup

Desk computation only — no bike. Inputs: the (ID, offset) table from
`docs/findings/can/byte-d7-cycle-hash.md`. Code:
`scripts/d7_offset_search.py`.

Searches:

1. **GF(2)-linear** — each output bit `b` of offset is XOR of a subset of
   ID bits. Per bit, enumerate all 2¹¹ masks and check whether the 9
   (ID, target_bit) constraints are satisfied.
2. **Affine** — linear plus a constant XOR (per-bit flip allowed).
3. **CRC-8** — every (poly × init × refin × refout × endian) combination,
   with `xorout` collapsed via consistency: for fixed parameters, all 9
   `(crc(ID) ^ offset) & 0x1F` values must agree.
4. **Modular** — `(a·ID + b) mod K` for `2 ≤ K < 64`.

## Result

All four searches fail.

- **Linear**: bits 0, 1, 2, 4 of the offset have **no** mask whose XOR
  parity matches the 9-ID targets. Bit 3 has 8 fitting masks, which is
  within Poisson noise of the chance expectation (E≈4, σ≈2) given the
  9-bit targets — not signal.
- **Affine**: same bits remain unsolvable after allowing a constant XOR
  per bit; flipping the target is just XOR with `0xFF`.
- **CRC-8**: 0 hits across all 255 polys × 256 inits × 4 reflection
  modes × 2 endians, low-5-bit match.
- **Modular**: 0 hits for `K < 64`.

## Interpretation

The offset is **not** any of: GF(2)-linear function of ID bits, affine
ditto, standard CRC-8 over ID bytes (low 5 bits), nor `(a·ID + b) mod K`.

Three remaining possibilities, ranked by current weight:

1. **The offset is `f(D0..D6)`, not per-ID.** The original finding flagged
   this hypothesis as motivated by the two offset collisions; this
   experiment's failure pushes weight onto it. Crucially, both `120` and
   `12D` had all-zero `D0..D6` payloads in their measurement windows —
   `f(zeros) = 0` would predict offset `0x00` on both. And `121`/`12A`
   sharing `0x08` is a much weaker constraint under `f(payload)` than
   under `g(ID)`.
2. **`g` is nonlinear in ID bits** (quadratic, S-box, Pearson hash over
   ID bytes). Search space large; not pursued here.
3. **`g(ID, DataID)` where DataID is a hidden ECU-internal constant** not
   present on the bus. Indistinguishable from (1) using bus data alone
   unless we obtain an ECU dump.

This experiment does not distinguish (2) from (1). However, the cheapest
next test — re-deriving offsets for `121` on its non-dominant payloads,
already listed as the "121 shared 0x08 test" Open item in the finding —
directly tests (1) vs (2)+(3). If `121`'s offset varies with payload, (1)
is confirmed and (2)/(3) are refuted as the primary story. If it stays
locked at `0x08` across all payloads, (1) is refuted and we must reach
for nonlinear ID functions or hidden DataIDs.

## Follow-ups

- Update `byte-d7-cycle-hash` Open section: move "per-ID secret
  vs payload-hash" to be the *single* most useful next test, with this
  experiment as the reason weight shifted toward payload-hash.
- Run the "121 shared 0x08 test" — per-payload offset derivation on
  `121` across the 9 distinct payloads in the idle-run-1 window.
- If the payload-hash story holds, then the linear/CRC-8/Pearson search
  should be re-run with payload bytes as input rather than ID bytes.

## Evidence

- Script: [`scripts/d7_offset_search.py`](../../scripts/d7_offset_search.py)
- Search corpus: 9 (ID, offset) pairs from
  [`docs/findings/can/byte-d7-cycle-hash.md`](../findings/can/byte-d7-cycle-hash.md)
