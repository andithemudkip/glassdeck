---
date: 2026-07-24
status: success
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/post-kill-decay-groups
    - can/signal-abs-lamp
    - can/signal-ride-mode
  references:
    - ktm-can-decoder
    - svartpilen-401-dash-user-manual
    - husqvarna-community-notes
  experiments:
    - 2026-06-17-payload-diff-idle
    - 2026-07-24-abs-fault-and-recovery
  supersedes:
    - 2026-07-12-dash-inputs
  logs:
    - 2026-07-24-abs-mode-toggle
    - 2026-07-24-abs-mode-toggle-2
    - 2026-07-24-abs-mode-toggle-3
---

# ABS mode toggle (ROAD ↔ SUPERMOTO) — engine-off, minimal

Scoped-down replacement for [2026-07-12-dash-inputs](2026-07-12-dash-inputs.md). Trip reset and dash short-presses were dropped as dash-internal by architecture; the mode toggle is the only cluster-side input that has to cross CAN (the ABS ECU is a separate module and needs the state).

## Hypothesis

The ROAD ↔ SUPERMOTO toggle broadcasts as a single alternating bit somewhere in the slow-decay group (`12A`, `12D`, `12E`, `450`, `541`) — most likely `12A` D1 bit 6 based on KTM-adjacent decoder evidence, secondarily any bit in that group whose idle baseline was LOW-CARD(2). The semantic is **rear-ABS-enable**, not requested-map: per the owner's manual this toggle disables rear-wheel ABS for supermoto-style riding and changes nothing else.

**Engine-off contingency.** The manual specifies "stationary" but not engine state. If the first SET-hold produces no dash mode change, the ABS ECU likely requires engine-on — abort and re-run engine-on (add starter + idle-settled steps to the YAML; the analysis is unchanged).

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. **Key ON, engine OFF**, kill switch in RUN, neutral.
- **Side stand UP, rider seated.** Planned as "side stand down, rider standing beside" to keep the seat unweighted — but on this bike the side-stand-down warning takes over the dash and blocks menu navigation entirely, so the ABS-screen navigation and SET-hold can't be performed with the stand down. Rider must be seated (side stand up = requires the rider on the bike to keep it upright). Consequence: [[signal-side-stand]] flips from the idle baseline, and any latent seat-occupancy bit is now ON throughout — factor both into the diff so we don't misattribute them to the mode toggle.
- Wifi-bridge is bike-powered ([[project-wifi-bridge-ota]]) — capture starts after key-on, no pre-key-off silence window. See [[feedback-wifi-bridge-procedures-key-on-start]].
- Engine off keeps the noise floor minimal so per-window diffs on the slow-decay group are cleanest.

## Procedure

> **Scripted** — driven by [`2026-07-24-abs-mode-toggle.procedure.yaml`](2026-07-24-abs-mode-toggle.procedure.yaml). Run with `bin/experiment-wifi-bridge abs-mode-toggle docs/experiments/2026-07-24-abs-mode-toggle.procedure.yaml`.
>
> **Timing convention:** auto-marks fire at **step start** — the moment the rider is cued to begin the SET-hold. The bus broadcast is keyed off the press edge, not the dash redraw, so this is the correct reference for window analysis.

1. Key already ON. Kill RUN, neutral, side stand down, engine OFF.
2. Start capture per the YAML: 30 s post-key-on baseline, then navigate to the ABS screen with MODE short-presses (the 4 s startup test also shows the current mode — you'll know the starting mode without navigating), then four SET-holds (3–5 s each) with 8 s settles.
3. Four toggles round-trip back to the starting mode so the exit state is known and matches the entry state.
4. If the first SET-hold produces no dash mode change, abort — this is the engine-off gating case; re-run engine-on.
5. If the dash *flashes* the mode indicator (per manual, a fault signature), abort entirely and diagnose.

`session.md` — log starting ABS mode (ROAD or SUPERMOTO, read from the 4 s startup display); whether Phase A took effect or was aborted for engine-off gating; any unexpected dash behaviour.

## Analysis plan

1. **`12A` D1 bit 6 first** — does it alternate with the four mode marks? If yes, polarity determines ROAD=0/SUPERMOTO=1 or vice versa → new `docs/findings/can/signal-ride-mode.md` at `confirmed`, semantics = rear-ABS-enable.
2. **If bit 6 doesn't move**: scan every bit in the slow-decay group; rank candidates by "alternates cleanly with mode marks and stays flat everywhere else."
3. **Reject flat-ON candidates.** Per the manual the ABS warning lamp stays ON below ~6 km/h, so any bit driving that lamp is ON-flat across this stationary capture — such a bit is a candidate for the [[signal-abs-lamp]] cohort, not for ride mode. The mode bit must *alternate*.
4. **Side-observation: incidental button-event bits.** The mode toggle *is* a SET-long-press. If a bit fires briefly at each SET-hold start (independent of which polarity we're going into), that's a candidate "SET pressed" line — flag it as a follow-up hook, don't try to decode it here.

## Expected outcomes

- **Mode toggle works engine-off** → `12A` D1 bit 6 (or a nearby candidate) alternates; [[signal-ride-mode]] finding lands at `confirmed`.
- **Mode toggle requires engine-on** → informative-null, re-run engine-on with a one-line YAML edit.
- **Nothing alternates in the slow-decay group** → the signal is elsewhere (maybe on a private ABS line we don't tap), which is itself a finding worth writing up.

## Result

**Toggle works engine-off, ride mode is a two-bit mirror**, promoted to `confirmed` in [[signal-ride-mode]].

Third capture attempt of the day (`2026-07-24-abs-mode-toggle-3/`, 33862 frames, 158 s) — attempts 1 and 2 were data-collection failures (see their `session.md` files; kept as evidence). Analysis via `scripts/abs_mode_scan.py`.

- **`12A` D2 bit 1** — primary. 100 % purity across all 5 stable windows (baseline + 4 post-toggle plateaus).
- **`450` D4 bit 7** — mirror, moves in lockstep with `12A` D2 b1 (transitions within 20–300 ms).
- **Polarity:** 0 = ROAD, 1 = SUPERMOTO. Starting mode was ROAD (rider-confirmed from the 4 s startup display); baseline window majority = 0 on both bits.
- **Transition timing:** each bit flips ~3.0–3.5 s after the SET-hold-start mark, matching the rider-observed dash UX (SET press → "keep holding" → ~3 s → "release" → old mode ~0.5 s → new mode). The 3 s is the cluster-side hold detection; the bit flip is the moment the state actually publishes.
- **KTM `12A` D1 bit 6 hint (from the ktm-can-decoder reference) is wrong for this bike** — flat 0 across the entire capture. Noted in [[signal-ride-mode]] as a debunked prior.

Independent cross-checks that supported `confirmed`:

- Both bits were **universally 0 across all 15 prior sessions** (every prior session was in ROAD by rider recall). This session is the first with any 1 value — matches the SUPERMOTO windows exactly.
- `450` was previously flagged in [[coverage.md]] as "payload static-frozen at fixed values … some rider input we haven't exercised must move it" — this experiment *is* that input.
- No competing stimulus in the session alternates 4× in this pattern. Side-stand (up throughout), seat occupancy (rider seated throughout), and MODE short-presses (only during navigation phase, before any toggle) all have wrong shapes.

**No separate command mechanism exists on the main CAN bus** — verified by a four-way scan (`scripts/abs_mode_command_scan.py`) across all 11 IDs, not just the slow-decay group:

- No hold-only or burst-only ID (rules out a UDS/ISO-TP request-response or a one-shot command frame appearing near the mark).
- No byte value that appears only in the hold windows (after correctly filtering `541` D6/D7 — D6 is a ~1 Hz counter, D7 the per-frame hash, extending the [[byte-d7-cycle-hash]] family).
- No bit whose 1-frequency is even 30 % elevated across all 4 hold windows vs baseline — no "button held" or "toggle requested" line.
- No bit elevated in the ±0.5 s burst around each mark either — no press-down event line.

So on this bike the "sustained signal" the cluster provides to the ABS ECU is the *state bit persisting at the new value*, not a separate button-hold broadcast. Only three ways a discrete command could still exist: on a bus we don't tap (LIN, K-line, private ABS↔cluster CAN), on a direct wire between the modules, or constructed to defeat the scan (a bit that fires at *different* offsets in each hold so per-mark aggregation cancels — no positive evidence for this and it's an unusual design).

## Interpretation

The bike's mode toggle is a state broadcast, not a command handshake. Cluster (or ABS ECU — see below) publishes the current mode continuously at ~50 ms period on one of the two mirror bits; the other module reads it and mirrors on its own broadcast. The four-way command-scan above rules out a separate "toggle command" or "button held" message on the main CAN — if a discrete command exists at all, it's off-bus.

**Command direction is still ambiguous.** Frame-by-frame precedence around each transition is inconsistent — Toggle 2 clearly has `450` leading by 267 ms (multiple `450` NEW frames before `12A` publishes NEW), Toggles 3 and 4 have `12A` appearing NEW first (though could be broadcast-phase artifacts on `450`). If the cluster owned the write-side (its SET button, its screen, its decision to interpret SET-hold as "toggle mode") we'd expect it to consistently lead. It doesn't. Three surviving possibilities:

1. **`450` is the cluster's command / requested-state broadcast; `12A` is the ABS ECU's confirmed-state mirror.** The precedence inconsistency is broadcast-phase noise on top of a small (~10-50 ms) true lag. Most likely, because the cluster owns the button.
2. **Both modules read a shared physical line** (SET wired directly to both) and each publishes its own state independently. Unlikely on modern CAN architecture but not impossible.
3. **The actual command is on a bus we don't sniff** (K-line, LIN, or a private ABS-cluster line). Some KTM/Husqvarna bikes do have a second bus.

Disambiguating this matters for the replacement dashboard's TX work — see Follow-ups.

**Cross-reference to community notes.** [[husqvarna-community-notes]] "ABS / TC disable: ECU wants 5 s of sustained signal" section describes a related bike where the custom dash abstracts the hold by *sustaining* the command frame for 5 s. Our 401 gates at ~3 s (matches manual's 3–5 s range). This is consistent with our interpretation: the "sustained signal" IS the state bit at its new value, and the ABS ECU accepts the change once the new value has been broadcast long enough. Ours is 3 s; other Husqvarnas may be 5 s.

## Follow-ups

- **Closes [[2026-07-24-abs-fault-and-recovery]] Phase A's mode-toggle objective.** That session can now drop mode toggles from its baseline and focus on fault-induction + ABS-active work. Its "secondary check on the ride-mode bit" analysis point now has specific bits to watch (`12A` D2 b1, `450` D4 b7) — no longer speculative.
- **TX probe for the replacement dashboard.** Not scoped here — needs its own experiment and ADR per the golden rule (no active TX without a docs/decisions/ authorization). Sketch: broadcast `450` D4 b7 = 1 continuously at 50 ms period for ≥10 s while bike is stationary in ROAD; observe whether `12A` D2 b1 follows. Complication: OEM cluster is presumably still broadcasting `450` D4 b7 = 0 in parallel — dueling-publisher problem. May need a passive "who owns `450`?" sub-experiment first (disconnect one module at a time, see which ID disappears from the bus) before authorizing active TX.
- **Debunked prior.** Add the "KTM `12A` D1 bit 6 is NOT ride mode on the 401" observation to [[ktm-can-decoder]] notes if that reference is versioned.
- **New finding lands:** `docs/findings/can/signal-ride-mode.md` at `confirmed` — see [[signal-ride-mode]].
