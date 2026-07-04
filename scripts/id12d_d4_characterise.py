#!/usr/bin/env python3
"""id12d_d4_characterise.py — characterise the 12D D4 → front wheel speed encoding.

Picks up where unknown_byte_sweep flagged `12D D4` as EXPLAINED-BY:wheel_front
(r ≈ +0.998 in two independent engine-off sessions). Pairs `12D` frames'
D4 byte with their decoded front wheel speed (D0:D1 high 12 bits / 12.0 km/h)
within each frame, fits a linear model, and checks for wrap.

Sessions used (engine-off, front wheel actively spinning):
  - 2026-06-24-front-wheel-decay-mark
  - 2026-06-24-front-wheel-hand-spin

Outputs:
  stdout: linear fit (slope, intercept, residual), scale interpretation,
          wrap diagnostic, and a few sample rows showing the mapping
"""

from __future__ import annotations

import math
import re
import statistics as stats
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

SESSIONS = [
    "2026-06-24-front-wheel-decay-mark",
    "2026-06-24-front-wheel-hand-spin",
]


def parse_12d_frames(path: Path) -> list[tuple[float, int, float]]:
    """Return [(timestamp, d4, front_kmh)] for every 12D frame in the log."""
    out = []
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            if m.group(2).upper() != "12D":
                continue
            hexd = m.group(3)
            if len(hexd) != 16:
                continue
            d = bytes.fromhex(hexd)
            front_raw = ((d[0] << 8) | (d[1] & 0xF0)) >> 4
            front_kmh = front_raw / 12.0
            out.append((float(m.group(1)), d[4], front_kmh))
    return out


def linear_fit(xs, ys):
    """Ordinary least squares. Returns (slope, intercept, r, residual_std)."""
    n = len(xs)
    mx = stats.fmean(xs)
    my = stats.fmean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx2 = sum((x - mx) ** 2 for x in xs)
    sy2 = sum((y - my) ** 2 for y in ys)
    slope = sxy / sx2
    intercept = my - slope * mx
    r = sxy / math.sqrt(sx2 * sy2)
    preds = [slope * x + intercept for x in xs]
    resid = [y - p for y, p in zip(ys, preds)]
    res_std = math.sqrt(sum(r_ * r_ for r_ in resid) / n)
    return slope, intercept, r, res_std


def main():
    print("# 12D D4 encoding characterisation\n")

    all_pairs: list[tuple[float, int, float]] = []
    for sess in SESSIONS:
        path = REPO_ROOT / "logs" / sess / "capture.log"
        pairs = parse_12d_frames(path)
        # Engine-off only: wheel speed varies from spin/decay; D0:D1 raw must
        # be a multiple of 16 (low nibble = 0) per byte-encoding-12-in-16
        # confirmed for engine-off captures. We don't actually need to filter
        # since the front_kmh derivation already masks the low nibble.
        # Keep only frames where front_kmh > 0 — D4 may be a saturated mirror
        # at zero speed; we want the moving region for the fit.
        moving = [p for p in pairs if p[2] > 0]
        zero = [p for p in pairs if p[2] == 0]
        # Quick stats per session
        d4_at_zero = Counter(p[1] for p in zero)
        d4_at_move = Counter(p[1] for p in moving)
        print(f"## {sess}")
        print(f"  total 12D frames:   {len(pairs)}")
        print(f"  wheel_front == 0:   {len(zero)}  (D4 values: {dict(d4_at_zero.most_common(5))})")
        print(f"  wheel_front  > 0:   {len(moving)}  (D4 range: {min(d4_at_move):d}..{max(d4_at_move):d})")
        all_pairs.extend(moving)
        print()

    if not all_pairs:
        print("No moving-wheel frames found.")
        return 1

    # Fit D4 (x) → wheel_front km/h (y). If linear, slope = km/h per LSB.
    xs = [p[1] for p in all_pairs]
    ys = [p[2] for p in all_pairs]
    slope, intercept, r, res_std = linear_fit(xs, ys)
    print("## Linear fit (D4 → wheel_front km/h, combined sessions)\n")
    print(f"  n = {len(xs)}")
    print(f"  slope     = {slope:.6f} km/h per LSB")
    print(f"  intercept = {intercept:+.4f} km/h")
    print(f"  Pearson r = {r:+.6f}")
    print(f"  residual σ = {res_std:.4f} km/h\n")

    # Common-encoding sanity check
    candidate_slopes = [
        (1.0,        "1 km/h per LSB"),
        (0.5,        "0.5 km/h per LSB (1 LSB / 2 km/h would wrap at 512)"),
        (2.0,        "2 km/h per LSB"),
        (0.1,        "0.1 km/h per LSB (wraps at 25.5 km/h — same as 12D D2 rear coarse)"),
        (1.0 / 6.0,  "1/6 km/h per LSB (analog of front-wheel 1/12 at half precision)"),
        (1.0 / 12.0, "1/12 km/h per LSB (same as the wide 12-bit field's effective step)"),
    ]
    print("## Slope candidates\n")
    print(f"  {'scale':<22} {'predicted':>10}  {'residual':>10}")
    for s, label in candidate_slopes:
        # predict wheel_front for each D4 using this slope + best intercept
        # (offset only; we're not refitting slope per candidate)
        preds = [s * x + intercept for x in xs]
        rs = math.sqrt(sum((y - p) ** 2 for y, p in zip(ys, preds)) / len(ys))
        diff_from_fit = abs(s - slope)
        flag = "← within 1% of fit" if diff_from_fit / slope < 0.01 else ""
        print(f"  {label:<22} {s:10.5f}  {rs:10.4f} km/h  {flag}")
    print()

    # Wrap check: D4 ranges 0..255. If slope ≈ 0.5 km/h/LSB, wrap at ~128 km/h
    # (never reached on hand spin). If 0.1 km/h, wrap at 25.5 km/h — well within
    # decay-mark range. Look for non-monotonic regions or sudden D4 jumps.
    print("## Wrap diagnostic\n")
    # Sort by wheel_front and check D4 monotonicity
    sorted_pairs = sorted(all_pairs, key=lambda p: p[2])
    # bin by wheel_front (1 km/h bins), report median D4 per bin
    bins: dict[int, list[int]] = {}
    for _, d4, kmh in sorted_pairs:
        b = int(kmh)
        bins.setdefault(b, []).append(d4)
    print(f"  {'bin km/h':>8}  {'n':>5}  {'D4 median':>9}  {'D4 min':>7}  {'D4 max':>7}")
    prev_med = None
    wrap_warnings = []
    for b in sorted(bins.keys()):
        vs = bins[b]
        med = stats.median(vs)
        lo = min(vs)
        hi = max(vs)
        if prev_med is not None and med < prev_med - 5:
            wrap_warnings.append(f"  ! wrap suspected: median fell from {prev_med:.1f} to {med:.1f} at bin {b} km/h")
        print(f"  {b:>8d}  {len(vs):>5d}  {med:>9.1f}  {lo:>7d}  {hi:>7d}")
        prev_med = med
    print()
    if wrap_warnings:
        print("\n".join(wrap_warnings))
    else:
        print("  No wrap detected over the observed speed range.")
    print()

    # D4 at zero-speed: confirm the rest value
    print("## D4 at wheel_front == 0\n")
    all_zero_d4 = []
    for sess in SESSIONS:
        path = REPO_ROOT / "logs" / sess / "capture.log"
        pairs = parse_12d_frames(path)
        all_zero_d4.extend(p[1] for p in pairs if p[2] == 0)
    c = Counter(all_zero_d4)
    print(f"  {len(all_zero_d4)} frames with wheel_front == 0")
    print(f"  D4 value distribution at zero speed:")
    for v, n in c.most_common(5):
        pct = 100 * n / len(all_zero_d4)
        print(f"    D4 = 0x{v:02X} ({v:3d}):  {n:6d} frames ({pct:5.1f}%)")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
