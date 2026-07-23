---
date: 2026-07-12
status: planned
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/post-kill-decay-groups
  references:
    - ktm-can-decoder
    - svartpilen-401-dash-user-manual
  experiments:
    - 2026-06-17-engine-idle-baseline-x3
    - 2026-06-17-payload-diff-idle
    - 2026-07-12-neutral-rpm-sweep
  supersedes:
    - 2026-06-18-engine-on-stationary-inputs
  logs: []
---

# Dash inputs — ROAD/SUPERMOTO toggle, trip reset, MODE/SET short presses (key-on, engine-off)

Split half of the original engine-on-stationary batch. The throttle blip and neutral-RPM sweep now live in [2026-07-12-neutral-rpm-sweep](2026-07-12-neutral-rpm-sweep.md); this experiment covers only cluster-side inputs, engine-off for cleanest per-window diffs.

## Hypothesis

The next layer of decoding is the **body-controller / instrument-cluster signals** — inputs the rider drives via the dashboard, not via mechanical levers. These should surface in the slow-decay group (`12A`, `12D`, `12E`, `450`, `541`, `5A0`), which we hypothesise originates from one or more dash-side modules.

Three overlapping sub-hypotheses, all cluster-side, all tested in one bracketed session:

1. **Mode toggle (ROAD ↔ SUPERMOTO):** per the Svartpilen 401 owner's manual this toggle is **ABS-only** — it disables rear-wheel ABS for supermoto-style riding and changes nothing else (no map, no power delta, no TC tweak). The ABS ECU still needs to know the state, so we expect the mode to be broadcast somewhere — KTM ties this on related platforms to `12A` D1 bit 6, and our idle `12A` D1 was LOW-CARD(2), so it's the leading candidate. A deliberate toggle resolves the bit; interpretation is **rear-ABS-enable**, not requested-map. Per the manual the toggle procedure is: navigate to the ABS screen (MODE button presses), then hold SET for 3–5 s while stationary.
2. **Trip reset:** per the manual, hold SET for 3 s while on the Trip 1 (or Trip 2) screen. Likely targets a momentary bit somewhere in the body-controller cluster (`12E`, `450`, `541` are candidates because they're slow-decay and currently UNKNOWN/LOW-CARD). May or may not be distinguishable from a generic SET-long-press event — the mode toggle in (1) is also a SET long-press, just in a different display context.
3. **Dash button short presses:** the cluster has only two buttons, **MODE** and **SET**. MODE short-press cycles displays (ABS → Info if warnings → ODO → Trip 1 → Trip 2 → wrap). SET short-press cycles sub-menus within the current display. Short presses are candidate momentary bits in the slow-decay group; MODE-vs-SET may be a single button-event line with an enum, or two separate bits.

Session structure matters: each input is bracketed by a held window with no other rider activity, so per-window statistics cleanly attribute movement to one input. The YAML fires an auto-mark at each transition.

**Engine-off contingency — mode toggle.** The manual specifies "stationary" but not engine state. If Phase A completes and the mode indicator on the dash doesn't change on any SET-hold, the ABS ECU may only accept mode changes with the engine running. In that case: abort Phase A (Phases B and C still stand — both are pure cluster-side), and re-run Phase A engine-on in a follow-up session. Flipping back is one file edit (add starter + idle-settled steps to the yaml, drop the engine-off note from the setup).

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. **Key ON, engine OFF**, kill switch in RUN, neutral, side stand down.
- **Wifi-bridge is bike-powered (ADR 0018 / [[project-wifi-bridge-ota]]).** The ESP is off until the key is on, so capture starts *after* key-on — there is no pre-key-off silence window. See [[feedback-wifi-bridge-procedures-key-on-start]].
- Engine off keeps the noise floor minimal: `120` D0,D1 (RPM) is `0x0000`, coolant/idle bytes on `540` don't drift, and no engine-load byte moves. Per-window bit diffs on the slow-decay group are cleanest under these conditions.
- Rider stands beside the bike (not seated) to keep weight off the seat — some bikes broadcast a seat-occupancy bit and we don't want to add a fifth input axis to this session by accident.
- Have a stopwatch / mental clock — phases run on time, not on "how it feels."

## Procedure

> **Scripted** — driven by [`2026-07-12-dash-inputs.procedure.yaml`](2026-07-12-dash-inputs.procedure.yaml) (ADR 0006). Run with `bin/experiment-wifi-bridge <label> <yaml>` — the operator screen handles step ordering, durations, and the per-phase marks automatically; the rider just follows the prompts.
>
> **Timing convention:** auto-marks fire at **step start** (the moment the rider is cued to begin the action — start of SET-hold), NOT at the dash's visual confirmation. The bus broadcast is keyed off the press edge, not the dash redraw, so this is the correct reference for window analysis.

1. Key must already be ON before running (wifi-bridge boots on ignition). Kill switch in RUN, neutral, side stand down. Engine OFF.
2. Start capture: `bin/experiment-wifi-bridge dash-inputs docs/experiments/2026-07-12-dash-inputs.procedure.yaml`.
3. YAML begins with a 30 s post-key-on baseline window — clean cluster-side broadcast, no rider activity. All subsequent phase windows diff against this.

### Phase A — ROAD ↔ SUPERMOTO toggle

Per the manual: navigate to the **ABS** screen with MODE button short-presses (the startup test sequence shows the current ABS mode for 4 s, so you'll know the starting mode without navigating). Then hold **SET** for 3–5 s to toggle; the dash flashes the new mode briefly. **If the mode indicator on the dash doesn't change after the first SET-hold, the ECU likely requires engine-on** — abort Phase A, continue with Phases B and C, and re-run Phase A engine-on later.

If the mode flashes on the dash after the hold, that indicates a fault (per manual) and the experiment should be aborted entirely.

The YAML auto-marks each MODE short-press and each SET-hold start. Four toggles round-trip back to the starting mode so the exit state is known.

Eight-second holds between toggles because mode-change broadcasts may include a settling transient (the ABS ECU updating its enable line, the dash redrawing the mode indicator); 8 s comfortably exceeds the 100 ms cycle of the slowest IDs.

### Phase B — trip reset

Per the manual: navigate to **Trip 1** with MODE short-presses, then hold **SET** for 3 s; the trip distance jumps to 0.0. Two resets to confirm reproducibility — the second is a no-op (Trip 1 is already 0.0), which separates "SET long-press event" from "trip counter actually changed value."

### Phase C — dash button short presses

The cluster has only **MODE** and **SET**. MODE short-press cycles displays; SET short-press cycles sub-menus within the current display. SET long-press was already exercised in Phases A and B; this phase is short-presses only.

Sub-menu walk:
- SET short-press through Trip 1 sub-menus (Time / Avg Speed / Avg F.C. / back to distance).
- MODE short-press → Trip 2. SET short-press through Trip 2 sub-menus.
- MODE short-press → ABS. **SET is suppressed here** — a long-press would re-toggle mode; even a short-press is skipped for simplicity.
- MODE short-press → ODO. SET short-press cycles ODO sub-menus (ODO / Fuel Range / Service).
- Final 8 s hold on ODO before shutdown.

### Shutdown

Key off, tail silence. No kill switch step — engine is already off.

`session.md` — log the starting ABS mode (ROAD or SUPERMOTO, read from the 4 s startup display), **whether Phase A mode toggle actually took effect** (or was aborted because engine-off), confirm Trip 1 was the one reset (not Trip 2), any unexpected dash behaviour at mode toggle (flashing = fault, abort), any sub-menu the rider miscounted or re-cycled.

## Analysis plan

1. **Phase A — mode toggle** (skip this section if Phase A was aborted for engine-off gating).
   - `12A` D1 bit 6: does it alternate with the mode marks? If yes, polarity (ROAD=0/SUPERMOTO=1 or vice versa) → [`docs/findings/can/signal-ride-mode.md`](../findings/can/signal-ride-mode.md) at `confirmed`, **semantics = rear-ABS-enable** (per manual: this toggle disables rear ABS and nothing else).
   - All bits in the slow-decay group: per-phase mode value. Any bit that alternates is candidate; rank by purity.
   - Cross-check against the idle baseline's LOW-CARD(2) bytes in `12A`, `12D`, `12E`, `450`, `541` — these are the most likely to be mode bits.
   - **Reject flat-ON candidates.** Per the manual the ABS warning lamp stays ON below ~6 km/h, so any bit that drives that lamp will be ON-flat across this whole stationary capture. It lives in the same ABS-side payloads we're scanning. The mode bit must *alternate* with mode marks — a flat-ON bit in `12A`/`12D` is a candidate for the ABS-warning-lamp line, not for ride mode.
2. **Phase B — trip reset.**
   - Look for a momentary bit (1 for one or a few frames around each reset mark, then 0). Don't expect a steady-level bit — trip reset is an event, not a state.
   - Compare the two reset events: the first changed Trip 1's value (X.X → 0.0), the second was a no-op (0.0 → 0.0). Any bit that fires on the first but not the second is the **value-changed** signal; any bit that fires on both is a **SET-long-press** signal. They may be the same bit (the dash broadcasts the press event regardless of effect) or different.
3. **Phase C — dash button presses.**
   - Frame-by-frame diff in a 100 ms window around each Phase C mark. Expect a momentary bit indicating "button pressed" — likely one bit/enum for MODE and another for SET (or a single button-id field).
   - Cross-check against the SET-long-press events in Phases A and B: a SET short-press in Phase C should share whatever line a SET long-press uses, distinguished only by duration. If the long-press and short-press lines differ, the cluster pre-classifies the press type before broadcasting.

MIL bit and side-stand engine-on confirmation both fall out of the engine-on timeline in [[2026-07-12-neutral-rpm-sweep]] (starter/kill transitions and a long idle window). Both are noted in that experiment's analysis plan.

## Expected outcomes

- **Mode toggle works engine-off** → clean Phase A, `12A` D1 bit 6 alternates and ride-mode (rear-ABS-enable) finding lands at `confirmed`.
- **Mode toggle requires engine-on** → Phase A aborted, Phases B and C still land their findings, follow-up runs Phase A engine-on. This is an informative-null outcome, not a failure.
- **A momentary bit somewhere in the slow-decay group fires on each dash button press** → button-event finding, but probably multiple bits/encodings — full decode may need a follow-up dedicated session.
- **Trip reset is a *different* bit from the short-press cluster** → consistent with a "long press detected" sentinel separate from the raw button line.

## Follow-ups

- If Phase A aborted (engine-off gating), re-author this file's YAML to add starter/idle-settled steps and run Phase A engine-on. The analysis plan is unchanged.
- The dash-button decode in particular may need a dedicated follow-up session — one button per capture, several presses each — depending on how clean Phase C looks.
- Once mode and dash buttons are decoded, the dashboard MVP's cluster-input mirror is essentially complete. Combined with the throttle/RPM outcomes from [[2026-07-12-neutral-rpm-sweep]] and vehicle speed (next-action per `docs/status.md`), the stationary-input surface is closed.
- **Mode-vs-engine independence.** The old plan folded a mode-invariance check into the throttle work. Now that the two experiments are split, run a small back-to-back comparison after both complete: at matched idle, do the throttle-position and RPM bytes read the same in ROAD and SUPERMOTO? If yes, the manual's ABS-only claim holds; if not, the manual is incomplete.
