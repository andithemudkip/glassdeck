---
date: 2026-07-24
status: planned
phase: 1
related:
  findings:
    - signal-abs-lamp
    - signal-12a-d1-bit2
    - dash-warning-lights
    - always-on-broadcast-ids
  decisions: []
  logs: []
---

# ABS fault induction, mode toggle, ABS-active, fault clear

## Hypothesis

Four things fall out of one session:

1. **The 5 remaining ABS-lamp bits may not all be the same signal.** Under a healthy self-test they all clear together, so we can't tell them apart. Under a fault the physical lamp stays lit — but other module states may or may not follow the lamp. If all 5 bits stay in "lit" polarity throughout the fault, they're behaving as one signal. If some track "lamp lit for fault" while others track "module ready" or "self-test complete" (which fails during a fault), we get a per-bit semantic split. See [[signal-abs-lamp]] "Five bits, but is it five signals?" for the open question.
2. **ROAD ↔ SUPERMOTO mode toggle should surface in some byte.** The rider's fault-clear procedure includes "switch between ABS modes" — this is what [[2026-07-12-dash-inputs]] Phase A was designed to hunt. Mode toggles here give us the same discriminator without the standalone experiment.
3. **ABS-active event may broadcast on a bit we haven't yet identified.** A hard brake that triggers ABS is a very specific stimulus. If there's a bit that fires only when the ABS system is actively modulating brake pressure (vs just "lamp is on" or "lamp is off"), this brake will surface it.
4. **The fault-clear moment itself is diagnostic.** Whichever bits transition at the moment the lamp goes out (after mode toggle + successful ABS actuation) are the "lamp state" bits — and if they transition in sequence rather than together, the ordering tells us the ECU's internal signal flow.

Bonus: also verifies [[signal-12a-d1-bit2]] against another engine-off / stationary / ignition-only condition (Phase B is exactly this shape) — its current pattern (rises at t+2s, drops at some session-varied time) can be checked against the induced-fault state.

## Setup

- Bike + rider warmed to normal operating temp, fully-fuelled, ideally on a stand for Phase B if the ground-disconnect is easier that way.
- Firmware: `wifi-bridge` latest on `master`.
- Phone-side capture as on 2026-07-22. GPS enabled if the app supports it (bonus data for Phase C ride).
- **Safety:** Phase C involves a deliberate hard-brake ABS trigger. That needs to be on a controlled surface with the rider prepared — parking lot, quiet closed-off road, or somewhere you've done this recovery before. Not on public road with traffic. Rider knows the recovery sequence better than any procedure could specify.
- Have a friend / helper if the ground-point is hard to reach mid-session and you'd rather not stop-and-start the bike between phases.

## Procedure — freeform (four phases, marked by natural transitions)

Nothing here is timed. The phases are what they are; move between them when it feels right.

### Phase A — clean baseline (~1-2 min)

Objective: capture the ABS bits + mode-toggle bit in a healthy state.

1. Start capture.
2. Key off, then key on normally. Bike healthy, ABS lamp lights → runs its self-test → lamp state as usual.
3. Sit stationary with the engine off for 30-60 s just to get the 5 ABS-lamp bits' "resting" values for later comparison.
4. Start the engine, sit at idle for another 30-60 s.
5. Toggle ABS mode: press MODE / whatever combination cycles ROAD ↔ SUPERMOTO ↔ (any other modes this bike has). Do it a couple of times if you can, so we see the transitions land in distinct polarities. Note in your head roughly when in the capture you did each toggle.
6. Come back to whatever mode you want to be in for Phase B (probably ROAD).

### Phase B — induce fault (~2-3 min)

Objective: capture the ABS bits and any ancillary signals in a real fault state.

1. Kill switch to STOP if the engine's running; then key off.
2. Disconnect the ABS ground point (the one you've done before).
3. Key on. Bike should light ABS lamp and refuse to clear it (fault). Rider observes any other dash indicators (fault code, mode indicator behaviour, blinking pattern).
4. Sit stationary key-on-engine-off for 30-60 s to catch the fault state at rest.
5. Attempt: cycle ABS mode again during the fault. If the button responds, that tells us mode-toggle is independent of ABS health. If it doesn't respond, that's also informative.
6. Optional: attempt walking-pace push (or a slow roll if you're set up to) so we catch the "lamp still lit despite motion" version of the trace. Rider notes if lamp behaves any differently across the 6 km/h threshold this time (it shouldn't extinguish — that's the whole point of the fault).
7. Key off. Reconnect the ABS ground point.

Optional sub-phase B': if the fault persists after reconnection *without* the recovery sequence — key on again with ground connected, stationary — capture 30 s of "ground restored but fault still latched" data. That's a *third* distinct state (lamp lit, ground healthy, ECU hasn't confirmed function yet).

### Phase C — clear the fault (rider's known recovery sequence)

Objective: capture the fault-clear transition itself, plus a real ABS-active event on the hard brake.

Rider's recipe. Roughly:

1. Cycle the ABS mode(s) as required by the recovery sequence (rider knows).
2. Move to a safe area for the hard-brake test.
3. Ride up to whatever speed feels appropriate for a controlled ABS trigger (~ 30-40 km/h is usually plenty; up to rider judgment).
4. Perform the hard-brake / ABS-triggering event. **This is the most useful single moment in the whole session** for signal-hunting: if there's a "ABS actively modulating" bit, this is when it fires.
5. Rider confirms lamp clears (or doesn't).
6. If lamp cleared, ride briefly to confirm normal behaviour resumed. If not, rider decides whether to retry or bail on Phase C.

### Phase D — post-clear baseline (~30 s)

Objective: confirm the 5 ABS bits are back to their post-self-test state.

1. Stop somewhere safe, engine at idle or off.
2. Sit for 30 s to catch the post-recovery resting state.
3. Toggle ABS modes a couple more times so we have a healthy-state mode-toggle trace to compare with Phase A's healthy-state one and Phase B's fault-state one (if the mode button responded during the fault).
4. End capture.

## What to note afterward

Rough narrative — no clock timings needed, the CAN trace has the timing. Just:

- Which mode you started in each phase and which mode transitions you made (ROAD → SUPERMOTO, back, etc.)
- What the dash showed during the fault — fault code number if visible, any indicator that behaved unusually, whether the mode indicator responded to the button during the fault.
- Did the mode button work during the fault?
- What speed you were at when you triggered ABS in Phase C.
- Any other dash weirdness — needle sweeps, warnings you weren't expecting, anything.

Also confirm afterward:

- Do you remember roughly the sequence you used to clear the fault (mode ↔ toggles, then brake)? A one-line description is fine.

## What we'll analyse

- **The 5 ABS-lamp bits across all 4 phases.** Track initial value and any transitions per phase per bit. Under the "all 5 are the same lamp signal" model they move together at Phase-C-lamp-clear and nowhere else. Under the "different module states" model, some may transition earlier (e.g., "self-test complete" might rise before the lamp goes out) or later. First per-phase divergence identifies the semantic.
- **Any bits that fire ONLY during the Phase C hard-brake event.** Cross-scan every payload byte, filter for bits with low overall duty that fire briefly at the brake moment.
- **The mode-toggle discriminator across Phases A, D (healthy) and B (faulty).** Which bit(s) move on mode button press, and do they respond the same way when the module is faulted vs healthy? Bonus: pins down the ROAD/SUPERMOTO signal we've been hunting.
- **Whether new arbitration IDs surface during the fault.** [[always-on-broadcast-ids]] says no non-always-on IDs in 800k+ frames. A fault might trigger diagnostic messages that the healthy corpus never saw — worth watching for.
- **[[signal-12a-d1-bit2]] behaviour** across the four phases — does it follow the pattern from the other stationary sessions (rise at t+2s, drop later), or does it correlate with anything specific to the fault/mode/brake events? Cheap sanity check.

## Interpretation

_To fill after the ride._

## Follow-ups

- If Phase A mode-toggle surfaces a clean bit: rewrite as part of a new `signal-abs-mode` finding. May close [[2026-07-12-dash-inputs]] Phase A entirely (no separate session needed).
- If Phase C brake surfaces an ABS-active bit: new finding, probably `signal-abs-active`. Also has implications for the brake-input hunt — if the ECU broadcasts an ABS-active signal but not a raw brake-pressed signal, that partially resolves the [[2026-07-10-brakes-stationary]] "brake input absent" question by giving us a downstream substitute.
- If Phase B surfaces a "fault detected" or "module unhealthy" bit distinct from the lamp bits, that's a new finding too.
- Update [[signal-abs-lamp]] "Five bits, but is it five signals?" section based on how the 5 bits behave across phases. If they split, rename per-bit and update `signals.yaml`.
- If [[signal-12a-d1-bit2]] behaviour correlates with the mode button or the fault event, that's the semantic-identification we were missing.
