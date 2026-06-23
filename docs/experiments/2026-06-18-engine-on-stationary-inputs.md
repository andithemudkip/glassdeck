---
date: 2026-06-18
status: planned
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/post-kill-decay-groups
    - can/signal-rpm
    - can/signal-throttle-position
    - can/signal-warmup-index
  references:
    - ktm-can-decoder
    - svartpilen-401-dash-user-manual
  experiments:
    - 2026-06-17-engine-idle-baseline-x3
    - 2026-06-17-payload-diff-idle
    - 2026-06-18-throttle-sweep-engine-off
    - 2026-06-23-engine-driven-rear-spin
  logs: []
---

# Engine-on stationary inputs — ROAD/SUPERMOTO, trip reset, dash buttons, throttle blip

## Hypothesis

After the engine-off batch resolves the basic level signals (kill, throttle, gear, clutch, side stand), the next layer of decoding is the **body-controller / instrument-cluster signals** — inputs the rider drives via the dashboard, not via mechanical levers. These should surface in the slow-decay group (`12A`, `12D`, `12E`, `450`, `541`, `5A0`), which we hypothesise originates from one or more dash-side modules.

Five overlapping sub-hypotheses, all to be tested in one session because each input alone produces a thin signal:

1. **Mode toggle (ROAD ↔ SUPERMOTO):** per the Svartpilen 401 owner's manual this toggle is **ABS-only** — it disables rear-wheel ABS for supermoto-style riding and changes nothing else (no map, no power delta, no TC tweak). The ABS ECU still needs to know the state, so we expect the mode to be broadcast somewhere — KTM ties this on related platforms to `12A` D1 bit 6, and our idle `12A` D1 was LOW-CARD(2), so it's the leading candidate. A deliberate toggle resolves the bit; interpretation is **rear-ABS-enable**, not requested-map. Per the manual the toggle procedure is: navigate to the ABS screen (MODE button presses), then hold SET for 3–5 s while stationary.
2. **Trip reset:** per the manual, hold SET for 3 s while on the Trip 1 (or Trip 2) screen. Likely targets a momentary bit somewhere in the body-controller cluster (`12E`, `450`, `541` are candidates because they're slow-decay and currently UNKNOWN/LOW-CARD). May or may not be distinguishable from a generic SET-long-press event — the mode toggle in (1) is also a SET long-press, just in a different display context.
3. **Dash button short presses:** the cluster has only two buttons, **MODE** and **SET**. MODE short-press cycles displays (ABS → Info if warnings → ODO → Trip 1 → Trip 2 → wrap). SET short-press cycles sub-menus within the current display. Short presses are candidate momentary bits in the slow-decay group; MODE-vs-SET may be a single button-event line with an enum, or two separate bits.
4. **Throttle blip engine-on:** confirms the throttle-position decoding from [2026-06-18-throttle-sweep-engine-off](2026-06-18-throttle-sweep-engine-off.md) holds with engine running.
5. **RPM-driven secondary signals + throttle-vs-RPM discrimination for `540` D1.** With the engine running, two complementary motion patterns are useful:
   - **Throttle blips** (Phase D, fast transients) make RPM-tracking bytes visible against the steady idle background. The payload-diff classified most `121` bytes as LOW-CARD without a hypothesis — engine-on blipping is the natural way to start separating them.
   - **Held RPM setpoints in neutral** (Phase E, matched to [[2026-06-23-engine-driven-rear-spin]] in 1st gear) decouple throttle from RPM. Analysis of the in-gear capture ([`scripts/engine_load_scan.py`](../../scripts/engine_load_scan.py) + [`scripts/idle_load_compare.py`](../../scripts/idle_load_compare.py)) already established two things about `540` D1: (a) off-idle it fits `D1 ≈ 14 + 0.8 × throttle%` cleanly across the 5 setpoints, and (b) in-gear-clutch-out at idle (genuine drivetrain drag) reads identical to neutral-idle at matched RPM/throttle — **MAP / engine-load is ruled out** because a real load signal would respond to drivetrain drag at fixed throttle. The leading interpretation is now **throttle-derived with a coolant-keyed idle offset**, recasting the prior [[signal-warmup-index]] reading. Phase E discriminates this from the remaining alternative (RPM-derived) cleanly:
     - **D1(neutral) < D1(in-gear) at matched RPM** ⇒ throttle-derived. In neutral the same RPM is reached at much lower throttle, so a throttle-keyed byte reads lower. This is the leading-hypothesis prediction.
     - **D1(neutral) ≈ D1(in-gear) at matched RPM** ⇒ RPM-derived. Throttle doesn't matter; only RPM drives the value.
     - **D1 tracks throttle within Phase E too** ⇒ direct re-derivation of [[signal-throttle-position]]; check the linear fit and the residual structure against the in-gear fit for any RPM-banded extra term.
   - The same per-setpoint table from `engine_load_scan.py` applied to Phase E will surface other unknown bytes whose RPM/throttle correlation differs between the two captures — `121` D0..D3 in particular, where the in-gear capture showed non-monotonic RPM-banded shapes that Phase E will reproduce (RPM-keyed) or wash out (load- or throttle-keyed in a way the in-gear data already accounted for).

The session structure matters: each input is bracketed by a held window with no other rider activity, so per-window statistics cleanly attribute movement to one input. Press the right event-mark key on every transition.

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. **Engine running, idling**, in neutral, side stand down (or paddock stand if available), kill switch in run.
- Engine should be at operating temperature before the session begins (idle for 5–10 min in advance, or do this immediately after a short warm-up ride). Coolant temp at operating temp keeps idle stable and removes a confound.
- Adapter / firmware / host as before.
- Rider stands beside the bike (not seated) to keep weight off the seat — some bikes broadcast a seat-occupancy bit and we don't want to add a fifth input axis to this session by accident.
- Have a stopwatch / mental clock — phases run on time, not on "how it feels."

## Procedure

> **Scripted** — driven by [`2026-06-18-engine-on-stationary-inputs.procedure.yaml`](2026-06-18-engine-on-stationary-inputs.procedure.yaml) (ADR 0006). Run with `--experiment` and the operator screen handles step ordering, durations, and the per-phase marks automatically; the rider just follows the prompts.
>
> **Timing convention shift from the original prose plan:** auto-marks fire at **step start** (the moment the rider is cued to begin the action — start of SET-hold, start of throttle blip), NOT at the dash's visual confirmation. The bus broadcast is keyed off the press edge, not the dash redraw, so this is the correct reference for window analysis. The narrative below describes intent; the YAML is the source of truth for what actually runs.

1. Start capture: `python scripts/capture.py --port /dev/cu.usbmodem101 --label engine-on-stationary-inputs --experiment docs/experiments/2026-06-18-engine-on-stationary-inputs.procedure.yaml`.
2. 5 s key-off baseline.
3. Key on, **space**. 30 s settling.
4. Press starter (**`s`**). Let engine catch. **`e`** when idle is stable. Hold 30 s of clean idle (idle-baseline replica window — useful to subtract from later phases).

### Phase A — ROAD ↔ SUPERMOTO toggle

Per the manual: navigate to the **ABS** screen with MODE button short-presses (the startup test sequence shows the current ABS mode for 4 s, so you'll know the starting mode without navigating). Then hold **SET** for 3–5 s to toggle; the dash flashes the new mode briefly. Manual warning: **do not open the throttle while changing modes** — keep the right wrist still through Phase A. If the mode flashes on the dash after the hold, that indicates a fault and the experiment should be aborted.

Mark `space` on each MODE short-press used to navigate. Mark `m` at the moment the dash shows the new mode.

1. MODE presses as needed to reach ABS (`space` each).
2. Hold SET 3–5 s. `m` when the new mode is shown. Hold 8 s of idle.
3. Hold SET 3–5 s (toggle back). `m`. Hold 8 s.
4. Hold SET 3–5 s (forward). `m`. Hold 8 s.
5. Hold SET 3–5 s (back to starting mode). `m`. Hold 8 s.

Eight-second holds because mode-change broadcasts may include a settling transient (the ABS ECU updating its enable line, the dash redrawing the mode indicator); 8 s comfortably exceeds the 100 ms cycle of the slowest IDs.

### Phase B — trip reset

Per the manual: navigate to **Trip 1** with MODE short-presses, then hold **SET** for 3 s; the trip distance jumps to 0.0. Two resets to confirm reproducibility.

6. MODE presses to reach Trip 1 (`space` each).
7. Hold SET 3 s. `r` at the moment Trip 1 reads 0.0. Hold 8 s.
8. Hold SET 3 s (no-op reset — already 0). `r`. Hold 8 s. This separates "SET long-press event" from "trip counter actually changed value."

### Phase C — dash button short presses

The cluster has only **MODE** and **SET**. MODE short-press cycles displays; SET short-press cycles sub-menus within the current display. We've already exercised SET long-press in Phases A and B; this phase is short-presses only.

9. From Trip 1 (where Phase B left us), SET short-press cycles Trip 1 sub-menus (Time / Avg Speed / Avg F.C. / back to distance). One press per beat, `space` at each press, 4 s hold. Press through the full cycle.
10. MODE short-press to Trip 2. `space`. 4 s hold. SET short-press through Trip 2 sub-menus (same set as Trip 1). `space` each, 4 s hold each.
11. MODE short-press to ABS. `space`. 4 s hold. (SET long-press is suppressed here — would re-toggle mode.)
12. MODE short-press to ODO. `space`. 4 s hold. SET short-press cycles ODO sub-menus (ODO / Fuel Range / Service). `space` each, 4 s hold each.
13. Final 8 s hold on ODO.

### Phase D — throttle blip engine-on

Three blips, increasing in aggression — single small **`t`** at the start of each, no need to mark the close.

14. Small blip (~25 % grip, ~0.5 s). `t`. RPM should rise to ~3000. Wait 4 s for idle to settle.
15. Medium blip (~50 % grip, ~0.5 s). `t`. RPM to ~5000. Wait 4 s.
16. Bigger blip (~75 % grip, ~0.5 s). `t`. RPM to ~7000. Wait 4 s. **Do not** go to redline on a static engine — no load means RPM climbs explosively and risks valve float / over-rev.

### Phase E — held RPM setpoints in neutral (matches [[2026-06-23-engine-driven-rear-spin]])

Five setpoints at the same nominal RPM targets as the in-gear rear-spin sweep (2000, 2500, 3500, 4500, 5500), held ~12 s each in neutral, with idle rests between. Analysis reads RPM from CAN frame-by-frame, so ±200 RPM of target is fine — what matters is **steady throttle hold** for the full 12 s, not the exact number.

Key delta from Phase D: no load on the engine (neutral, no gear engaged), so at matched RPM the throttle position needed in Phase E will be **lower** than in the in-gear capture, and any genuinely load-driven byte will read lower too. The 12 s hold gives the same window length the in-gear analysis script already expects (`WINDOW_SKIP_S=3`, `WINDOW_LEN_S=8`).

Engine has now been at idle/blip for several minutes — coolant should be at full operating temperature, which keeps the comparison against the in-gear capture clean (both at warm floor for any coolant-keyed quantities).

17. ~2000 RPM hold, 12 s. `setpoint` auto-mark at start. Settle to idle 6 s between.
18. ~2500 RPM hold, 12 s. Settle 6 s.
19. ~3500 RPM hold, 12 s. Settle 6 s.
20. ~4500 RPM hold, 12 s. Settle 6 s.
21. ~5500 RPM hold, 12 s. Settle 6 s. **Do not exceed ~6500 RPM in neutral** — same valve-float caveat as Phase D.

### Shutdown

22. Kill switch (**`k`**). Let everything decay. Key off when silent. Wait 2 s. `q`.
23. `session.md` — log the starting ABS mode (ROAD or SUPERMOTO, read from the 4 s startup display), confirm Trip 1 was the one reset (not Trip 2), any unexpected dash behaviour at mode toggle (flashing = fault, abort), any rev-limiter intervention on the throttle blips, and any RPM hold the rider had trouble keeping steady in Phase E.

## Analysis plan

1. **Phase A — mode toggle.**
   - `12A` D1 bit 6: does it alternate with the `m` marks? If yes, polarity (ROAD=0/SUPERMOTO=1 or vice versa) → [`docs/findings/can/signal-ride-mode.md`](../findings/can/signal-ride-mode.md) at `confirmed`, **semantics = rear-ABS-enable** (per manual: this toggle disables rear ABS and nothing else).
   - All bits in the slow-decay group: per-phase mode value. Any bit that alternates is candidate; rank by purity.
   - Cross-check against the idle baseline's LOW-CARD(2) bytes in `12A`, `12D`, `12E`, `450`, `541` — these are the most likely to be mode bits.
   - **Reject flat-ON candidates.** Per the manual the ABS warning lamp stays ON below ~6 km/h, so any bit that drives that lamp will be ON-flat across this whole stationary capture. It lives in the same ABS-side payloads we're scanning. The mode bit must *alternate* with `m` marks — a flat-ON bit in `12A`/`12D` is a candidate for the ABS-warning-lamp line, not for ride mode.
2. **Phase B — trip reset.**
   - Look for a momentary bit (1 for one or a few frames around each `r`, then 0). Don't expect a steady-level bit — trip reset is an event, not a state.
   - Compare the two `r` events: the first reset changed Trip 1's value (X.X → 0.0), the second was a no-op (0.0 → 0.0). Any bit that fires on the first but not the second is the **value-changed** signal; any bit that fires on both is a **SET-long-press** signal. They may be the same bit (the dash broadcasts the press event regardless of effect) or different.
3. **Phase C — dash button presses.**
   - Frame-by-frame diff in a 100 ms window around each `space` mark in Phase C. Expect a momentary bit indicating "button pressed" — likely one bit/enum for MODE and another for SET (or a single button-id field).
   - Cross-check against the SET-long-press events in Phases A and B: a SET short-press in Phase C should share whatever line a SET long-press uses, distinguished only by duration. If the long-press and short-press lines differ, the cluster pre-classifies the press type before broadcasting.
4. **Phase D — throttle blip engine-on (transient response).**
   - `120` D2: confirm same encoding as engine-off (linear, same scale).
   - `12A` D0 bit 1 (throttle-open flag): same threshold as engine-off?
   - `12A` D1 bit 6: should be **invariant** to throttle/RPM (per the manual, the mode bit is ABS-only and not engine-conditioned). If it moves with throttle or RPM, that contradicts the manual and is itself a finding worth flagging.
   - **`540` D1 transient response** — the throttle blips give three fast throttle→RPM excursions. Because throttle plate position leads RPM (throttle snaps open, RPM rises over ~100–300 ms), the leading-edge behaviour separates throttle-following from RPM-following:
     - D1 spikes with the throttle leading edge (within one or two 100 ms frames) ⇒ **throttle / MAP-keyed**.
     - D1 lags the throttle and tracks decoded RPM ⇒ **RPM-keyed**.
     - D1 stays flat through all three blips ⇒ **coolant-keyed only** (Phase E setpoints will then also read flat — single confirmation).
   - RPM-tracking bytes generally: any byte that climbs with `120` D0,D1 — engine load %, ignition advance, fuel pulse-width. Plot suspects against decoded RPM. The held setpoints in Phase E are the cleaner steady-state read for these; Phase D mostly informs which candidates are worth ranking in Phase E.

5. **Phase E — held RPM setpoints (matched-RPM comparison vs [[2026-06-23-engine-driven-rear-spin]]).**
   - Run [`scripts/engine_load_scan.py`](../../scripts/engine_load_scan.py) on this capture with `--session logs/<this session>` and compare the per-setpoint table directly against the in-gear table from the rear-spin capture.
   - **`540` D1 (the [[signal-warmup-index]] re-attribution).** Pre-existing evidence from the rear-spin capture already ruled MAP/engine-load out and fit `D1 ≈ 14 + 0.8 × throttle%` off-idle (see [[signal-warmup-index]] preamble). Phase E discriminates throttle-derived from RPM-derived. At matched RPM:
     - D1(neutral) < D1(in-gear), and a linear D1-vs-throttle fit in Phase E recovers the same slope as the in-gear fit → **throttle-derived** (the leading-hypothesis outcome). Rewrite the finding under a throttle-fuel-index name; the coolant offset stays as the idle-only behaviour.
     - D1(neutral) ≈ D1(in-gear) within noise → **RPM-derived**, and the in-gear throttle correlation was just RPM and throttle being co-linear in that capture. Rewrite the finding around RPM-keyed semantics.
     - D1(neutral) > D1(in-gear) at matched RPM → unexpected; would suggest some inverse-load behaviour or a sensor we don't know about — flag as a new puzzle.
   - **Other unknown bytes from `engine_load_scan.py` Q2b** (`121` D0..D3 in particular, which showed non-monotonic shapes in the in-gear sweep). For each:
     - Same matched-RPM table. A byte that tracks RPM identically in both captures is RPM-derived (likely ignition advance base, RPM-banded fuel map index, etc.).
     - A byte that differs between captures at matched RPM is load- or throttle-derived (MAP, injection pulse-width, computed load %).
     - Non-monotonic shapes that **reproduce** between the two captures at matched RPM are load- or RPM-banded look-ups, not noise.
   - **Engine-on baseline byte values at idle.** The 30 s idle-settled window at the start of this capture, plus the 6 s rest windows between Phase E setpoints, give a clean idle reference. Any byte that's static at idle and non-static at the setpoints is a strong engine-load candidate even without the in-gear comparison.
6. **Cross-phase invariants.** Coolant temp (`540` D5,D6) should drift very slightly upward across the ~5 min session (Phase E adds load-free revs which warm the engine a little). Gear should remain neutral. Side stand should remain down. Any of these moving without the corresponding input is a calibration issue with the experiment.
7. **MIL bit (free finding from existing transitions).** Per the manual the malfunction indicator lamp is ON whenever the engine is not running and OFF whenever it is. The existing timeline already gives two MIL transitions: key-on → idle (ON → OFF at the `e` mark) and kill → silence (OFF → ON at the `k` mark). Diff a key-on-engine-off window against the steady-idle window: any bit that's HIGH in both engine-off windows and LOW in the idle window is a MIL candidate. We need this signal for the dashboard regardless — passive analysis only.
8. **Mode-vs-engine independence (manual cross-check).** Per the owner's manual the mode toggle is rear-ABS-only. So between Phase A and Phases D/E: idle RPM, idle throttle position, and any candidate engine-load / fuelling bytes (e.g. `540` D1) should be **identical across the two modes**. If they differ, the manual is incomplete and the toggle also nudges an engine-side parameter — record as a contradicting finding.

## Expected outcomes

- **`12A` D1 bit 6 alternates with mode toggle** → ride-mode (rear-ABS-enable) finding confirmed; KTM/Husqvarna platform mapping holds.
- **Mode bit lives elsewhere** → identify and finding.
- **No engine-side byte differs between the two modes** → consistent with the manual; mode is purely an ABS input.
- **A momentary bit somewhere in the slow-decay group fires on each dash button press** → button-event finding, but probably multiple bits/encodings — full decode may need a follow-up dedicated session.
- **Trip reset is a *different* bit from the short-press cluster** → consistent with a "long press detected" sentinel separate from the raw button line.
- **Throttle decoder holds engine-on** → promote engine-off throttle finding from `provisional` (if that's how it was filed) to `confirmed` engine-on.
- **An RPM-tracking byte appears** → new candidate finding; may need a dedicated dyno-style sweep to fully characterise.
- **`540` D1 reads lower in Phase E than in [[2026-06-23-engine-driven-rear-spin]] at matched RPM** → [[signal-warmup-index]] is actually an **engine-load / MAP signal**; rewrite the finding under a new name, leave the cold→warm walk as a secondary idle-floor effect. This is the headline outcome of the load-decoupling design.
- **`121` D0..D3 reproduce the non-monotonic RPM-banded shape in Phase E** → those bytes encode an RPM-keyed look-up (ignition advance map, fuel map index, or similar) independent of load; deserves a follow-up session targeting the band boundaries.

## Follow-ups

- This is the most input-dense single capture in the plan. If the analysis is messy (multiple things moving in lockstep, hard to attribute), split into per-input reruns (mode-only, dash-buttons-only) for clean signals.
- The dash-button decode in particular may need a dedicated follow-up session — one button per capture, several presses each — depending on how clean Phase C looks.
- Once mode and dash buttons are decoded, the dashboard MVP's input-mirror surface is essentially complete (kill / gear / clutch / stand / throttle / RPM / coolant / mode / dash buttons). The remaining big unknown is **vehicle speed**, which needs the motion capture currently listed in `status.md` as next action 3.
