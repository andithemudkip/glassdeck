---
area: can
status: provisional
established_by:
  - 2026-06-23-engine-driven-rear-spin
  - 2026-06-17-engine-idle-baseline-x3
  - 2026-06-24-front-wheel-hand-spin
  - 2026-06-24-front-wheel-decay-mark
  - 2026-07-22-first-moving-ride
supersedes_claim:
  - "D1 bit 0 is a rear-wheel-speed threshold flag firing at ~ 27 km/h"
---

# `12D` D1 low nibble — 4-bit rear-wheel-speed band (25 km/h steps)

The low 4 bits of `12D` D1 form a **rear-wheel-speed band indicator**: an unsigned integer equal to **floor(rear_wheel_kmh / 25)**. The 25 km/h step size is what generated the original single-bit "flag at ~ 27 km/h" observation — that was really bit 0 of this 4-bit field flipping at the band-0-to-band-1 boundary (25 km/h), with the "27 km/h" figure being a slightly noisy read of the rear speed at the flip moment.

```python
rear_speed_band = data[1] & 0x0F   # 0..15, each unit = 25 km/h of rear speed
# Rough bands, with rear speed measured via 12D D5:D6 * 0.0565 (signal-wheel-speed-rear):
#   band 0: rear  0-25   km/h
#   band 1: rear 25-50   km/h
#   band 2: rear 50-75   km/h
#   band 3: rear 75-100  km/h
#   band 4: rear 100-125 km/h  (peak observed 108 km/h → band 4)
```

The high 4 bits of D1 (bits 7:4) belong to the front-wheel-speed slot — see [[signal-wheel-speed-front]]. Decoders must mask `D1 & 0xF0` for wheel-speed and `D1 & 0x0F` for band, and never treat the whole u16 (D0:D1) as one integer.

## Evidence — 5-file moving-ride corpus with rear speed 0-108 km/h

`scripts/first_moving_ride_12d_d1_bit0.py` bins every 12D frame by rear speed (5 km/h bins) and reports P(D1 bit 0 = 1) per bin, across all 5 captures combined:

| Rear km/h bin | n | P(D1 bit 0 = 1) | Predicted band | Predicted bit 0 |
|---------------|---:|----------------:|:--------------:|:---------------:|
|  0-5  | 33321 | 0.000 | 0 | 0 ✓ |
|  5-10 |  2683 | 0.000 | 0 | 0 ✓ |
| 10-15 |  3050 | 0.000 | 0 | 0 ✓ |
| 15-20 |  2448 | 0.000 | 0 | 0 ✓ |
| 20-25 |  2565 | 0.062 | 0→1 (transition) | 0/1 ✓ (band changes inside bin) |
| 25-30 |  1547 | 1.000 | 1 | 1 ✓ |
| 30-35 |  1540 | 1.000 | 1 | 1 ✓ |
| 35-40 |  1231 | 1.000 | 1 | 1 ✓ |
| 40-45 |  2345 | 1.000 | 1 | 1 ✓ |
| 45-50 |  2719 | 0.990 | 1→2 (transition) | 1/0 ✓ |
| 50-55 |  4722 | 0.000 | 2 | 0 ✓ |
| 55-60 |  6811 | 0.000 | 2 | 0 ✓ |
| 60-65 |  6603 | 0.000 | 2 | 0 ✓ |
| 65-70 |  3434 | 0.000 | 2 | 0 ✓ |
| 70-75 |  2508 | 0.000 | 2 | 0 ✓ |
| 75-80 |  2911 | 1.000 | 3 | 1 ✓ |
| 80-85 |  3291 | 1.000 | 3 | 1 ✓ |
| 85-90 |  4984 | 1.000 | 3 | 1 ✓ |
| 90-95 |  3075 | 1.000 | 3 | 1 ✓ |
| 95-100 |  919 | 0.979 | 3→4 (transition) | 1/0 ✓ |
| 100-105 |  120 | 0.000 | 4 | 0 ✓ |

Bit 0 exactly matches `floor(rear_kmh / 25) & 1` in every settled bin; the transition bins land exactly where the 25 km/h boundaries do (with a modest overshoot in the 20-25 bin because rear tyre calibration gives a couple percent of speed error near the boundary). Bit 1 (the next bit of the band) sets first at rear = 50 km/h; bit 2 first at rear = 100 km/h — both verified by inspecting D1's full byte value across the sample set:

| Rear km/h | Typical D1 (hex) | Low nibble | Low nibble binary |
|-----------|:----------------:|:----------:|:-----------------:|
|  10       | 0xB0             | 0          | 0000 |
|  25       | 0x01, 0x11       | 1          | 0001 |
|  50       | 0x92, 0x72, 0xA2 | 2          | 0010 |
|  75       | 0x03, 0x13       | 3          | 0011 |
| 100       | 0xC4, 0x34, 0x54 | 4          | 0100 |

Band 4 is the highest observed; the 4-bit field caps at 15 (= 375 km/h), well above anything this bike will produce.

## How the original "27 km/h flag" observation reconciles

[[2026-06-23-engine-driven-rear-spin]] was engine-driven with the front wheel stationary throughout. In that data:

- The high 12 bits of D0:D1 (front wheel speed) stayed at 0.
- The low nibble of D1 tracked rear-wheel-speed band, exactly as this finding now claims.
- Bit 0 of the low nibble flipped when rear crossed 25 km/h (± 2 km/h calibration slop — hence the "~ 27 km/h" number). Bits 1-3 never fired because the session peaked at 30 km/h rear.

The original "flag" language was a per-bit reading of a multi-bit field. Bit 0 alone looked like a threshold flag because we only exercised the band-0/band-1 boundary and never got high enough to see bit 1 fire independently.

## Consumer perspective

The band field is derivable from `wheel_speed_rear` — it's redundant. A dashboard replacement should read [[signal-wheel-speed-rear]] directly and ignore the band field (or use it as a consistency check). The field's likely internal purpose is to trigger downstream ECU state machines (traction, ABS, sound-control) at fixed speed thresholds without those modules having to duplicate the wheel-speed decode logic. It's a hint at what internal speed regimes matter to the platform's ECU cluster: 25, 50, 75, 100 km/h boundaries.

## Open

- **Rear vs vehicle speed driver.** In every capture in the current corpus, rear ≈ front (motion) or rear ≈ 0 (stationary front) — the band always matches rear-derived floor. If the ECU derived it from front, we'd see the same. Distinguishing rear-derived from front-derived (or max-of-both) needs a capture where front and rear speeds diverge significantly — e.g. wheel-spin on gravel, or a paddock-stand engine-driven-rear-spin with front on the front stand (same conditions as the 2026-06-23 session).
- **Bits 1-3 semantics vs the whole low nibble.** This finding treats bits 0-3 as a 4-bit unsigned integer. That's the simplest model; an alternative is that bits 0-3 are 4 independent threshold flags at 25/50/75/100 km/h. The two models are behaviorally indistinguishable up to the tested range because integer count and one-hot-below-threshold produce the same bit patterns for the specific bands 0-4. Only a capture where band > 4 (rear speed > 100 km/h to band 5+) would exercise the model — band 5 as an integer is 0b0101 (bit0=1, bit1=0, bit2=1), while an independent-flag interpretation would probably use a different bit for that regime. Peak observed here is 108 km/h (band 4); a future 125+ km/h capture pins it.
- **Bit 3 first activation.** Band 3 (75 km/h) is the highest currently exercised. Band 8 (200 km/h) would flip bit 3 for the first time in an integer interpretation — moot for this bike but a KTM 690 with a higher top speed might.

## Evidence

- [[2026-06-23-engine-driven-rear-spin]] — established the band-0-to-band-1 boundary at ~ 27 km/h (original single-bit reading).
- [[2026-07-22-first-moving-ride]] — established the multi-bit band structure and pinned the 25 km/h step size; refuted the single-bit-flag interpretation.
- [`scripts/id12d_d1_bit0_duty.py`](../../../scripts/id12d_d1_bit0_duty.py) — original single-bit duty analysis (still valid for the engine-driven-rear-spin regime).
- [`scripts/first_moving_ride_12d_d1_bit0.py`](../../../scripts/first_moving_ride_12d_d1_bit0.py) — moving-ride corpus P(bit 0) per rear speed bin.
- [`scripts/first_moving_ride_12d_d1_probe.py`](../../../scripts/first_moving_ride_12d_d1_probe.py) — full raw-value dump per bin that revealed the low-nibble structure.

## Notes

Surfaced by a raw-value inspection while investigating a puzzling P(D1 bit 0 = 1) result across the moving-ride corpus. The single-bit finding predicted P monotonically low below 27 km/h and monotonically 1 above. The moving-ride data instead showed alternating bands — which forced looking at bits 1, 2, 3 and eventually the whole low nibble, at which point the 4-bit integer structure became obvious.

See also: [[signal-wheel-speed-front]] (D0 + D1 high nibble carries the front wheel speed; masking rules), [[signal-wheel-speed-rear]] (D5:D6 is the source of truth for rear speed, which drives this band), [[byte-encoding-12-in-16]] (broader pattern note).
