#!/usr/bin/env python3
"""first_moving_ride_d1_step_response.py — step-response and butterfly-hypothesis tests.

Second-pass follow-up to first_moving_ride_d1_full_scan.py. That scan showed:

  - D1 residual is fully explained by (grip, RPM, coolant) — nothing else on
    the bus adds info once those three are fixed.
  - D1 is gear-invariant at fixed (grip, RPM) under drive — rules out any
    quantity that depends on real work at the wheel (torque, load, MAP, MAF).
  - D1 is ELEVATED during overrun, especially with strong engine-braking
    (121_A most negative → D1 highest).
  - The grip-cross-correlation kept monotonically rising past +500 ms, hinting
    at a large filter lag OR at a longer-timescale confound.

Two candidate interpretations survive:
  H1. Ride-by-wire butterfly *commanded angle* (M60 target). The rider grip
      is B80. The ECU applies smoothing and adds:
        - fast-idle bypass at cold (coolant-keyed)
        - decel-comfort crack at overrun (RPM-keyed with braking severity)
        - full-open at WOT
      Would be gear-invariant (butterfly command doesn't know the gear).
  H2. Base injector pulse-width setpoint (pre-cut). Same shape but different
      units. Doesn't fit fuel model integration checks (already tried).

Tests here:

  T1. Extended time-lag (D1 vs grip) out to ±3 s to find the peak.
  T2. Individual step-response: pick large grip transitions and plot the
      per-step D1 trajectory. Butterfly command would have millisecond-scale
      response; a filtered load estimate would be smoother.
  T3. Idle-band D1 vs coolant lookup rebuilt from the moving corpus, compare
      to the existing signal-fuel-injection-setpoint idle table (which was built from bike-
      stationary idle only).
  T4. Overrun trajectory: for a couple of clean overrun episodes, dump the
      D1(t), RPM(t), grip(t), 121_A(t) sequence.
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


def extract_channels(path):
    ch = {"rpm": [], "grip": [], "d540_d1": [], "d121_a": [], "coolant": [],
          "rear_kmh": [], "gear": []}
    for ts, arb, d in parse_frames(path):
        if arb == "120" and len(d) >= 3:
            ch["rpm"].append((ts, (d[0] << 8) | d[1]))
            ch["grip"].append((ts, d[2]))
        elif arb == "540" and len(d) >= 7:
            ch["d540_d1"].append((ts, d[1]))
            ch["coolant"].append((ts, ((d[5] << 8) | d[6]) * 0.1))
        elif arb == "121" and len(d) >= 4:
            ch["d121_a"].append((ts, int.from_bytes(d[0:2], "big", signed=True)))
        elif arb == "12D" and len(d) >= 7:
            ch["rear_kmh"].append((ts, ((d[5] << 8) | d[6]) * 0.0565))
        elif arb == "129" and len(d) >= 1:
            ch["gear"].append((ts, (d[0] >> 4) & 0x0F))
    return ch


def resample_grid(channels, dt=0.05):
    t_lo = min(ch[0][0] for ch in channels.values() if ch)
    t_hi = max(ch[-1][0] for ch in channels.values() if ch)
    grid = []
    positions = {k: 0 for k in channels}
    last = {k: None for k in channels}
    t = t_lo
    while t <= t_hi:
        for k, ser in channels.items():
            j = positions[k]
            while j + 1 < len(ser) and ser[j + 1][0] <= t:
                j += 1
            positions[k] = j
            if j < len(ser) and ser[j][0] <= t:
                last[k] = ser[j][1]
        grid.append(dict(last, ts=t))
        t += dt
    return grid


def stddev(xs):
    return statistics.pstdev(xs) if len(xs) > 1 else 0.0


def pearson(xs, ys):
    if len(xs) < 3:
        return None
    import math
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def per_file_frames(path, dt=0.05):
    ch = extract_channels(path)
    if not ch["rpm"]:
        return []
    return resample_grid(ch, dt=dt)


def main():
    all_grids = []
    for p in sorted(SESSION.glob("moving-*.log")):
        g = per_file_frames(p, dt=0.05)
        for pt in g:
            pt["file"] = p.name
        all_grids.append((p.name, g))
        print(f"{p.name}: {len(g)} points @ 50 ms")

    # ==================================================================
    print("\n## T1. Extended time-lag (per file, avoids merge artefacts)\n")
    max_lag_frames = 60  # 60 * 50ms = 3 s
    lags = list(range(-max_lag_frames, max_lag_frames + 1, 4))
    for fname, grid in all_grids:
        usable = [p for p in grid
                  if p["rpm"] is not None and p["grip"] is not None
                  and p["d540_d1"] is not None and p["rpm"] > 500]
        if len(usable) < 200:
            continue
        D1 = [p["d540_d1"] for p in usable]
        GRIP = [p["grip"] for p in usable]
        rs = []
        for lag in lags:
            if lag >= 0:
                xs = GRIP[:len(GRIP) - lag] if lag > 0 else GRIP[:]
                ys = D1[lag:] if lag > 0 else D1[:]
            else:
                xs = GRIP[-lag:]
                ys = D1[:len(D1) + lag]
            r = pearson(xs, ys)
            rs.append((lag, r))
        best = max(rs, key=lambda x: x[1] if x[1] is not None else -1)
        print(f"  {fname}  best-lag {best[0]*50:+5d} ms  r={best[1]:+.3f}")
        # Show curve at select points
        for lag in [-1000, -500, 0, 500, 1000, 2000, 3000]:
            match = [r for l, r in rs if l * 50 == lag]
            if match and match[0] is not None:
                print(f"     lag {lag:+5d} ms  r={match[0]:+.3f}")

    # ==================================================================
    print("\n## T2. Step-response — large grip transitions\n")
    for fname, grid in all_grids:
        usable = [p for p in grid
                  if p["rpm"] is not None and p["grip"] is not None
                  and p["d540_d1"] is not None]
        # find rising steps: grip goes from <10 to >60 within 200 ms
        events = []
        for i in range(4, len(usable) - 20):
            if (usable[i]["grip"] is not None and usable[i-4]["grip"] is not None
                    and usable[i-4]["grip"] < 10 and usable[i]["grip"] > 60):
                events.append(i)
        # find falling steps: >60 to <10 within 200 ms
        falling = []
        for i in range(4, len(usable) - 20):
            if (usable[i]["grip"] is not None and usable[i-4]["grip"] is not None
                    and usable[i-4]["grip"] > 60 and usable[i]["grip"] < 10):
                falling.append(i)
        print(f"  {fname}: {len(events)} big rising grip steps, {len(falling)} big falling.")
        # sample the first 2 rising
        for idx in events[:2]:
            print(f"    RISING at t={usable[idx]['ts']:.2f}s (grip {usable[idx-4]['grip']:3d} → {usable[idx]['grip']:3d})")
            print(f"    {'offset ms':>10}  {'grip':>4}  {'D1':>4}  {'RPM':>5}  {'121_A':>6}")
            for j in range(-4, 20):
                if 0 <= idx + j < len(usable):
                    pt = usable[idx + j]
                    print(f"    {j*50:>+10d}  {pt['grip'] or 0:>4}  {pt['d540_d1'] or 0:>4}  "
                          f"{pt['rpm'] or 0:>5}  {pt['d121_a'] if pt['d121_a'] is not None else 0:>+6}")
            print()

    # ==================================================================
    print("\n## T3. Idle-band D1 vs coolant lookup (moving corpus)\n")
    # concat all files
    all_pts = []
    for fname, grid in all_grids:
        all_pts.extend(grid)
    idle_pts = [p for p in all_pts
                if p["rpm"] is not None and p["grip"] is not None
                and p["d540_d1"] is not None and p["coolant"] is not None
                and p["grip"] < 5 and p["rpm"] < 2200 and p["rpm"] > 800]
    print(f"  {len(idle_pts)} idle-like frames (grip<5, 800<RPM<2200)")
    print(f"  {'coolant °C':>12}  {'n':>4}  {'D1 μ±σ':>10}  {'D1 mode':>7}")
    cool_bins = defaultdict(list)
    for p in idle_pts:
        cool_bins[int(p["coolant"] // 3) * 3].append(p["d540_d1"])
    for lo in sorted(cool_bins):
        d1s = cool_bins[lo]
        if len(d1s) < 5:
            continue
        from collections import Counter
        mode = Counter(d1s).most_common(1)[0][0]
        print(f"  {lo:>4}-{lo+3:<4}     {len(d1s):>4}  {statistics.mean(d1s):5.2f}±{stddev(d1s):4.2f}  {mode:>7}")

    # ==================================================================
    print("\n## T4. Overrun trajectories — 3 sample episodes with 121_A trace\n")
    # find a few overrun events on the concat grid, but keep file boundaries
    for fname, grid in all_grids[:2]:  # first two files
        usable = [p for p in grid
                  if p["rpm"] is not None and p["grip"] is not None
                  and p["d540_d1"] is not None and p["d121_a"] is not None
                  and p["rpm"] > 500]
        events = []
        i = 0
        while i < len(usable):
            if usable[i]["grip"] < 5 and usable[i]["rpm"] > 3500:
                j = i
                while j < len(usable) and usable[j]["grip"] < 5 and usable[j]["rpm"] > 2000:
                    j += 1
                if (j - i) * 0.05 >= 2.0:  # ≥ 2 s
                    events.append((i, j))
                i = j
            else:
                i += 1
        print(f"  {fname}: {len(events)} clean overrun episodes ≥ 2s")
        for a, b in events[:2]:
            print(f"    Episode t={usable[a]['ts']:.2f}s..{usable[b]['ts']:.2f}s ({(b-a)*0.05:.1f}s)")
            print(f"    {'t':>5}  {'grip':>4}  {'RPM':>5}  {'D1':>4}  {'121_A':>6}")
            # sample every 200 ms
            for k in range(a, b, 4):
                pt = usable[k]
                print(f"    {(pt['ts']-usable[a]['ts']):5.2f}  "
                      f"{pt['grip']:>4}  {pt['rpm']:>5}  {pt['d540_d1']:>4}  {pt['d121_a']:>+6}")
            print()


if __name__ == "__main__":
    sys.exit(main())
