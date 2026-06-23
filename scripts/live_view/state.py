"""Per-bit baseline stats, grouped anomaly rows, watch pins, and the
small render helpers shared by both the mark-driven and discovery panes."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from signals import Signal

from .constants import (
    ANOMALY_HALO_SECS,
    ANOMALY_HOT_SECS,
    ANOMALY_WARM_SECS,
    SPARKLINE_BUFFER,
    SPARKLINE_WIDTH,
)


@dataclass(slots=True)
class BaselineStats:
    """Per-bit EWMA of inter-flip intervals (ADR 0007).

    `mu` and `var` are exponentially-weighted; `count` gates the warmup
    branch so rare-but-real flips surface before the EWMA has had time to
    stabilise. Score-then-update order (see `_record_transition`) keeps a
    single tail event from blunting its own z-score."""

    last_flip_ts: float
    mu: float = 0.0
    var: float = 0.0
    count: int = 0


@dataclass(slots=True)
class ByteActivityStats:
    """Per-byte rolling range + EWMA baseline (ADR 0008), extended by
    ADR 0012 with a separate display buffer + peak ratio + frozen
    snapshot for the redesigned Active unknown bytes pane.

    `buffer` keeps the last ~ACTIVITY_WINDOW_SECS of (ts, value) samples
    — sized by time, evicted from the left at update. `short_range` is
    recomputed from the buffer; `baseline_range_ewma` is the long-running
    smooth of short_range. The first sweep on a previously-flat byte
    trips against a baseline near 0, so ratio jumps to ∞ against
    BASELINE_FLOOR — rare-but-real activity surfaces for free, no
    warmup escape hatch required (unlike the bit-flip case).

    ADR 0012 fields:
    - `display_buffer` — fixed-cadence (~4 Hz) ring of `SPARKLINE_BUFFER`
      samples driving the sparkline. Separate from `buffer` so the
      sparkline reflects ~3 s of byte shape regardless of the detection
      window length, and doesn't wash out as activity tapers off.
    - `frozen_buffer` — snapshot of `display_buffer` taken at the
      active→tail transition. The pane renders this during decay so the
      operator keeps seeing what shape the byte was making at peak.
      Cleared when activity resumes.
    - `last_display_sample_ts` — gates `display_buffer` appends to
      ~BYTE_ACTIVITY_SAMPLE_SECS cadence regardless of broadcast rate.
    - `peak_ratio` / `peak_ratio_ts` — track the loudest moment of the
      current activity episode so the row can show `peak=N.N×` and a
      time-since-peak annotation across HOT and DIM tiers. Reset when
      the row drops past `BYTE_ACTIVITY_RETENTION_SECS`."""

    buffer: deque[tuple[float, int]] = field(default_factory=deque)
    baseline_range_ewma: float = 0.0
    last_active_ts: float | None = None
    display_buffer: deque[float] = field(
        default_factory=lambda: deque(maxlen=SPARKLINE_BUFFER)
    )
    frozen_buffer: list[float] = field(default_factory=list)
    last_display_sample_ts: float = 0.0
    peak_ratio: float = 0.0
    peak_ratio_ts: float | None = None


@dataclass(slots=True)
class GroupedRow:
    """One arbitration ID's worth of anomalous bit-flips, ready to render.

    Both the mark-driven pane and the continuous discovery pane render
    through this shape — same grouping rule everywhere (ADR 0007 change
    #5). The caller chooses the sort: mark-driven sorts by `max_z`, the
    discovery pane sorts by `latest_ts` (newest first)."""

    arb: int
    bits: list[tuple[int, int]]    # (byte, bit), sorted
    earliest_ts: float             # earliest anomaly time in the group
    latest_ts: float               # latest anomaly time in the group
    max_z: float                   # ∞ if any bit in the group was warmup
    mu: float                      # of the bit that supplied `max_z`
    sigma: float                   # of the bit that supplied `max_z`
    transitions: list[str]         # unique transitions present, for display
    count: int = 0                 # ADR 0011 — anomalies in retention window
    bucket_timeline: list[int] = field(default_factory=list)  # ADR 0011 — per-bucket counts

    def render_bits(self) -> str:
        """Compact bit listing: 'D3 b2,b5' per byte; '..' range when >5
        bits on one byte; multiple bytes joined with two-space separator."""
        per_byte: dict[int, list[int]] = defaultdict(list)
        for byte, bit in self.bits:
            per_byte[byte].append(bit)
        parts: list[str] = []
        for byte in sorted(per_byte):
            bits = sorted(per_byte[byte])
            if len(bits) > 5:
                head = f"b{bits[0]}..b{bits[4]}"
                parts.append(f"D{byte} {head} (+{len(bits) - 5})")
            else:
                parts.append(f"D{byte} " + ",".join(f"b{b}" for b in bits))
        return "  ".join(parts)


@dataclass(slots=True)
class WatchPin:
    """One row in the watch panel (ADR 0007 change #1). `kind="signal"`
    pins a decoded `signals.yaml` entry; `kind="raw"` pins an arbitrary
    `(arb, byte, bit)` triplet. `buffer` is a small ring sampled at the
    decoded-refresh tick — sparkline auto-scales to its local min/max."""

    kind: Literal["signal", "raw"]
    label: str
    signal: Signal | None = None
    raw: tuple[int, int, int] | None = None  # (arb, byte, bit)
    buffer: deque[float] = field(default_factory=lambda: deque(maxlen=SPARKLINE_BUFFER))

    @property
    def boolean(self) -> bool:
        """Raw pins are always single-bit; signal pins follow the schema."""
        if self.kind == "raw":
            return True
        return self.signal is not None and self.signal.encoding in ("bool", "enum")

    def sample(
        self,
        latest: dict[str, tuple[Any, Any, float]],
        current_bytes: dict[tuple[int, int], int],
    ) -> None:
        """Push the pin's current value into its sparkline buffer."""
        if self.kind == "signal" and self.signal is not None:
            entry = latest.get(self.signal.name)
            if entry is None:
                return
            _value, raw, _ts = entry
            if raw is None:
                return
            if self.boolean:
                self.buffer.append(float(bool(raw)))
            else:
                try:
                    self.buffer.append(float(raw))
                except (TypeError, ValueError):
                    return
        elif self.kind == "raw" and self.raw is not None:
            arb, byte, bit = self.raw
            val = current_bytes.get((arb, byte))
            if val is None:
                return
            self.buffer.append(float((val >> bit) & 1))

    def current_text(
        self,
        latest: dict[str, tuple[Any, Any, float]],
        current_bytes: dict[tuple[int, int], int],
    ) -> str:
        """Render the pin's current value as a display string."""
        if self.kind == "signal" and self.signal is not None:
            entry = latest.get(self.signal.name)
            return self.signal.format(entry[0]) if entry is not None else "—"
        if self.kind == "raw" and self.raw is not None:
            arb, byte, bit = self.raw
            val = current_bytes.get((arb, byte))
            return "—" if val is None else str((val >> bit) & 1)
        return "—"


def _signed_secs(t: float) -> str:
    """`+0.12s` for positive, `-0.12s` for negative — used by mark-driven
    latency annotations where future-vs-past direction is meaningful."""
    return f"+{t:.2f}s" if t >= 0 else f"{t:.2f}s"


def _render_group_row(g: GroupedRow, time_label: str) -> str:
    """One render path for the mark-driven pane (ADR 0007 §3). The
    continuous discovery pane uses `_render_anomaly_row` (ADR 0011) — it
    needs stable columns + activity sparkline + decay/halo state that
    don't apply to the mark-driven case."""
    if math.isinf(g.max_z) and g.max_z > 0:
        score = "z=∞ (warmup)"
    elif math.isinf(g.max_z):  # -inf marker for --show-suppressed rows
        score = "[dim]suppressed[/dim]"
    else:
        score = f"z={g.max_z:.1f}  μ={g.mu:.2f}s ±{g.sigma:.2f}s"
    trans = "/".join(g.transitions) if g.transitions else "—"
    bits_label = "1 bit" if len(g.bits) == 1 else f"{len(g.bits)} bits"
    return (
        f"  0x{g.arb:03X}  {g.render_bits()}  {bits_label}  {trans}  "
        f"{time_label:>7}  {score}"
    )


def _anomaly_sparkline(buckets: Sequence[int]) -> str:
    """Bucket-count sparkline for the live anomalies pane (ADR 0011).

    Each input slot is a non-negative count; the cell height scales to
    the max bucket. Empty cells render as ` ` so the eye reads spikes
    against blank space rather than a baseline ramp."""
    width = SPARKLINE_WIDTH
    if not buckets:
        return " " * width
    tail = list(buckets)[-width:]
    hi = max(tail)
    if hi <= 0:
        return " " * width
    ramp = "▁▂▃▄▅▆▇█"
    out: list[str] = []
    for v in tail:
        if v <= 0:
            out.append(" ")
        else:
            idx = int((v / hi) * 8)
            if idx > 7:
                idx = 7
            out.append(ramp[idx])
    return "".join(out).ljust(width)


def _anomaly_glyph(g: GroupedRow) -> str:
    """ADR 0011 §glyph rules — a one-char hint at the anomaly's shape.

    `⊞` multi-bit on a shared byte (signal-like), `↻` single bit on a
    fast-cycling baseline (counter outlier), `·` otherwise (isolated
    single-bit flip)."""
    if len(g.bits) >= 2:
        per_byte: dict[int, int] = defaultdict(int)
        for byte, _bit in g.bits:
            per_byte[byte] += 1
        if max(per_byte.values()) >= 2:
            return "⊞"
        return "·"
    if len(g.bits) == 1 and not math.isinf(g.max_z) and g.mu < 0.5:
        return "↻"
    return "·"


def _render_anomaly_row(
    g: GroupedRow,
    now: float,
    *,
    accent: str | None,
    halo: bool,
) -> str:
    """ADR 0011 — column-aligned row for the live anomalies pane.

    Stable widths so the eye can anchor across refreshes:
      [2 sp or '▶ '][arb 7][glyph 3][bits 18][spark 12][ │ ][z 9][age 7]

    `accent` colors the arb token to mark a co-occurrence cluster.
    `halo` overrides accent with a `[bold yellow]` arb + leading `▶`.
    Brightness decay wraps the whole line in `[dim]` once age exceeds
    ANOMALY_WARM_SECS."""
    age = max(0.0, now - g.latest_ts)
    arb_token = f"0x{g.arb:03X}"
    if halo:
        arb_render = f"[bold yellow]{arb_token}[/bold yellow]"
        lead = "▶ "
    elif accent is not None:
        arb_render = f"[{accent}]{arb_token}[/{accent}]"
        lead = "  "
    else:
        arb_render = arb_token
        lead = "  "

    bits_field = f"{g.render_bits():<18}"
    if len(bits_field) > 18:
        bits_field = bits_field[:18]
    spark = _anomaly_sparkline(g.bucket_timeline)
    glyph = _anomaly_glyph(g)

    if math.isinf(g.max_z) and g.max_z > 0:
        score = "z=∞"
    elif math.isinf(g.max_z):
        score = "[dim]supp[/dim]"
    else:
        score = f"z={g.max_z:.1f}"
    score_field = f"{score:<9}"

    age_field = f"-{age:.1f}s".rjust(6)

    line = f"{lead}{arb_render}  {glyph}  {bits_field}  {spark}  │  {score_field}{age_field}"
    if age >= ANOMALY_WARM_SECS and not halo:
        line = f"[dim]{line}[/dim]"
    return line


def is_halo_active(now: float, last_event_ts: float | None) -> bool:
    """True if a mark hotkey was pressed recently enough that its halo
    should still be visible on the live anomalies pane."""
    if last_event_ts is None:
        return False
    return now < last_event_ts + ANOMALY_HALO_SECS


def is_hot(now: float, latest_ts: float) -> bool:
    """Recency check for the co-occurrence accent — only fresh bursts
    qualify, otherwise old clusters keep colouring the pane."""
    return now - latest_ts < ANOMALY_HOT_SECS


def _render_byte_row(
    stats: "ByteActivityStats",
    arb: int,
    byte: int,
    cur: int,
    *,
    now: float,
    dim: bool,
    shape_suffix: str,
) -> str:
    """ADR 0012 — column-aligned row for the Active unknown bytes pane.

    Same `0x<arb> D<byte> … <sparkline> │ <metric>` skeleton as the
    live anomalies pane (ADR 0011) so the two panes scan together.

    `dim=True` wraps the row in `[dim]` once `age` crosses the
    HOT-tier hysteresis threshold (set by the caller — semantics are
    pane-side, not state-side).

    Sparkline source: `frozen_buffer` if non-empty (we're in tail
    rendering the shape we snapshotted at active→tail transition),
    otherwise the live `display_buffer`. The caller is responsible
    for snapshotting `frozen_buffer` at the right moment."""
    if stats.frozen_buffer:
        spark_values = stats.frozen_buffer
    else:
        spark_values = list(stats.display_buffer)
    spark = sparkline(spark_values)

    if math.isinf(stats.peak_ratio):
        peak_str = "∞"
    else:
        peak_str = f"{stats.peak_ratio:.1f}×"
    peak_field = f"peak={peak_str:<6}"

    if stats.peak_ratio_ts is not None:
        age_since_peak = max(0.0, now - stats.peak_ratio_ts)
        age_field = f"-{age_since_peak:.1f}s".rjust(6)
    else:
        age_field = "    —"

    line = (
        f"  0x{arb:03X} D{byte}   value={cur:>3} / 0x{cur:02X}   "
        f"{spark}  │  {peak_field}  {age_field}{shape_suffix}"
    )
    if dim:
        line = f"[dim]{line}[/dim]"
    return line


def classify_byte(values: Sequence[int]) -> str:
    """Coarse one-word shape guess for the byte's recent buffer (ADR 0008 §6).

    Heuristic only — labels are a hint, not a verdict. Anything that
    doesn't cleanly fit a bucket returns "" (the sparkline already
    shows the shape; a wrong label is worse than none). Counter check
    runs before step because a 4-distinct monotonic series is a
    counter near rollover, not a 4-state machine."""
    if len(values) < 4:
        return ""
    distinct = set(values)
    if len(distinct) < 2:
        return ""
    if len(distinct) == 2:
        return "boolean"
    deltas = [b - a for a, b in zip(values, values[1:])]
    # d >= 0 is a normal step; d < -200 is a 0xFF→low wraparound (byte
    # max delta on wrap is -255). Anything in between is a real backtrack.
    monotonic = sum(1 for d in deltas if d >= 0 or d < -200)
    if monotonic >= len(deltas) - 1:
        return "counter"
    if len(distinct) <= 5:
        return "step"
    return "sensor"


def sparkline(samples: Sequence[float], width: int = SPARKLINE_WIDTH, *, boolean: bool = False) -> str:
    """Render up to `width` samples as a unicode bar string.

    For numeric series, scales to the buffer's own min/max — a stationary
    series renders as a flat mid-block row, not as full-scale noise. For
    boolean series, segments are `_` (0) / `▔` (1) so the eye reads it as
    a square wave rather than a smooth ramp."""
    if not samples:
        return " " * width
    tail = list(samples)[-width:]
    if boolean:
        s = "".join("▔" if bool(x) else "_" for x in tail)
        return s.ljust(width)
    lo = min(tail)
    hi = max(tail)
    if hi - lo < 1e-9:
        return ("▄" * len(tail)).ljust(width)
    ramp = "▁▂▃▄▅▆▇█"
    out_chars = []
    span = hi - lo
    for x in tail:
        idx = int((x - lo) / span * 8)
        if idx > 7:
            idx = 7
        out_chars.append(ramp[idx])
    return "".join(out_chars).ljust(width)
