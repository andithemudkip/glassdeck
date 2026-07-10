---
date: 2026-06-24
status: superseded
superseded_by:
  - docs/hardware/dash-connector.md
  - docs/experiments/2026-07-10-brakes-stationary.md
phase: 1
related:
  findings:
    - bike/dash-warning-catalog
    - bike/dash-warning-lights
    - can/always-on-broadcast-ids
    - can/signal-side-stand
    - can/signal-kill-switch
  references:
    - ktm-can-decoder
  experiments:
    - 2026-06-18-side-stand-toggle
    - 2026-06-18-kill-switch-toggle
    - 2026-06-21-cross-session-payload-diff
    - 2026-07-10-brakes-stationary
  logs: []
---

# Handlebar switches, engine off — left/right indicators, high beam, horn

> **Superseded — not run.** The four primary targets of this plan were
> answered by evidence that came in after 2026-06-24 without needing a
> capture session:
>
> - **Left/right indicators + high beam** — [`docs/hardware/dash-connector.md`](../hardware/dash-connector.md)
>   (2026-07-01, from the repair-manual schematic) confirms all three are
>   **off-bus, dedicated wires on X10** (pins 11, 12, 8). The OEM dash
>   physically has to read them there to drive its lamps; there's no
>   dashboard-side motivation to duplicate them on CAN. Replacement dash
>   reads them as level-shifted GPIO, same treatment as fuel level.
>   Catalog rows for "Turn signal" and "High beam" already flipped from
>   `open` to `off-bus`.
> - **Brake-lever switches** — indirectly covered by
>   [[2026-07-10-brakes-stationary]], which pulled each brake lever
>   through its entire travel (gentle → medium → hard) six times per
>   side, well past the ~5 mm switch-close point. No bit on any of the
>   11 always-on IDs flipped in correlation. Brake-lever switch is not
>   on the always-on broadcast set.
> - **Kill switch** — already documented as doubly-wired via
>   [[signal-kill-switch]] (CAN) and X10 pin 5 (schematic mirror).
>
> **Residual open question, low priority:** horn. Not on X10, not in the
> dash user manual (the OEM dash has no horn indicator — horn is
> functional, not a display), so the replacement dash has no reason to
> know when it's pressed. Would only surface as CAN-corpus enrichment.
> Not worth its own session; if a future engine-off procedure has 60 s
> of idle time, a couple of horn taps could be piggy-backed as
> auto-marks then.
>
> Preserved per repo rule #3 ("preserve failed experiments") — the plan
> below is the state of the reasoning on 2026-06-24, before the
> schematic mapping shrank the problem.

Decode the handlebar switchgear. **Primary target: left/right turn-signal state**, which is the #1 stated motivation for the whole project (`docs/research.md` — "Separate left/right indicator icons"). **Secondary: high beam**, which lights a dedicated dash indicator (`bike/dash-warning-catalog.md`) and is therefore definitely broadcast somewhere. **Tertiary, free piggy-backs in the same session: horn and brake levers.**

All inputs sit on the same left/right handlebar pods, the bike doesn't have to be supported in any special way, and every state is a clean held position with a visible dash confirmation. Equivalent in scope and cost to [[2026-06-18-side-stand-toggle]] or [[2026-06-18-kill-switch-toggle]] — a single ~15 min engine-off session that should crack 2–4 signals.

## Hypothesis

Each input below is independently broadcast somewhere on one of the 11 always-on IDs. None has a KTM cross-walk hypothesis ([[ktm-can-decoder]] doesn't list indicators, high beam, horn, or brake-lever state — the KTM 690 either doesn't broadcast them or the decoder author didn't reach them), so this is a **bus-wide bit-scan** session rather than a targeted (ID, byte, bit) verification.

| Input | Expected bit count | Notes |
|---|---:|---|
| Left turn signal | 1 | Switch position; may carry independently of lamp flash phase |
| Right turn signal | 1 | Same |
| High beam | 1 | Latched on the handlebar switch (push-up dimmer); dash lights blue indicator |
| Horn | 1 | Momentary; only on while button is pressed |
| Front brake lever | 1 | Momentary; lights the rear brake lamp |
| Rear brake pedal | 1 | Same effect, distinct switch |

A **key sub-hypothesis for the indicators**: is the broadcast value the **switch position** (held `1` while the switch is in left/right) or the **lamp state** (toggles ~1 Hz with the actual bulb flash)? Holding each indicator state for ≥6 s — long enough to span 5+ flash cycles at the ~1 Hz visible flash rate — discriminates cleanly. A held-`1` value across the whole window is switch-position; an alternating `0/1` pattern at ~1 Hz is lamp-state. The dashboard replacement wants both, but the switch-position signal is the cleaner driver for a separate-L/R icon (no need to track flash phase to know "the rider intends to turn left").

Hazards (both indicators simultaneously) are present on this bike's handlebar (a top-bar button on the left pod). Worth probing because either (a) it's broadcast as a third distinct bit, (b) it manifests as both L and R bits asserted at once, or (c) it's handled internally by the body controller without a CAN flag. Any of those answers updates our model of the indicator subsystem.

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. **Engine off**, neutral, side stand down, key on (position 1), kill switch in **run**.
- No special support needed — bike sits on its side stand throughout. Do not press the starter at any point.
- Adapter / firmware / host as before. Capture via `scripts/capture.py` with a procedure YAML driving the operator screen.
- Rider keeps eyes on the dash + handlebar throughout to confirm each input took effect (indicator arrow blinks, blue high-beam lamp lights, brake lamp visible in a mirror, etc.). Note anomalies in `session.md`.

## Procedure

Scripted via `docs/experiments/2026-06-24-handlebar-switches-engine-off.procedure.yaml`. Each input is held in each state long enough to span multiple `100 ms`-cohort broadcast cycles and (for the indicators) multiple visible flash cycles. Run with:

```
python scripts/capture.py --port /dev/cu.usbmodem101 --label handlebar-switches-engine-off --experiment docs/experiments/2026-06-24-handlebar-switches-engine-off.procedure.yaml
```

Phases at a glance:

- **A — Left indicator.** 3× (on → off) cycles, 8 s held in each state, with the cancel pressed at the end of each "on" hold. Mark key: `l` at each switch action.
- **B — Right indicator.** Mirror of Phase A. Mark key: `r`.
- **C — Hazards.** 3× (on → off) cycles via the hazard button. If the bike doesn't surface a separate hazard button (or it's locked behind ignition state), skip this phase via the operator screen — Phase A and B already cover the underlying L+R bits. Mark key: `h`.
- **D — High beam.** 3× (flash-to-pass momentary presses) followed by 3× (latched on → latched off) cycles, 6 s held in each latched state. The flash-to-pass + latched distinction may matter (some bikes route them through different switches; the bus may or may not distinguish). Mark key: `b`.
- **E — Horn.** 5× short presses (~1 s each, 4 s settle between). Horn is momentary so the broadcast bit, if any, will be a narrow pulse around each press. Mark key: `n`.
- **F — Brake levers.** 3× front-lever squeezes (6 s held, 4 s released) then 3× rear-pedal presses (same). Mark keys: `f` and `p`.

Total walltime ~9 min capture + a couple of minutes for setup and `session.md`.

## Analysis plan

The window-aware bit-scan template used by [`scripts/side_stand_scan.py`](../../scripts/side_stand_scan.py) and [`scripts/kill_switch_scan.py`](../../scripts/kill_switch_scan.py) generalises directly. Per phase:

1. **Window partitioning.** Use the auto-marks (`l`, `r`, `h`, `b`, `n`, `f`, `p`) plus the YAML-recorded step durations to label every frame with the input state at the time it was recorded.
2. **Bus-wide bit scan.** For every (ID, byte, bit) in the 11 always-on IDs, compute per-window dominant value and per-window purity. Flag any bit whose dominant value alternates in lockstep with the input state at ≥ 0.95 per-window purity. Trim 300 ms after each mark for debounce / propagation, as in the prior scans.
3. **Phase-by-phase output.** Each input gets its own attribution: "L indicator = ID X byte Y bit Z, polarity 1=on". Cross-check that the bit found in Phase A doesn't also flip during Phase B (would mean we've identified some shared "indicator on" bit rather than the L-specific one).
4. **Switch-position vs lamp-state for indicators.** Within each "indicator on" window, count the number of `0→1` transitions on the candidate bit. **0–1 transitions over a 6+ s window = switch-position (held).** **5+ transitions ≈ once per second = lamp-state (flashing).** Both outcomes are informative; switch-position is cleaner for the dash logic but lamp-state is what the OEM cluster physically reads to light its arrow.
5. **Hazard interpretation.** Three possible findings: (a) a new bit unique to Phase C, (b) both L-bit and R-bit asserted simultaneously throughout Phase C (no distinct hazard channel), (c) neither L nor R asserted but some third bit moves (hazard handled separately from regular indicators). Whichever it is, document.
6. **High-beam latched vs momentary.** Phase D's first half (momentary flash-to-pass) and second half (latched) probe two slightly different switch behaviours. If both produce the same bit transition shape, the bus carries a single "high beam commanded" bit. If they differ, document — could mean the flash-to-pass is wired through a separate switch the body controller OR-gates into the same lamp.
7. **Horn pulse width.** Phase E gives ~1 s pulses. Any bit that asserts during the horn press and clears within ~100 ms of release is a candidate.
8. **Brake-lever bits.** Phase F separates front vs rear so they don't collapse into one "brake applied" bit by accident. Either is fine to find (or both as distinct bits), but distinguishing them matters for any future dashboard brake-status feature.
9. **Bit-pollution cross-check.** None of these inputs should flip kill-switch, side-stand, gear, or coolant-temp bits. Run the scan over the union of those known-attributed bits as a sanity check — any unexpected movement is a bug in the experiment (e.g. accidental side-stand bump) or a hint that the bit we previously attributed is actually shared.

## Expected outcomes

- **All 6 inputs attributed to distinct bits, all on `540` or `541` (Slow group, body-controller cohort).** Most likely outcome — these are all body/handlebar switch signals, the same family as side-stand. Writes 4–6 new `signal-*.md` findings (the brake levers may collapse to one bit; hazards may collapse into L+R simultaneous).
- **Indicators broadcast as switch-position (held).** Cleanest case for the dashboard. Writes [[signal-indicator-left]] and [[signal-indicator-right]].
- **Indicators broadcast as lamp-state (~1 Hz flash).** Still usable for the dashboard (compute "intent to turn" as "any flash in the last 1.5 s") but requires a small state machine. Findings note the flash semantics.
- **One or more inputs not found in any always-on broadcast.** Possible for horn (briefly-asserted bits can hide if the broadcast period misses the pulse — `541` at 100 ms could miss a 200 ms horn pulse cleanly, though unlikely). Less expected for indicators or high beam, which are dash-driven. A null result on indicators would be the most interesting failure: it would mean the dash drives its indicator icon from a non-bus source, which (combined with the auto-headlight observation) starts to suggest the body controller has multiple internal-only channels to the cluster. Follow-up: probe the dash's own broadcast traffic when the cluster is the active source rather than the listener.
- **High beam shares a bit with an indicator or brake.** Unexpected but possible if the body controller multiplexes; would be flagged by the bit-pollution cross-check.

## Caveats

- The bike's hazard button may be ignition-state-gated (some bikes require key off, or only respond with the engine running). If it doesn't activate, skip Phase C via the operator screen — not load-bearing for the primary indicators question.
- Auto-cancel on the indicators: this bike's indicator switch auto-cancels by a centre-inward press, but some indicator implementations also auto-cancel after a fixed time or distance. With the bike stationary we won't trip distance-based cancel; if time-based cancel kicks in mid-hold the analysis just sees the bit drop early in that window — flag in `session.md` and treat that window as shorter, the bit attribution still holds.
- Brake-lever switches are also wired into the bike's start-circuit interlock (engine won't crank without a brake on, on some models). Irrelevant here because we're not cranking; noted in case it affects bit semantics ("brake commanded" vs "brake-and-interlock-armed").
- Horn pulses must be **separated by ≥4 s** to keep each press in its own analysis window. The procedure YAML enforces this.

## Follow-ups

- Findings to write (status TBD by results):
  - `docs/findings/can/signal-indicator-left.md`
  - `docs/findings/can/signal-indicator-right.md`
  - `docs/findings/can/signal-indicator-hazard.md` (only if Phase C surfaces a distinct bit)
  - `docs/findings/can/signal-high-beam.md`
  - `docs/findings/can/signal-horn.md` (only if Phase E surfaces a bit)
  - `docs/findings/can/signal-brake-front.md`, `signal-brake-rear.md` (only if Phase F surfaces bits)
- Update `docs/findings/bike/dash-warning-catalog.md`: flip "Turn signal" and "High beam" rows from `open` to `derived` with citations.
- Update [[ktm-can-decoder]] with whichever (ID, byte, bit) locations land — these are bits the KTM author didn't document, so we're extending the cross-walk rather than verifying against it.
- If the indicators are switch-position (held), the dashboard implementation can use the bit value directly. If lamp-state, write a small "intent" state machine in `firmware/` per the lamp-state interpretation.
- The bit-scan output may also surface unexpected co-movement on other bits (e.g. high beam triggering a draw-current bit, brake-lever triggering an interlock bit). Worth a brief note in the experiment Result section for the bus-wide catalogue.
