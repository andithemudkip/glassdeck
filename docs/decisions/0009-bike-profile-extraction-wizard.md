# 0009 — Bike-profile extraction wizard

**Date:** 2026-06-22
**Status:** Superseded by [ADR 0019](0019-browser-signal-discovery-wizard.md)

## Context

The project's stated north star is a dashboard portable across bikes ([[dashboard-bike-portability]], reinforced concretely by ADR 0005's `signals.yaml` schema). Today portability is *theoretically* possible — the firmware reads from `signals.yaml`, and another bike's signals would slot into the same schema — but operationally, the gap between "I own a different bike" and "the dashboard works on my bike" is the same multi-week reverse-engineering effort being spent right now on the 390 platform. That does not scale. Either the project is "Husqvarna dashboard with optional portability for anyone willing to repeat the work," or it builds the machinery to compress that work into something a non-expert operator can run on their own bike.

Three observations make a wizard credible now, not later:

- **The dashboard's signal needs are closed-set.** RPM, speed, gear, fuel, coolant temperature, indicators, neutral, side stand, kill switch, odometer, ABS warning, lean angle (maybe), throttle position, brake — somewhere around 15–25 signals, not a full DBC. "Find these specific signals" is a far more tractable problem than "decode the bus."
- **The primitives are in place.** ADR 0006's procedure schema already drives operators through timed step sequences with reliable cue-timed marks. `bit_transition_scan.py` finds bits that change during labeled windows. `cross_session_diff.py` correlates across sessions. ADR 0005's `signals.yaml` is already the format the firmware consumes. What's missing is (a) an orchestrator that chains per-signal procedures into a single session, (b) an inference layer that proposes typed entries from the resulting bit transitions, and (c) an operator-driven validation phase that confirms each proposal before it ships.
- **Each dashboard signal admits a purpose-built procedure.** RPM = throttle blip with operator-entered peak dash reading; gear = sequential shift through the box with neutral re-checks; indicators = left/right/hazard cycle; kill switch = the toggle pattern from [[2026-06-18-kill-switch-toggle]]. Many of these procedures already exist as one-off experiments. Curated and de-bike-ified, they become the wizard's library.

Two things this is *not*:

- **Not a generic CAN decoder.** Open-ended decoding — multiplexed messages, motion-only signals, anything not on the dashboard signal list — stays manual. The wizard's scope is the closed set the dashboard needs.
- **Not zero-knowledge.** The operator still needs hardware access: a wired adapter, the diag/OBD connector or splice point, the ability to safely run the engine on a stand. The wizard lowers the *software/analysis* wall, not the hardware wall. People who can't get on the bus electrically are not in the addressable user set.

The strategic shift is from "one bike, deeply decoded" to "any bike whose owner spends ~an hour following prompts." Community-contributed bike profiles become possible. Current project work continues to produce two outputs simultaneously: the 390 platform's profile, and the wizard's procedure library — as byproducts of the same experimental effort.

## Decision

**Build `scripts/extract.py` as the operator-facing wizard that produces a per-bike `signals.yaml` profile.**

The output is a `signals.yaml` file in exactly the schema from ADR 0005 — same format the dashboard firmware already consumes. No new artifact type, no new format. A "bike profile" is just an instance of `signals.yaml` with a header block identifying its bike and provenance.

**Each dashboard signal has one or more associated procedure files in a wizard-owned library.**

- New directory `scripts/wizard/procedures/<signal-key>.procedure.yaml` — same schema as ADR 0006's experiment procedures, reused verbatim. Each procedure is designed to make one signal's bits flip in an isolated, labeled window.
- Procedures are not bike-specific. "Shift through the gears with clutch revalidation" works the same way on a Honda as on a Husqvarna; what differs is which arbitration IDs respond to it. The procedure tells the operator what to do; inference figures out where the signal landed.
- The 390 platform's existing experiments seed the library — [[2026-06-18-kill-switch-toggle]], the gear/side-stand batch, the throttle sweep, etc. — generalised to drop bike-specific terminology. Promoting an experiment's procedure into the library is a conscious authoring step, not automatic.

**Run shape: chained procedures in one session, single output file.**

- `python scripts/extract.py --port <port> --bike <slug>` walks the operator through the full procedure battery in one session. Each procedure produces its own labeled window in a unified `capture.log`; `events.csv` records which procedure was active when. The session lands under `logs/YYYY-MM-DD-extract-<slug>/` like any other capture.
- The wizard prompts for ground-truth values inline whenever scaling is needed: "hold ~3000 RPM steady for 5 seconds; enter the dash reading at the end." These entries land in the session as labeled marks so the inference layer can correlate them with the captured frames.
- At the end of the session, an inference pass runs and emits `<bike-slug>.signals.yaml` plus a session-local report explaining how each signal was found (or why it wasn't).

**Inference: typed proposals with confidence scoring.**

- **Boolean / enum signals** (kill, neutral, side stand, gear position, indicator state): bits or byte-groups that flip exclusively during the labeled window. High confidence when one and only one bit/group correlates consistently across multiple repeats.
- **Continuous signals** (RPM, speed, coolant temp, throttle position): bytes whose values track monotonically with operator-entered ground truth across the sweep. Scale + offset solved by linear regression against the entered reference points; endianness, byte order, and signedness inferred by candidate-fit residuals across the plausible interpretations.
- **Counter signals** (odometer): bytes that increase monotonically over the session and never decrement.
- Every proposed signal carries a `confidence: high|medium|low` field and a `provenance: { procedure: <slug>, window: <id>, fit: <residual or rule> }` block. Low-confidence signals are written into the profile but commented out, requiring operator confirmation in the validation phase to enable.

**Validation phase: live confirmation loop before the profile is saved.**

- After inference, the wizard re-enters a live-decode mode (the `--live` view from ADR 0005, reusing the visualizer's reconstructibility-safe code path) and walks the operator through each proposed signal: "we think this is RPM. Rev the engine — does the value on screen track?" Operator confirms or rejects each signal.
- Rejected signals are dropped from the profile but recorded in the session's `events.csv` with the proposed mapping intact, so post-hoc readers see why each entry was accepted or dropped. A wrong-but-plausible mapping shipped silently is worse than no mapping; validation is non-skippable for any signal that did not already reach `confidence: high` from multi-repeat consensus.

**Profile metadata: provenance and tolerance.**

- Each `<bike>.signals.yaml` starts with a header block: make, model, year, ECU firmware version if known, wizard version, capture date, operator's adapter type, and the list of procedures run. Profiles are not portable between bike-model + ECU-rev combos; provenance makes the boundary explicit and lets a future registry refuse silently-incompatible reuse.
- The dashboard firmware MUST treat absent signals as "widget unavailable" rather than as a fatal error. Not every bike exposes every signal — no ABS, no lean angle, fuel sender on K-line instead of CAN. The firmware-side change is in scope of a separate ADR (signal-tolerance); this ADR's commitment is that the wizard is allowed to emit profiles with missing entries and that's a normal outcome, not a wizard failure.

**Scope: desk-reachable signals only in v1. Ride-along deferred.**

- v1 targets signals reachable from a paddock-stand desk session: ignition state, kill switch, side stand, neutral, gear (via clutch + shift), indicators, RPM, coolant temp, throttle position, brake switch.
- Motion-required signals — wheel speed, ABS faults, fuel level changes over distance, lean angle — are out of v1. The wizard emits them as `unknown` with a note that ride-along extraction is needed. A follow-up ADR will cover the ride-along tier once v1 lands and the inference quality is measured against the 390 platform's known answers.

## Consequences

- **Project frame shifts.** "Reverse-engineer the 390 platform" becomes a means to two outputs: the 390 profile, and a generalised wizard. Experiment work continues but is consciously authored so its procedure can graduate into a wizard procedure. CLAUDE.md's `### Experiments` section should pick up a one-line note about this dual purpose — promoted procedures move into `scripts/wizard/procedures/` rather than staying experiment-local, and the experiment links forward to the library file.
- **`signals.yaml` schema becomes load-bearing for outside users.** Today it is an internal artifact; once the wizard ships, third-party profiles depend on its shape. Schema changes will need a migration path. Adding a `schema_version: 1` header to every profile (and the project's own `docs/signals/signals.yaml`) is a cheap forward-compatibility step worth doing as part of v1.
- **The procedure library is the project's growth surface.** Each new signal-finder procedure added — or each existing procedure hardened against operator variance — directly improves the wizard's coverage on every bike. This is the asset that compounds, more so than any individual bike's profile.
- **Inference is the hardest engineering piece.** Boolean/enum extraction is mostly already implemented in `bit_transition_scan.py`'s windowing. Continuous-signal regression with endianness/byte-order/signedness/scale solving is new work and is where the wizard's quality bar will be set. The 390 platform's known answers become the regression test set: an inference change that breaks a known-good 390 signal is a regression.
- **Validation phase is non-negotiable.** A wizard that produces silently wrong mappings is worse than nothing — the dashboard would lie to the rider. ADR 0005's reconstructibility principle carries forward: every confirmation or rejection the operator gives during validation lands in `events.csv` with the proposed mapping recorded, so post-hoc readers see why each entry was accepted or dropped.
- **Firmware needs to handle absent signals gracefully.** Currently the dashboard assumes its target signals exist. A separate ADR will cover the firmware-side change (widget hide, N/A display, no fatal init). This ADR is upstream of that work but does not block on it for v1 wizard development — they can proceed in parallel.
- **Community profile sharing is enabled but not built.** Once one CB650R owner runs the wizard, the resulting `cb650r-2023.signals.yaml` could in principle be reused by another owner without re-running. The mechanism (registry, signing, trust, conflict resolution between contributed profiles) is out of scope here — the data-model commitment is just "profiles are shareable artifacts." A registry, if/when it exists, gets its own ADR.
- **Realistic ceiling.** v1 should aim for "works first-shot on ~60–70% of bikes for ~70% of desk-reachable signals." The rest comes from procedure-library maturity over time, community-shared partial profiles, and manual fallback for the long tail. This is a multi-month build; do not ship half-trained inference and call it done. The signal that v1 is ready is the wizard reproducing the 390 platform's existing confirmed signals end-to-end from a single fresh session.
- **Scope discipline.** The wizard's purpose is the dashboard's closed signal set. It is not a general-purpose CAN decoder. If a future use case wants full-bus decoding, that is a different tool with different constraints, not this wizard with more procedures bolted on.
- **Deferred.** Ride-along tier for motion-only signals; profile schema versioning beyond a `schema_version` field; community profile registry; profile signing and trust; firmware signal-tolerance ADR; inter-profile conflict resolution when two contributed profiles disagree on "the same" bike model; CI-style regression suite for the inference layer against fixture sessions.
