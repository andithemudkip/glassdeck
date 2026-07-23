---
area: can
status: confirmed
established_by:
  - 2026-06-24-front-wheel-hand-spin
  - 2026-06-24-front-wheel-decay-mark
  - 2026-06-30-unknown-byte-corpus-sweep
  - 2026-07-22-first-moving-ride
supersedes_claim:
  - "LSB 3/64 km/h (was fit against the old-canonical-decode of front wheel)"
  - "D3 always 0x00 (was a corpus artefact — front wheel never got above 12.7 km/h before 2026-07-22)"
---

# `12D` D3:D4 — redundant 16-bit big-endian front-wheel-speed mirror

`12D` D3:D4 is a second front-wheel-speed broadcast — same physical quantity as the canonical [[signal-wheel-speed-front]] at D0:D1, but with its own encoding scale. Refit against the 2026-07-22 corpus (n = 92 827 frames across the 0-102 km/h range):

| Field | Encoding | Scale | Behaviour |
|------:|----------|-------|-----------|
| **D3:D4** | 16-bit BE u16 (D3 = high byte, D4 = low byte) | **≈ 0.0577 km/h per LSB** (≈ 1/17.34, working best-fit; not a clean fraction) | `0` at rest. Snaps to `0` in lockstep with the canonical decode. Now exercised across the full 0-102 km/h range; D3 walks 0..6, both bytes carry information. |

```python
front_mirror_kmh = ((data[3] << 8) | data[4]) * 0.0577    # working ± ~1% until dash-verified anchor
```

The canonical front-wheel-speed source remains [[signal-wheel-speed-front]] (D0:D1, 12-bit at 1/10 km/h). D3:D4 is a redundant mirror at a *different* LSB — same km/h reading, different byte-level scale.

## Evidence — 2026-07-22 refit

Prior fit used LSB 3/64 km/h/LSB against the pre-2026-07-22 canonical decode of front wheel speed (which was ~1/192 km/h/LSB on the raw u16 view). Both the canonical LSB and the mirror LSB have been corrected. Using the corrected canonical (12-bit at 1/10 km/h):

- **n = 92 827 12D frames** across the 5-file moving corpus, spanning canonical decoded front speed 0.00-102.20 km/h and raw D3:D4 values 0-1764.
- **OLS fit:** `canonical_kmh = 0.0576724 × raw_D3D4 + 0.2176`
- **Pearson r = 0.99997332** — essentially a perfect line.
- **RMS residual = 0.245 km/h** — sub-quarter-km/h across the whole speed range.

Candidate LSB check (each holding intercept at the OLS-optimum for that slope):

| Slope tried | RMS residual (km/h) |
|-------------|--------------------:|
| **0.0577 (this fit)** | **0.245** |
| 1/16 = 0.0625 | 2.82 |
| 1/20 = 0.0500 | 4.47 |
| 3/64 = 0.046875 (old finding) | 6.29 |
| 1/12 = 0.0833 | 14.93 |

The fit lands cleanly on ~ 0.0577 (= ~ 1/17.34). Not a clean small-integer fraction, but Bosch clearly used non-clean LSBs elsewhere on this bike (rear D5:D6 sits at ~ 0.0565 = ~ 1/17.7 — same rough magnitude). The old finding's clean 3/64 was a fit against the wrong canonical; the working data always supported ~ 0.0577.

## D3 activation confirms multi-byte structure

D3 was static `0x00` across every pre-2026-07-22 session because front wheel speed never exceeded ~ 12.7 km/h (D4-alone saturates at ~ 14.7 km/h at LSB 0.0577). The moving corpus takes the bike to 102 km/h, exercising D3 through values 0..6:

| Speed bin | Typical D3 | Typical D4 | Combined raw |
|-----------|:----------:|:----------:|:------------:|
| 0-15 km/h | 0 | 0-200 | 0-260 |
| 15-30 km/h | 1 | 50-200 | 290-465 |
| 30-45 km/h | 2 | 45-190 | 555-740 |
| 45-60 km/h | 3 | 50-180 | 820-1000 |
| 60-75 km/h | 4 | 55-195 | 1075-1255 |
| 75-90 km/h | 5 | 55-170 | 1335-1520 |
| 90-102 km/h | 6 | 65-210 | 1600-1745 |

D3 increments by 1 approximately every 256 D4 counts, i.e., every 14.8 km/h — exactly what a 16-bit BE u16 predicts. The finding's Open question "Confirm D3 high-byte behaviour" (from the 2026-06-30 corpus-sweep era) is now closed.

## Encoding was correct; scale had to shift

The original 2026-06-24 finding's structural claim ("D3:D4 is a 16-bit BE mirror of front wheel speed at some finer scale than D0:D1's canonical") holds. The specific LSB (3/64) was fit against a canonical that was subsequently rewritten. The finding's method — compute Pearson r vs canonical, fit slope — still works; just needs re-running when the canonical changes.

**Lesson embedded here:** mirror LSBs are always downstream of the canonical LSB. When the canonical is provisional, mirror LSBs are provisional too. This finding was `provisional` for that reason; with both canonical and mirror now on the same 2026-07-22 corpus, the mirror upgrades to `confirmed` on the encoding and `provisional` on the exact LSB (same dash-verified-procedure dependency as [[signal-wheel-speed-front]]).

## Evidence — encoding

The corpus sweep ([[2026-06-30-unknown-byte-corpus-sweep]]) flagged `12D` D4 as the only EXPLAINED-BY hit in the entire 53-byte unknown space, with the strongest correlation in the whole pass:

| Session | D4 vs `wheel_speed_front` Pearson r |
|---|---:|
| 2026-06-24-front-wheel-decay-mark (engine-off) | +0.9985 |
| 2026-06-24-front-wheel-hand-spin (engine-off) | +0.9978 |

Pooling moving-wheel frames from both sessions (n = 7 767), an OLS fit of D4 → decoded `wheel_speed_front` (km/h) gives:

| metric | value |
|---|---:|
| slope | **0.046875 km/h per LSB** (exactly 3/64) |
| intercept | +0.795 km/h |
| Pearson r | +0.999933 |
| residual σ | 0.024 km/h (≈ ½ LSB) |

Residual at quantisation precision; the +0.795 km/h intercept corresponds to a constant 17-LSB pre-offset that places D4 = 33 at exactly the 2.34 km/h snap threshold (see "Snap-to-zero" below).

Candidate slope check (residual against alternative encodings at the same intercept):

| candidate slope | residual σ |
|---|---:|
| **3/64 = 0.04688 km/h/LSB** | **0.024 km/h** ← fit |
| 1/12 = 0.08333 km/h/LSB (same as the wide D0:D1 field) | 3.97 km/h |
| 1/16 = 0.0625 km/h/LSB (same as rear D5:D6) | 49 km/h |
| 1/10 = 0.1 km/h/LSB (same as D2 coarse rear mirror) | 5.79 km/h |

The fit lands cleanly on `3/64`, not on either of the other wheel-speed scales already in use on this ID — three different wheel-speed encodings co-broadcast within the same arbitration ID.

## Snap-to-zero behaviour

D3:D4 snaps to `0x0000` in lockstep with the canonical [[signal-wheel-speed-front]] D0:D1. Both fields share the ECU's low-speed broadcast floor: below the floor threshold both read exactly 0; above it both track linearly.

## What this rules out

- **`12D` D3:D4 is not throttle-derived, RPM-derived, or coolant-derived.** The corpus sweep tested all known references; only front wheel speed exceeded |r| = 0.9, and it did so at r ≈ 0.998 in the original engine-off sessions and r ≈ 0.99997 in the 2026-07-22 corpus.
- **D3:D4 is not the same encoding as D2 (rear coarse mirror).** D2 wraps every 25.5 km/h at 0.1 km/h LSB; D3:D4 spans 0-102 km/h monotonically without wrapping.
- **D3:D4 is not a redundant copy of the canonical D0:D1 12-bit field.** Different LSB (0.0577 vs 0.1 km/h/LSB on the extract) and different byte position. Independent broadcast, same input quantity.

## Open

- **Absolute LSB anchor.** Currently anchored to the corrected canonical decode of front wheel speed (which is itself provisional at ± ~ 1 %). A dash-verified moving procedure or GPS ride will pin both simultaneously.
- **Why three wheel-speed scales on one ID?** Different downstream consumers (canonical D0:D1 → speedo; D3:D4 → possibly ABS module; D2 → coarse rear reference for something). Doesn't block anything.

## Evidence

- [[2026-06-24-front-wheel-hand-spin]] — engine-off, hand-spin pushes 2-10 km/h. Established the D4 correlation on the low-speed regime.
- [[2026-06-24-front-wheel-decay-mark]] — engine-off, hand-spin + decay tail. Confirmed the shared floor with the canonical.
- [[2026-06-30-unknown-byte-corpus-sweep]] — flagged the correlation and ran the original encoding fit.
- [[2026-07-22-first-moving-ride]] — corpus that (a) exercised D3 for the first time, confirming multi-byte structure, (b) refit the LSB against the corrected canonical, (c) promoted the finding to `confirmed`.
- [`scripts/id12d_d4_characterise.py`](../../../scripts/id12d_d4_characterise.py) — original characterisation script (pre-2026-07-22).
- [`scripts/first_moving_ride_d3d4_refit.py`](../../../scripts/first_moving_ride_d3d4_refit.py) — 2026-07-22 refit + D3 activation check.

See also: [[signal-wheel-speed-front]] (canonical D0:D1 12-bit field), [[signal-wheel-speed-rear]] (rear D5:D6 + D2 coarse mirror), [[byte-encoding-12-in-16]], [[always-on-broadcast-ids]].
