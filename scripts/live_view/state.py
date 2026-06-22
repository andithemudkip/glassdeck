"""Per-bit baseline stats, grouped anomaly rows, watch pins, and the
small render helpers shared by both the mark-driven and discovery panes."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from signals import Signal

from .constants import SPARKLINE_BUFFER, SPARKLINE_WIDTH


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
    """One render path for both the mark-driven and continuous panes — they
    differ only in the `time_label` form ('+Δt' vs '-age'). Keeps the
    on-screen shape consistent so the eye reads the two panes the same."""
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
