---
date: 2026-08-02
status: planned
phase: 2
related:
  findings:
    - can/signal-engine-torque
    - can/signal-side-stand
    - can/signal-clutch
    - can/signal-gear-position
  logs: []
---

# `121` D0:D1 engine-off: is the −36 state gear-conditional or start-inhibit-conditional?

## Hypothesis

Rider observation (2026-08-02, live view, engine off / ignition on / kill RUN): the +166 ↔ −36 throttle-threshold behaviour documented in [[2026-07-24-torque-throttle-threshold-engine-off]] **only happens in neutral**. In gear, `121` D0:D1 reads **−36 at all throttle positions**.

That capture was run in neutral throughout, so this is an unstated scope limit in [[signal-engine-torque]], not a contradiction of it. The interesting part is what the in-gear pinning implies about the semantic.

**Primary hypothesis — the −36 state is "predicted torque under a no-fuel policy", and the ECU predicts no-fuel whenever a start is inhibited.** On this bike, in gear + side stand down is the start interlock. Neutral + WOT-held is flood-clear arming. Both are "the ECU would not fuel this engine right now", and both read −36. Under this reading the throttle threshold isn't the mechanism — it's one of several inputs to a single fuel-policy prediction, and gear/interlock state is another.

**The confound that makes this experiment necessary:** the rider's in-gear observation was almost certainly made with the side stand *down*, which conflates two candidate causes:

1. **Gear itself** — the ECU pins −36 whenever the gearbox is not in neutral, interlock irrelevant.
2. **Start-inhibit** — the ECU pins −36 whenever a start is currently inhibited; in gear with the stand *up* and the clutch *pulled* (start permitted) it should revert to +166 and to threshold behaviour.

The discriminating cell is **in gear, side stand up, clutch pulled**. Everything else in the matrix is control.

**Third possibility to keep live:** interlock state is broadcast somewhere we haven't attributed. The 2026-07-24 bus-wide diff found no sibling mode bit for the *throttle* transition, but it never varied gear or stand. A gear/stand-driven transition is a fresh chance to catch a fuel-cut or start-inhibit flag on an unattributed byte.

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. Key ON, kill switch RUN, **engine OFF throughout**.
- Capture: wifi-bridge → `scripts/capture.py --experiment`. Procedure starts key-on ([[feedback-wifi-bridge-procedures-key-on-start]]).
- Rider drives throttle by hand; no mechanical throttle hold.
- **Engaging gear engine-off** needs the input shaft turning to align the dogs — rock the bike back and forth (or spin the rear wheel) while applying lever pressure, per [[2026-06-23-paddock-stand-gear-spin]]. Confirm the gear enum in the live view before starting each in-gear phase; do not proceed on a guessed gear.
- Stand-up phases need the rider **seated, feet down, bike upright** ([[project-dash-menu-blocked-by-sidestand]] is the same posture constraint).

**Clutch-sensor caveat — load-bearing for phase D.** The clutch lever switch on this bike is unreliable ([[signal-clutch]], [[project-clutch-sensor-unreliable]]). If the ECU can't see the clutch pulled, phase D is not actually the "start permitted" cell and a −36 reading there is uninterpretable. Mitigation: the live view decodes `129` D0 bit 3 — the rider pumps the lever until the bit reads 1, *then* holds. The procedure repeats phase D three times so at least one trial is likely to land with the clutch bit genuinely asserted. **A phase D trial where the clutch bit never registered is discarded, not counted as evidence for hypothesis 1.**

## Procedure

`docs/experiments/2026-08-02-torque-engine-off-gear-dependence.procedure.yaml`

```
python scripts/capture.py --port <port> --label torque-engine-off-gear-dependence \
  --experiment docs/experiments/2026-08-02-torque-engine-off-gear-dependence.procedure.yaml
```

Matrix, each cell = 10 s hands-off steady state, then one slow 0→WOT→0 sweep (~8 s up, 3 s hold, ~8 s down):

| Phase | Gear | Stand | Clutch | Expectation under "start-inhibit" hypothesis |
|-------|------|-------|--------|-----------------------------------------------|
| A | N | down | out | +166, flips to −36 at throttle ≥ 234 (replicates 2026-07-24) |
| B | N | **up** | out | same as A — isolates the stand from the gear |
| C | 3 | down | out | pinned −36, no throttle response |
| C2 | 1 | down | out | same as C — tests "not-neutral" vs a gear-value dependence |
| D | 3 | **up** | **pulled** | **+166 with threshold behaviour restored** (×3 trials) |
| E | 3 | up | out | pinned −36 — the paired control for D |

## Analysis plan

1. **Per-cell steady-state value of `121` D0:D1** at throttle 0, and the full throttle-vs-D0:D1 histogram per cell. The 2026-07-24 result gives the neutral reference: strictly two-valued, no intermediates, threshold at `120` D2 = 234, ~500 ms entry debounce, ≤1 frame exit.
2. **Does the threshold survive in-gear?** In any cell where D0:D1 is not pinned, extract the crossing throttle value and the entry debounce and compare against 234 / ~500 ms. A *different* threshold or debounce in-gear is a much more interesting result than a pin.
3. **Phase D validity gate.** For each D trial, confirm `129` D0 bit 3 (clutch) was actually 1 for the duration. Report trials separately; do not pool.
4. **Bus-wide diff on the gear transitions.** Last frame before / first frame after each N↔gear enum change, all always-on IDs, D7 excluded ([[byte-d7-cycle-hash]]). Prime suspects for a start-inhibit flag: `540` (already carries side stand), `12A`, `12D`, `129`. Same diff across the stand transitions.
5. **`121` D2:D3.** Pinned at exactly +463 in the neutral engine-off capture. Does it move with gear? If it tracks the gear condition while D0:D1 also does, the "channel B is redundant torque" reading gets stronger; if it stays +463 across everything, it's an engine-off constant.

## Expected outcomes

- **D reverts to +166 / threshold behaviour, with the clutch bit confirmed asserted** → the driver is start-inhibit, not gear. `signal-engine-torque` § engine-off gets rewritten around a fuel-policy prediction with interlock as an input, and we go looking for the interlock flag on the bus as a follow-up (it would be a genuinely useful dashboard signal — "why won't it start").
- **D stays pinned at −36 with the clutch bit confirmed asserted** → gear alone pins it. Simpler, less interesting, still needs the finding scoped. Note this outcome is also what a broken-clutch-input ECU would produce even if the true rule is interlock-based, so it is weaker evidence than it looks — say so in the result.
- **A or B fails to replicate the 2026-07-24 threshold** → something in the setup differs from that session (temperature, elapsed key-on, battery state). Stop and diagnose before interpreting C–E; the whole matrix depends on A being the known reference.

## Follow-ups

- Rewrite [[signal-engine-torque]] § "Idle behaviour" — the engine-off two-state description must state its gear/stand conditions whatever the outcome.
- If an interlock flag is found on the bus: new finding under `docs/findings/can/`, and it likely belongs in the dashboard's startup diagnostics.
- Candidate for the discovery essentials library ([ADR 0019](../decisions/0019-browser-signal-discovery-wizard.md)): "does this signal's behaviour depend on gearbox/interlock state?" is a bike-agnostic sweep worth running against any engine-off scalar, not just this one.
