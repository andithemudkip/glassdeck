---
date: 2026-06-24
status: done
phase: 1
related:
  findings:
    - can/signal-wheel-speed-front
    - can/signal-wheel-speed-rear
    - can/always-on-broadcast-ids
    - bike/dash-warning-lights
  references:
    - ktm-can-decoder
  experiments:
    - 2026-06-22-wheel-spin-paddock-stand
    - 2026-06-23-engine-driven-rear-spin
    - 2026-06-23-first-bike-roll
  logs:
    - 2026-06-24-front-wheel-hand-spin
---

## Result summary

- **Front wheel speed confirmed at `12D` D0 + D1 high nibble (12-bit BE)**, LSB **1/192 km/h** (= 1/12 km/h per effective transmitted step). Established here for byte location; LSB pinned by the follow-up [[2026-06-24-front-wheel-decay-mark]]. New finding [[signal-wheel-speed-front]] at `confirmed`.
- **D2 coarse-mirror is rear-specific.** Front motion to ~11 km/h on the dash left D2 at `0x00` across all 9 pushes — D2 mirrors only the rear D5:D6, not "whichever wheel is moving". Noted in [[signal-wheel-speed-rear]].
- **Front and rear use different LSB families** — front 1/192 km/h, rear ~1/16 km/h. Both are calibrated km/h (not pulses-per-time, which was the pulses hypothesis the LSB asymmetry initially suggested) — different scales reflect different consumer requirements within the ECU, not different physical quantities. The front fit does not transfer to the rear, but the binary-friendly fraction (1/192) on the front strongly suggests the rear is the equally-binary-friendly 1/16, and the ~10% gap in the rear's best-fit is the gearing/tyre estimate being off rather than a non-binary unit.
- **Bonus signal in the same byte slot.** [[signal-12d-d1-bit0]] surfaced: D1 bit 0 carries an engine-correlated flag (set ~3.5% of frames engine-on, never set engine-off). Spotted during the encoding-pattern cross-check against the engine-on rear-spin capture; doesn't affect the wheel-speed decode if the decoder explicitly masks `D1 & 0xF0`.
- **Encoding-pattern finding.** New [[byte-encoding-12-in-16]] documents the "wide field in the high bits + narrow field(s) in the low nibble" pattern, with the gotcha that a naïve "all multiples of 16 → 12-bit padded" reading misses co-located low-bit signals.
- **Auto-headlight is NOT front-wheel-keyed.** Rear-only 2026-06-22 fired it; this front-only session did not. Eliminates front-keyed and OR-gated-across-wheels; remaining candidates are rear-keyed (likely off-bus, since the 2026-06-22 rolling-threshold scan found no CAN bit) or body-controller-internal. [[bike/dash-warning-lights]] updated.
- **ABS warning lamp did NOT extinguish** despite the front wheel (which the dash and ABS lamp logic source from) running well above 6 km/h. Engine was off. Working hypothesis: the ABS module's pump self-test requires the engine running before it will clear the lamp regardless of measured speed. Added as a provisional precondition to [[bike/dash-warning-lights]]; confirms next engine-on motion capture.
- **Bike-roll fallback ([[2026-06-23-first-bike-roll]]) remains superseded** — no longer load-bearing for the front LSB question, kept on file only for the both-wheels-spinning cross-check it would provide.

# Front wheel hand-spin on a jack — front-wheel byte, encoding mirror-test, OEM-speedo cross-check

Substitutes for [[2026-06-23-first-bike-roll]]. With rear wheel speed encoding fully pinned ([[signal-wheel-speed-rear]] `confirmed`: `12D` D5:D6 BE uint16 ~1/16 km/h, D2 coarse mirror), the front wheel is the only remaining wheel-speed unknown — and unlike the rear, a hand-spin gives the OEM speedometer something to display, because the speedo is front-wheel-sourced (see [[signal-wheel-speed-rear]] § "Why the OEM speedometer reads 0 during a rear-only spin"). That makes the front-stand hand-spin strictly richer than the rear hand-spin was, and removes the need for a bike-push session for the same coverage.

## Hypothesis

Spinning the front wheel by hand with the front of the bike jacked up should produce, in a single capture:

1. **Front wheel speed bytes emerge.** KTM cross-walk predicts front wheel speed at `12D` D0..D1 BE uint16 ([[ktm-can-decoder]]; same `12D` layout that placed rear at D5:D6). Both bytes were STATIC `0x00` through every rear-only session — they should ramp with motion now. Falsified if D0..D1 stay `0x00` while some other byte on some other ID responds to the spin.

2. **Encoding finalised by mirror-image test.** The decay envelope sweeps through the low-decoded-value regime where uint16 vs single-byte is cleanest to discriminate:
   - uint16 fine scaling (~1/16 km/h LSB, mirroring rear): at 5 km/h ⇒ raw = 80 ⇒ D0=0x00, D1=0x50. High byte stays at zero, low byte does all the work.
   - single-byte uint8 (~1 km/h LSB): at 5 km/h ⇒ D0=0x05, D1=0x00. Low byte stays at zero, high byte does the work.
   Exact mirror images. Expectation, given the KTM cross-walk and the rear D5:D6 result: uint16 with D0=high, D1=low.

3. **LSB calibration against the OEM speedometer.** The dashboard reads the front wheel, so during the spin the rider can read the peak km/h shown on the dash (e.g. "dash peaked at 8") and we cross-reference against the peak raw byte value at the same frame. One push gives one calibration anchor; three or four pushes across different peak speeds give a fit. This is the cross-check that resolves the open question on the rear LSB too: if D5:D6 and D0..D1 share the same encoding family (likely), the front calibration transfers to the rear.

Secondary (free) wins from the same capture, both untestable on every prior session:

- **Auto-headlight threshold bit.** The auto-headlight is front-wheel-keyed (it fired in the rear-only 2026-06-22 session, contradicting "front-wheel-keyed" — see Caveats; the open question is what speed it actually triggers at, on whichever wheel). With km/h decoded at every frame from D0..D1, any bit anywhere on the bus that transitions at a consistent km/h value across multiple spins is a headlight candidate, with hysteresis values readable directly off the trace.
- **ABS lamp threshold confirmation.** Per [[bike/dash-warning-lights]] the ABS warning extinguishes ~6 km/h; the rear-only spins held it lit because the lamp reads the front wheel. The decay envelope ramps smoothly through 6 km/h, so the rider's "ABS lamp extinguished at decoded ~X km/h" observation pins the threshold to a real number for the first time, instead of the eyeballed "~6" from `dash-warning-lights`.

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. **Engine off**, neutral, key on (position 1), kill switch in run.
- **Front of the bike jacked up so the front wheel spins freely.** Hydraulic jack under the front engine guard — lifts the front wheel clear with the bike resting stable on the side stand + jack contact. Resolves the "no front stand" blocker that deferred Phase C of [[2026-06-22-wheel-spin-paddock-stand]]. Check stability before going hands-on with the wheel; the front guard is a load-bearing point but the bike isn't designed to be lifted there, so a wobble during a hand-spin is the failure mode to watch for.
- Rear wheel stays on the ground (or on the rear paddock stand — irrelevant either way; the rear sensor is stationary).
- Side stand: per the bike's actual posture once jacked. No `j` toggles.
- Adapter / firmware / host as before.
- Operator/rider spins the front wheel by hand — no special tools.
- Rider keeps eyes on the dashboard during each push (km/h reading, headlight transitions, ABS lamp transitions). This is the cross-reference for the whole analysis; without it the LSB calibration and threshold pins are unrecoverable.

## Procedure

**Free-form, no procedure YAML.** The wheel-speed bytes themselves delimit each push window (`12D` D0..D1 or D5:D6 non-zero ⇒ pushing; zero ⇒ stopped). Hand-driven pushes can't be hotkey-marked anyway (see [[experiment-design-hand-driven-marks]]); the rider's `session.md` notes are the cross-reference for what the dash showed and which lamps changed state during each push.

1. Start capture: `python scripts/capture.py --port /dev/cu.usbmodem101 --label front-wheel-hand-spin`.
2. **Verify frames are flowing** (the `frames` counter in the status line incrementing) before going hands-on with the wheel.
3. ~30 s zero-motion baseline. Confirms `12D` D0..D1 at `0x00 0x00` at rest (clean comparison to the post-spin state).
4. **Phase A — gentle pushes (~3–5 km/h on the dash).** 3–4 reps, settle to zero between each. The low-speed regime is where the encoding mirror-test discriminates cleanest. Rider notes per push: peak km/h on the dash, whether ABS lamp extinguished and at roughly what dash value, whether auto-headlight came on.
5. **Phase B — harder pushes (8+ km/h on the dash).** 2–3 reps, settle to zero between each. Definitely above ABS-lamp threshold; probably above headlight threshold; gives a second calibration regime for the LSB fit and a higher-byte ceiling test (does D0 ever leave `0x00`? At ~16 km/h on a 1/16 LSB encoding, D0 should emerge as `0x01`).
6. **Optional Phase C — sustained spin if mechanically possible.** A wheel held at a roughly constant velocity for ~5 s (e.g. with a continuous palm push on the tyre tread) gives a steady-state km/h sample that strengthens the calibration. Skip if it's too awkward to sustain by hand — Phases A+B cover the goal.
7. Settle to zero, stop capture with `q`.

## `session.md` notes to record

The whole analysis hinges on the rider's qualitative observations. Record per push:

- Peak km/h the dash reached during the push (e.g. "push 2 — dash peaked at 5, briefly touched 6").
- Whether the **auto-headlight (low beam) came on** during the push, and roughly when in the envelope (start of push? near the peak? on the way down?).
- Whether the **ABS warning lamp extinguished** during the push, and roughly when (used to pin the [[bike/dash-warning-lights]] ~6 km/h threshold to a real number).
- Any **dash display jumps** observed (e.g. "0 → 3 → 7, skipped 4–6") — useful for understanding whether the dash filters/quantises its display.
- Anything else weird — ABS lamp re-arming behaviour, dash freezing, side-stand interlock chatter, lamps that come on that we weren't expecting.
- **Jack stability** — flag anything that wobbled or shifted during a push, in case it affected the spin or recurs on a future session.

## Analysis plan

1. **Segment the capture into push windows.** Find contiguous runs of `12D` frames where D0 ≠ 0 or D1 ≠ 0 (front-wheel motion, if the hypothesis holds) or D2 ≠ 0 or D5/D6 ≠ 0 (rear-wheel motion — should be empty this session; if present, the front-stand setup is letting the rear move too, flag it). Each contiguous front-motion run is one push window.

2. **Front-wheel byte attribution.** Per push window, full `12D` byte distribution. D0..D1 should be non-zero during pushes, STATIC `0x00` in stationary windows. If they stay flat and a different byte (or different ID) responds instead, the KTM cross-walk for front-wheel position is refuted and we follow the actual responding byte.

3. **Single-byte vs uint16 discrimination.** Per push window in Phase A (low-speed):
   - D1 non-zero while D0 stays at `0x00` → uint16 BE encoding, low byte active. (Expected.)
   - D0 non-zero while D1 stays at `0x00` → single-byte uint8 encoding.
   - Both non-zero at the same frame → check magnitudes and apply the rear's `1/16 km/h` LSB tentatively; either it's a fine-scaled uint16 already past the 16 km/h ceiling (unlikely in Phase A) or a different scaling.

4. **LSB calibration against the OEM speedo.** Cross-reference each push's peak dash km/h against the peak raw byte value at the same frame (or short window around the peak). Multiple pushes give multiple calibration points — linearity confirmed by fit. Expected: ~1/16 km/h per LSB (BE uint16), matching the rear; if the fit lands cleanly on 1/16, the rear's open LSB question ([[signal-wheel-speed-rear]] § Open → "Exact LSB") also closes by symmetry.

5. **Auto-headlight bit hunt by rolling threshold.** With km/h decoded at every frame:
   - For every (ID, byte, bit) on the bus, find the km/h value at the moment that bit transitions 0→1 and 1→0.
   - A real threshold has a **consistent km/h** value across transitions — tight cluster on the ON side, tight cluster on the OFF side (with hysteresis).
   - A bit that's noise will scatter randomly across speeds.
   - Cross-reference against the rider's per-push headlight notes to validate.

6. **ABS-lamp threshold pin.** Same rolling-threshold technique applied to the ABS lamp transitions the rider observed. Promotes the eyeballed ~6 km/h in [[bike/dash-warning-lights]] to a real number.

7. **High-byte ceiling test (Phase B).** At ~16 km/h decoded, D0 should emerge as `0x01` (1/16 LSB uint16). If it does, encoding is confirmed. If D0 stays `0x00` at 16+ km/h while D1 wraps, the LSB is finer than 1/16 (maybe ~1/256 km/h, single-byte high-resolution) — handle in interpretation.

## Expected outcomes

- **D0..D1 vary cleanly during pushes**, D5:D6 stay at `0x00` → front wheel speed confirmed at the KTM-mirrored location. Promotes a new finding [`signal-wheel-speed-front`](../findings/can/signal-wheel-speed-front.md).
- **Encoding finalised** — BE uint16 with D0=high, D1=low, ~1/16 km/h per LSB (most likely).
- **LSB calibration** anchored against the OEM speedo, with the same number transferring to the rear via shared encoding family. Closes [[signal-wheel-speed-rear]] § Open → "Exact LSB".
- **Auto-headlight bit located** at some consistent km/h threshold, with hysteresis values → new [[signal-auto-headlight]] finding.
- **ABS-lamp threshold pinned** to a real number → updates [[bike/dash-warning-lights]] from "~6 km/h" to the measured value.
- **Auto-headlight bit NOT found** in the rolling-threshold scan → strong evidence the body controller drives the lamp directly from an internal read of the wheel-speed sensor (no CAN intermediate), and the 2026-06-22 rear-only headlight trigger was via a non-CAN path. Useful negative result; doesn't reopen the front-wheel location question.

## Caveats and what this does NOT cover vs the bike-push

- **No simultaneous-both-wheels sanity check.** The bike-push would have had front and rear turning at the same physical speed; that's a cross-check we lose here. Not load-bearing given the rear is already `confirmed`, but if Phase B produces a weird front decode we may want to fall back to the bike-push to resolve it.
- **The auto-headlight on the rear-only 2026-06-22 session.** Headlight came on during rear hand-spins per the 2026-06-22 hypothesis section — that's evidence *against* a purely front-wheel-keyed headlight. Possible resolutions: OR-gated across both wheels, sourced from the rear, or sourced from an internal-to-the-body-controller signal that doesn't appear on the CAN bus at all. The rolling-threshold analysis here will either find a bit that fires at a consistent front-wheel km/h (front-keyed or OR-gate) or fail to find one (off-bus or rear-keyed; cross-check by running the same scan over the 2026-06-22 rear-spin capture).
- **Engine-driven sweep behaviour at higher speeds.** This is a hand-spin — no sustained high-speed regime. The bike-push wouldn't have given that either; for >30 km/h front-wheel data we'd need the mobile capture rig (Tooling follow-ups in `docs/status.md`). Not in scope for this session.

## Follow-ups

- Findings to write or update:
  - `docs/findings/can/signal-wheel-speed-front.md` (new, status TBD by results).
  - `docs/findings/can/signal-wheel-speed-rear.md` — close the "Exact LSB" open question if the front fit lands cleanly on 1/16 km/h; flip from "best-fit 0.05633" to "confirmed 0.0625".
  - `docs/findings/can/signal-auto-headlight.md` (new, if a CAN bit is found).
  - `docs/findings/bike/dash-warning-lights.md` — replace the eyeballed ~6 km/h ABS threshold with the measured value.
- [[2026-06-23-first-bike-roll]] gets marked `superseded` (kept on file as a higher-confidence fallback if this hand-spin produces ambiguous LSB or auto-headlight results).
- [`scripts/wheel_spin_scan.py`](../../scripts/wheel_spin_scan.py) is already the right tool for the per-push decay analysis; may need a flag to focus on `12D` D0..D1 instead of D2/D6. Rolling-threshold bit scan for the auto-headlight is a new script — likely a generalisation of [`scripts/id541_d4_tick_rate.py`](../../scripts/id541_d4_tick_rate.py)'s per-frame join pattern but over every (ID, byte, bit) keyed on decoded km/h.
