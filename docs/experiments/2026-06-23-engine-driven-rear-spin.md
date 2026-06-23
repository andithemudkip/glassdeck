---
date: 2026-06-23
status: success
phase: 1
related:
  findings:
    - can/signal-wheel-speed-rear
    - can/signal-rpm
    - can/always-on-broadcast-ids
  references:
    - ktm-can-decoder
  experiments:
    - 2026-06-22-wheel-spin-paddock-stand
    - 2026-06-23-first-bike-roll
  logs:
    - 2026-06-23-engine-driven-rear-spin
---

# Engine-driven rear spin on paddock stand — steady-state speeds + scaling via RPM-anchored ground truth

## Hypothesis

Three things, all unlocked by **driving the rear wheel through the gearbox under controlled throttle** instead of hand-spinning it:

1. **`12D` D3 and D5 are the high bytes of two uint16s, currently STATIC `0x00` only because hand-spin never exceeded their single-byte ceilings.** Under the working units hypothesis (D2:D3 = little-endian uint16 in 0.1 km/h, D5:D6 = little-endian uint16 in 1/16 km/h — see [[signal-wheel-speed-rear]]), the single-byte ceilings are ~25.5 km/h for D2 alone and ~16 km/h for D6 alone. Any sustained throttle above those values forces D3 / D5 to start incrementing. If D3 stays at `0x00` while D2 saturates at `0xFF`, the encoding is something else and the finding needs a rewrite.

2. **D2 and D6 disambiguate at steady-state.** The current finding logs three working models for why two bytes encode the same wheel (filtered-vs-raw, different scaling laws, ABS-estimate-vs-tone-ring-count). All three predict different things at a **sustained constant speed**, which hand-spin can't produce. Specifically:
   - **Filtered-vs-raw**: at steady-state the filter catches up, so D6/D2 ratio should converge to a constant (likely matching the decay-tail ratio of ~1.17×). Transient lag disappears.
   - **Different scaling laws**: ratio stays speed-dependent even at steady-state.
   - **ABS-estimate-vs-tone-ring-count**: D6 should be integer-stepwise (counts per CAN cycle) while D2 is smooth — visible in the per-frame trace at constant throttle.

3. **Byte-to-km/h scaling, anchored to RPM × known gearing.** Engine RPM is already decoded ([[signal-rpm]] at `120` D0..D1). With known transmission ratios + final drive + wheel circumference, RPM → wheel km/h is a direct calculation. Holding several throttle setpoints in 1st gear gives multiple (RPM, D2, D3, D5, D6) tuples to regress against. **This pins the scale without rolling the bike** — and at higher speeds than [[2026-06-23-first-bike-roll]] can reach.

Together, this resolves the three open questions in [[signal-wheel-speed-rear]] (scaling, D2-vs-D6, D3/D5 encoding) for the rear wheel, leaving only front-wheel attribution open. The bike-roll capture [[2026-06-23-first-bike-roll]] complements this one: bike-roll covers the front wheel and gives an OEM-speedo cross-check at low speed; this one covers steady-state and the high-byte regime that bike-roll's walking-pace speeds can't reach.

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. **Engine ON.** Rear paddock stand (load-rated for the rear axle under torque — most aftermarket spool stands qualify). Front wheel parked straight, bike strapped or held if the stand is borderline.
- Side stand up, kill switch RUN, key on, **1st gear** (low gear-per-RPM ratio = finer resolution and slower speed creep; safer if the throttle is bumped).
- Adapter / firmware / host as before.
- **No hand near the chain or rear sprocket at any time.** Throttle from the right grip; left hand off the bike entirely during throttle holds.

## Safety + practical concerns

- **ABS fault is expected.** Rear sensor sees motion, front sensor sees zero — the ABS module will almost certainly throw a fault and illuminate the ABS warning lamp. Not damaging, clears on the next normal ride (or a code reset). Likely visible on the bus as new traffic and/or degraded broadcasts; log anything unusual in `session.md`.
- **Engine cooling.** No airflow over the radiator. Sweep through setpoints quickly (~10 s per hold, with rests at idle between) rather than holding at high RPM. Watch coolant temp via the dash and abort if it approaches the fan-on threshold.
- **Chain pinch hazard.** Standard rear-stand-with-engine-running caveat. Sleeves rolled, nothing dangling. Both hands accounted for at all times.
- **Stand stability.** Bike strapped or braced. A sudden chuck of the chain (especially at clutch engagement) can shift the bike if the stand isn't fully seated.

## Procedure

> **Scripted** — driven by [`2026-06-23-engine-driven-rear-spin.procedure.yaml`](2026-06-23-engine-driven-rear-spin.procedure.yaml). Auto-marks fire at the start of each throttle hold (the rider's "begin holding now" cue). All holds are short (~10 s); rests at idle are longer to let the engine cool.

The session sweeps several throttle setpoints in 1st gear, each held steady long enough to read a stable byte value. Setpoints are chosen to:
- Cross D2's predicted single-byte ceiling (25.5 km/h ≈ ~2500 RPM in 1st on this gearing, ballpark).
- Cross D6's predicted single-byte ceiling (16 km/h ≈ ~1700–1800 RPM in 1st).
- Provide multiple anchor points for the linear regression D2 → km/h.

1. Pre-engine baseline (key on, no engine, 30 s) — gives a baseline for the new bytes that may light up under engine-on.
2. Engine start, idle settle 30 s.
3. **Clutch in, shift to 1st**, clutch *slowly* out — let the wheel start spinning at idle.
4. **Idle-in-gear hold** ~15 s. Rear wheel spinning at idle RPM through 1st gear — first data point for the regression.
5. **Throttle setpoint sweep** — 4–5 RPM levels above idle, each held 10–12 s, with a return-to-idle rest of ~8 s between holds.
6. **Clutch in, neutral**, return to idle, kill switch, key off, tail silence.

## Analysis plan

1. **Sanity: rear wheel motion bytes vary as expected.** `12D` D2 and D6 should ramp with throttle. Cross-validate against [[signal-wheel-speed-rear]]: same byte positions, similar envelope shape (now extended and held steady rather than decay-only).

2. **High-byte emergence.** Per setpoint, what do D3 and D5 read?
   - **D3 = 0 across all setpoints AND D2 saturates at 0xFF** → uint16 hypothesis wrong, encoding rewrite needed.
   - **D3 increments as D2 wraps past 0xFF** → uint16 confirmed, endianness deducible from the wrap direction.
   - **D3 reads consistent value when D2 saturates** → mid-confidence uint16, but endianness less clean.
   - Same logic for D5 / D6.

3. **Endianness check.** With known RPM → expected raw value, compare the byte values against both big-endian and little-endian decodes. The one that matches the predicted km/h wins. Specifically: at e.g. 30 km/h with 0.1 km/h scale, raw = 300 = 0x012C. LE: D2=0x2C, D3=0x01. BE: D2=0x01, D3=0x2C. Pick whichever the bytes actually show.

4. **D2 vs D6 at steady-state.** Per setpoint, compute mean and std-dev of D6/D2 ratio over the held window:
   - **Ratio constant across setpoints + within tight std-dev** → same quantity, different scales. Likely 0.1 vs 1/16 km/h, ratio = 1.6.
   - **Ratio varies between setpoints (smoothly with speed)** → different quantities, e.g. one linear in km/h and one with an additive offset.
   - **D6 stair-steps (integer-valued at each step) while D2 is smooth** → D6 is the raw tone-ring count, D2 is the ABS estimate.

5. **Byte-to-km/h regression.** For each setpoint, compute predicted wheel km/h from RPM × gearing × wheel circumference. Fit linear regression `km/h ≈ a × raw_value + b` for each candidate (D2, D6, D2:D3-LE-uint16, D5:D6-LE-uint16). Expected: clean linear fit, intercept ~0, slope = the encoded LSB. The slope numerically pins the units (0.1 km/h vs 1/16 km/h vs something else entirely).

6. **ABS warning lamp + any new always-on IDs.** Diff the always-on ID set against [[always-on-broadcast-ids]] — any new IDs that appear when the ABS module faults are themselves a useful surface area to explore later.

7. **Auto-headlight side observation.** Rear-only spin trips the auto-headlight (established in [[2026-06-22-wheel-spin-paddock-stand]]). With sustained spin at known speed, log whether the headlight stays on through the full hold (expected) and at what setpoint it first comes on. Per-frame bit scan against engine-on baseline can re-attempt the headlight-bit hunt with much cleaner ON/OFF windows than hand-pushing could give.

## Gearing — KTM 390 platform (matches Husqvarna Svartpilen 401)

Sourced from the KTM Duke 390 factory spec; this bike shares the same drivetrain.

- **Primary reduction:** 80 / 30 = **2.667**
- **1st gear:** 32 / 12 = **2.667**
- **Final drive:** 45 / 15 = **3.000**
- **Total reduction in 1st:** 2.667 × 2.667 × 3.000 = **21.33**

Rear tyre 150/60ZR17 → outer diameter ~611.8 mm → circumference ~1.922 m. So wheel speed = `(engine_RPM / 21.33) × 1.922 m × 60 / 1000` km/h.

| Engine RPM | Wheel km/h | Predicted D2 raw (0.1 km/h) | D3 | Predicted D6 raw (1/16 km/h) | D5 |
|-----------:|-----------:|----------------------------:|---:|-----------------------------:|---:|
| 1700 (idle) | 9.2  | 92 (0x5C)  | 0x00 | 147 (0x93)               | 0x00 |
| 2000        | 10.8 | 108 (0x6C) | 0x00 | 173 (0xAD)               | 0x00 |
| 2500        | 13.5 | 135 (0x87) | 0x00 | 216 (0xD8)               | 0x00 |
| 3500        | 18.9 | 189 (0xBD) | 0x00 | 302 → low 46 (0x2E)      | **0x01** ← D5 emerges |
| 4500        | 24.3 | 243 (0xF3) | 0x00 | 389 → low 133 (0x85)     | 0x01 |
| 5500        | 29.7 | 297 → low 41 (0x29) | **0x01** ← D3 emerges | 475 → low 219 (0xDB) | 0x01 |

(LE-uint16 decode shown; if it's big-endian, the high and low bytes swap and the predictions are mirror images.)

The 5-setpoint sweep in 1st gear lands neatly:
- **2000 + 2500** — both below all ceilings, pure single-byte regime, two clean low-speed regression points for both D2 and D6.
- **3500** — first setpoint past D6's predicted ceiling (16 km/h). D5 should jump to `0x01`. Cleanest single test of D6's high-byte hypothesis.
- **4500** — D5 stays at `0x01`, D6 continues incrementing in its new wrap. D2 still single-byte.
- **5500** — first setpoint past D2's predicted ceiling (25.5 km/h). D3 should jump to `0x01`. Cleanest single test of D2's high-byte hypothesis.

If either high-byte jump fails to appear at the predicted setpoint, the corresponding encoding hypothesis is refuted and a rewrite is required — clean refutation, not ambiguity.

**Plan B (add 2nd gear) is not needed for this experiment** — 1st gear at 5500 RPM is already 30 km/h, well past the highest predicted byte ceiling. A 2nd-gear follow-up only becomes relevant if we want to chase wrap-around behaviour at much higher speeds, in which case the mobile rig + real road capture is the more honest evidence anyway.

## Result

Captured 2026-06-23 evening — 118 416 frames, 5 min 2 s, [`logs/2026-06-23-engine-driven-rear-spin`](../../logs/2026-06-23-engine-driven-rear-spin/). Procedure executed cleanly; rider held each setpoint for ~12 s with normal drift. Analysis: [`scripts/engine_driven_rear_spin.py`](../../scripts/engine_driven_rear_spin.py).

### Per-setpoint table (8 s steady-state window starting 3 s into each hold)

| Setpoint | RPM μ | predicted km/h | D2 μ (range) | D3 | D5 | D6 μ (range) | D5:D6 BE decoded km/h (÷16) |
|----------|------:|---------------:|--------------:|---:|---:|--------------:|----------------------------:|
| Phase A — idle in 1st | 1706 |  9.22 | 100.5 (0x4B..0x7D) | 0x00 | 0x00              | 161.8 (0x74..0xCD) | 10.11 |
| B1 ~2000 RPM           | 1975 | 10.68 | 115.6 (0x5C..0x9F) | 0x00 | 0x00 (rare 0x01)  | 186.6 (0x00..0xFE) | 11.66 |
| B2 ~2500 RPM           | 2131 | 11.52 | 124.1 (0x57..0xAF) | 0x00 | 0x00 (rare 0x01)  | 181.3 (0x00..0xFF) | 13.00 |
| B3 ~3500 RPM           | 3017 | 16.31 | 171.6 (0x85..0xC3) | 0x00 | **0x01** emerges  |  60.4 (0x02..0xFF) | **18.18** |
| B4 ~4500 RPM           | 3944 | 21.32 | 221.9 (0xCD..0xFA) | 0x00 | 0x01              | 121.1 (0x5B..0xA9) | 23.57 |
| B5 ~5500 RPM           | 4966 | 26.85 | **wraps** (0x00..0xFF) | 0x00 | 0x01..**0x02**| 192.7 (0x00..0xFF) | **29.64** |
| Phase C — idle in 1st  | 1698 |  9.18 | 100.5 (0x4D..0x81) | 0x00 | 0x00              | 161.8 (0x78..0xD4) | 10.11 |

RPM held within ~140 RPM of target except B2 (rider held ~2130 vs 2500 target) — irrelevant since RPM is read frame-by-frame from `120`.

### Linear regression — km/h = a·raw + b across all 7 setpoints

| Decode candidate | Slope (km/h/LSB) | Intercept | RMS residual |
|------------------|-----------------:|----------:|-------------:|
| **D5:D6 BE**     | **0.05633**      | **+0.071** | **0.019**    |
| D5:D6 LE         | -6e-5            | +17.3     | 6.29         |
| D2 alone         | -0.0059          | +15.7     | 6.32 (wraps) |
| D2:D3 LE         | -0.0059          | +15.7     | 6.32 (D3 = 0) |
| D2:D3 BE         | -2e-5            | +15.7     | 6.32         |
| D6 alone         | -0.0149          | +17.3     | 6.29 (wraps) |

D5:D6 BE is the only candidate with a clean linear fit. Slope ~10% below the binary-friendly 0.0625 km/h/LSB — attributable to back-of-envelope gearing/tyre numbers, not the encoding (see [[signal-wheel-speed-rear]] § Open).

### D6 / D2 ratio at no-wrap setpoints

| Setpoint        | D2 μ | D6 μ | D6/D2 |
|-----------------|-----:|-----:|------:|
| Phase A idle    | 100.5 | 161.8 | **1.610** |
| B1 ~2000 RPM    | 115.6 | 186.6 | **1.614** |
| Phase C idle    | 100.5 | 161.8 | **1.609** |
| (B2+ — D6 wrapping, ratio meaningless) | | | — |

Ratio 1.610 matches predicted 16/10 = 1.6 (1/16 km/h ÷ 1/10 km/h) within noise.

### Falsification outcomes vs Expected outcomes section

| Prediction | Outcome |
|------------|---------|
| **D5 emerges as `0x01` at B3 (~16 km/h ceiling)** | **Confirmed.** Mostly 0x01 by B3, fully 0x01 by B4. |
| **D3 emerges as `0x01` at B5 (~25.5 km/h ceiling)** | **Refuted.** D2 wrapped through full 0x00..0xFF at B5; D3 stayed at 0x00. D2:D3 is not a uint16. |
| Filtered-vs-raw (D6/D2 → constant at steady-state) | Partial: ratio is constant in the no-wrap regime, but the constant matches the **scale ratio**, not a filter time-constant. |
| Different-scaling-laws (D6/D2 stays speed-dependent) | Refuted — ratio is constant at 1.61 across no-wrap setpoints. |
| ABS-vs-tone-ring (D6 stair-steps, D2 smooth) | Refuted — both bytes show similar per-frame noise envelopes, not the discrete-vs-smooth split that hypothesis predicted. |
| ABS warning lamp trips, new always-on IDs appear | **Refuted on bus traffic.** Same 11 always-on IDs, identical to baseline ([[always-on-broadcast-ids]]). ABS lamp behaviour not separately observed in this analysis pass; if it tripped, it didn't manifest as new traffic. |

## Interpretation

**Three things settled, one prediction refuted, one open:**

1. **D5:D6 is a big-endian uint16 carrying rear wheel speed at ~1/16 km/h per LSB.** Cleanest result of the session — single-candidate fit at three orders of magnitude tighter than any other decode. The exact LSB sits 10% below the binary-friendly 0.0625; almost certainly because the back-of-envelope KTM 390 gearing × 150/60ZR17 circumference numbers in this experiment doc are off by ~10%, not because the encoding is some non-binary unit. Resolves on (a) an authoritative gearing source, or (b) a low-speed road capture cross-checking against the OEM speedo ([[2026-06-23-first-bike-roll]]).

2. **D2 is a coarse mirror of the same wheel speed at ~1/10 km/h per LSB**, uint8, with no companion high byte. D3 stayed at 0x00 throughout — including the moment D2 wrapped through 0x00..0xFF at B5 — so D2:D3 as a uint16 is cleanly out. D2 is genuinely just a single byte that wraps every 25.5 km/h. Quirky design choice (the dashboard never displays speed > 25.5 km/h from this byte, ever) but unambiguous from the data.

3. **D2 vs D6 is the simplest possible relationship: same quantity, different scales.** Ratio 1.610 ± 0.003 at no-wrap setpoints matches 16/10 = 1.6 within frame-level noise. The three prior hypotheses (filtered-vs-raw, different scaling laws, ABS-estimate-vs-tone-ring) were all too clever — none survive. The decay-tail ratio difference observed in the 2026-06-22 hand-spin session was almost certainly small-denominator noise, not a real speed-dependent shape.

**What this doesn't tell us:**

- **Front-wheel byte location** stays open. D0..D1 was STATIC `0x00` throughout (rear-only spin) — consistent with the KTM cross-walk prediction, not a test of it. [[2026-06-23-first-bike-roll]] is the next move.
- **Whether D4 carries anything** (STATIC `0x00` here too). Not motivated to chase.
- **Exact OEM unit (0.0625 vs ~0.056)** awaits gearing reconciliation or an OEM-speedo cross-check at low speed.
- **ABS warning lamp behaviour on the dash** wasn't recorded in the analysis. session.md still has TODOs.

## Expected outcomes

- **D2 and D6 ramp smoothly with RPM, D2:D3 (or D5:D6) reads as a uint16 with one of the two predicted scalings** → promote [[signal-wheel-speed-rear]] from `provisional` to `confirmed` for the rear wheel; rewrite the "D3/D5 are padding" sub-section as "D3/D5 are high bytes, not yet exercised below ~25 / ~16 km/h"; rewrite "encoding open" as "uint16 LE, scale = X.X km/h per LSB."
- **D2/D6 ratio converges to a constant at steady-state** → "filtered-vs-raw" hypothesis confirmed; D6 is the raw signal, D2 the filtered estimate.
- **D2/D6 ratio stays speed-dependent at steady-state** → different quantities; need more thinking and probably another experiment.
- **Linear regression yields slope = 0.1 km/h for D2** → confirms decimal-friendly OEM scaling.
- **Linear regression yields slope = 1/16 km/h for D6** → confirms binary-friendly OEM scaling.
- **D3 never increments above zero even when D2 saturates** → uint16 hypothesis refuted; rewrite the finding accordingly. Likely needs a follow-up experiment to figure out the actual encoding (maybe the bike just clamps at 25.5 km/h on this byte and broadcasts speed elsewhere at higher resolution?).
- **New always-on IDs appear when ABS faults** → catalogue them for later analysis, potentially a "fault-state broadcast" finding.

## Follow-ups

- Findings updated:
  - [[signal-wheel-speed-rear]] — **promoted to `confirmed`**. Rewritten: D5:D6 BE uint16 (~1/16 km/h) primary, D2 uint8 (~1/10 km/h) coarse mirror, D3 not a high byte (refuted). KTM cross-walk refined.
- New analysis script: [`scripts/engine_driven_rear_spin.py`](../../scripts/engine_driven_rear_spin.py).
- **Bike's official gearing** — pin the LSB to 0.0625 km/h (or whatever it actually is) by either (a) finding authoritative KTM 390 gearing + measured rolling circumference, or (b) cross-checking against the OEM speedo on a low-speed roll (the [[2026-06-23-first-bike-roll]] capture already covers this).
- **Front-wheel attribution still open** — only [[2026-06-23-first-bike-roll]] (or a real motion capture) can resolve it. Two experiments stay complementary.
- **No new ABS-fault traffic** — closes the "fault-state broadcast" angle for this session. If/when ABS lamp behaviour is reproduced, look for *bit-level* changes in existing IDs, not new IDs.
- **Higher-speed regime** — D5:D6 BE doesn't wrap until ~256 km/h; D2 wraps every 25.5 km/h forever. No motivation for a 2nd-gear follow-up; mobile rig + road capture is the right next escalation.
