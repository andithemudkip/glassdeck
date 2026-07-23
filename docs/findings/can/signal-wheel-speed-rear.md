---
area: can
status: confirmed
established_by:
  - 2026-06-22-wheel-spin-paddock-stand
  - 2026-06-23-engine-driven-rear-spin
  - 2026-06-24-front-wheel-hand-spin
  - 2026-07-22-first-moving-ride
references:
  - ktm-can-decoder
---

# Rear wheel speed — `12D` D5:D6 (primary uint16) + D2 (coarse mirror)

Rear wheel speed on the 2020 Husqvarna Svartpilen 401 is broadcast in arbitration ID **`0x12D`** at two locations, both tracking the same physical quantity at different scales:

| Bytes | Encoding | Scale | Behaviour |
|------:|----------|-------|-----------|
| **D5:D6** | big-endian uint16 (D5 = high, D6 = low) | **≈ 0.0565 km/h per LSB** (= 1/17.7) | Primary signal. Full range, clean. |
| **D2**    | uint8 alone (D3 is **not** a high byte) | **≈ 1/10 km/h per LSB** | Coarse mirror. **Wraps modulo 256 above ~25.5 km/h.** |
| D3        | STATIC `0x00`                            | —     | Not a high byte for D2. Refuted by engine-driven sweep where D2 wrapped through 0x00..0xFF while D3 stayed at 0x00. |

```python
rear_wheel_kmh = ((data[5] << 8) | data[6]) * 0.0565     # primary; ±1% (see LSB section)
rear_wheel_kmh_coarse = data[2] / 10.0                   # only valid below ~25.5 km/h
```

D5:D6 has full speed range and clean integer behaviour. Use it as the source of truth. D2 is useful as a sanity check at low speed but should not be relied on alone.

**LSB note.** Two independent measurements converge on ~ 0.0563–0.0565 km/h/LSB (not the round 1/16 = 0.0625 previously assumed): the engine-driven best-fit against RPM × gearing predicted speed ([[2026-06-23-engine-driven-rear-spin]]) landed on 0.05633, and cross-checks against rider-observed dash values on the first moving ride ([[2026-07-22-first-moving-ride]]) landed on 0.05649 (dash-101 peak) and 0.05682 (dash-60 steady). Working value 0.0565; final ±1 % anchor pending a dash-verified moving procedure.

## Evidence — engine-driven sweep ([[2026-06-23-engine-driven-rear-spin]])

7 steady-state setpoints in 1st gear, ~8 s analysis window per setpoint, with RPM read from `120` D0:D1 frame-by-frame:

| Setpoint | RPM μ | D5:D6 BE (μ raw) | km/h @ 1/16 LSB | D2 μ | D3 | D5 |
|----------|------:|------------------:|----------------:|-----:|---:|---:|
| Idle in 1st (Phase A) | 1706 | 161.8 | 10.11 | 100.5 | 0x00 | 0x00 |
| B1 ~2000 RPM | 1975 | 186.6 | 11.66 | 115.6 | 0x00 | 0x00 (rare 0x01) |
| B2 ~2500 RPM | 2131 | 207.9 | 13.00 | 124.1 | 0x00 | 0x00 (rare 0x01) |
| B3 ~3500 RPM | 3017 | 290.8 | 18.18 | 171.6 | 0x00 | **0x01** ← D5 emerges |
| B4 ~4500 RPM | 3944 | 377.1 | 23.57 | 221.9 | 0x00 | 0x01 |
| B5 ~5500 RPM | 4966 | 474.3 | 29.64 | wraps | 0x00 | **0x01..0x02** |
| Idle (Phase C, post-sweep) | 1698 | 161.8 | 10.11 | 100.5 | 0x00 | 0x00 |

Linear regression km/h = a·raw + b over all 7 setpoints (predicted km/h from RPM × known gearing as the ground truth):

| Candidate decode | Slope (km/h/LSB) | Intercept | RMS residual |
|------------------|-----------------:|----------:|-------------:|
| **D5:D6 BE**     | **0.05633**      | **+0.071** | **0.019**    |
| D2 alone         | -0.0059          | +15.7     | 6.3 (wraps)  |
| D2:D3 LE         | -0.0059          | +15.7     | 6.3 (D3 = 0) |
| D5:D6 LE         | -6e-5            | +17.3     | 6.3          |

D5:D6 BE wins by orders of magnitude. The slope **0.05633** is within ~10% of the binary-friendly **0.0625 km/h/LSB (= 1/16)**; the gap is attributable to back-of-envelope gearing/tyre numbers and resolves once a road capture or authoritative gearing source pins the unit. Until then, **encoding = uint16 BE, scale = ~1/16 km/h** is the best-fit and lossless interpretation.

### Why D2 mirrors D5:D6

At setpoints where neither byte wraps (Phase A idle, B1), the **D6/D2 ratio is 1.610 and 1.614** — matching the 16/10 = 1.6 scaling-ratio prediction within noise. Both bytes report the same physical quantity at different resolutions:

- D2 = km/h × 10 (uint8, wraps at 25.5 km/h, no companion high byte)
- D5:D6 = km/h × 16 (uint16, clean to at least ~31 km/h, more above)

The three working hypotheses in the previous version (filtered-vs-raw, different scaling laws, ABS-vs-tone-ring) were all too clever. Outcome: **same quantity, different scales** — the simplest explanation. The decay-tail ratio difference observed in the hand-spin session (~1.17× at low decoded values) was almost certainly noise dominating the small denominators, not a real speed-dependent shape.

**D2 mirrors *only* the rear, not "whichever wheel is moving".** The front-only hand-spin ([[2026-06-24-front-wheel-hand-spin]]) drove the front wheel to ~11 km/h while D2 stayed at `0x00` across all 9 push windows. D2 is a rear-channel artifact tied to D5:D6 specifically, not a general coarse-speed mirror within `12D`.

### High-byte ceiling tests (clean falsification)

- **D6 ceiling (16 km/h):** D5 emerged as `0x01` at B3 (3500 RPM, decoded 18.18 km/h) and stayed at `0x01` through B4, then jumped to `0x02` at B5 (29.64 km/h, second wrap). Behaviour exactly matches a uint16 BE encoding.
- **D2 ceiling (25.5 km/h):** D2 wrapped through the full `0x00..0xFF` range at B5 while **D3 stayed at `0x00`**. The "D2:D3 = uint16" hypothesis is cleanly refuted. D2 is a standalone uint8.

## Why the OEM speedometer reads 0 during a rear-only spin

D5:D6 and D2 both responded to the rear-only spin; the dashboard speedometer stayed at 0 km/h regardless, and the **ABS warning lamp stayed lit throughout** (independently confirmed in the [[2026-06-23-engine-driven-rear-spin]] session — ABS normally extinguishes at ~6 km/h per [[dash-warning-lights]], but that threshold reads the front wheel, which never moved). Consistent split:

- **Rear-wheel readers** (auto-headlight, possibly some traction logic) responded to the spin via these bytes.
- **Front-wheel readers** (OEM speedo, ABS-lamp-extinguish logic) all stayed at zero, because the front sensor was static.
- **Front-wheel byte location confirmed at `12D` D0..D1 BE uint16** by [[2026-06-24-front-wheel-hand-spin]] — see [[signal-wheel-speed-front]]. Front and rear share the same arbitration ID but use different bytes and **different LSB scales** (front ~1/190 km/h, rear ~1/16 km/h); the front fit does **not** close the rear's "Exact LSB" open question below.

## Cross-walk vs KTM

KTM's ktm-can decoder ([reference](../../references/ktm-can-decoder.md)) places wheel speeds on the 2020 KTM 690 Enduro R at `12B` D0..D3 (front uint16 BE, then rear uint16 BE). On the Svartpilen 401:

- **ID relocated** `12B` → `12D` (same 10 ms period, different arbitration ID).
- **Rear wheel byte position changed: KTM D2:D3 BE → Husqvarna D5:D6 BE.** The byte pair moved, the encoding (BE uint16) and the position-within-payload pattern (high-byte first) are preserved.
- **D0..D1 = front-wheel BE uint16, confirmed** ([[signal-wheel-speed-front]]). Byte position preserved exactly from KTM's layout; LSB scale differs from rear (~1/190 vs ~1/16 km/h).
- **D2 is a Husqvarna addition** — KTM has rear wheel speed there but as the high byte of a uint16; Husqvarna repurposes D2 as a standalone coarse mirror of the rear wheel speed at 0.1 km/h scale. The Bosch ECU is reusing the byte position for a related but distinct purpose.
- **D5..D6 was KTM's tilt/lean.** The 2020 Svartpilen 401 has no lean sensor, freeing those bytes — Husqvarna repurposed them for the primary wheel-speed uint16. This is a clean lean-slot-for-wheel-slot swap, with the same encoding family (BE uint16) preserved.
- **D7** is the universal cross-ID 6-cycle byte ([[byte-d7-cycle-hash]]) — not data — same as on KTM.

Refines the earlier "D0..D3 preserved, D4..D7 differs" hypothesis: Husqvarna kept KTM's D0..D1 (front) and replaced D2..D3 (KTM's rear) with a D2-coarse + D5..D6-primary split, freed by the missing lean sensor.

## Evidence

- [[2026-06-22-wheel-spin-paddock-stand]] — initial location of D2 and D6 as motion-responsive bytes (hand-spin, no steady-state).
- [[2026-06-23-engine-driven-rear-spin]] — promoted to `confirmed`: steady-state speeds via RPM × gearing pinned the encoding (D5:D6 BE uint16 ≈ 1/16 km/h), refuted D2:D3 as a uint16, and resolved the D2/D6 dual-byte question as same-quantity-different-scales.
- [`scripts/engine_driven_rear_spin.py`](../../../scripts/engine_driven_rear_spin.py) — per-setpoint analysis, regression, ratio table.
- [`scripts/wheel_spin_scan.py`](../../../scripts/wheel_spin_scan.py) — per-push analysis from the earlier hand-spin session.

## Open

- ~~**Exact LSB.**~~ Converged on ~ 0.0565 km/h/LSB across three independent measurements (engine-driven best-fit 0.05633; dash-101 endpoint 0.05649; dash-60 steady 0.05682, per [[2026-07-22-first-moving-ride]]). Final anchor to ±1 % pending the dash-verified moving procedure (rider holds ~ 20/40/60/80/100 km/h with in-procedure marks). Previously suspected clean 1/16 = 0.0625 is refuted by all three anchors. The finding's Bosch-clean-fraction argument was already circular — [[signal-wheel-speed-front]]'s "clean fraction 1/192" was also incorrect (see that finding's 2026-07-22 rewrite), so the analogy doesn't apply.
- ~~**Front wheel speed location.**~~ Closed by [[2026-06-24-front-wheel-hand-spin]] — see [[signal-wheel-speed-front]].
- **D4 STATIC `0x00`.** Unused in everything observed so far; possibly reserved for a third signal (e.g. estimated vehicle speed combining both wheels). [[2026-07-22-first-moving-ride]] gets rear speeds above 100 km/h without D4 changing, so it's not simply a high-byte for a wider counter.
- ~~**Does the rear also use 12-bit-in-16-bit packing?**~~ The 12-bit-in-16-bit claim for **front** turned out to be an engine-off corpus artifact (see [[signal-wheel-speed-front]] 2026-07-22 rewrite). This open question is moot — rear is full uint16 BE, front is also full uint16 BE, both are just linear speed encodings at different LSBs. Confirmed by [[2026-07-22-first-moving-ride]]: rear D6 low nibble is non-zero on 93.3–93.9 % of moving frames across all five files, consistent with a straightforward u16 with no low-bit-reserved segmentation.
- **High-speed wrap behaviour.** D5:D6 BE handles wraps cleanly through 110 km/h in [[2026-07-22-first-moving-ride]] (raw ~1961 = 0x07A9); the uint16 max at the new LSB is ~ 3700 km/h, far beyond anything this bike will see. D2 wraps every 25.5 km/h forever — a confirmed quirk, no follow-up needed.

See also: [[always-on-broadcast-ids]], [[ktm-can-decoder]], [[signal-side-stand]] (contrast with the `540` -1-byte shift pattern — `12D` doesn't shift, it swaps roles within the payload).
