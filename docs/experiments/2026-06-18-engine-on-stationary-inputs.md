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

1. **Mode toggle (ROAD ↔ SUPERMOTO):** per the Svartpilen 401 owner's manual this toggle is **ABS-only** — it disables rear-wheel ABS for supermoto-style riding and changes nothing else (no map, no power delta, no TC tweak). The ABS ECU still needs to know the state, so we expect the mode to be broadcast somewhere — KTM ties this on related platforms to `12A` D1 bit 6, and our idle `12A` D1 was LOW-CARD(2), so it's the leading candidate. A deliberate toggle resolves the bit; interpretation is **rear-ABS-enable**, not requested-map.
2. **Trip reset:** the long-press input on the dash. Likely targets a momentary bit somewhere in the body-controller cluster (`12E`, `450`, `541` are candidates because they're slow-decay and currently UNKNOWN/LOW-CARD).
3. **Other dash buttons:** the bike has a mode-select / set button cluster. Short presses are different signals from the long-press trip reset. Any combination of bits across the slow-decay group is fair game.
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

Three toggles. The mode toggle on this bike is a dash button combination — confirm the exact combo before starting (typically a short press on the mode/menu button when on the home screen). Press **`m`** at the instant of each toggle.

1. Toggle 1 (whatever the current mode is → the other). `m`. Hold 8 s.
2. Toggle 2 (back). `m`. Hold 8 s.
3. Toggle 3 (forward again). `m`. Hold 8 s.
4. Toggle 4 (back to starting mode). `m`. Hold 8 s.

Eight-second holds because mode-change broadcasts may include a settling transient (the ABS ECU updating its enable line, the dash redrawing the mode indicator); 8 s comfortably exceeds the 100 ms cycle of the slowest IDs.

### Phase B — trip reset

Two presses to confirm reproducibility. Trip reset is a long-press on the mode/set button (or the dedicated trip button — confirm before starting).

5. Long-press trip reset. `r` at the start of the press, release whenever the bike acknowledges (trip A or B shows 0). Hold 8 s.
6. Long-press trip reset again. `r`. Hold 8 s.

### Phase C — dash button short presses

This catches anything broadcast on a button event independent of any state change.

7. Short-press the mode/menu button (cycle through display screens — odometer, trip A, trip B, voltage, etc.). One press, **space**. Hold 4 s.
8. Repeat for each press needed to cycle through all dash screens once. Each press: **space** at the press, 4 s hold. Press as many times as the dash has screens.
9. Final 8 s hold once back at the starting screen.

### Phase D — throttle blip engine-on

Three blips, increasing in aggression — single small **`t`** at the start of each, no need to mark the close.

10. Small blip (~25 % grip, ~0.5 s). `t`. RPM should rise to ~3000. Wait 4 s for idle to settle.
11. Medium blip (~50 % grip, ~0.5 s). `t`. RPM to ~5000. Wait 4 s.
12. Bigger blip (~75 % grip, ~0.5 s). `t`. RPM to ~7000. Wait 4 s. **Do not** go to redline on a static engine — no load means RPM climbs explosively and risks valve float / over-rev.

13. Kill switch (**`k`**). Let everything decay. Key off when silent. Wait 2 s. `q`.
14. `session.md` — log the starting mode (ROAD or SUPERMOTO), how many dash screens were cycled, whether trip A or trip B was reset, any unexpected dash behaviour at mode toggle, any rev-limiter intervention on the throttle blips.

## Analysis plan

1. **Phase A — mode toggle.**
   - `12A` D1 bit 6: does it alternate with the `m` marks? If yes, polarity (ROAD=0/SUPERMOTO=1 or vice versa) → [`docs/findings/can/signal-ride-mode.md`](../findings/can/signal-ride-mode.md) at `confirmed`, **semantics = rear-ABS-enable** (per manual: this toggle disables rear ABS and nothing else).
   - All bits in the slow-decay group: per-phase mode value. Any bit that alternates is candidate; rank by purity.
   - Cross-check against the idle baseline's LOW-CARD(2) bytes in `12A`, `12D`, `12E`, `450`, `541` — these are the most likely to be mode bits.
2. **Phase B — trip reset.**
   - Look for a momentary bit (1 for one or a few frames around each `r`, then 0). Don't expect a steady-level bit — trip reset is an event, not a state.
   - Also check for any cumulative counter that resets to 0 within the slow-decay group (the dash's local trip A counter might be broadcast).
3. **Phase C — dash button presses.**
   - Frame-by-frame diff in a 100 ms window around each `space` mark. Expect a momentary bit indicating "button pressed" — possibly different bits for different buttons, possibly an enum.
   - Cross-check against the trip-reset event for whether it's a different button-id or the same line with a longer press.
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
6. **Mode-vs-engine independence (manual cross-check).** Per the owner's manual the mode toggle is rear-ABS-only. So between Phase A and Phase D: idle RPM, idle throttle position, and any candidate engine-load / fuelling bytes (e.g. `540` D1) should be **identical across the two modes**. If they differ, the manual is incomplete and the toggle also nudges an engine-side parameter — record as a contradicting finding.

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
