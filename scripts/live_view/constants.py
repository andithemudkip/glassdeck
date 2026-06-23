"""Module-wide constants for the live_view TUI."""

from __future__ import annotations

FLIP_WINDOW_SECS = 0.5  # observe flips for this long after each event mark
DECODED_REFRESH_HZ = 4
FRAME_DRAIN_HZ = 30
PROCEDURE_TICK_HZ = 10
STALE_AFTER_SECS = 2.0  # dim decoded values not updated within this window

PREVIEW_LOOKAHEAD = 3  # number of upcoming steps shown on the operator screen
MARK_FLASH_SECS = 1.5  # how long a "✓ marked: ..." confirmation stays visible
ACT_HIGHLIGHT_SECS = 2.5  # first N seconds of an action step render in "act" red

# ADR 0007 — baseline-aware discovery
EWMA_ALPHA = 0.06           # ~32-sample effective window
SIGMA_FLOOR = 0.005         # 5 ms; prevents z-explosion on perfect counters
SPARKLINE_WIDTH = 12
SPARKLINE_BUFFER = 12
DISCOVERY_PANE_ROWS = 10
WATCH_MODAL_LIST_ROWS = 6

# ADR 0011 — live anomalies pane redesign
ANOMALY_HOT_SECS = 3.0           # rows brighter while younger than this
ANOMALY_WARM_SECS = 20.0         # rows dim once older than this
ANOMALY_COOCCUR_SECS = 0.3       # cluster radius for the co-occurrence accent
ANOMALY_HALO_SECS = 4.0          # halo persists this long after a mark hotkey
ANOMALY_ACCENT_COLORS = ("cyan", "magenta", "green", "yellow")

# ADR 0008 — byte-level activity discovery
ACTIVITY_WINDOW_SECS = 2.0          # default rolling window for short_range
ACTIVITY_RATIO = 3.0                # default multiplicative threshold
ACTIVITY_HYSTERESIS_SECS = 5.0      # ADR 0012 — HOT-tier extension past active_now (was 3.0 exit grace)
ACTIVITY_EWMA_ALPHA = 0.02          # ~100-sample effective window for baseline_range_ewma
BASELINE_FLOOR = 4                  # suppress LSB jitter and prevent zero-baseline pathologies
ACTIVE_BYTES_PANE_ROWS = 10

# ADR 0012 — byte-activity retention + decay + frozen sparkline
BYTE_ACTIVITY_RETENTION_SECS = 30.0  # total time a row stays visible past last_active_ts
BYTE_ACTIVITY_SAMPLE_SECS = 0.25     # display-buffer sample cadence (~4 Hz)
