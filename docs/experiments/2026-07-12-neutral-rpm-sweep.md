---
date: 2026-07-12
status: planned
phase: 1
related:
  findings:
    - can/signal-rpm
    - can/signal-throttle-position
    - can/signal-fuel-injection-setpoint
    - can/signal-engine-torque
    - can/signal-12d-d1-bit0
  references:
    - ktm-can-decoder
  experiments:
    - 2026-06-18-throttle-sweep-engine-off
    - 2026-06-23-engine-driven-rear-spin
    - 2026-07-12-dash-inputs
  supersedes:
    - 2026-06-18-engine-on-stationary-inputs
  logs: []
---

# Neutral RPM sweep — throttle blip + five held setpoints matched to the in-gear rear-spin

Split half of the original engine-on-stationary batch. Dash inputs (mode toggle, trip reset, button presses) are now in [2026-07-12-dash-inputs](2026-07-12-dash-inputs.md). This experiment is the throttle/RPM-in-neutral no-load reference for the in-gear engine-driven capture, and the [[signal-fuel-injection-setpoint]] discriminator.

## Hypothesis

Two complementary motion patterns, both engine-on, both in neutral, both compared against the in-gear analysis from [[2026-06-23-engine-driven-rear-spin]]:

1. **Throttle blip engine-on (Phase D — fast transients).** Confirms the throttle-position decoding from [[2026-06-18-throttle-sweep-engine-off]] holds with the engine running. Fast throttle→RPM excursions also make RPM-tracking bytes visible against the steady idle background — the payload-diff classified most `121` bytes as LOW-CARD without a hypothesis, and engine-on blipping is the natural way to start separating them.

2. **Held RPM setpoints in neutral (Phase E — steady-state, no load).** Five setpoints matched to the in-gear rear-spin sweep (2000, 2500, 3500, 4500, 5500 RPM), held ~12 s each with idle rests between. Analysis reads RPM from CAN frame-by-frame, so ±200 RPM of target is fine — what matters is **steady throttle hold** for the full 12 s. Purpose: decouple throttle from RPM for `540` D1 attribution.

Analysis of the in-gear capture ([`scripts/engine_load_scan.py`](../../scripts/engine_load_scan.py) + [`scripts/idle_load_compare.py`](../../scripts/idle_load_compare.py)) already established two things about `540` D1: (a) off-idle it fits `D1 ≈ 14 + 0.8 × throttle%` cleanly across the 5 setpoints, and (b) in-gear-clutch-out at idle (genuine drivetrain drag) reads identical to neutral-idle at matched RPM/throttle — **MAP / engine-load is ruled out** because a real load signal would respond to drivetrain drag at fixed throttle. The leading interpretation is now **throttle-derived with a coolant-keyed idle offset**, recasting the prior [[signal-fuel-injection-setpoint]] reading. Phase E discriminates this from the remaining alternative (RPM-derived) cleanly:

- **D1(neutral) < D1(in-gear) at matched RPM** ⇒ throttle-derived. In neutral the same RPM is reached at much lower throttle, so a throttle-keyed byte reads lower. This is the leading-hypothesis prediction.
- **D1(neutral) ≈ D1(in-gear) at matched RPM** ⇒ RPM-derived. Throttle doesn't matter; only RPM drives the value.
- **D1 tracks throttle within Phase E too** ⇒ direct re-derivation of [[signal-throttle-position]]; check the linear fit and the residual structure against the in-gear fit for any RPM-banded extra term.

The same per-setpoint table from `engine_load_scan.py` applied to Phase E will surface other unknown bytes whose RPM/throttle correlation differs between the two captures — `121` D0..D3 in particular, where the in-gear capture showed non-monotonic RPM-banded shapes that Phase E will reproduce (RPM-keyed) or wash out (load- or throttle-keyed in a way the in-gear data already accounted for).

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. **Engine running, idling**, in neutral, side stand down (or paddock stand if available), kill switch in run.
- Engine at operating temperature before the session begins — after a short warm-up ride, or ~5–10 min at idle before starting the procedure. Matches the coolant condition of the in-gear capture. ([[2026-07-12-dash-inputs]] is engine-off and does not warm the engine — run this experiment after riding, or after a dedicated idle warm-up.)
- **Wifi-bridge is bike-powered (ADR 0018 / [[project-wifi-bridge-ota]]).** The ESP is off until the key is on, so capture starts *after* key-on — no pre-key-off silence window.
- Rider on the throttle for Phases D and E — different posture from the dash-inputs experiment. Stand beside the bike; keep weight off the seat.
- Have a tach or the live view visible so the RPM setpoints in Phase E can be held within ±200 RPM.

## Procedure

> **Scripted** — driven by [`2026-07-12-neutral-rpm-sweep.procedure.yaml`](2026-07-12-neutral-rpm-sweep.procedure.yaml) (ADR 0006). Run with `bin/experiment-wifi-bridge <label> <yaml>` — the operator screen handles step ordering, durations, and the per-phase marks automatically; the rider just follows the prompts.
>
> **Timing convention:** auto-marks fire at **step start** (the moment the rider is cued to open the throttle), NOT at the peak of the blip or the RPM landing. The bus broadcast is keyed off the throttle plate edge, not the RPM response, so this is the correct reference for window analysis.

1. Key must already be ON before running (wifi-bridge boots on ignition). Kill switch in RUN, neutral, side stand down.
2. Start capture: `bin/experiment-wifi-bridge neutral-rpm-sweep docs/experiments/2026-07-12-neutral-rpm-sweep.procedure.yaml`.
3. YAML begins with a short baseline, then starter press, then 30 s of clean idle before Phase D.

### Phase D — throttle blip engine-on

Three blips, increasing in aggression — auto-mark at each blip start.

- Small blip (~25 % grip, ~0.5 s). RPM should rise to ~3000. Wait 4 s for idle to settle.
- Medium blip (~50 % grip, ~0.5 s). RPM to ~5000. Wait 4 s.
- Bigger blip (~75 % grip, ~0.5 s). RPM to ~7000. Wait 4 s. **Do not** go to redline on a static engine — no load means RPM climbs explosively and risks valve float / over-rev.

### Phase E — held RPM setpoints in neutral (matches [[2026-06-23-engine-driven-rear-spin]])

Five setpoints, held 12 s each in neutral, with 6 s idle rests between. `setpoint` auto-mark fires at each hold start. Key delta from Phase D: no load on the engine, so at matched RPM the throttle position needed here will be **lower** than in the in-gear capture, and any genuinely load-driven byte will read lower too. The 12 s hold gives the same window length the in-gear analysis script already expects (`WINDOW_SKIP_S=3`, `WINDOW_LEN_S=8`).

Engine has been at idle/blip for several minutes by this point — coolant should be at full operating temperature, which keeps the comparison against the in-gear capture clean (both at warm floor for any coolant-keyed quantities).

- ~2000 RPM hold, 12 s. Settle 6 s.
- ~2500 RPM hold, 12 s. Settle 6 s.
- ~3500 RPM hold, 12 s. Settle 6 s.
- ~4500 RPM hold, 12 s. Settle 6 s.
- ~5500 RPM hold, 12 s. Settle 6 s. **Do not exceed ~6500 RPM in neutral** — same valve-float caveat as Phase D.

### Shutdown

Kill switch, decay window, key off, tail silence. `session.md` — log the ABS mode the session ran in (read from the 4 s startup display), any rev-limiter intervention on the throttle blips, and any RPM setpoint the rider had trouble keeping steady in Phase E.

## Analysis plan

1. **Phase D — throttle blip engine-on (transient response).**
   - `120` D2: confirm same encoding as engine-off (linear, same scale) → promote [[signal-throttle-position]] from engine-off to engine-on-confirmed.
   - `12A` D0 bit 1 (throttle-open flag): same threshold as engine-off?
   - `12A` D1 bit 6: should be **invariant** to throttle/RPM (per the manual, the mode bit is ABS-only and not engine-conditioned). If it moves with throttle or RPM, that contradicts the manual and is itself a finding worth flagging.
   - **`540` D1 transient response.** The throttle blips give three fast throttle→RPM excursions. Because throttle plate position leads RPM (throttle snaps open, RPM rises over ~100–300 ms), the leading-edge behaviour separates throttle-following from RPM-following:
     - D1 spikes with the throttle leading edge (within one or two 100 ms frames) ⇒ **throttle / MAP-keyed**.
     - D1 lags the throttle and tracks decoded RPM ⇒ **RPM-keyed**.
     - D1 stays flat through all three blips ⇒ **coolant-keyed only** (Phase E setpoints will then also read flat — single confirmation).
   - RPM-tracking bytes generally: any byte that climbs with `120` D0,D1 — engine load %, ignition advance, fuel pulse-width. Plot suspects against decoded RPM. The held setpoints in Phase E are the cleaner steady-state read for these; Phase D mostly informs which candidates are worth ranking in Phase E.

2. **Phase E — held RPM setpoints (matched-RPM comparison vs [[2026-06-23-engine-driven-rear-spin]]).**
   - Run [`scripts/engine_load_scan.py`](../../scripts/engine_load_scan.py) on this capture with `--session logs/<this session>` and compare the per-setpoint table directly against the in-gear table from the rear-spin capture.
   - **`540` D1 (the [[signal-fuel-injection-setpoint]] re-attribution).** Pre-existing evidence from the rear-spin capture already ruled MAP/engine-load out and fit `D1 ≈ 14 + 0.8 × throttle%` off-idle (see [[signal-fuel-injection-setpoint]] preamble). Phase E discriminates throttle-derived from RPM-derived. At matched RPM:
     - D1(neutral) < D1(in-gear), and a linear D1-vs-throttle fit in Phase E recovers the same slope as the in-gear fit → **throttle-derived** (the leading-hypothesis outcome). Rewrite the finding under a throttle-fuel-index name; the coolant offset stays as the idle-only behaviour.
     - D1(neutral) ≈ D1(in-gear) within noise → **RPM-derived**, and the in-gear throttle correlation was just RPM and throttle being co-linear in that capture. Rewrite the finding around RPM-keyed semantics.
     - D1(neutral) > D1(in-gear) at matched RPM → unexpected; would suggest some inverse-load behaviour or a sensor we don't know about — flag as a new puzzle.
   - **Other unknown bytes from `engine_load_scan.py` Q2b** (`121` D0..D3 in particular, which showed non-monotonic shapes in the in-gear sweep). For each:
     - Same matched-RPM table. A byte that tracks RPM identically in both captures is RPM-derived (likely ignition advance base, RPM-banded fuel map index, etc.).
     - A byte that differs between captures at matched RPM is load- or throttle-derived (MAP, injection pulse-width, computed load %).
     - Non-monotonic shapes that **reproduce** between the two captures at matched RPM are load- or RPM-banded look-ups, not noise.
   - **`12D` D1 bit 0 speed-vs-RPM discriminator** (per [[signal-12d-d1-bit0]]). The rear-spin capture is 1st-gear-only, so RPM and rear km/h are tightly coupled; Phase E in neutral has RPM up to 5500 with vehicle speed = 0. If the bit fires at 5500 RPM in neutral, it's RPM-keyed; if it doesn't, the 27 km/h speed threshold from the in-gear reading is confirmed.
   - **Engine-on baseline byte values at idle.** The 30 s idle-settled window at the start of this capture, plus the 6 s rest windows between Phase E setpoints, give a clean idle reference. Any byte that's static at idle and non-static at the setpoints is a strong engine-load candidate even without the in-gear comparison.

3. **Cross-phase invariants.** Coolant temp (`540` D5,D6) should drift very slightly upward across the session (Phase E adds load-free revs which warm the engine a little). Gear should remain neutral. Side stand should remain down. Any of these moving without the corresponding input is a calibration issue with the experiment.

4. **MIL bit (free finding from the engine-on timeline).** Per the manual the malfunction indicator lamp is ON whenever the engine is not running and OFF whenever it is. This session gives two MIL transitions — key-on → idle (ON → OFF at the starter/idle-settled mark) and kill → silence (OFF → ON at the kill mark). Diff the post-key-on-engine-off window against the steady-idle window: any bit that's HIGH pre-start and LOW at idle is a MIL candidate. Passive analysis, no extra rider action needed. See [[dash-warning-catalog]].

5. **Side-stand engine-on confirmation.** [[signal-side-stand]] is confirmed engine-off at `540` D3 bit 0. The long idle-settled window gives free engine-on confirmation with the stand held down throughout — the bit should stay steady LOW (stand-down polarity from the finding) across the entire idle window. Any drift is worth flagging.

## Expected outcomes

- **Throttle decoder holds engine-on** → promote engine-off throttle finding from `provisional` (if that's how it was filed) to `confirmed` engine-on.
- **An RPM-tracking byte appears** → new candidate finding; may need a dedicated dyno-style sweep to fully characterise.
- **`540` D1 reads lower in Phase E than in [[2026-06-23-engine-driven-rear-spin]] at matched RPM** → [[signal-fuel-injection-setpoint]] is actually a **throttle-derived fuel index** (or, alternate outcome, RPM-derived); rewrite the finding under the new name and leave the cold→warm walk as a secondary idle-floor effect. This is the headline outcome of the load-decoupling design.
- **`121` D0..D3 reproduce the non-monotonic RPM-banded shape in Phase E** → those bytes encode an RPM-keyed look-up (ignition advance map, fuel map index, or similar) independent of load; deserves a follow-up session targeting the band boundaries.
- **`12D` D1 bit 0 stays LOW at 5500 RPM neutral** → confirms the 27 km/h speed threshold from the in-gear reading. Fires at 5500 RPM neutral → the bit is RPM-keyed and the in-gear reading was a coincidence of gear ratio.

## Follow-ups

- If the `540` D1 re-attribution lands, rename the finding and cross-reference from any downstream signal work.
- **Mode-vs-engine independence.** Combined with [[2026-07-12-dash-inputs]], a small back-to-back comparison at matched idle across ROAD and SUPERMOTO would confirm the manual's ABS-only claim: throttle-position and RPM bytes should read identical across modes.
- If Phase E is messy (RPM setpoints too jittery to fit cleanly), re-run just Phase E with a tighter setpoint discipline or bracket each hold with longer settles.
