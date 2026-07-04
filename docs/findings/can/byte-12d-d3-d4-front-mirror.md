---
area: can
status: provisional
established_by:
  - 2026-06-24-front-wheel-hand-spin
  - 2026-06-24-front-wheel-decay-mark
  - 2026-06-30-unknown-byte-corpus-sweep
---

# `12D` D3:D4 — redundant 16-bit big-endian front-wheel-speed mirror

`12D` D3:D4 is a second front-wheel-speed broadcast at a different scale to the canonical wide field at D0:D1. Best-fit encoding is **D3:D4 BE u16 at exactly 3/64 km/h per LSB** (≡ 64/3 ≈ 21.333 LSB per km/h), with the same snap-to-zero behaviour as [[signal-wheel-speed-front]]. D3 has been static `0x00` across every captured condition because the front wheel never exceeded ~12 km/h, so the encoding is so far only confirmed on the low byte D4.

| Field | Encoding | Scale | Behaviour |
|------:|----------|-------|-----------|
| **D3:D4** | 16-bit BE u16 (D3 = high byte, D4 = low byte) | **0.046875 km/h per LSB** = 3/64 km/h | `0` at rest. Snaps to `0` below ~2.3 km/h (same threshold as the wide D0:D1 field). D3 = 0x00 observed in all captures because front wheel < 12.7 km/h cap of D4 alone. |

```python
# Decode (low byte already saturates the byte at ~12.7 km/h — D3 needed above that)
front_mirror_kmh = ((data[3] << 8) | data[4]) * 0.046875
```

The canonical front-wheel-speed source remains [[signal-wheel-speed-front]] (D0:D1, 1/12 km/h LSB on the extracted 12-bit value). D3:D4 is a redundant mirror — same value at coarser resolution, similar in spirit to how D2 carries the coarse rear-speed mirror noted in [[signal-wheel-speed-rear]].

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

D4 = `0x00` for every frame where `wheel_speed_front` decodes to `0`. The minimum non-zero D4 value observed across both sessions is `33`, which decodes to `33 × 0.046875 + 0.795 ≈ 2.34 km/h` — matching the wide field's snap threshold at raw 448 (≡ 2.333 km/h) from [[signal-wheel-speed-front]] to within quantisation. Both fields share the same threshold and snap together.

| `wheel_speed_front` (km/h) | D4 range observed | D4 median per bin |
|---|---|---:|
| 0 | `{0x00}` only | 0 |
| 2 – 3 | 33 – 67 | 40 – 58 |
| 4 – 5 | 68 – 110 | 75 – 99 |
| 6 – 7 | 111 – 152 | 121 – 143 |
| 8 – 9 | 153 – 195 | 163 – 183 |
| 10 | 196 – 201 | 197 |

D4 monotonic across the full speed range observed; no wrap detected. Bin-median residual ≤ 1 LSB at every bin.

## Why D3 is reported as observed-zero, not reserved

D3 = `0x00` across every frame of every captured session, and the unknown-byte sweep initially classified it as a static-zero byte. After the D4 encoding is locked, D3 is better read as the **high byte of an unexercised 16-bit slot**:

- D4 alone saturates at `0xFF × 0.046875 + 0.795 ≈ 12.74 km/h`. Above that, the encoding must overflow into D3.
- Every front-wheel-active session in the current corpus is hand-spin or decay — front wheel maxes out at ~10 km/h observed. No engine-driven front-wheel-active session exists (those are all rear-spin on the paddock stand with the front stationary).
- A live-bike capture that gets the front wheel above ~12.7 km/h is the cheapest discriminator. Decoding `((D3 << 8) | D4) × 0.046875` should track `wheel_speed_front` (D0:D1) one-to-one through and past the rollover.

Until that capture exists, **the encoding is confirmed on D4 only**; the multi-byte structure is a strong hypothesis but not yet observed.

## What this rules out

- **`12D` D4 is not throttle-derived, RPM-derived, or coolant-derived.** The corpus sweep tested all known references; only front wheel speed exceeded |r| = 0.9, and it did so at r ≈ 0.998 in two independent sessions.
- **D4 is not the same encoding as D2 (rear coarse mirror).** D2 wraps at 25.5 km/h with 0.1 km/h LSB; D4 has a different slope and shows no wrap signature in the observed range. Three wheel-speed scales on the same ID.
- **D4 is not a redundant copy of the wide D0:D1 12-bit field.** Different slope (3/64 vs 1/12) and different byte position. Independent broadcast, same input quantity.

## Status

**Provisional.** D4 encoding confirmed (r ≈ 0.9999, residual σ ≈ ½ LSB across two independent engine-off sessions). Multi-byte D3:D4 structure is the leading hypothesis but D3 itself remains observed-zero until a higher-speed front-wheel capture confirms rollover.

## Open

- **Confirm D3 high-byte behaviour.** First on-bike rolling capture above ~13 km/h on the front wheel will either confirm `((D3 << 8) | D4) × 0.046875` decoding or reveal a different overflow scheme (saturation at 0xFF, wraparound, separate counter).
- **Why three scales on one ID?** Different downstream consumers (canonical D0:D1 → speedo; D3:D4 → ?; D2 → coarse rear). Worth noting but doesn't block the dashboard MVP — only the canonical D0:D1 is needed for display.
- **Promote to `signals.yaml`** once D3 is confirmed.

## Evidence

- [[2026-06-24-front-wheel-hand-spin]] — engine-off, hand-spin pushes 2–10 km/h.
- [[2026-06-24-front-wheel-decay-mark]] — engine-off, hand-spin + decay tail.
- [[2026-06-30-unknown-byte-corpus-sweep]] — flagged the correlation and ran the encoding fit.
- [`scripts/id12d_d4_characterise.py`](../../../scripts/id12d_d4_characterise.py) — characterisation script (linear fit, slope candidates, wrap diagnostic).

See also: [[signal-wheel-speed-front]] (canonical D0:D1 12-bit field), [[signal-wheel-speed-rear]] (rear D5:D6 + D2 coarse mirror), [[byte-encoding-12-in-16]], [[always-on-broadcast-ids]].
