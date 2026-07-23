#!/usr/bin/env python3
"""first_moving_ride_warmup_index_check.py — extend `540 D1` cold-walkup table.

moving-1 is a fresh cold-start ride covering coolant 26 → 87 °C over ~ 5 minutes.
The existing [[signal-fuel-injection-setpoint]] finding built its (coolant → D1) table
from the 2026-06-17-engine-idle-baseline Run 1 alone (bike stationary, engine
idling, ~ 3 minutes of warmup). This gives us a second independent walkup
under different conditions (rider actively riding, so throttle varies) — cross-
check the existing table and note any deltas.

Filter to idle-like conditions to isolate the coolant response from D1's
now-known throttle+load response. Two filters:

  A. Strict idle: throttle < 8 raw AND RPM < 2200 (near-idle regardless of gear)
  B. Loose near-idle: throttle < 8 raw (any RPM — includes overrun)

Report D1 mean per coolant bin under each filter, and compare against the
existing finding's table.
"""

from __future__ import annotations

import re
import statistics
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


def main():
    coolant = []
    rpm = []
    thr = []
    d1 = []
    for ts, arb, d in parse_frames(LOG):
        if arb == "540" and len(d) >= 7:
            coolant.append((ts, ((d[5] << 8) | d[6]) * 0.1))
            d1.append((ts, d[1]))
        if arb == "120" and len(d) >= 3:
            rpm.append((ts, (d[0] << 8) | d[1]))
            thr.append((ts, d[2]))

    if not coolant:
        print("no data")
        return 1

    # Resample onto 200ms grid (coolant is 100ms, so this is fine)
    dt = 0.2
    t_lo = max(coolant[0][0], rpm[0][0], thr[0][0], d1[0][0])
    t_hi = min(coolant[-1][0], rpm[-1][0], thr[-1][0], d1[-1][0])
    n = int((t_hi - t_lo) / dt)

    def resample(series):
        out = [None] * n
        j = 0
        for i in range(n):
            t = t_lo + i * dt
            while j + 1 < len(series) and series[j + 1][0] <= t:
                j += 1
            if j < len(series) and series[j][0] <= t:
                out[i] = series[j][1]
        return out

    cool_g = resample(coolant)
    rpm_g = resample(rpm)
    thr_g = resample(thr)
    d1_g = resample(d1)

    # Build filtered lists
    strict_idle = []      # throttle < 8, RPM < 2200
    near_idle = []        # throttle < 8, any RPM
    for c, r, t, d in zip(cool_g, rpm_g, thr_g, d1_g):
        if None in (c, r, t, d):
            continue
        if t < 8:
            near_idle.append((c, r, t, d))
            if r < 2200:
                strict_idle.append((c, r, t, d))

    def bin_and_report(label, group, bin_width=3):
        print(f"\n## {label}  (n = {len(group)})")
        if not group:
            print("  no data")
            return
        bins = defaultdict(list)
        for c, r, t, d in group:
            b = int(c // bin_width) * bin_width
            bins[b].append(d)
        print(f"  {'coolant bin (°C)':>18}  {'n':>5}  {'D1 μ':>6}  {'D1 mode':>8}  {'D1 min/max':>12}")
        for b in sorted(bins):
            vals = bins[b]
            if len(vals) < 5:
                continue
            mean = statistics.mean(vals)
            # mode
            counts = {}
            for v in vals:
                counts[v] = counts.get(v, 0) + 1
            mode = max(counts, key=counts.get)
            print(f"  {b:>4}-{b+bin_width:<3}          {len(vals):>5}  {mean:6.1f}  0x{mode:02X} ({mode:>3})  {min(vals):>3}..{max(vals):<3}")

    print(f"# 540 D1 vs coolant on moving-1 cold walkup")
    print(f"Coolant span: {min(c for c,*_ in strict_idle):.1f} → {max(c for c,*_ in strict_idle):.1f} °C  (strict-idle filter)")

    bin_and_report("Strict idle (throttle < 8 raw, RPM < 2200) — closest to 2026-06-17 baseline conditions", strict_idle)
    bin_and_report("Near idle (throttle < 8 raw, any RPM — includes overrun)", near_idle)

    print(f"\n## Existing table from 2026-06-17-engine-idle-baseline Run 1 for comparison")
    print(f"  {'coolant °C':>12}  {'D1 (hex, dec)':>15}")
    table = [
        (26, "0x19 (25) brief"),
        (28, "0x14 (20)"),
        (31, "0x13 (19)"),
        (40, "0x11 (17)"),
        (55, "0x10 (16)"),
        (70, "0x0F (15)"),
        (85, "0x0E (14)"),
    ]
    for temp, val in table:
        print(f"  {temp:>10}    {val:>15}")


if __name__ == "__main__":
    sys.exit(main())
