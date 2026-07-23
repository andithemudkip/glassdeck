#!/usr/bin/env python3
"""first_moving_ride_coolant_scan.py — hunt for coolant-derived bytes on moving-1.

moving-1 is the only capture with a real cold-start warmup: coolant walks
26.3 → 87 °C over ~5 min. Any byte that walks *with* coolant (positive or
negative Pearson r) is a candidate for coolant-derived state (fuel enrichment,
idle bypass, warmup timer, etc.).

Rule out RPM/speed confounds: also compute Pearson r against RPM and speed.
Candidate coolant-derived byte has |r vs coolant| much larger than |r vs RPM|
and |r vs speed|.

D7 (cycle hash) excluded.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG = REPO_ROOT / "logs" / "2026-07-22-first-moving-ride" / "moving-1.log"
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


def pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def main():
    # Collect coolant, rpm, rear-speed, and every byte on every ID
    coolant = []
    rpm = []
    rear = []
    all_bytes = defaultdict(list)  # (id, byte) → [(ts, val), ...]

    for ts, arb, d in parse_frames(LOG):
        if arb == "540" and len(d) >= 7:
            coolant.append((ts, ((d[5] << 8) | d[6]) * 0.1))
        if arb == "120" and len(d) >= 3:
            rpm.append((ts, (d[0] << 8) | d[1]))
        if arb == "12D" and len(d) >= 7:
            rear.append((ts, ((d[5] << 8) | d[6]) * 0.0565))
        for bi in range(min(7, len(d))):  # skip D7
            all_bytes[(arb, bi)].append((ts, d[bi]))

    # Resample onto 1 s grid (coolant only moves ~0.1 °C/s, so 1 s is fine)
    dt = 1.0
    if not coolant:
        print("no coolant")
        return 1
    t_lo, t_hi = coolant[0][0], coolant[-1][0]
    grid = [t_lo + i * dt for i in range(int((t_hi - t_lo) / dt))]

    def nearest_past(series, t):
        prev = None
        for st, sv in series:
            if st > t:
                break
            prev = sv
        return prev

    coolant_g = [nearest_past(coolant, t) for t in grid]
    rpm_g = [nearest_past(rpm, t) for t in grid]
    rear_g = [nearest_past(rear, t) for t in grid]

    # drop grid points where any is None
    idxs = [i for i in range(len(grid)) if coolant_g[i] is not None and rpm_g[i] is not None and rear_g[i] is not None]
    coolant_v = [coolant_g[i] for i in idxs]
    rpm_v = [rpm_g[i] for i in idxs]
    rear_v = [rear_g[i] for i in idxs]

    print(f"moving-1: coolant walks {coolant_v[0]:.1f} → {coolant_v[-1]:.1f} °C over {len(coolant_v)} s\n")
    print(f"  {'ID':>4} {'byte':>4}  {'min..max':>15}  {'r vs cool':>10}  {'r vs RPM':>10}  {'r vs speed':>10}  {'known signal?':<30}")

    KNOWN = {
        ("120", 0): "RPM hi", ("120", 1): "RPM lo", ("120", 2): "throttle",
        ("540", 1): "warmup index (D1)",
        ("540", 5): "coolant hi", ("540", 6): "coolant lo",
        ("540", 3): "side-stand + gear-mirror",
        ("541", 4): "engine-on counter",
        ("12D", 2): "coarse rear speed",
        ("12D", 5): "rear speed hi", ("12D", 6): "rear speed lo",
        ("12D", 0): "front speed hi", ("12D", 1): "front speed lo + band",
        ("12D", 3): "front-mirror hi", ("12D", 4): "front-mirror lo",
        ("129", 0): "gear + clutch + shift-failed",
        ("121", 0): "int A hi", ("121", 1): "int A lo",
        ("121", 2): "int B hi", ("121", 3): "int B lo",
        ("121", 5): "kill mirror + engine-state",
        ("121", 6): "quickshifter (b0, b1)",
        ("541", 2): "kill bits", ("541", 6): "engine-off counter",
        ("5B0", 0): "kill mirror",
    }

    candidates = []
    for (arb, bi), series in all_bytes.items():
        vals_g = [nearest_past(series, t) for t in grid]
        vals_v = [vals_g[i] for i in idxs if vals_g[i] is not None]
        if len(vals_v) < len(idxs) or len(set(vals_v)) < 2:
            continue
        if max(vals_v) - min(vals_v) < 3:
            continue  # skip byte that barely moves (noise-level)
        # trim to matched length
        vals_v = vals_v[: len(idxs)]
        r_cool = pearson(coolant_v[: len(vals_v)], vals_v)
        r_rpm = pearson(rpm_v[: len(vals_v)], vals_v)
        r_speed = pearson(rear_v[: len(vals_v)], vals_v)
        if r_cool is None:
            continue
        score = abs(r_cool)
        candidates.append((score, arb, bi, r_cool, r_rpm, r_speed,
                           min(vals_v), max(vals_v)))

    candidates.sort(reverse=True)
    for score, arb, bi, r_c, r_r, r_s, mn, mx in candidates[:25]:
        tag = KNOWN.get((arb, bi), "")
        print(f"  {arb:>4} D{bi:<3}  {mn:5.0f}..{mx:<5.0f}   "
              f"{r_c:+10.3f}  {r_r:+10.3f}  {r_s:+10.3f}  {tag:<30}")


if __name__ == "__main__":
    sys.exit(main())
