---
date: 2026-06-23
status: planned
phase: 2
related:
  findings:
    - can/signal-wheel-speed-rear
    - can/always-on-broadcast-ids
  references:
    - ktm-can-decoder
  experiments:
    - 2026-06-22-wheel-spin-paddock-stand
  logs: []
---

# First motion capture — push the bike at walking pace, engine off

## Hypothesis

Three overlapping things to test in one capture, all unlocked by both wheels turning at the same known physical speed (dash visible throughout):

1. **Front wheel speed lives at `12D` D0..D1** (big-endian uint16, by analogy with KTM `12B` — see [[ktm-can-decoder]]). Both bytes are STATIC `0x00` in every prior session because the front wheel never turned. A bike-push has front and rear turning together, so D0..D1 should both go non-zero in lockstep with the push.

2. **Single-byte vs uint16 encoding** for the wheel speed bytes. The cleanest discrimination is at **low speed**:
   - If uint16 at fine scaling (e.g. 0.1 km/h per unit): 5 km/h ⇒ raw = 50 ⇒ D0=0x00, D1=0x32. **High byte stays zero, low byte does all the work.**
   - If single-byte uint8 (e.g. 1 km/h per unit): 5 km/h ⇒ D0=0x05, D1=0x00. **Low byte stays zero, high byte does all the work.**
   - These are exact mirror images — observing 5 km/h tells us which encoding is in play in a single reading. Same test applies to the rear at D2..D3.

3. **Byte-to-km/h scaling, anchored to the OEM speedo.** With the dash visible during the push and the dash showing some real km/h number, the byte value at the same moment becomes a calibration point. One push at ~5 km/h is enough to pin the scale; two or three at different speeds give confidence.

Secondary (free) wins from the same capture:

- **`12D` D6 at sustained known speed.** All our D6 data so far is from decaying hand-spin envelopes — never steady-state. A 5-second walk at constant pace gives a stable read on D6 vs D2 at a known km/h. Helps disambiguate the three current hypotheses about what D6 encodes (filtered estimate / different scaling law / ABS-derived vehicle speed — see [[signal-wheel-speed-rear]]).
- **Auto-headlight threshold via rolling threshold analysis.** Once km/h is decoded at every frame, any bit anywhere on the bus that transitions at a *consistent* km/h value across multiple push windows is a candidate headlight bit. No `b` marks needed — the speed trace is itself the ground truth. Generalises to every future "X triggers at speed Y" question.

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. **Engine off**, neutral, key on (position 1), kill switch in run. **Both wheels on the ground, no stand.** Side stand up while pushing.
- Capture: laptop in a backpack, lid closed, sleep disabled in System Settings → Battery → Options → Prevent automatic sleeping on power adapter (or equivalent for battery mode). Macbook fully charged before starting.
- Adapter / firmware / host as before.
- Rider observes the dashboard speedometer during each push — that's the ground truth for km/h scaling. No keypresses needed during the push.

## Procedure

**No procedure.yaml — this is free-form.** The wheel-speed bytes themselves delimit each push window (`12D` D2/D6 non-zero ⇒ pushing; zero ⇒ stopped). The rider's `session.md` notes are the cross-reference for what km/h the dash showed and whether the headlight came on.

1. Start capture: `python scripts/capture.py --port /dev/cu.usbmodem101 --label first-bike-roll`.
2. **Verify frames are flowing** (the `frames` counter in the status line incrementing) before closing the lid.
3. Close laptop lid, put in backpack.
4. ~30 s stationary baseline (laptop in backpack, bike not moving, hands off).
5. Push at roughly **3 km/h** until the dash shows a stable reading, stop completely, settle ~10 s.
6. Push at roughly **5 km/h**, stop, settle.
7. Push at roughly **6 km/h**, stop, settle.
8. **Optional:** one harder push (8+ km/h) to definitely trip the auto-headlight if earlier pushes didn't.
9. Return to start, take the laptop out, stop capture with `q`.

Three (or four) pushes give us multiple stop→go transitions to cross-check, and three distinct steady-state speed levels for the scaling calibration.

## `session.md` notes to record

The whole analysis hinges on the rider's qualitative observations of the dash and the lamp. Record per push:

- Highest km/h the dash reached during the push (e.g. "push 2 — dash showed 5, briefly touched 6").
- Whether the **auto-headlight (low beam) came on** during the push, and roughly when (start? middle? near the end?).
- Any **dash display jumps** observed (e.g. "0 → 3 → 7, skipped 4–6").
- Anything else weird — ABS lamp behaviour, side-stand interlock chatter, dash freezing, etc.

## Analysis plan

1. **Segment the capture into motion windows.** Find runs of `12D` frames where D2 ≠ 0 or D6 ≠ 0 (rear-wheel motion) or D0 ≠ 0 or D1 ≠ 0 (front-wheel motion, if our hypothesis holds). Each contiguous run is one push window.

2. **Per-window: full `12D` byte distribution.** Especially D0, D1, D2, D3, D6. Identify which bytes vary, which stay static. Confirm the front-wheel prediction directly: D0..D1 should be non-zero during pushes, STATIC `0x00` in stationary windows.

3. **Single-byte vs uint16 discrimination.** Per push window, check the mirror-image test:
   - If D1 is non-zero while D0 stays at 0 → uint16 encoding, low byte active.
   - If D0 is non-zero while D1 stays at 0 → single-byte encoding.
   - If both are non-zero → could be uint16 at coarser scaling (e.g. 1 km/h per unit BUT the byte spilled over into D0 at 5 km/h, which would imply scaling of ~5 units per km/h × 256 LSB step = unlikely but possible).
   - Same test for rear at D2..D3.

4. **Byte-to-km/h scaling.** Cross-reference the rider's observed dash readings against the byte values in each push window. Two or three push windows give multiple calibration points — linearity confirmed by fit.

5. **D6 steady-state.** During a sustained-pace push, what's D6 doing? Is the D6/D2 ratio constant (linear scaling of the same quantity) or speed-dependent (different quantities)? Resolves one of the open questions in [[signal-wheel-speed-rear]].

6. **Auto-headlight bit hunt by rolling threshold.** With km/h decoded at every frame:
   - For every (ID, byte, bit) on the bus, find the km/h value at the moment that bit transitions 0→1 and 1→0.
   - A real threshold has a **consistent km/h** value across transitions — tight cluster on the ON side, tight cluster on the OFF side (with hysteresis).
   - A bit that's noise will scatter randomly across speeds.
   - Cross-reference against the rider's per-push headlight-on/off notes to validate.

7. **Speedo-source confirmation.** If the front-wheel byte (D0..D1) is identified and scales to the dash-displayed km/h, the question "which byte drives the speedometer display?" is answered — and the apparent contradiction from [[2026-06-22-wheel-spin-paddock-stand]] ("rear spin moves D2/D6 but dash reads 0") is fully resolved.

## Expected outcomes

- **D0..D1 vary cleanly during pushes** → front wheel speed confirmed at the predicted KTM-mirrored location. Promote [[signal-wheel-speed-rear]] to `confirmed` if rear D2..D3 also confirms its encoding, and write a new `signal-wheel-speed-front` finding.
- **Single-byte vs uint16 resolved** → encoding finalised for both wheels.
- **km/h scaling pinned** → bytes become first-class signals usable by the replacement dashboard's decoder layer.
- **D6 steady-state behaviour observed** → D6 interpretation narrowed (or definitively pinned) — see [[signal-wheel-speed-rear]] § Why two bytes for one wheel.
- **Auto-headlight bit found** at some consistent km/h threshold → new `signal-auto-headlight` finding, with hysteresis values.
- **Auto-headlight bit NOT found** in the rolling-threshold scan → strong evidence the body controller drives the lamp directly from its internal read of the wheel-speed sensor, with no CAN intermediate. Useful negative result.

## Follow-ups

- Findings to write or update:
  - `docs/findings/can/signal-wheel-speed-front.md` (new, status TBD).
  - `docs/findings/can/signal-wheel-speed-rear.md` — promote to `confirmed`, fold in scaling and the D6 resolution.
  - `docs/findings/can/signal-auto-headlight.md` (new, if found).
- Once km/h is decoded, **every future capture gains a speed-vs-time axis** for free. Other signals can be re-analysed against it (e.g. revisit ABS warning lamp at the speedo-confirmed ~6 km/h threshold from [[dash-warning-lights]]).
- Higher-speed regime testing (D1/D3 behaviour at riding speeds, ride-mode-on-speed coupling, etc.) still requires the mobile rig from the post-experiment discussion — SD card + USB battery path, see ADR sequence around [[0001-usb-power-during-development]]. This bike-push capture is what justifies committing to that build.
