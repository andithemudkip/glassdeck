---
date: 2026-06-18
status: planned
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/post-kill-decay-groups
    - can/signal-rpm
  references:
    - ktm-can-decoder
    - svartpilen-401-dash-user-manual
  experiments:
    - 2026-06-17-engine-idle-baseline-x3
    - 2026-06-17-payload-diff-idle
    - 2026-06-18-throttle-sweep-engine-off
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
5. **RPM-driven secondary signals:** with the engine running and the throttle blipped, RPM moves from idle ~1700 up to maybe ~4000–5000 briefly. Any byte that tracks RPM (a load index, a derived gear-ratio in neutral, an engine-load %) becomes visible. The payload-diff classified most `121` bytes as LOW-CARD without a hypothesis — engine-on blipping is the natural way to start separating them.

The session structure matters: each input is bracketed by a held window with no other rider activity, so per-window statistics cleanly attribute movement to one input. Press the right event-mark key on every transition.

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. **Engine running, idling**, in neutral, side stand down (or paddock stand if available), kill switch in run.
- Engine should be at operating temperature before the session begins (idle for 5–10 min in advance, or do this immediately after a short warm-up ride). Coolant temp at operating temp keeps idle stable and removes a confound.
- Adapter / firmware / host as before.
- Rider stands beside the bike (not seated) to keep weight off the seat — some bikes broadcast a seat-occupancy bit and we don't want to add a fifth input axis to this session by accident.
- Have a stopwatch / mental clock — phases run on time, not on "how it feels."

## Procedure

1. Start capture: `python scripts/capture.py --port /dev/cu.usbmodem101 --label engine-on-stationary-inputs`.
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

17. Kill switch (**`k`**). Let everything decay. Key off when silent. Wait 2 s. `q`.
18. `session.md` — log the starting ABS mode (ROAD or SUPERMOTO, read from the 4 s startup display), confirm Trip 1 was the one reset (not Trip 2), any unexpected dash behaviour at mode toggle (flashing = fault, abort), any rev-limiter intervention on the throttle blips.

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
4. **Phase D — throttle blip engine-on.**
   - `120` D2: confirm same encoding as engine-off (linear, same scale).
   - `12A` D0 bit 1 (throttle-open flag): same threshold as engine-off?
   - `12A` D1 bit 6: should be **invariant** to throttle/RPM (per the manual, the mode bit is ABS-only and not engine-conditioned). If it moves with throttle or RPM, that contradicts the manual and is itself a finding worth flagging.
   - RPM-tracking bytes: any byte that climbs with `120` D0,D1 — engine load %, MAP-derived signal, etc. Plot suspects against decoded RPM.
   - **`540` D1 — physical-quantity discriminator for [[signal-warmup-index]].** At warm idle this byte sits at ~0x0E (14). The three blips give three throttle/RPM excursions on top of a steady thermal background, which separates the three open candidates:
     - **Rises with throttle** (e.g., 14 → 18-22 during the blip, returns to 14 after) → power enrichment on top of the warm-idle baseline → byte is a **fuelling enrichment %** (cold-start + power-enrichment composite). Consistent with the cold→warm 25→14 walk being warm-up enrichment dialling down.
     - **Drops with throttle** (e.g., 14 → 11-12 during the blip) → an AFR-shaped quantity that goes richer under load. Fits the warm-idle ~14 ≈ stoich coincidence but doesn't explain the cold-start direction (cold engines run richer = lower AFR, but our cold value is *higher*) — flag as conflict, needs a separate cold-start engine-on capture to resolve.
     - **Flat through all three blips** → byte is purely coolant-temp-keyed, independent of fuelling/load → points at **fast-idle target / idle-air-bypass position** rather than an enrichment quantity.
     - **Moves with RPM but not with throttle position** (the blips have correlated RPM and throttle — distinguishable by looking at the recovery: throttle returns to 0 fast, RPM bleeds down slower over 1-2 s) → RPM-conditioned, not throttle-conditioned. Less likely given the data, but worth checking.
   - Plot `540` D1 alongside `120` D2 (throttle) and decoded RPM across all three blips on one timeline; the three blips give three independent reads of the same discriminator.
5. **Cross-phase invariants.** Coolant temp (`540` D5,D6) should drift very slightly upward across the ~3 min session. Gear should remain neutral. Side stand should remain down. Any of these moving without the corresponding input is a calibration issue with the experiment.
6. **MIL bit (free finding from existing transitions).** Per the manual the malfunction indicator lamp is ON whenever the engine is not running and OFF whenever it is. The existing timeline already gives two MIL transitions: key-on → idle (ON → OFF at the `e` mark) and kill → silence (OFF → ON at the `k` mark). Diff a key-on-engine-off window against the steady-idle window: any bit that's HIGH in both engine-off windows and LOW in the idle window is a MIL candidate. We need this signal for the dashboard regardless — passive analysis only.
7. **Mode-vs-engine independence (manual cross-check).** Per the owner's manual the mode toggle is rear-ABS-only. So between Phase A and Phase D: idle RPM, idle throttle position, and any candidate engine-load / fuelling bytes (e.g. `540` D1) should be **identical across the two modes**. If they differ, the manual is incomplete and the toggle also nudges an engine-side parameter — record as a contradicting finding.

## Expected outcomes

- **`12A` D1 bit 6 alternates with mode toggle** → ride-mode (rear-ABS-enable) finding confirmed; KTM/Husqvarna platform mapping holds.
- **Mode bit lives elsewhere** → identify and finding.
- **No engine-side byte differs between the two modes** → consistent with the manual; mode is purely an ABS input.
- **A momentary bit somewhere in the slow-decay group fires on each dash button press** → button-event finding, but probably multiple bits/encodings — full decode may need a follow-up dedicated session.
- **Trip reset is a *different* bit from the short-press cluster** → consistent with a "long press detected" sentinel separate from the raw button line.
- **Throttle decoder holds engine-on** → promote engine-off throttle finding from `provisional` (if that's how it was filed) to `confirmed` engine-on.
- **An RPM-tracking byte appears** → new candidate finding; may need a dedicated dyno-style sweep to fully characterise.

## Follow-ups

- This is the most input-dense single capture in the plan. If the analysis is messy (multiple things moving in lockstep, hard to attribute), split into per-input reruns (mode-only, dash-buttons-only) for clean signals.
- The dash-button decode in particular may need a dedicated follow-up session — one button per capture, several presses each — depending on how clean Phase C looks.
- Once mode and dash buttons are decoded, the dashboard MVP's input-mirror surface is essentially complete (kill / gear / clutch / stand / throttle / RPM / coolant / mode / dash buttons). The remaining big unknown is **vehicle speed**, which needs the motion capture currently listed in `status.md` as next action 3.
