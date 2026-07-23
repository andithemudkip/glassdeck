#!/usr/bin/env python3
"""first_moving_ride_541d1.py — characterise 541 D1 across the moving corpus.

moving-1 is the only capture in this ride bundle that starts cold-ish and warms
through. If 541 D1 is coolant-derived (as suggested by prior informal notes),
we'd expect a monotonic relationship with 540 D5:D6 across the warm-up window.

Reports:
  1. 541 D1 vs coolant (Pearson r, per-file and combined).
  2. 541 D1 vs RPM, throttle, engine-on counter — to rule out other drivers.
  3. Timeline of 541 D1 unique values across moving-1, with coolant at each
     first-appearance.
"""

from __future__ import annotations

import re
import statistics
import sys
from pathlib import Path
from collections import defaultdict

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


def resample_to_common_grid(*series_dict, dt=0.1):
    """Given multiple (ts, value) series, return time-aligned parallel arrays
    using nearest-past-sample resampling at `dt` seconds. All series must span
    the same wall-clock window (we take the intersection)."""
    if not series_dict:
        return None
    t_lo = max(s[0][0] for s in series_dict)
    t_hi = min(s[-1][0] for s in series_dict)
    if t_hi <= t_lo:
        return None
    n = int((t_hi - t_lo) / dt)
    grid = [t_lo + i * dt for i in range(n)]

    resampled = []
    for series in series_dict:
        vals = []
        j = 0
        for t in grid:
            while j + 1 < len(series) and series[j + 1][0] <= t:
                j += 1
            vals.append(series[j][1])
        resampled.append(vals)
    return grid, resampled


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0 or syy == 0:
        return None
    return sxy / (sxx ** 0.5 * syy ** 0.5)


def analyse_file(path):
    print(f"\n## {path.name}")
    coolant, rpm, throttle, d1_541, on_counter = [], [], [], [], []
    for ts, arb, d in parse_frames(path):
        if arb == "540" and len(d) >= 7:
            coolant.append((ts, ((d[5] << 8) | d[6]) * 0.1))
        elif arb == "120" and len(d) >= 3:
            rpm.append((ts, (d[0] << 8) | d[1]))
            throttle.append((ts, d[2]))
        elif arb == "541" and len(d) >= 5:
            d1_541.append((ts, d[1]))
            on_counter.append((ts, d[4] & 0x7F))

    if not d1_541 or not coolant:
        print("  missing 541 or 540 frames.")
        return

    d1_uniq = sorted(set(v for _, v in d1_541))
    print(f"  541 D1 unique values: {d1_uniq}")

    # Coolant span
    coolant_start = coolant[0][1]
    coolant_end = coolant[-1][1]
    coolant_min = min(c for _, c in coolant)
    coolant_max = max(c for _, c in coolant)
    print(f"  Coolant: start {coolant_start:.1f} °C, min {coolant_min:.1f}, max {coolant_max:.1f}, end {coolant_end:.1f}")

    # Timeline: first appearance of each new 541 D1 value, and coolant at that moment
    print(f"  541 D1 first-appearance timeline (value, wall t+s, coolant °C, RPM at that ts):")
    ts0 = d1_541[0][0]
    seen = set()

    # Build fast RPM lookup
    def lookup_nearest(series, ts):
        # binary-ish search — the lists are chronological
        # simple linear for clarity
        best = None
        for st, sv in series:
            if st > ts:
                break
            best = sv
        return best

    for ts, v in d1_541:
        if v in seen:
            continue
        seen.add(v)
        c = lookup_nearest(coolant, ts)
        r = lookup_nearest(rpm, ts)
        c_str = f"{c:5.1f}°C" if c is not None else "  n/a  "
        r_str = str(r) if r is not None else "n/a"
        print(f"    D1={v:>3}  t+{ts - ts0:>7.2f}s  coolant={c_str}  RPM={r_str}")

    if len(d1_uniq) == 1:
        print(f"  ⇒ 541 D1 is static at {d1_uniq[0]} across this capture. No correlation possible.")
        return

    # ------ Correlations on resampled grid
    grid_result = resample_to_common_grid(coolant, rpm, throttle, d1_541, on_counter, dt=0.5)
    if grid_result is None:
        print("  couldn't align series — different time windows.")
        return
    grid, [c_r, rpm_r, th_r, d1_r, oc_r] = grid_result

    r_c = pearson(d1_r, c_r)
    r_rpm = pearson(d1_r, rpm_r)
    r_th = pearson(d1_r, th_r)
    r_oc = pearson(d1_r, oc_r)

    print(f"  Pearson r (0.5s grid, n={len(grid)}):")
    print(f"    541 D1 vs coolant :  {r_c:+.4f}" if r_c is not None else "    (undefined)")
    print(f"    541 D1 vs RPM     :  {r_rpm:+.4f}" if r_rpm is not None else "    (undefined)")
    print(f"    541 D1 vs throttle:  {r_th:+.4f}" if r_th is not None else "    (undefined)")
    print(f"    541 D1 vs on_ctr  :  {r_oc:+.4f}" if r_oc is not None else "    (undefined)")


def main():
    files = sorted(SESSION.glob("moving-*.log"))
    print("# 541 D1 characterisation across 2026-07-22 moving corpus")
    for f in files:
        analyse_file(f)


if __name__ == "__main__":
    sys.exit(main())
