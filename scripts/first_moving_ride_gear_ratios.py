#!/usr/bin/env python3
"""first_moving_ride_gear_ratios.py — verify gear enum via RPM / speed ratio.

For each gear g in the 129 D0[7:4] enum, in steady-drive frames (throttle > 8),
compute RPM / rear_kmh. That ratio is a function of (transmission gear × final
drive × wheel circumference), constant per gear. If the gear enum is correct,
each gear's ratio distribution is tight; ratios should decrease monotonically
from 1st (highest) to 6th (lowest).
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


def main():
    # Collect series
    rpm = []
    thr = []
    gear = []
    rear = []
    for path in sorted(SESSION.glob("moving-*.log")):
        for ts, arb, d in parse_frames(path):
            if arb == "120" and len(d) >= 3:
                rpm.append((ts, (d[0] << 8) | d[1]))
                thr.append((ts, d[2]))
            elif arb == "129" and len(d) >= 1:
                gear.append((ts, (d[0] >> 4) & 0x0F))
            elif arb == "12D" and len(d) >= 7:
                rear.append((ts, ((d[5] << 8) | d[6]) * 0.0565))

    # Resample onto a common 100 ms grid — for each grid tick, take
    # nearest-past sample of each channel.
    def to_dict(series):
        return series

    per_gear = defaultdict(list)  # gear → list of RPM/kmh ratio

    # Merge on gear timestamps (least frequent among 129 at 20 ms). Look up
    # nearest-past for the other channels.
    rpm_iter = iter(rpm); thr_iter = iter(thr); rear_iter = iter(rear)
    rpm_prev = None; thr_prev = None; rear_prev = None
    rpm_next = next(rpm_iter, None); thr_next = next(thr_iter, None); rear_next = next(rear_iter, None)

    for ts_g, g in gear:
        # advance each nearest-past
        while rpm_next is not None and rpm_next[0] <= ts_g:
            rpm_prev = rpm_next
            rpm_next = next(rpm_iter, None)
        while thr_next is not None and thr_next[0] <= ts_g:
            thr_prev = thr_next
            thr_next = next(thr_iter, None)
        while rear_next is not None and rear_next[0] <= ts_g:
            rear_prev = rear_next
            rear_next = next(rear_iter, None)
        if rpm_prev is None or thr_prev is None or rear_prev is None:
            continue
        # steady-drive filter: throttle > 8, speed > 15 km/h, RPM > 1500
        if thr_prev[1] < 8 or rear_prev[1] < 15 or rpm_prev[1] < 1500:
            continue
        if g == 0:  # neutral — rear speed and RPM decouple
            continue
        per_gear[g].append(rpm_prev[1] / rear_prev[1])

    print("# Gear-ratio verification\n")
    print(f"  {'gear':>4}  {'n':>7}  {'RPM/kmh μ':>10}  {'σ':>6}  {'p10':>6}  {'p90':>6}")
    prev_med = None
    for g in sorted(per_gear):
        vals = per_gear[g]
        vals.sort()
        n = len(vals)
        if n < 20:
            continue
        med = statistics.median(vals)
        p10 = vals[int(0.10 * n)]
        p90 = vals[int(0.90 * n)]
        std = statistics.pstdev(vals)
        arrow = ""
        if prev_med is not None:
            arrow = f"  Δ from prev gear: {(med-prev_med)/prev_med*100:+5.1f}%"
        print(f"  {g:>4}  {n:>7}  {statistics.mean(vals):10.1f}  {std:6.1f}  {p10:6.1f}  {p90:6.1f}{arrow}")
        prev_med = med


if __name__ == "__main__":
    sys.exit(main())
