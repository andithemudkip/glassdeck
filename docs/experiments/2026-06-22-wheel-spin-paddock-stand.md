---
date: 2026-06-22
status: partial
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/post-kill-decay-groups
    - can/signal-side-stand
    - can/signal-wheel-speed-rear
  references:
    - ktm-can-decoder
  experiments:
    - 2026-06-17-payload-diff-idle
    - 2026-06-21-bit-transition-scan
  logs:
    - 2026-06-22-wheel-spin-paddock-stand
---

# Rear (and front) wheel spin on paddock stand — hunt wheel-speed byte(s) and auto-headlight threshold bit

## Hypothesis

Two overlapping things to test in one engine-off capture:

1. **Wheel-speed broadcast.** The 2020 Husqvarna Svartpilen 401 has no separate VSS — the speedometer reads off the ABS wheel-speed sensors via CAN. Each sensor is a Hall + tone-ring assembly that doesn't know whether the wheel is rolling on tarmac or spinning in mid-air, so spinning a wheel on a paddock stand should put the same data on the bus that the bike would broadcast at the equivalent road speed. Per the KTM 690 cross-walk ([`references/ktm-can-decoder.md`](../references/ktm-can-decoder.md)) wheel speed lives at `12B` (10 ms). On this bike the only 10 ms always-on broadcast is `12D` and its D0–D6 are all STATIC `0x00` at zero motion — `12D` is the prime candidate to encode the equivalent on Husqvarna.

2. **Auto-headlight threshold.** Live observation during planning: with the engine off, spinning the **rear** wheel briskly (~4–6 km/h equivalent) is enough to make the low beam turn on. The OEM dash speedometer, by contrast, stays at 0 during the same rear-only spin. So:
   - The dash speedometer is **front-wheel-sourced** (or front-priority), not rear.
   - But *something* on the bus is reading the rear wheel sensor, because the auto-headlight logic triggers from it.
   - The body controller's "vehicle is moving" / "headlight on" line is therefore either OR-gated across both wheels, or sources from rear directly. Whichever it is, the transition is a binary bit somewhere in the slow-decay group — fires at the threshold, with hysteresis on the way back down.

By varying spin speed (slow = below threshold, fast = above) in one session we should be able to:

- Identify continuous byte(s) that scale with wheel rotation.
- Identify the binary bit that flips at the auto-headlight threshold, with ON/OFF hysteresis values.
- Confirm which candidate byte drives the *speedo display* (it's the one that doesn't move during a rear-only spin) versus which feeds the body-controller's motion logic.

Bonus: if a front stand is available, repeating the spins on the front wheel attributes each candidate byte unambiguously to front vs rear, and tells us whether front-only spin also trips the auto-headlight (OR-gate vs rear-only logic).

## Setup

- Bike: 2020 Husqvarna Svartpilen 401, **engine off**, neutral, key on (position 1), kill switch in run.
- **Rear paddock stand** required throughout. Front stand optional but recommended (enables Phase C).
- Bike held upright by the paddock stand; side stand stays in its physical position throughout (no `j` toggles in this experiment).
- Adapter / firmware / host as before.
- Operator/rider spins the wheel by hand — no special tools.

## Procedure

> **Scripted** — driven by [`2026-06-22-wheel-spin-paddock-stand.procedure.yaml`](2026-06-22-wheel-spin-paddock-stand.procedure.yaml) (ADR 0006). Auto-marks fire at step start (moment the rider is cued to push). Headlight ON/OFF transitions are not time-predictable — the rider presses **`b`** (high-beam-toggle hotkey, repurposed as "headlight event") manually when they see the low beam change state.

**Push, don't spin.** Hand-spinning the wheel sustains for only ~1 s before it coasts to a stop. Each procedure step is therefore one short push followed by its decay envelope — not a long sustained spin window. Reps per phase give statistical power on the threshold values.

1. Start capture: `python scripts/capture.py --port /dev/cu.usbmodem101 --label wheel-spin-paddock-stand --experiment docs/experiments/2026-06-22-wheel-spin-paddock-stand.procedure.yaml`.
2. 6 s key-off baseline.
3. Key on. 30 s zero-motion settling window.

### Phase A — REAR gentle pushes (sub-threshold)

Six gentle one-flick pushes of the rear wheel, one per step. Low beam should **not** come on. If a push accidentally trips the headlight, mark `b` and continue — the data is still useful, it just means that push counts toward Phase B's threshold sample.

### Phase B — REAR hard pushes (above threshold)

Eight firm pushes of the rear wheel, one per step, each hard enough to definitely trip the auto-headlight. For each push:

- Press `b` the moment the low beam turns ON.
- Press `b` again the moment the low beam turns OFF as the wheel slows (≪1 s later, given the short coast).

Eight reps give us 8 ON-threshold samples and 8 OFF-threshold samples to characterise the hysteresis.

### Phase C — FRONT wheel (optional)

If no front stand, end the capture with `q` after Phase B. If front stand available: 3 gentle front pushes, then 5 hard front pushes, marking `b` on headlight ON/OFF as in Phase B.

Phase C disambiguates: a byte that moves with rear-only pushes but stays at 0 during front-only pushes is rear-wheel; the reverse is front-wheel (and is the speedo-display source); a byte that moves with both is an aggregate or shared signal. Phase C also resolves the OR-gate question for the auto-headlight bit.

### Shutdown

- Key off. 3 s tail silence. `q`.
- `session.md` — note whether the user has a front stand (whether Phase C ran), whether the cluster's speedometer display moves at all with front-only spin (rider observation), the approximate spin rates achieved on slow vs fast (rough rev/s helps later when converting tone-ring counts to expected km/h), and any unexpected dash behaviour (ABS lamp flicker, interlock warnings, etc.).

## Analysis plan

1. **Continuous wheel-speed byte hunt.** For every (ID, byte) and (ID, byte-pair big-endian uint16), classify by per-window value across:
   - 30 s zero-motion baseline (Steps 2–3 of setup).
   - Each **push event window** (from the spin-start mark out to ~3 s, covering the brief motion + decay envelope).
   - Each rest window (the gap between consecutive pushes, plus the longer between-phase rests).

   Each push gives a short pulse-shaped trace per candidate byte: zero before the spin-start mark, peak shortly after, decay back to zero within ~1–2 s. Candidate bytes are those whose peak-vs-rest amplitude is consistently non-zero across pushes and whose decay shape is consistent with mechanical coast. STATIC-zero in baseline and rest windows is a hard requirement.

   Prime suspect: `12D` D0–D6 (the only 10 ms always-on broadcast, all STATIC at zero motion). Scan all IDs anyway — front and rear may live on the same ID at different byte offsets (KTM 690 pattern) or on different IDs entirely.

2. **Rear vs front attribution.** Compare REAR pushes (Phases A + B) vs FRONT pushes (Phase C, if run). A byte that pulses only during REAR pushes is rear-wheel; only during FRONT pushes is front-wheel; with both is either an aggregate or an unrelated motion artefact. The byte that pulses with **front pushes only** is the speedo-display source.

3. **Scale check.** Gentle (Phase A) vs hard (Phase B) pushes produce different peak amplitudes — a real wheel-speed byte should scale roughly with push intensity. We can't put km/h units on the byte without a future road capture, but the relative ordering (rest ≈ 0, gentle peak < hard peak) should be clean.

4. **Headlight bit hunt.** Frame-by-frame around each `b` mark in Phase B (and Phase C if run): scan every bit in every payload for a bit whose transition aligns with the `b` press. Two transitions per hard push (ON, then OFF), 8 reps in Phase B = 16 transitions to triangulate against. The bit should be in the slow-decay group (`12A`, `12D`, `12E`, `450`, `541`, `5A0`) since the body controller drives the headlight.

5. **Hysteresis.** From the wheel-speed byte values at each `b`-press transition (8 ON values + 8 OFF values from Phase B): ON threshold should be higher than OFF threshold (typical motion-sensor hysteresis to suppress chatter near the boundary). Take the median of each. Useful for the replacement dashboard's own auto-headlight reimplementation if we ever add that.

6. **Cross-check the OR-gate hypothesis.** If Phase C runs, the front-only fast spin should also trigger the headlight if the body controller OR-gates both wheels. If only the rear-spin triggers it, the body controller uses rear exclusively for auto-headlight, and the front sensor feeds the speedometer only. Either outcome is a clean finding.

7. **Side-stand bit invariance.** `540` D3 bit 0 should remain at its physical value throughout (paddock stand doesn't move the side stand). Sanity check that nothing unexpected is happening with the `540` payload during this capture.

## Result

Capture: [`logs/2026-06-22-wheel-spin-paddock-stand/`](../../logs/2026-06-22-wheel-spin-paddock-stand/) — 77 694 frames, 11 always-on IDs, 14 `spin` marks (6 gentle + 8 hard). Phase C did **not** run — no front stand available; the rider quit out at the Phase C prompt. **No `b` (headlight transition) marks landed in the events log** — the rider found it impossible to push the wheel and key-press at the same time, so the auto-headlight ON/OFF transitions were observed but not timestamped. A few procedure rewinds appear in `events.csv` early on (premature key-on mark) and at the Phase A → B boundary (one stray `b` press during the very first Phase B push made the rider rewind to step 11 and restart the phase cleanly).

Analysed with [`scripts/wheel_spin_scan.py`](../../scripts/wheel_spin_scan.py), which summarises each push window on the target ID (default `12D`) and runs the headlight-bit candidate hunt.

### Wheel-speed bytes — `12D` D2 and D6

Both bytes are STATIC `0x00` everywhere except during push windows, where they ramp up at push start and decay smoothly to zero over ~1–2 s — a classic mechanical-coast envelope. Per-push peaks:

| Push  | Peak D2    | Peak D6    | Peak at  | Envelope                  | Frames |
|-------|------------|------------|---------:|---------------------------|-------:|
| A1    | 0x1D (29)  | 0x23 (35)  |  +2.47 s | t+2.47→t+2.49 (0.02 s)    |      4 |
| A2    | 0x1D (29)  | 0x22 (34)  |  +2.34 s | (single frame)            |      1 |
| A3    | 0x23 (35)  | 0x2D (45)  |  +1.51 s | t+1.51→t+1.64 (0.13 s)    |     15 |
| A4    | 0x28 (40)  | 0x37 (55)  |  +1.12 s | t+1.12→t+1.50 (0.38 s)    |     39 |
| A5    | 0x23 (35)  | 0x2E (46)  |  +1.13 s | t+1.13→t+1.31 (0.18 s)    |     19 |
| A6    | 0x2D (45)  | 0x3F (63)  |  +0.97 s | t+0.97→t+1.51 (0.54 s)    |     54 |
| **B1** | — | — | — | **no motion in window**  |      0 |
| B2    | 0x3E (62)  | 0x5D (93)  |  +1.54 s | t+1.54→t+3.75 (2.21 s)    |    168 |
| B3    | 0x42 (66)  | 0x65 (101) |  +1.04 s | t+1.04→t+2.11 (1.07 s)    |    107 |
| B4    | 0x49 (73)  | 0x70 (112) |  +0.82 s | t+0.82→t+1.96 (1.14 s)    |    114 |
| B5    | 0x49 (73)  | 0x71 (113) |  +1.30 s | t+1.30→t+2.36 (1.06 s)    |    107 |
| B6    | 0x4B (75)  | 0x75 (117) |  +1.22 s | t+1.22→t+2.38 (1.16 s)    |    116 |
| B7    | 0x46 (70)  | 0x6B (107) |  +0.86 s | t+0.86→t+1.98 (1.12 s)    |    112 |
| B8    | 0x44 (68)  | 0x68 (104) |  +1.30 s | t+1.30→t+2.41 (1.11 s)    |    112 |

**B1 had no motion at all in the analysis window** — the auto-mark fired before the rider was in position to push, and the push fell outside the t-1→t+6 s window. Confirmed by the next-mark-window check: no orphaned motion frames between B1 and B2.

**D6 always exceeds D2 during motion, with a speed-dependent ratio**: peak ratios in Phase B are tightly clustered at ~1.53× (range 1.50–1.56), while gentle-push peaks ratio at ~1.30–1.40. The ratio decreases during decay: in B4 the peak is D2/D6 = 73/112 ≈ 0.65 (so D6 ~1.53× D2), and at the tail D2/D6 = 29/34 ≈ 0.85 (so D6 ~1.17× D2). The two bytes are clearly linked but encode different quantities; see Interpretation.

### Headlight bit hunt — no separate broadcast

The full-bus bit scan (bits ON during Phase B windows but zero in baseline + Phase A + inter-phase rest) returned **exactly one candidate**: `12D` D2 bit 6. But that's the high bit of the speed byte itself — set whenever D2 ≥ 0x40. It tracks wheel speed crossing the 64-unit mark; it is **not a separate headlight broadcast**.

The pattern across pushes is consistent with the user's threshold observation, though:

- Phase A (all 6 gentle pushes): peak D2 = 0x1D–0x2D. D2 bit 6 never set. Rider observed headlight off throughout (consistent).
- Phase B push 2: peak D2 = 0x3E (62). D2 bit 6 never set. Just below the 0x40 threshold — would predict no headlight on this push.
- Phase B pushes 3–8: peak D2 = 0x42–0x4B. D2 bit 6 set for 6–28 frames each. Would predict headlight ON for those pushes.

This is suggestive but **not confirmed** — without the `b` marks, we can't directly correlate D2-bit-6 transitions with the dash's low-beam state.

### Anomaly — 90 motion frames in the inter-phase rest

`12D` shows wheel-speed motion at +75.8 s → +95.0 s from key-on, peak D2 = 0x34, peak D6 = 0x4C. That's the inter-phase rest window between Phase A push 6 and Phase B push 1. Most likely the rider gave the wheel an extra spin between phases (warm-up / testing rig). Doesn't affect any per-push analysis since it falls outside every push window.

## Interpretation

- **`12D` D2 and D6 are both rear-wheel-speed bytes** on the 2020 Husqvarna Svartpilen 401 (engine off, paddock stand, wheel spun by hand). Provisional finding written: [`docs/findings/can/signal-wheel-speed-rear.md`](../findings/can/signal-wheel-speed-rear.md). Promote to `confirmed` on a future real-motion capture that pins the byte-to-km/h scale and verifies both bytes against an external speed reference.
- **Two bytes for one wheel is unusual.** The D6/D2 ratio at peak (~1.53×) versus at decay tail (~1.17×) shows they're not simple unit conversions of each other (constant ratio would be expected then). Plausible models: (a) D2 is filtered/smoothed and D6 is raw, with the filter introducing lag visible on fast acceleration (peak D6 leads D2 because D2's average hasn't caught up); (b) D2 and D6 use different scaling laws (e.g. one linear in wheel RPM, one with an additive offset); (c) D2 is an ABS-derived "vehicle speed estimate" and D6 is the raw tone-ring count. **No way to distinguish from this engine-off-rear-only capture** — needs front-wheel-only spin (Phase C) and/or a steady-state road capture to compare against ground truth.
- **The OEM speedometer reading 0 km/h during a rear-only spin** is now consistent with these findings: `12D` D2 + D6 are rear-only signals (we only spun rear and both bytes moved together). The speedo reads its value from a different byte sourced from the front wheel, which was stationary throughout. So both observations — "rear spin produces motion on the bus" and "dash speedo reads 0 during rear-only spin" — are simultaneously true, no contradiction. The front-wheel-speed byte location is still unknown.
- **The auto-headlight does NOT appear to be broadcast as a separate bit.** Two readings of this:
  - **Most likely:** the body controller drives the headlight relay directly from its read of the wheel-speed sensor (or an internal "vehicle moving" line), with no need to broadcast a derived "headlight on" signal to other modules. The bit just doesn't exist on the bus.
  - **Less likely:** the bit is broadcast at a longer period than our observation window (e.g. only on transitions, with a low repeat rate), or in an ID we don't see (an event-triggered broadcast).
  - Either way, **the threshold appears to align with `12D` D2 crossing ~0x40** (64 raw units): all 6 gentle pushes stayed below it (headlight off), Phase B push 2 just missed it (rider report and headlight observation needed but consistent), and Phase B pushes 3–8 cleared it (headlight expected on). This is a hypothesis, not a finding, until a session with reliable `b` marks lines up D2-bit-6 transitions with dash observations.
- **Operator-driven `b` marks during a hand-push are not feasible.** Lesson for future captures of physical-input events that need synchronised marking: either the action and the marking need to be doable one-handed (e.g. toggle switches), or the experiment needs a second person, or the mark trigger needs to be automated (e.g. a microswitch fed into a GPIO that the firmware turns into an SLCAN comment line). The wheel-spin case fails on all three: needs both hands to push, no second person, no hardware mark trigger yet.
- **The `12B` (KTM) → `12D` (Husqvarna) shift is real.** Both IDs broadcast at 10 ms; both carry wheel-speed-related data. Adds another "ID relocation" data point to the KTM cross-walk (alongside the kill switch moving from `120` to `541`). The 10 ms period and the role both fit KTM's `12B`, but the ID number itself is different.
- **Byte positions D0..D3 appear preserved between KTM and Husqvarna.** KTM puts front wheel at D0..D1 and rear wheel at D2..D3 as big-endian uint16. Our rear-only spin moves D2 (matching KTM's rear-high-byte position), while D0..D1 stay at zero (consistent with front being stationary). **This gives us a testable prediction: front wheel speed should live at `12D` D0..D1 in the same encoding.** A front-only spin or any real motion capture will resolve it.
- **D3 stays at zero throughout 836 motion frames.** KTM's test vector (`12B 00 00 02 16 ... → rear_wheel=534`) shows the LSB actively used at low speeds on KTM, so the divergence is real. Most likely Husqvarna's simpler ABS module quantises rear-wheel speed to single-byte resolution at D2 — but it could also be that D3 only activates above some speed threshold hand-spin never reaches. A road capture settles it.
- **D6 is a Husqvarna-specific signal.** KTM's `12B` uses D5..D7 for 12-bit lean and tilt; the 2020 Svartpilen 401 has no lean sensor, so D5..D7 are free to repurpose. Husqvarna fills D5 with padding, D7 with the universal cross-ID 6-cycle byte ([[byte-d7-cycle-hash]]), and inserts a new wheel-derived signal at D6. What D6 actually encodes — filtered speed estimate, vehicle-speed-from-both-wheels, acceleration, derivative — remains open ([[signal-wheel-speed-rear]] § Why two bytes for one wheel?).
- **KTM doesn't unlock km/h scaling either.** Their decoder emits raw uint16; the test vector `rear_wheel=534` is raw, no km/h factor. The cross-walk gives us byte positions and an encoding hint (uint16 big-endian) but not units. A real-speed reference is still required to put km/h on these bytes.

## Expected outcomes

- **One byte/pair in `12D` (or elsewhere) tracks rear wheel speed; STATIC in baseline/rest, non-zero during spins** → candidate `signal-wheel-speed-rear` finding at `provisional`. Promote to `confirmed` on a future motion/road capture that pins a real km/h scale.
- **A second byte tracks front wheel speed during Phase C** → analogous `signal-wheel-speed-front` candidate. The front byte is the one driving the speedometer display.
- **A single bit in the slow-decay group flips with the `b` marks** → `signal-auto-headlight` finding, with ON and OFF thresholds recorded.
- **Front-only spin also triggers the headlight** → OR-gate confirmed; note in the auto-headlight finding.
- **Front-only spin does NOT trigger the headlight** → body controller uses rear exclusively for the headlight logic.
- **No byte moves with spin** → unlikely given the headlight reaction is direct evidence the data exists, but if so: ABS ECU may broadcast only on an event-triggered ID we haven't seen yet, or only above a higher threshold. Re-plan with more aggressive spin.

## Follow-ups

- [x] [`docs/findings/can/signal-wheel-speed-rear.md`](../findings/can/signal-wheel-speed-rear.md) at `provisional`.
- [x] Update [`docs/references/ktm-can-decoder.md`](../references/ktm-can-decoder.md): KTM `12B` → Husqvarna `12D` for wheel-speed signals (same 10 ms period, different ID).
- [x] Reusable analysis script: [`scripts/wheel_spin_scan.py`](../../scripts/wheel_spin_scan.py).
- [ ] **Front-wheel attribution is open.** Phase C didn't run (no front stand). The signal that drives the dashboard speedometer — which stayed at 0 during this rear-only capture — is therefore unlocated. Best resolved by either (a) a future engine-off front-stand spin, or (b) a real motion capture where the bike is rolled a few metres in neutral with both wheels turning.
- [ ] **Auto-headlight finding deferred.** Without `b` marks lining up against D2 transitions, the "D2 ≥ 0x40 = headlight ON" hypothesis is only suggestive. To promote: rerun the hard-push phase with a second person pressing `b`, or instrument a microswitch / Hall sensor on the headlight power feed and route it into the firmware as an auto-mark (analogous to the way procedure-driven auto-marks already work).
- [ ] **Byte-to-km/h scaling.** Both bytes' real units stay open until a road capture pins them. Once available, this `12D` D2/D6 decode can be promoted to `confirmed`. See [[signal-wheel-speed-rear]] § Open.
- [ ] **What is D6 vs D2?** The non-constant ratio between the two bytes (~1.53× at peak, ~1.17× at decay tail) shows they're not just a unit conversion of each other. Plausible models in the Interpretation section above. A steady-state spin (motor-driven, not hand-driven) would let us read both bytes at a stable speed and disambiguate.

A finding for rear wheel speed. Combined with the existing decoded signals (RPM, throttle, coolant, kill, gear/N, side stand, shift lever), the dashboard input-mirror surface now covers ~9 of the ~12 signals the replacement cluster will need. Big remaining unknowns: **front wheel speed / vehicle speed**, **clutch state engine-on**, **ride mode (ROAD/SUPERMOTO)**, **dash button presses**.
