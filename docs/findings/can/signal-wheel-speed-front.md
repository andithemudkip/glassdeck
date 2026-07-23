---
area: can
status: provisional
established_by:
  - 2026-06-24-front-wheel-hand-spin
  - 2026-06-24-front-wheel-decay-mark
  - 2026-07-22-first-moving-ride
supersedes_claim:
  - "LSB 1/192 km/h/raw = 1/12 km/h on the 12-bit extract (was low-speed-corpus artifact)"
  - "full uint16 BE at ~1/162 km/h (my own intermediate rewrite on 2026-07-22 morning — undone once the D1 low-nibble semantics were understood)"
references:
  - ktm-can-decoder
---

# Front wheel speed — `12D` D0 + D1 high nibble (12-bit BE)

Front wheel speed on the 2020 Husqvarna Svartpilen 401 is broadcast in arbitration ID **`0x12D`** at **D0 (all 8 bits) + D1 high nibble (bits 7:4) as a 12-bit big-endian value**, LSB **~ 1/10 km/h per extracted 12-bit value** (equivalently ~ 1/160 km/h on the raw u16 (D0<<8)|D1). Working LSB anchored empirically at ~ 1/10.15 across the ride corpus; expected to snap to exactly 1/10 with a dash-verified moving procedure.

```python
speed_field_12bit = ((data[0] << 8) | (data[1] & 0xF0)) >> 4
front_wheel_kmh = speed_field_12bit / 10.0
# Equivalently on the raw u16:
front_wheel_kmh = ((data[0] << 8) | (data[1] & 0xF0)) / 160.0
```

**Do mask off the low 4 bits of D1** for wheel-speed decoding. The low nibble is a *separate* 4-bit field carrying a rear-wheel-speed-band indicator — see [[signal-12d-d1-bit0]] for the semantic. Reading D0:D1 as a plain uint16 (unmasked) rounds the wheel-speed reading incorrectly *and* mixes in the band signal.

Same arbitration ID as the rear wheel ([[signal-wheel-speed-rear]]), different bytes, different LSB — rear is ~ 0.0565 km/h/LSB on a full uint16, front is 1/10 km/h/LSB on a 12-bit field. A separate redundant front-wheel-speed **mirror** lives at D3:D4 on the same ID — see [[byte-12d-d3-d4-front-mirror]] (LSB re-fit needed given the LSB revision here).

## History of this finding

Three iterations to converge on the correct encoding:

1. **2026-06-24 (original, `confirmed`).** 12-bit-in-16-bit, LSB 1/12 km/h on the extracted value. Correct on the *structure* (12-bit BE in the high 12 bits, low nibble is a separate field) but wrong on the LSB — the "raw 1344 ⇔ dash 7" hand-spin fit was distinguishable only within dash-quantisation slop between 1/12 and 1/10.
2. **2026-07-22 morning rewrite (undone).** "Full uint16 BE at ~ 1/162 km/h/LSB." Wrong on the structure — I saw the D1 low nibble non-zero on 72-89 % of moving frames and concluded the whole u16 must be speed, missing that the low nibble is a band field with a clean speed-dependent value. Right coincidentally on the LSB, because ~ 1/162 on raw u16 ≈ ~ 1/10 on the 12-bit extract.
3. **2026-07-22 afternoon (this version, `provisional`).** Correct structure (original 12-bit split) + correct LSB (1/10, not 1/12). Verified by inspecting raw D0:D1 vs decoded rear across the ride corpus.

The lesson embedded here is worth preserving: **a low-nibble that appears active isn't proof that the encoding is a full uint16** — the low nibble can still be a separate field with a speed-correlated value. Distinguishable only by tabulating the low nibble against speed (as this finding now does).

## Evidence — LSB 1/10 on the 12-bit extract

Per-frame sample from `scripts/first_moving_ride_12d_d1_probe.py` across all 5 moving-ride files (first frame in each rear-speed bin where the bike was actually moving):

| Rear km/h (from D5:D6) | Raw D0:D1 u16 | 12-bit extract (raw >> 4) | Front km/h at LSB 1/10 |
|-----------------------:|--------------:|--------------------------:|-----------------------:|
| 5.0 | 960 | 60 | 6.0 |
| 10.1 | 1712 | 107 | 10.7 |
| 15.1 | 2448 | 153 | 15.3 |
| 20.1 | 3280 | 205 | 20.5 |
| 25.1 | 4097 | 256 | 25.6 |
| 30.0 | 4849 | 303 | 30.3 |
| 35.1 | 5633 | 352 | 35.2 |
| 40.2 | 6433 | 402 | 40.2 |
| 45.0 | 7281 | 455 | 45.5 |
| 50.3 | 8082 | 505 | 50.5 |
| 55.1 | 8898 | 556 | 55.6 |
| 60.1 | 9650 | 603 | 60.3 |
| 65.2 | 10402 | 650 | 65.0 |
| 70.3 | 11218 | 701 | 70.1 |
| 75.0 | 12035 | 752 | 75.2 |
| 80.2 | 12835 | 802 | 80.2 |
| 85.3 | 13795 | 862 | 86.2 |
| 90.1 | 14499 | 906 | 90.6 |
| 95.0 | 15171 | 948 | 94.8 |
| 100.1 | 16068 | 1004 | 100.4 |

Front decoded values are systematically ~ 0.3-1.0 km/h higher than concurrent rear decoded values across the range. That's roughly consistent with either (a) real rear tyre being slightly larger effective radius than front (making rear turn fewer rev/km) or (b) small residual mis-calibration on either LSB. Not big enough to distinguish a real physical difference from a rounding-slop artefact; both are consistent with LSB = 1/10 on front.

Cross-check with the corpus's binary-friendly-LSB expectation: rear best-fit is ~ 0.0565 km/h, not a clean fraction; front best-fit is 1/10 = 0.1, a clean decimal. The two channels *don't* share a clean-fraction style, so the Bosch-uses-binary-fractions argument from the original finding was wrong. Bosch mixed decimal and non-decimal on the same ID.

## Front/rear ratio — corrected reading of the constant

The `first_moving_ride.py` analysis reported a rock-solid front/rear ratio of 0.762 across the whole speed range. That was under old-LSBs (front 1/192, rear 1/16). Under corrected LSBs (front 1/10, rear ~ 0.0565):

- decoded_front / decoded_rear = (raw_front_12bit / 10) / (raw_rear_u16 * 0.0565)
- Empirically raw_front_12bit / raw_rear_u16 ≈ 9.144 / 16 = 0.572 (I was previously dividing by u16 not by the 12-bit extract; the extract divides raw u16 by 16, hence /16)
- decoded ratio = 0.572 / (10 * 0.0565) = 0.572 / 0.565 ≈ 1.01 ✓

Both channels agree on decoded km/h to ~ 1 % once the encoding and LSBs are right. That's the sanity check the previous rewrite couldn't produce.

## ECU low-end broadcast floor still holds

[[2026-06-24-front-wheel-decay-mark]] pinned the ECU broadcast floor at raw 448 = 0x01C0 (D0=0x01, D1=0xC0). At LSB 1/10 on the 12-bit extract, `448 >> 4 = 28`, decoded = 2.8 km/h. So the ECU stops broadcasting non-zero front-wheel speed below ~ 2.8 km/h — consistent with the rider's decay-session observation that "dash briefly displays 2, never 1" (dash-2 band is [1.5, 2.5), and the ECU floor at 2.8 km/h leaves only a brief flash inside the dash-2 window before the ECU snaps to 0).

## Front and rear use different LSBs (intentional)

Rear D5:D6 is a full uint16 at ~ 0.0565 km/h/LSB. Front D0:D1 top 12 bits at 1/10 km/h/LSB.

| | Rear D5:D6 | Front D0:D1[15:4] |
|---|-----------|-------------------|
| LSB | ≈ 0.0565 km/h | 0.1 km/h (= 1/10) |
| Effective bits | full uint16 | 12-bit |
| Max representable | ~ 3700 km/h | 409.5 km/h |
| Coarse mirror on same ID | D2 at 0.1 km/h | D3:D4 at (LSB pending, see [[byte-12d-d3-d4-front-mirror]]) |
| ECU floor | not observed | raw 448 = 2.8 km/h |
| Auxiliary field in the slot | none | D1 low nibble = rear-speed band ([[signal-12d-d1-bit0]]) |

Front's ~ 10× coarser LSB probably reflects the ABS module's use of front-wheel signal for slip detection — 0.1 km/h resolution across 0-410 km/h is enough for that. Rear is finer because the engine-side logic (auto-headlight threshold, ignition maps) benefits from tighter resolution at lower speeds.

## Cross-walk vs KTM

KTM's ktm-can decoder places front wheel speed at `12B` D0:D1 BE uint16 on the 2020 KTM 690 Enduro R. On the Svartpilen 401:

- **ID relocated** `12B` → `12D`.
- **Byte position preserved exactly** — front wheel in D0 + D1 high bits.
- **12-bit-in-16-bit packing preserved from KTM likely.** KTM decoder documents "uint16" but doesn't call out whether the low nibble is used — worth cross-checking against KTM 690 data if it exists.
- **LSB scale differs** from what KTM's decoder documented. Not unusual; Bosch variants differ per-model.

## Evidence

- [[2026-06-24-front-wheel-hand-spin]] — engine-off, hand-spin 2-10 km/h; original 12-bit structure identification.
- [[2026-06-24-front-wheel-decay-mark]] — ECU floor at raw 448.
- [[2026-07-22-first-moving-ride]] — real-motion corpus that revealed the D1 low-nibble is a rear-speed-band field (not part of the wheel-speed encoding, not just noise) and pinned the LSB at 1/10 km/h.
- [`scripts/first_moving_ride_12d_d1_probe.py`](../../../scripts/first_moving_ride_12d_d1_probe.py) — the per-speed-band raw-value dump that revealed the encoding.

## Open

- **Absolute LSB — 1/10 exactly, or close?** Empirical best-fit lands 1/10.11 to 1/10.20. Most likely 1/10 exactly with a small residual front-tyre-diameter-vs-rear calibration offset baked into the ratio-of-decodes. The dash-verified moving procedure will pin it to ~ 0.3 % using multiple steady-state holds; until then treat "front km/h = 12-bit extract / 10" as the working formula and note ± 1 % uncertainty.
- **Whether the low nibble of D1 is derived from rear speed or vehicle speed or something else.** See [[signal-12d-d1-bit0]] — the finding's own Open questions cover this.
- **D3:D4 mirror LSB re-fit** — [[byte-12d-d3-d4-front-mirror]] had its 3/64 LSB fit against the old canonical decode; needs re-fitting against 1/10.

See also: [[signal-wheel-speed-rear]], [[byte-12d-d3-d4-front-mirror]], [[signal-12d-d1-bit0]], [[always-on-broadcast-ids]], [[ktm-can-decoder]], [[dash-warning-lights]].
