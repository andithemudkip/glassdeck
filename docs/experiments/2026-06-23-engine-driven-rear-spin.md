---
date: 2026-06-23
status: planned
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
  logs: []
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

## Expected outcomes

- **D2 and D6 ramp smoothly with RPM, D2:D3 (or D5:D6) reads as a uint16 with one of the two predicted scalings** → promote [[signal-wheel-speed-rear]] from `provisional` to `confirmed` for the rear wheel; rewrite the "D3/D5 are padding" sub-section as "D3/D5 are high bytes, not yet exercised below ~25 / ~16 km/h"; rewrite "encoding open" as "uint16 LE, scale = X.X km/h per LSB."
- **D2/D6 ratio converges to a constant at steady-state** → "filtered-vs-raw" hypothesis confirmed; D6 is the raw signal, D2 the filtered estimate.
- **D2/D6 ratio stays speed-dependent at steady-state** → different quantities; need more thinking and probably another experiment.
- **Linear regression yields slope = 0.1 km/h for D2** → confirms decimal-friendly OEM scaling.
- **Linear regression yields slope = 1/16 km/h for D6** → confirms binary-friendly OEM scaling.
- **D3 never increments above zero even when D2 saturates** → uint16 hypothesis refuted; rewrite the finding accordingly. Likely needs a follow-up experiment to figure out the actual encoding (maybe the bike just clamps at 25.5 km/h on this byte and broadcasts speed elsewhere at higher resolution?).
- **New always-on IDs appear when ABS faults** → catalogue them for later analysis, potentially a "fault-state broadcast" finding.

## Follow-ups

- Findings to write or update:
  - [[signal-wheel-speed-rear]] — promote to `confirmed` for rear, fold in scaling and the D2/D6 resolution.
  - Maybe a new finding `signal-vehicle-speed-rear-filtered` vs `signal-vehicle-speed-rear-raw` if D2 and D6 turn out to be filtered/raw of the same quantity.
- Bike's official gearing — find authoritative source (service manual, factory spec sheet, or measure directly: lift rear, mark wheel + sprocket, count rotations through one engine cycle in known gear) and replace the back-of-envelope numbers above before publishing the analysis.
- **Front-wheel attribution still open** — only [[2026-06-23-first-bike-roll]] (or a real motion capture) can resolve it. Run that one too; the two experiments are complementary, not redundant.
- **Higher-speed regime** — if Plan A is clean and you want to chase the D3/D5 high-byte behaviour: schedule a 2nd-gear follow-up. Or wait for the mobile rig + a real road capture, which is more honest evidence anyway.
