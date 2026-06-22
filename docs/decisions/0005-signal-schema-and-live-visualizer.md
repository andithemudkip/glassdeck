# 0005 — Canonical signal schema and live-visualizer principle

**Date:** 2026-06-21
**Status:** Accepted

## Context

Two related needs have surfaced after the Phase 1 desk-batch close-out.

**1. Decoded-signal locations are scattered.** The same (ID, byte, bit) constants appear hardcoded across nine decoder scripts (`kill_switch_scan.py`, `gear_scan.py`, `side_stand_scan.py`, `throttle_sweep.py`, `cross_session_diff.py`, etc.). The "known signal" table in [[2026-06-21-cross-session-payload-diff]] is reproduced in each script as a literal — adding a confirmed signal means editing several files, and they can silently drift apart. There is no single artifact that says "this is what we currently believe about the bus."

**2. The capture → desk-analyze loop is the bottleneck for the next batch.** Phase 1's remaining experiments — gear sweep 2–6, clutch revalidation, ROAD/SUPERMOTO toggle, dash buttons, throttle blip — all require the engine running on a paddock stand. That is exactly when post-hoc cycle time hurts most: every speculative capture costs a teardown and an analysis pass before you know whether you got useful data. A live view answering "did anything actually flip when I pressed that button?" would convert several speculative captures into one guided session.

But naïvely bolting on a live decoder creates two failure modes:

- **Drift.** A live view with its own decoder implementation diverges from the post-hoc scripts. The screen says one thing, the analysis script says another.
- **Exclusive observation channel.** A human watching the screen confirms something ("yes, bit X is the clutch") and the confirmation never lands in files. The next agent reading the session is missing context that only the human saw.

The decision below addresses both — the schema is what prevents drift, and the visualizer principle is what prevents the exclusive-observation failure.

## Decision

**Adopt `signals/signals.yaml` as the canonical decoded-signal schema.**

- Single file under `docs/signals/` listing every promoted signal: arbitration ID, byte range, bit range, encoding, scale/offset, polarity, units, source finding link.
- Every entry corresponds to a `confirmed` or `provisional` finding under `docs/findings/can/`. Promoting a signal means writing the finding *and* adding it to `signals.yaml` in the same change.
- Decoder scripts that currently hardcode (ID, byte, bit) constants migrate to read from `signals.yaml`. The hardcoded "known signal reproduction check" tables in `cross_session_diff.py` and `bit_transition_scan.py` become assertions against the schema.
- Format is hand-editable YAML for Phase 1. Conversion to DBC happens later (or as an export) once the entry count justifies a binary tool — `signals.yaml` stays the source of truth.

**Build a live visualizer as a `--live` mode of `scripts/capture.py`, governed by three principles.**

1. **Reuse, don't fork.** The live "flipped-since-mark" pane runs the same windowing logic as `bit_transition_scan.py` over a sliding window. The live decode pane reads `signals.yaml` — the same file the post-hoc scripts read. Divergence between live and post-hoc is a bug in shared logic, not "two implementations."
2. **No exclusive observation channel.** Anything the human notices live must have a path back into the session artifacts. The mechanism is the existing event-mark system extended with a hotkey that captures the current "flipped-since-mark" table as a sidecar JSON in the session directory and inserts a labeled event mark referencing it. "I confirmed X at 14:32:01" survives as a file, not as something only on-screen.
3. **Reconstructibility test.** The design constraint: if the visualizer is turned off, an agent reading the session afterwards must get the same picture they would get with it on. Anything the visualizer *shows* must be reproducible from `capture.log` + `events.csv` + `signals.yaml`. Anything the human *learns* lands in `session.md`, an event mark, or a signals.yaml update.

**Optional `live_decode.csv` sidecar.** When `--live` is active, the visualizer also streams per-frame decoded values of every `signals.yaml` entry to `live_decode.csv` next to `capture.log`. Same code path as the on-screen decode — no second implementation. Costs nothing because the decoder is running for the screen anyway; saves agents a decode pass when analyzing the session.

## Consequences

- One-time migration: existing decoder scripts replace their hardcoded constants with `signals.yaml` lookups. The known-signal reproduction checks in `cross_session_diff.py` and `bit_transition_scan.py` become the schema's self-test.
- Adding a confirmed signal becomes a two-step ritual: write the finding under `docs/findings/can/`, add the entry to `signals.yaml`. Both live view and every post-hoc script pick it up automatically.
- The visualizer cannot become ground truth. The reconstructibility test is the load-bearing constraint: future contributors (human or agent) extending the visualizer must satisfy it or the principle is broken. If you find yourself wanting to add a feature that violates it, the right move is to add the underlying derivation to a script first, then surface it in the visualizer.
- Sets up the bike-portability goal ([[dashboard-bike-portability]]) concretely: another bike means another `signals.yaml`, same tooling. The eventual phone-app dashboard ([[deferred — no ADR yet]]) consumes the same schema over BLE for the same reason.
- `capture.py` grows a TUI dependency (textual or curses). Acceptable; it's an optional flag, not the default capture path.
- Cost of getting the visualizer wrong: the screen lies, the human trusts it, an experiment burns. The reconstructibility test mitigates this — anything on-screen can be verified post-hoc against the same artifacts.
- If a future need (live multi-host viewing during rider-in-motion experiments, phone-app telemetry) demands a separate viewer process, supersede this ADR. The schema half (`signals.yaml`) almost certainly carries forward unchanged; the visualizer half may evolve from a `capture.py` mode into a standalone consumer of the same stream.
