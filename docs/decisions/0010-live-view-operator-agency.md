# 0010 — Live view: operator agency on the discovery surface

**Date:** 2026-06-22
**Status:** Draft

## Context

ADR 0007 added bit-flip discovery and ADR 0008 added byte-value discovery. Together they form a credible discovery surface — automatic baselines, hysteresis, classification — and the analytical side is doing real work. But the surface is **read-only**, and its behaviour is **set at startup**:

- Eight CLI flags now shape what surfaces (`--anomaly-z-threshold`, `--anomaly-warmup-flips`, `--discovery-retention-secs`, `--show-d7`, `--show-suppressed`, `--byte-activity-window-secs`, `--byte-activity-ratio`, `--byte-activity-hysteresis-secs`). Defaults are well-reasoned, but the operator has no in-session way to discover that the threshold is wrong for this bus, or this session. They quit, re-launch, re-baseline. The whole 0007/0008 warmup pays again.
- After 0008 lands the screen carries **seven panes** (watch / decoded / flipped-known / flipped-unknown / continuous-bits / active-bytes / status). The ADR itself flagged this as tight. The `1fr` decoded pane — the one most useful to a non-discovery operator — is the loser every time a new discovery pane lands. Collapsibility was deferred; it has now come due.
- When the active-bytes pane surfaces "0x290 D2 is a sensor, range 142, ratio 23×, shape `sensor`" the operator's next move is to `alt-tab` to an editor and write a `signals.yaml` entry by hand. The classifier knows the shape, the pane knows the arb+byte+range, the watch infrastructure knows how to pin things — but none of that flows into a hypothesis the next session can act on. The discovery loop has one step left.

These three gaps share a theme: the discovery surface should be a conversation, not a display.

We considered and rejected: adding more detection (smarter classifiers, finer baselines) — the analytical side is already past the point of diminishing returns relative to operator-control returns; a richer set of CLI flags — more knobs the operator must guess at; auto-collapsing panes by content — surprising layout shifts during a ride are worse than wasted real estate.

## Decision

Three changes, ordered by how load-bearing each is.

### 1. Collapsible panes

Every analysis-screen pane gets a one-line collapsed state showing only its header and a brief content summary (e.g. `Active unknown bytes  [3 rows]` or `Decoded signals  [12 named, 2 stale]`). Default state is **all expanded** — no startup surprise. Hotkey `Ctrl+1` … `Ctrl+7` toggles pane 1 through 7 from top to bottom; the status pane is always visible and not in the cycle. Collapsed state is session-local (not persisted to disk — the operator will re-collapse on the next launch and that's fine).

Implementation is a CSS height toggle plus a per-pane bool on the `AnalysisScreen` instance. The pane's render method already exists; collapsed mode just renders the header line.

Why explicit (operator-driven) and not implicit (auto-collapse on empty): a procedure-driven ride is exactly when panes go from "empty" to "spiking" and back. Auto-collapse would yank vertical real estate around mid-ride. Stable layout > efficient layout.

Why `Ctrl+digit` and not a "panes" overlay modal: zero-friction. The operator's already looking at the pane; one chord and it folds. A modal would be discoverable but slower for the everyday case.

### 2. Hot-tunable thresholds

Two of the eight CLI flags are tuned constantly across sessions in practice — `--anomaly-z-threshold` and `--byte-activity-ratio`. They are the multiplicative gates on the two discovery panes; the operator dials them as they learn the noise floor of the current bus. Make them in-session adjustable:

- `Ctrl+↑` / `Ctrl+↓` — bit-flip `z_threshold` by ±0.5 (clamped to ≥ 0.5)
- `Alt+↑` / `Alt+↓` — byte-activity `ratio` by ±0.5 (clamped to ≥ 0.5)

Current values render in the status pane:

```
[Status]  …  z=3.0  ratio=3.0×  (Ctrl-↑↓ z, Alt-↑↓ ratio, Ctrl-D D7, Ctrl-Y suppressed)
```

Two binary toggles join them since they share the "currently filtering the pane" character:

- `Ctrl+D` — toggle `show_d7`
- `Ctrl+Y` — toggle `show_suppressed`

Settings remain session-local. They never write back to disk. If a setting consistently wants a non-default starting value, the CLI flag is still the path.

We considered a settings modal (`s` opens an overlay with arrow-key controls). Rejected: tuning a threshold and watching the pane respond is the entire interaction — a modal blocks the very thing the operator is trying to see. The inline-HUD-in-the-status-pane variant gives 4 Hz feedback in the pane itself.

We considered making more flags hot-tunable (warmup-flips, retention, window-secs, hysteresis-secs). Rejected for now: they're structural, not dial-knobs. Operators tune them once per project, not per session. If experience shows otherwise, add more keybindings — the framework will already be in place.

Constraint that drove keybinding choice: every printable character is reserved for mark hotkeys (`capture.py` HOTKEYS). Modifier+arrow combinations are the only safe namespace.

### 3. Hypothesis capture from a pane row

A new hotkey `Ctrl+N` opens a small modal listing the top rows currently in the active-unknown-bytes pane (and, in a second tab — `Tab` switches — the continuous-bit pane; both tabs ship in the first iteration). The operator picks a row from the list, types a name, optionally edits the proposed encoding (defaulted from the classifier — `sensor` → `uint`, `boolean` → `bool`, `counter` → `uint`, `step` → `enum`; bit rows default to `bool`), and submits.

(Originally drafted as `n`. Changed to `Ctrl+N` during implementation because `n` is the `neutral` mark hotkey in `capture.py`'s `HOTKEYS` table — intercepting it for the modal would silently drop the mark. `Ctrl` is the only modifier namespace that's both unambiguous on macOS and Linux terminals and currently unused.)

Output is a YAML stanza appended to `<session_dir>/hypotheses.yaml` (created on first use):

```yaml
- name: throttle_hint
  status: hypothesis
  arbitration_id: 0x290
  byte: 2
  bit_length: 8
  encoding: uint
  scale: 1
  offset: 0
  notes: "Captured live 2026-06-22T14:32:01; range 142, ratio 23.5×, shape=sensor."
```

The shape, range, and ratio at capture time get embedded in `notes` automatically — these are exactly the breadcrumbs a future session needs to decide whether the hypothesis held up. The file is session-scoped because **hypotheses are not findings**: the project convention (CLAUDE.md golden rule #4) says a hypothesis is promoted to `docs/findings/` and `docs/signals/signals.yaml` only after a confirming experiment. The session's `hypotheses.yaml` is the raw material the next experiment is designed around.

A future iteration could load `hypotheses.yaml` back into the live decoder (so the named byte appears in the decoded pane immediately, with a `hyp:` prefix marking it provisional). Out of scope here — the minimal version is the capture; consumption is one step removed and warrants observation before commitment.

Watch-pinning the captured row at submit time is the natural pairing — the operator named it because they want to watch it — so the modal includes a default-on "pin to watch panel" checkbox. Unchecking is a single key.

We considered appending directly to `docs/signals/signals.yaml` from the hotkey. Rejected: it conflates hypothesis with finding, violates the golden rule, and creates a class of typo that's hard to undo (a yaml syntax error in `signals.yaml` breaks all future captures). Session-scoped file is the right blast radius.

We considered adding row-focus navigation (arrow keys to select a row in the active-bytes pane, then capture the focused row). Rejected for the MVP: focus management across multiple panes is a bigger Textual lift than the value warrants. The modal-with-numbered-list works and matches `WatchModal` precedent.

## Consequences

- **The discovery loop now closes inside one session.** Sweep the byte, see it surface, press `n`, name it. The next ride starts with a structured hypothesis to confirm or refute rather than a vague "I think I saw the RPM byte move." This is the loop ADR 0008 promised but stopped one step short of.
- **Eight CLI flags shrink to four-plus-two-keybindings.** The structural flags stay (window sizes, hysteresis windows, retention). The two threshold flags become defaults the operator can override at any moment without leaving the session. Toggle flags become keybindings. The CLI surface is no smaller, but the perceived complexity at the prompt is: defaults that "just work" become explicit only when the operator wants them to be.
- **Vertical real estate stops being zero-sum.** Adding a future pane (mark-driven byte view from 0008 §5, or anything else) no longer means another fixed slice of the screen; collapsibility absorbs it.
- **Hypothesis files are a new artifact under `logs/`.** They sit alongside `session.md` / `events.csv` / `live_decode.csv` as part of the session record. They're append-only during a session; never modified after the session closes (same discipline as raw captures). A new `scripts/promote_hypothesis.py` (out of scope here) would later be the path from `hypotheses.yaml` → `signals.yaml`, gated by an experiment.
- **One more file in the session dir to describe.** The `session.md` template will gain a "Hypotheses captured" section. Trivial.
- **Status pane grows by one line.** From three lines to four. Acceptable given collapsibility is now an option for everything else.
- **Keybinding budget is now tight.** `Ctrl+digit` × 5 (the layout has five collapsible panes top-to-bottom; the side-by-side bit panes share one slot), `Ctrl+/Alt+↑↓` × 4, `Ctrl+D`, `Ctrl+Y`, `Ctrl+N`, plus the existing `?`, `.`, `w`, `u`, `Tab`, `Space`, `Left`, marks. The legend pane (`?`) needs updating; beyond that the only constraint is "printable chars are marks." Future keys must keep using modifiers or fold into modals.
- **Scope discipline.** This ADR is in-session interaction with the existing discovery surface. It is not a redesigned decoder, not a `signals.yaml` editor, not a hypothesis-promotion pipeline, not a non-modal HUD framework. Each of those is its own decision if pressure exists.
- **Implementation touch points.** `scripts/live_view/app.py` gains keybindings, status-line rendering of current tunables, a `_capture_hypothesis` action, and an `is_collapsed: dict[str, bool]` on `AnalysisScreen`. `scripts/live_view/modals.py` gains a `HypothesisModal`. `scripts/live_view/screens.py` CSS gets a collapsed variant per pane. `capture.py` gains nothing — the CLI surface is unchanged; the new flags would be regressions. `docs/signals/signals.yaml` is untouched.
