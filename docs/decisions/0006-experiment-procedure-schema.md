# 0006 — Experiment procedure schema and operator screen

**Date:** 2026-06-22
**Status:** Accepted

## Context

The capture-time experimentation loop currently asks the rider to memorise a procedure (often dozens of timed steps — see `2026-06-18-kill-switch-toggle.md`: six RUN↔STOP toggles with 5 s settles; or the upcoming gear-sweep 2→6 + clutch revalidation batch) and execute it while also flipping the physical switch, watching the bike, and hitting the right hotkey on `scripts/capture.py`. In practice this means high cognitive load and the occasional mis-toggle, mis-timed mark, or skipped settle window — any of which can degrade post-hoc analysis because the decoder scripts assume the procedure was executed cleanly (e.g. `kill_switch_scan.py` partitions the capture into exactly seven windows from six toggles).

Two related observations make this worth fixing now rather than later:

- **Procedures are already first-class artifacts.** Every experiment under `docs/experiments/` documents a procedure in its body, and CLAUDE.md mandates the procedure exists before the capture runs. The procedure is the load-bearing thing the rider needs to follow exactly. It is currently only encoded as human prose.
- **Auto-generated event marks would be more reliable than human-keyed ones.** When the operator hits `k` "around" the moment they flick the switch, the timing is rider-bounded (reaction time + intent-vs-physical-travel delay). When a procedure script *tells* the rider when to act and logs the mark at the prompt moment, the timing is procedure-bounded — and the post-hoc scripts get a labeled timeline they can rely on (`kill toggle 3 of 6 → STOP` is more useful than the seventh anonymous `kill` row).

The natural extension is to (a) give procedures a machine-readable form and (b) drive the operator through them with a dedicated screen during capture. This sits cleanly atop ADR 0005's principles: live UI is presentation, all observations land in artifacts.

## Decision

**Adopt `procedure.yaml` as a sidecar to each experiment that warrants scripting.**

- One file per experiment, co-located with the experiment markdown: `docs/experiments/<slug>.procedure.yaml`. The experiment markdown links to it; the YAML is the source of truth for the procedure.
- Not every experiment needs one. Procedures are only for experiments whose value depends on consistent timing or step ordering. Ad-hoc / exploratory captures still go through `capture.py` with classic hotkey marks.
- Schema per step:

  ```yaml
  name: kill-switch-toggle
  description: Six RUN↔STOP toggles to locate the kill bit
  experiment: 2026-06-18-kill-switch-toggle      # back-reference to the .md slug

  steps:
    - prompt: "Settle bike — ignition on, kill RUN, idle if engine on"
      duration_secs: 10
      mark: { key: idle_settled, label: "idle settled" }

    - repeat: 6                                  # loop construct; iter is 1-based
      steps:
        - prompt: "Toggle kill switch to STOP"
          countdown_from: 3                      # show 3..2..1..NOW cue
          duration_secs: 5
          mark: { key: kill, label: "kill toggle {iter} of 6 (→ STOP)" }
        - prompt: "Toggle kill switch back to RUN"
          countdown_from: 3
          duration_secs: 5
          mark: { key: kill, label: "kill toggle {iter} of 6 (→ RUN)" }

    - prompt: "Experiment complete. Press q to stop capture."
      duration_secs: null                        # null = wait for manual advance
  ```

- `mark` is optional. When present, an event is auto-logged into `events.csv` at the step's start moment (NOT at the keypress moment — the cue is the timing reference). Label placeholders `{iter}` and `{loop_count}` interpolate from the enclosing `repeat`.
- `countdown_from` is an optional small int (typically 3). When present, the operator screen displays a countdown for those final seconds of the previous step's settle / lead-in.
- Loops are flat (no nested repeat for now); a single-level `repeat` covers every existing experiment's shape.

**Build the operator screen as a separate Textual screen, switchable from the analysis view.**

- New `--experiment <path>` flag on `capture.py` — when given, the procedure loads and capture launches in operator screen by default. `--live` without `--experiment` keeps the current three-pane analysis view.
- `Tab` toggles between operator screen and analysis screen. During the experiment the operator screen is the focus; between steps or after the experiment ends, the rider can flip to the analysis screen to inspect what happened.
- Operator screen layout (vertical):

  ```
  ┌──────────────────────────────────────────────────────────┐
  │  STEP 4 of 13                              ▌▌▌▌▌▌░░░░░   │
  │                                                          │
  │     Toggle kill switch to STOP                           │
  │                                                          │
  │                     3                                    │
  │                                                          │
  │  Coming up:                                              │
  │    → Toggle kill switch back to RUN          (5s)        │
  │    → Toggle kill switch to STOP              (5s, ⏱3)    │
  │    → Toggle kill switch back to RUN          (5s, ⏱3)    │
  │                                                          │
  │  Tab: analysis view   Space: pause   ←: prev step        │
  ├──────────────────────────────────────────────────────────┤
  │  04:23   frames 12,438   ids 11   marks 4   step 4/13    │
  └──────────────────────────────────────────────────────────┘
  ```

- Big prompt + big countdown is the focal point; next 3 steps shown in a compact preview so the rider knows what to prepare for. Status line preserved at the bottom for bus-alive feedback.
- Hotkeys: `Tab` switch screen; `Space` pause/resume the procedure (capture continues — only the step advance is paused); `←` jump to previous step (logs a `procedure-rewind` event); `q` quit. The classic hotkeys (k/g/n/etc.) remain available for ad-hoc marking on top of the procedure marks.

**Snapshot the procedure into the session directory.**

- When `--experiment` is passed, copy the YAML into `<session>/procedure.yaml.snapshot` before capture starts. The session becomes self-documenting: an agent reading it sees exactly what the operator was instructed to do, not just what was marked in `events.csv`. (The reconstructibility-from-artifacts principle from ADR 0005 applied to the procedure layer.)

## Consequences

- **New artifact type under `docs/experiments/`.** Adding `procedure.yaml` files alongside the `.md` is additive — no existing experiment changes shape. Conventions for naming, location, and the back-reference field need a one-line note in CLAUDE.md's `### Experiments` section so future experiments and agents reach for the sidecar by default for scripted procedures.
- **Post-hoc scripts get richer event-mark labels.** Decoder scripts like `kill_switch_scan.py` currently look for the rider's `k` keypresses and assume exactly six. With procedure-driven marks they can match by label (`kill toggle N of 6 (→ STOP)` vs `(→ RUN)`) and explicitly verify the expected count. Migration optional, opportunistic — the existing label-agnostic windowing still works.
- **Operator-screen mode trades the analysis view for focus during the experiment.** When you need novel-discovery surface (Tab back to analysis), you have it; when you're mid-countdown, you don't see bit-flip tables you can't act on. This matches the cognitive-load reality the rider lives with.
- **Auto-marks vs human marks are timed differently.** A procedure-driven mark is logged at the *cue* moment, before the rider physically completes the action (the existing rider-keyed `k` mark is logged at the *intent* moment, also before completion — same class of latency, but procedure marks are zero-jitter relative to the prompt). Scan scripts that trim "debounce slop" around marks (e.g. `kill_switch_scan.py`'s post-mark trim) keep their existing logic; the trim window may want tuning if procedure-driven sessions show systematically different rider-completion latencies.
- **Pause + rewind change the session timeline shape.** A `procedure-rewind` event mark lets post-hoc scripts notice and either ignore the rewound segment or analyse both attempts. Pauses simply stretch the timeline; capture continues throughout.
- **Library surface grows.** A small `scripts/procedure.py` (parser, validation, step iterator with countdown/duration logic, loop expansion) becomes a new module alongside `scripts/signals.py`. Both are schema loaders; both have post-hoc consumers and live consumers. Same pattern.
- **Scope discipline.** Procedures are for *scripted* experiments. Free-form first-motion captures, debug sessions, or any experiment whose value lies in observation rather than timing don't need a procedure file. Don't gold-plate every experiment with one — the existence of the file should mean "this needs to be executed exactly as written."
- **Future extensions deferred.** No nested repeats, no branching/conditional steps, no inline pass/fail criteria, no auto-replay against a captured log. All possible later if pressure exists; out of scope here.
