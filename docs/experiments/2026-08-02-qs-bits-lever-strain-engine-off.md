---
date: 2026-08-02
status: planned
phase: 2
related:
  findings:
    - can/signal-quickshifter
    - can/signal-shift-failed
    - can/signal-gear-position
    - can/signal-clutch
  logs: []
---

# `121` D6 bits 0/1 engine-off: sustained on incomplete downshift pressure, silent on upshift

## Hypothesis

Rider observation (2026-08-02, live view, engine off / ignition on / kill RUN), refined over two rounds:

1. Gentle **downward** (downshift-direction) pressure on the shift lever while in gear — easiest in 3rd — asserts the `121` D6 bits documented in [[signal-quickshifter]], **engine off**, and holds them for **500 ms+** against the 60 ms median measured during real riding.
2. **Only while the shift does not complete.** Push hard enough to actually change gear and the assertion ends.
3. **Upward (upshift-direction) lever movement does nothing at all** engine-off.

The sustained-hold part is the headline, but the **direction asymmetry is the more informative observation**, because the ride corpus showed a perfectly symmetric partitioning: 31/31 upshifts produced `0x01`, 25/25 downshifts produced `0x03`. Whatever suppresses the upshift path engine-off is absent when the engine runs.

### What this qualifies in the current finding

- *"Bit 0 is a genuine shift-event flag — not triggered outside shifts."* The corpus contained no stationary lever loading, so it could only show the bit doesn't fire spuriously *while riding*.
- *"Cut duration median 60 ms."* If the rider can hold it 500 ms+, that median measures **how long the mechanism stays loaded during a real shift**, not an ECU-fixed cut window.
- *"bit 1 = auto-blip (throttle blip to match revs)."* Engine off, there is nothing to blip. At most bit 1 is downshift-direction.

### Competing structures for D6

Observation 3 raises a structural question the ride data could not:

- **A — two independent flags** (current finding): bit 0 = cut requested, bit 1 = downshift/blip. Predicts upshift pressure engine-off should produce `0x01`. It doesn't.
- **B — a small enum**: `0x00` idle, `0x01` upshift-in-progress, `0x03` downshift-in-progress. Only three values have ever been observed and bit 1 has never appeared without bit 0 — exactly an enum's signature. Under B the states can have different preconditions, which is a natural home for the asymmetry.

### Why might the upshift path be silent engine-off?

- **RPM/speed precondition.** An ignition cut is meaningless at 0 RPM, so the ECU may gate the upshift state on the engine turning, while the downshift state (blip/rev-match logic) has no such gate or a different one. Most interesting outcome; would be a real ECU behaviour worth documenting.
- **Mechanical, not electrical.** Lifting the lever engine-off may simply not develop sustained load — the linkage may travel freely upward until engagement, where pressing down meets a firmer stop. Mundane, and must be ruled out before claiming anything about the ECU. Ruling it out is why the upshift trials below are a deliberate battery rather than a token control.
- **Sensor asymmetry.** The strain element may be sensitive in compression but not tension (or vice versa). Would show as silence on upshift under *all* conditions, engine-on included — but the ride data already refutes that: upshifts produced `0x01` 31 times out of 31.

That last point is worth stating plainly: **the ride corpus rules out a purely mechanical/sensor explanation for a total upshift silence**, because upshifts do produce `0x01` when riding. So the asymmetry is conditional on something that differs engine-off — which is what makes it worth chasing.

## The completion confound — and why phase 4 is no longer decisive

My first draft of this plan treated "hold pressure through a completed shift" as the deciding test between raw lever strain and a cut-request state machine that clears on shift completion. **Observation 2 shows that test can't decide it**, and the reason is mechanical:

a QS force sensor sits in the shift rod / linkage and measures **load in the rod**. Before the shift, your foot's force is reacted by the shift drum's detent — high rod load. The instant the drum breaks away and the gear engages, that resistance disappears and rod load collapses **whether or not your foot is still pushing**. So "bit goes off when the shift completes" is the expected signature of raw strain *and* of a state machine. The two are not separable without an independent measure of applied force.

This experiment therefore does not claim to resolve that question. It gathers what a software-only capture can:

- whether the bit's fall **leads or lags** the `129` gear-enum change, at 20 ms resolution, over many trials;
- whether the bit ever survives even a few frames past a completed shift;
- whether re-loading the lever after a completed shift re-asserts immediately (raw strain) or needs a release first (latched state).

Separating them properly needs an **instrumented lever** — a load cell or strain gauge on the shift rod fed into a spare ADC on the logger, giving applied force alongside the bus. That is a hardware follow-up, and this capture should be read as scoping it, not substituting for it.

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. Key ON, kill RUN, **engine OFF throughout**, side stand down, stationary.
- Capture: wifi-bridge → `scripts/capture.py --experiment`. Starts key-on ([[feedback-wifi-bridge-procedures-key-on-start]]).
- Engage gears engine-off by rocking the bike / spinning the rear wheel while loading the lever ([[2026-06-23-paddock-stand-gear-spin]]). **Verify the gear enum in the live view before each phase.**
- Hands and feet are busy throughout, so **no hotkey marks** — every mark is a step boundary ([[experiment-design-hand-driven-marks]]). Hold durations come from the bit trace, not rider timing; the mark only says which trial a window belongs to.
- "Gentle" means enough force to feel the lever load but not enough to move the drum. Any hold that accidentally completes a shift is still useful — note it in `session.md`, the gear enum will show it.

## Procedure

`docs/experiments/2026-08-02-qs-bits-lever-strain-engine-off.procedure.yaml`

```
python scripts/capture.py --port <port> --label qs-bits-lever-strain-engine-off \
  --experiment docs/experiments/2026-08-02-qs-bits-lever-strain-engine-off.procedure.yaml
```

1. **Baseline** — 20 s, no lever contact. The `D6 = 0x00` floor.
2. **Press holds in 3rd** — gentle, ~1 s / ~3 s / ~5 s, 8 s settle between. The primary reproduction.
3. **Press force ladder in 3rd** — barely-touching / light / medium / firm-but-not-shifting, ~3 s each. Finds the assertion threshold and whether it's binary in force.
4. **Escalation trials** (×3) — start gentle, confirm assertion, then *smoothly increase* until the shift completes, and keep the foot down 3 s after. Puts the assert-to-completion transition on one continuous trace.
5. **Upshift battery** — the negative claim, worked hard: gentle / medium / firm lifts in 3rd, then repeated in 2nd and 4th, then **three completed upshifts** (lift and rock until the gear engages). A negative needs this much effort before it's reportable.
6. **Press in other gears** — 2nd and 4th, ~3 s gentle holds, to test whether "especially doable in third" is a gear property or just lever feel.
7. **Rapid press taps** ×5 — short events to compare against the 60 ms ride median.
8. **Re-load after completion** ×3 — complete a downshift, fully release, then immediately re-load gently. Does it re-assert?
9. **Neutral control** — gentle press and lift in neutral.
10. **Clutch cross** ×3 — gentle press with the clutch held in, clutch bit confirmed in the live view each time.

## Analysis plan

1. **Assertion inventory.** Every `121` D6 non-zero run: onset, duration, value, enclosing step. Flag any value outside `{0x00, 0x01, 0x03}` loudly — a new value would settle the enum-vs-flags question immediately.
2. **Direction asymmetry — the headline.** Total assertion count and duration under press vs lift, across all gears and force levels in phases 2–6. The claim to test is strict silence on lift; a handful of brief lift assertions would mean "harder to trigger", which is a completely different conclusion from "gated off".
3. **Completed upshift vs completed downshift** (phases 5 and 4). Does a completed upshift engine-off produce *any* D6 activity? If a completed downshift pulses and a completed upshift stays flat, the asymmetry is in the ECU, not the linkage — the strongest result available here.
4. **Fall edge vs gear-enum change** (phase 4, 20 ms resolution). Lead / lag / same-frame, per trial. Read against the completion confound above — this is evidence, not proof.
5. **Duration distribution vs the ride corpus.** Per-hold duration against intended 1/3/5 s. Tracking rider intent confirms the 60 ms median is a mechanism-loading time, not an ECU window.
6. **Force threshold** (phase 3). Qualitative only — rider-graded force, no instrumentation. Can support "a threshold exists", never a number. This is the gap the instrumented lever closes.
7. **Micro-movement rule-out.** Across every hold: gear enum constant, and `129` D0 bit 1 ([[signal-shift-failed]]) state. Any firing there is itself notable — that flag currently rests on two firings in one 2026-06-18 capture.
8. **Torque cross-check.** `121` D0:D1 through these events. In gear engine-off it should sit pinned at −36 per [[2026-08-02-torque-engine-off-gear-dependence]]; movement during a lever-strain assertion would couple the two engine-off behaviours and force a re-read of both.

## Expected outcomes

- **Press asserts and holds, lift stays silent across the whole battery including completed upshifts** → rewrite [[signal-quickshifter]] around a downshift-conditional state with an engine-running precondition on the upshift path, and adopt the enum reading (structure B) unless something argues otherwise. Bit 1's "auto-blip" name goes.
- **Lift asserts sometimes, under firm force or in other gears** → the asymmetry is a force/linkage effect, not an ECU gate. Less interesting, but it means the sustained-hold behaviour is direction-independent and the finding just needs the stationary trigger added.
- **Nothing reproduces on the bus** → the live-view observation was a render artefact. Replay `capture.log` through the render pipeline before concluding anything ([[feedback-verify-render-against-logs]]).

## Follow-ups

- Rewrite [[signal-quickshifter]] per outcome; the bit-1 "auto-blip" name is likely wrong either way.
- **Instrumented shift lever** — load cell / strain gauge on the shift rod into a spare logger ADC. The only way to separate rod force from ECU state, and it converts the qualitative force ladder into a real threshold in newtons. Worth an ADR if we build it.
- **Engine-on stationary repeat.** If the upshift path turns out RPM-gated, the same procedure at warm idle in neutral is the direct test, and it's cheap. Note it needs a running-engine risk review first — everything here is engine-off by design.
- Does not resolve the finding's standing **QS-vs-clutched** open question (the ECU reads the same unreliable clutch switch we do), but a stationary on-demand trigger makes the eventual repaired-sensor test a 10-minute job instead of a ride.
- Candidate for the discovery essentials library ([ADR 0019](../decisions/0019-browser-signal-discovery-wizard.md)): "load the control without letting the actuation complete, and hold it" is a bike-agnostic technique for separating sensor bits from event bits — with the rod-load-collapse caveat documented alongside it, since that confound generalises to any force-sensed control.
