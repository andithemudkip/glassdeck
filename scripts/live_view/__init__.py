"""live_view — Textual TUI surfacing decoded signals and bit-flips live.

Two screens, switchable with Tab when a procedure is loaded:

  • AnalysisScreen (default): the three-pane decoded / flipped-bits view.
    – Decoded signals: current value of every entry in signals.yaml.
    – Flipped since last mark: every (ID, byte, bit) whose value differs
      from the snapshot taken at the most recent event mark.
    – Status: frames / unique IDs / event-mark count.

  • OperatorScreen (only when capture.py is run with --experiment): drives
    the rider step-by-step through a procedure.yaml, auto-logging marks
    at each step's cue moment. See ADR 0006.

ADR 0005 principles applied:
  • Decoded values come from signals.py (same code path as post-hoc
    decoders) — no second implementation of the schema.
  • All event marks and frames are written to capture.log / events.csv
    just as they would be without --live. The TUI is a window onto the
    same artifacts an agent could reconstruct from disk.
  • The `.` hotkey snapshots the current flipped-bits table to
    `snapshot-<n>.json` in the session dir AND records a `snapshot-<n>`
    event mark referencing it.
  • `live_decode.csv` (long format: ts, signal, value, raw) is streamed
    next to capture.log so the per-frame decoded view is available to
    agents without rerunning the decoder.

ADR 0006 additions:
  • `procedure.yaml.snapshot` is copied into the session dir by capture.py
    before the app starts.
  • Procedure-driven auto-marks share the same `_mark()` path as hotkey
    marks — the flip-baselining window opens regardless of which screen
    is visible.

Used only by capture.py when --live (or --experiment) is passed.
"""

from .app import LiveView
from .bridge import LiveBridge

__all__ = ["LiveBridge", "LiveView"]
