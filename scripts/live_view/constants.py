"""Module-wide constants for the live_view TUI."""

from __future__ import annotations

FLIP_WINDOW_SECS = 0.5  # observe flips for this long after each event mark
DECODED_REFRESH_HZ = 4
FRAME_DRAIN_HZ = 30
PROCEDURE_TICK_HZ = 10
STALE_AFTER_SECS = 2.0  # dim decoded values not updated within this window

PREVIEW_LOOKAHEAD = 3  # number of upcoming steps shown on the operator screen

# ADR 0007 — baseline-aware discovery
EWMA_ALPHA = 0.06           # ~32-sample effective window
SIGMA_FLOOR = 0.005         # 5 ms; prevents z-explosion on perfect counters
SPARKLINE_WIDTH = 12
SPARKLINE_BUFFER = 12
DISCOVERY_PANE_ROWS = 10
WATCH_MODAL_LIST_ROWS = 6
