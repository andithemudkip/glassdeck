#!/usr/bin/env python3
"""first_moving_ride_d3d4_refit.py — re-fit 12D D3:D4 mirror against corrected
canonical front decode.

Old fit ([[byte-12d-d3-d4-front-mirror]]): slope 3/64 = 0.046875 km/h/LSB,
intercept +0.795 km/h, against a canonical front decode at LSB 1/192 (which
was subsequently shown to be wrong — corrected LSB is 1/10 on the 12-bit
extract, per [[signal-wheel-speed-front]] 2026-07-22 rewrite).

The correlation itself doesn't change (D3:D4 mirrors *whatever the front sensor
says*), but the specific slope scales with the canonical LSB. Refit against the
corrected canonical using the full 2026-07-22 speed range (previous corpus never
crossed ~ 12.7 km/h front; this one hits 100+).

Model: canonical_kmh = slope × raw_D3D4 + intercept.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSION = REPO_ROOT / "logs" / "2026-07-22-first-moving-ride"
LINE_RE = re.compile(r"\(([\d.]+)\)\s+t([0-9A-Fa-f]{3})([0-9A-Fa-f])([0-9A-Fa-f]*)")


def parse_frames(path):
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            arb = m.group(2).upper()
            length = int(m.group(3), 16)
            hex_data = m.group(4)
            if len(hex_data) < length * 2:
                continue
            data = bytes.fromhex(hex_data[: length * 2])
            yield float(m.group(1)), arb, data


def main():
    pairs = []
    for path in sorted(SESSION.glob("moving-*.log")):
        for ts, arb, d in parse_frames(path):
            if arb != "12D" or len(d) < 7:
                continue
            # canonical front: 12-bit BE at 1/10 km/h
            front_12bit = ((d[0] << 8) | (d[1] & 0xF0)) >> 4
            canonical_kmh = front_12bit / 10.0
            # mirror candidate: D3:D4 raw
            raw_d3d4 = (d[3] << 8) | d[4]
            pairs.append((raw_d3d4, canonical_kmh, d[3], d[4]))

    if not pairs:
        print("no 12D frames")
        return 1

    # OLS fit y = a·x + b
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    resid = [y - (slope * x + intercept) for x, y in zip(xs, ys)]
    rms = (sum(r * r for r in resid) / n) ** 0.5
    # Pearson r
    syy = sum((y - my) ** 2 for y in ys)
    r_pear = sxy / (sxx * syy) ** 0.5

    print(f"# 12D D3:D4 mirror re-fit against corrected canonical (LSB 1/10 km/h)")
    print(f"n = {n} frames across the 5-file moving corpus\n")

    print(f"Raw D3:D4 range: {min(xs)} to {max(xs)}")
    print(f"Canonical km/h range: {min(ys):.2f} to {max(ys):.2f}\n")

    print(f"OLS fit: canonical_kmh = {slope:.7f} × raw_D3D4 + {intercept:+.4f}")
    print(f"  slope   = {slope:.7f} km/h/LSB")
    print(f"  intercept = {intercept:+.4f} km/h")
    print(f"  Pearson r = {r_pear:.8f}")
    print(f"  RMS residual = {rms:.4f} km/h\n")

    # Compare against candidate slopes
    print(f"Candidate slope check (residual against alternate encodings):")
    candidates = [
        ("current (old finding)", 3 / 64.0),
        ("1/20 = 0.05000", 1 / 20.0),
        ("1/16 = 0.0625", 1 / 16.0),
        ("3/64 = 0.046875", 3 / 64.0),
        ("1/12 = 0.083333 (matches 12-bit-in-16 pattern at 1/10 → 1/1.6)", 1 / 12.0),
        ("this fit", slope),
    ]
    for label, cand_slope in candidates:
        # refit intercept given slope
        b_cand = my - cand_slope * mx
        resid_cand = [y - (cand_slope * x + b_cand) for x, y in zip(xs, ys)]
        rms_cand = (sum(r * r for r in resid_cand) / n) ** 0.5
        print(f"  slope = {cand_slope:.7f} ({label}) → intercept = {b_cand:+.4f}, RMS = {rms_cand:.4f} km/h")

    # Range check
    print(f"\nD3 activity (previously observed 0 across all captured conditions):")
    d3_vals = sorted(set(p[2] for p in pairs))
    print(f"  D3 unique values: {d3_vals[:20]}{'...' if len(d3_vals) > 20 else ''}")
    print(f"  D3 range: {min(d3_vals)} to {max(d3_vals)}")
    if max(d3_vals) > 0:
        print(f"  → D3 now exercised (previously all-zero). Confirms multi-byte 16-bit BE encoding.")

    # Check some spot values at known speeds
    print(f"\nSpot-check at various canonical speeds:")
    binned = {}
    for raw, kmh, d3, d4 in pairs:
        b = int(kmh // 5) * 5
        binned.setdefault(b, []).append((raw, kmh, d3, d4))
    print(f"  {'bin km/h':>10}  {'n':>7}  {'D3 μ':>6}  {'D4 μ':>6}  {'D3:D4 μ':>8}  {'implied km/h @ new slope':>25}")
    for b in sorted(binned):
        if len(binned[b]) < 30:
            continue
        d3_mean = sum(p[2] for p in binned[b]) / len(binned[b])
        d4_mean = sum(p[3] for p in binned[b]) / len(binned[b])
        raw_mean = sum(p[0] for p in binned[b]) / len(binned[b])
        implied = slope * raw_mean + intercept
        print(f"  {b:>3}-{b+5:<4}  {len(binned[b]):>7}  {d3_mean:6.1f}  {d4_mean:6.1f}  {raw_mean:8.1f}  {implied:23.2f}")


if __name__ == "__main__":
    sys.exit(main())
