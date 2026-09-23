# 0020 — Browser-based operator procedure runner

**Date:** 2026-07-26
**Status:** Proposed
**Relates to:** [ADR 0006](0006-experiment-procedure-schema.md) (moves the operator surface it introduced from Textual to the browser; procedure schema v1 unchanged); [ADR 0018](0018-m4-browser-primary-capture.md) (reuses `POST /mark` and browser-primary capture); [ADR 0019](0019-browser-signal-discovery-wizard.md) (narrows its "no retirement plan" for `scripts/live_view/` — see § Consequences)

## Context

ADR 0006 gave procedures a machine-readable schema and a Textual operator screen that drives the rider through them. A month of procedures later, the schema is holding up — nothing in `docs/experiments/` has needed schema changes since it landed — but the presentation layer is showing its limits.

The TUI is bottlenecked by what a terminal can do:

- **Typography is capped at cell size.** The big prompt tops out at whatever Textual's `Digits` widget renders in the current terminal font; there is no "make the countdown fill the viewport." Rider has to lean in to read at arm's length.
- **Color and motion are ANSI-shaped.** Mode transitions (rest → ready → act) are border-color swaps. There is no full-viewport wash for the "GO" moment, no pulse animation, no genuine attention-grabbing render — the things a rider actually needs when a hand is on a control.
- **One keyboard, no touch, no voice, no haptics.** The rider on the bike can't feel the mode change with gloves on, can't hear the next step called out, can't tap a big pause zone. All of these are things the operator role actively needs and the TUI structurally can't provide.
- **Layout is vertical-terminal-shaped.** A phone in a tank bag or on a bar mount is landscape and touch-first; the TUI's layout was designed around a laptop on a workbench.

Two developments make now the right time to move:

1. **ADR 0018 already put the browser in the capture loop.** Every session already has a browser tab open on the operator's phone recording to IDB, and marks already flow in-band as `# MARK` lines via `POST /mark` → ring → `/stream` → the same tab's IDB sink. The transport for a browser-side operator runner is fully built out; only the UI and the state machine are missing.
2. **ADR 0019 committed to a browser-first flow for the discovery wizard.** That wizard is going to render an operator UI over the same procedure schema. Having two operator implementations (Textual for authored experiments, browser for discovery) doubles the surface for a role that is fundamentally the same.

The intent here is deliberately narrow. This ADR moves the operator *surface* from Textual to the browser. It does not change the procedure schema (v1 stays; schema v2 is ADR 0019's concern, layered on top of this runner). It does not change what analysis scripts do with marks — only where the marks come from on disk.

### Considered and rejected

- **Keep the TUI operator screen, add a browser one alongside.** Dual-maintaining the same state machine in Python and JS pays ongoing tax for no user-visible upside — every procedure schema tweak becomes a two-language change. The TUI operator screen has served its purpose; retiring it is the honest move once the browser path is stable.
- **Serve procedures from the ESP.** Would require a build step to embed selected `.procedure.yaml` files into the firmware image, or a companion HTTP server on the laptop. Both add friction; the phone browser can pick a YAML off disk in five lines of JS.
- **Extend the schema to embed voice/haptic cues per step.** Tempting, but rider-agnostic defaults ("speak the prompt at start, buzz per countdown second, longer buzz at ACT") cover every existing procedure without per-step config. Add schema fields only if a real procedure needs to override.

## Decision

### Move the operator surface to wifi-bridge's browser page, landscape-primary

The operator UI becomes a new mode of the existing wifi-bridge live view — same tab, same WS connection, same IDB capture sink. Landscape-primary because the phone will be mounted (bar or tank bag) during procedure runs; portrait remains functional but not the design target.

Layout follows ADR 0006's model (big prompt, big countdown digit, coming-up preview, mode-colored surround) but uses viewport-sized typography, full-viewport wash on mode transitions, and touch-first controls. The four stoplight modes (rest / ready / act / end) become full-surround color states, not border colors.

### Port `procedure.py` to JS verbatim

New `firmware/wifi-bridge/main/ui/procedure.js`. Straight translation of `scripts/procedure.py`: schema validation, `repeat` expansion, `{iter}` / `{loop_count}` interpolation, countdown validation. Same `Procedure`/`Step`/`Mark` shape as data objects. YAML via a bundled `js-yaml` (~20 KB min+gz).

Schema v1 is untouched. Any `.procedure.yaml` that runs on the TUI today runs on the browser tomorrow with the same expansion, same mark timing, same countdown behavior.

### Procedure source: file picker

Rider taps a "Load procedure" control in the operator UI, picks a `.procedure.yaml` from the phone's file system. Uploaded via `<input type="file">`; the browser reads the bytes into memory and passes them to the parser. Simplest path, no firmware or laptop-side sidecar required, and matches the "laptop + phone both in the loop" workflow the user actually runs.

### Marks flow via `POST /mark`, extended with `?key=`

`POST /mark` already stamps `esp_timer_get_time()` at receive and emits `# MARK <label>\r` into the ring + `/stream` (main.c:602). Extend the handler to accept an optional `?key=` query param and emit `# MARK key=<key> label=<label>\r` when present, falling back to the current `# MARK <label>\r` shape when absent (backward-compatible with M7a callers).

The operator runtime posts one mark per procedure step at step-start, matching TUI semantics. `procedure-rewind` and `procedure-skip` are posted with those literal keys.

Timing model: firmware stamps at receive. Browser-to-firmware RTT on the AP is single-digit ms in practice — same order as Textual's tick→EventLogger latency. No behavioural change to downstream analysis.

### Marks live in the capture stream, not `events.csv`

The browser doesn't write a separate `events.csv`. `# MARK` lines land in the recorded capture.log via the WS echo, at ring-authoritative timestamps, in the exact byte position they arrived. This unifies the two mark sources the project has today (TUI's `events.csv` + wifi-bridge's in-stream `# MARK`) down to one going forward.

Analysis scripts that read `events.csv` (`scripts/verify_procedure.py` and any consumers of the auto-marks defined in `procedure.py::auto_marks`) grow a second source: `# MARK` lines grepped out of `capture.log`. Both sources are supported during the transition; new sessions produce only the in-stream form.

### Voice and haptics on by default

- **Voice** (`window.speechSynthesis`): speak the step's `prompt` at step start. Speak "now" at the ACT transition. Countdown numerals stay visual/haptic — spoken numerals talk over the rider's own thinking without adding information the digit doesn't already carry.
- **Haptics** (`navigator.vibrate`): short buzz per countdown second in ready mode; longer buzz at the ACT transition; double-buzz on mark-fired confirmation.
- Both surfaces are individually togglable in the operator UI, persisted to `localStorage` alongside the existing prefs (see `ui/prefs.js`). Defaults: on.

### Touch gestures

Explicit on-screen buttons — prev / pause / skip / quit — visible during `rest` and `end` modes. Hidden during `ready` and `act` so the rider can't tap them mid-action. Keyboard shortcuts (`Space`, `←`, `→`, `q`) remain available for the laptop-side view but are not the design target.

### Snapshot: YAML bytes as IDB sidecar

The uploaded YAML bytes are stored verbatim as a sidecar record in the capture's IDB entry, exported alongside `capture.log` as `procedure.yaml.snapshot`. Byte-for-byte match with what `capture.py --experiment` writes today, so downstream tooling doesn't care which runner produced the session directory.

### Retire the TUI operator screen once the browser path is stable

`scripts/live_view/screens.py::OperatorScreen` and its `_procedure_tick` / `_start_step` machinery in `scripts/live_view/app.py` come out. `capture.py --experiment` prints a redirect message pointing at the browser flow. `scripts/live_view/`'s analysis screen (three-pane discovery / active-bytes / watch) stays as the R&D TUI surface for advanced users — this narrows [ADR 0019](0019-browser-signal-discovery-wizard.md)'s "no retirement plan" for `scripts/live_view/` down to the analysis screen specifically.

Retirement is gated on the browser runner reproducing a full existing procedure end-to-end with matching marks in the capture.log — not on this ADR being accepted.

## Consequences

- **Ongoing tax on the procedure schema drops by half.** One runner, one schema evolution surface. When ADR 0019's schema v2 introduces typed discovery step kinds, the browser runner is where the render specializations land — no Textual counterpart to keep in sync.
- **`events.csv` becomes a legacy artifact.** Existing sessions with `events.csv` keep working; new sessions don't produce one. The two-source period ends when the last TUI-driven session is analysed. `scripts/verify_procedure.py` grows a `# MARK` reader that returns the same shape `auto_marks()` compares against — modest refactor, single place.
- **Rider UX gains that the TUI structurally can't provide.** Viewport-scaled prompt and countdown, full-viewport mode wash, `speechSynthesis` prompting, `navigator.vibrate` cues on countdown / ACT / mark. Landscape phone layout matches the mount / tank-bag reality. Eyes-off procedure execution becomes plausible in a way it wasn't.
- **One transport, one storage clock, one recording path.** Marks stamped at firmware receive, echoed on `/stream`, recorded in the same tab's IDB. No separate CSV, no host-side clock offset, no session directory to reconstruct — the exported capture bundle *is* the session artifact.
- **Firmware change is small and additive.** `mark_handler` grows a `?key=` branch (~20 lines). Existing M7a `POST /mark?label=` calls keep working unchanged.
- **Punch list for the execution session:**
  1. Firmware: `mark_handler` accepts `?key=`, emits `# MARK key=<k> label=<l>\r` when present.
  2. `firmware/wifi-bridge/main/ui/procedure.js` — port of `scripts/procedure.py`.
  3. Operator UI: landscape layout, tick engine, mode-color transitions, buttons, keyboard shortcuts.
  4. Voice + haptics surfaces, prefs toggles, localStorage persistence.
  5. `capture.js`: procedure picker, IDB sidecar record for the YAML bytes, export bundle includes `procedure.yaml.snapshot`.
  6. `scripts/verify_procedure.py` (and any other `events.csv` consumers surfaced by grep): accept `# MARK` from `capture.log` as a mark source.
  7. TUI operator retirement: delete `OperatorScreen`, strip `_procedure_tick` / `_start_step` from `app.py`, `capture.py --experiment` prints the redirect.
- **Out of scope, deferred.** Schema v2 (ADR 0019's typed discovery kinds). Procedure discoverability from the ESP (curated list served from firmware) — file picker covers current needs. Procedure editing in-browser (author still edits YAML in the repo). Multi-rider procedure sync across multiple connected phones — one operator, one tab.
