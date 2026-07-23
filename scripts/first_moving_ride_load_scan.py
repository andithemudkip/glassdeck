#!/usr/bin/env python3
"""first_moving_ride_load_scan.py — real-load discriminator on the 2026-07-22 corpus.

Two open questions the paddock stand couldn't answer:

  Q1. Is `540` D1 (formerly "warmup index", currently "throttle-derived +
      coolant-keyed idle offset" per [[signal-fuel-injection-setpoint]]) actually load-
      derived? The 2026-06-23 paddock-stand test ruled out load-derived on the
      basis of drivetrain drag not moving it at fixed RPM/throttle. Drivetrain
      drag ≠ real riding load (no wind, no acceleration inertia). This corpus
      is the first with real load.

  Q2. Same test for `121` D0:D1 and `121` D2:D3 (twin int16 channels A, B —
      currently "encoding confirmed, physical quantity open" per
      [[signal-engine-torque]]). Corpus-sweep verdict was that these aren't
      MAP/load-driven (best r vs RPM×throttle ≈ +0.31 on paddock-stand data)
      and are more likely lambda short-term trim or ignition advance
      correction. Same "paddock-stand load isn't real load" caveat applies.

Approach: resample every 100 ms; bin by (RPM, throttle); within each bin with
enough frames and enough vehicle-speed spread, report whether the target byte
varies with vehicle speed (proxy for load — same RPM+throttle at higher speed
means bigger wind resistance to overcome, higher gear at same RPM+throttle
means more wind at same wheel-torque, same output). Also report the same
against coolant temp inside each bin (to check whether the residual is the
"coolant-keyed offset" the current interpretation posits).

Report:
  * Overall population stats (RPM/throttle/speed/coolant spread across the ride)
  * Per (RPM, throttle) bin: n, speed spread, coolant spread, target μ and σ
  * Within-bin regressions: target vs speed, target vs coolant

The signal we're looking for: **within-bin σ that's meaningfully larger than
across-repeats measurement noise AND correlates with speed**. That's load
signature. If within-bin σ is small (target is nearly determined by RPM+thr
alone), current no-load ruling stands.
"""

from __future__ import annotations

import math
import re
import statistics
import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSION = REPO_ROOT / "logs" / "2026-07-22-first-moving-ride"
LINE_RE = re.compile(r"\(([\d.]+)\)\s+t([0-9A-Fa-f]{3})([0-9A-Fa-f])([0-9A-Fa-f]*)")

RPM_BIN = 500        # RPM
THROTTLE_BIN = 8     # throttle raw counts (~3.1% of the 254 full-scale)
MIN_BIN_N = 60       # min resampled frames per bin to consider
MIN_SPEED_SPREAD = 20.0  # km/h — bin must span at least this much speed to distinguish load


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
    """Return per-ID event-time series for the signals we need."""
    ch = {"rpm": [], "throttle": [], "d540_d1": [],
          "d121_a": [], "d121_b": [],
          "coolant": [], "rear_kmh": []}
    for ts, arb, d in parse_frames(path):
        if arb == "120" and len(d) >= 3:
            ch["rpm"].append((ts, (d[0] << 8) | d[1]))
            ch["throttle"].append((ts, d[2]))
        elif arb == "540" and len(d) >= 7:
            ch["d540_d1"].append((ts, d[1]))
            ch["coolant"].append((ts, ((d[5] << 8) | d[6]) * 0.1))
        elif arb == "121" and len(d) >= 4:
            # signed int16 BE
            a = int.from_bytes(d[0:2], "big", signed=True)
            b = int.from_bytes(d[2:4], "big", signed=True)
            ch["d121_a"].append((ts, a))
            ch["d121_b"].append((ts, b))
        elif arb == "12D" and len(d) >= 7:
            ch["rear_kmh"].append((ts, ((d[5] << 8) | d[6]) * 0.0565))
    return ch


def resample_grid(channels, dt=0.1):
    """Nearest-past resample every channel onto a common 100 ms grid.

    Returns a list of dicts, one per grid point, each carrying all channels'
    latest values (or None if that channel has never emitted yet)."""
    t_lo = min(min(ch[0][0] for ch in channels.values() if ch) for ch in [channels] if channels)
    t_hi = max(max(ch[-1][0] for ch in channels.values() if ch) for ch in [channels] if channels)
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


def merge_all_files():
    """Aggregate all 5 moving-* logs into one resampled grid.

    Time-base note: files have per-boot timestamps. We treat each file
    independently and offset it into a synthetic continuous timeline so a
    single (RPM, throttle) bin can pool data across files without pretending
    they're contiguous."""
    all_points = []
    file_bounds = []
    offset = 0.0
    for path in sorted(SESSION.glob("moving-*.log")):
        ch = extract_channels(path)
        if not ch["rpm"]:
            continue
        t0 = ch["rpm"][0][0]
        # normalise this file to start at `offset` in the merged timeline
        norm = {k: [(ts - t0 + offset, v) for ts, v in ser] for k, ser in ch.items()}
        grid = resample_grid(norm, dt=0.1)
        for pt in grid:
            pt["file"] = path.name
        all_points.extend(grid)
        file_end = max(ser[-1][0] for ser in norm.values() if ser)
        file_bounds.append((path.name, offset, file_end))
        offset = file_end + 10  # 10 s gap between files (keeps them distinguishable)
    return all_points, file_bounds


def bin_key(rpm, throttle):
    return (int(rpm // RPM_BIN) * RPM_BIN, int(throttle // THROTTLE_BIN) * THROTTLE_BIN)


def stddev(xs):
    return statistics.pstdev(xs) if len(xs) > 1 else 0.0


def pearson(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def main():
    points, bounds = merge_all_files()
    print(f"# Rolling-load discriminator on 2026-07-22 moving corpus")
    print(f"\n{len(points)} resampled points (100 ms grid) across {len(bounds)} files")
    for name, lo, hi in bounds:
        print(f"  {name}: merged-timeline t = {lo:.1f}..{hi:.1f} s ({hi-lo:.1f} s)")

    # ----- filter to fully-populated grid points (engine on, all channels present)
    usable = [p for p in points
              if p["rpm"] is not None and p["throttle"] is not None
              and p["d540_d1"] is not None and p["d121_a"] is not None
              and p["d121_b"] is not None and p["coolant"] is not None
              and p["rear_kmh"] is not None
              and p["rpm"] > 500]  # engine running
    print(f"\n{len(usable)} points with all channels present and engine running.")

    rpm_lo, rpm_hi = min(p["rpm"] for p in usable), max(p["rpm"] for p in usable)
    thr_lo, thr_hi = min(p["throttle"] for p in usable), max(p["throttle"] for p in usable)
    speed_lo, speed_hi = min(p["rear_kmh"] for p in usable), max(p["rear_kmh"] for p in usable)
    coolant_lo, coolant_hi = min(p["coolant"] for p in usable), max(p["coolant"] for p in usable)
    print(f"  RPM span: {rpm_lo:.0f} .. {rpm_hi:.0f}")
    print(f"  throttle span (raw / percent): {thr_lo:.0f}..{thr_hi:.0f} ({thr_lo*100/254:.1f}%..{thr_hi*100/254:.1f}%)")
    print(f"  rear-speed span: {speed_lo:.1f} .. {speed_hi:.1f} km/h")
    print(f"  coolant span: {coolant_lo:.1f} .. {coolant_hi:.1f} °C")

    # ----- bin by (RPM, throttle)
    bins = defaultdict(list)
    for p in usable:
        bins[bin_key(p["rpm"], p["throttle"])].append(p)

    print(f"\n{len(bins)} (RPM×throttle) bins populated (bin size: {RPM_BIN} RPM × {THROTTLE_BIN} thr counts).")

    # ----- report high-utility bins (n ≥ MIN_BIN_N and speed spread ≥ MIN_SPEED_SPREAD)
    # These are the bins where the ride sampled multiple loads at fixed RPM+throttle.
    print(f"\n## Bins with enough frames AND enough speed spread to discriminate load")
    print(f"    (n ≥ {MIN_BIN_N} frames × 100 ms = ≥ {MIN_BIN_N/10:.0f} s of data, "
          f"rear-speed spread ≥ {MIN_SPEED_SPREAD} km/h within the bin)\n")
    print(f"  {'RPM bin':>10}  {'thr bin':>8}  {'n':>5}  {'speed range':>15}  "
          f"{'coolant range':>15}  {'D1_540 μ±σ':>12}  {'A_121 μ±σ':>14}  {'B_121 μ±σ':>14}")
    header_shown = True
    discriminating_bins = []
    for key in sorted(bins):
        pts = bins[key]
        if len(pts) < MIN_BIN_N:
            continue
        speeds = [p["rear_kmh"] for p in pts]
        spread = max(speeds) - min(speeds)
        if spread < MIN_SPEED_SPREAD:
            continue
        d1 = [p["d540_d1"] for p in pts]
        a = [p["d121_a"] for p in pts]
        b = [p["d121_b"] for p in pts]
        cool = [p["coolant"] for p in pts]
        r_bin, t_bin = key
        thr_pct = t_bin * 100 / 254
        print(f"  {r_bin:>4}-{r_bin+RPM_BIN:<4}   {t_bin:>3}-{t_bin+THROTTLE_BIN:<3}  {len(pts):>5}  "
              f"{min(speeds):5.1f}-{max(speeds):5.1f}  "
              f"{min(cool):5.1f}-{max(cool):5.1f}  "
              f"{statistics.mean(d1):5.1f}±{stddev(d1):4.2f}  "
              f"{statistics.mean(a):7.1f}±{stddev(a):5.2f}  "
              f"{statistics.mean(b):7.1f}±{stddev(b):5.2f}")
        discriminating_bins.append((key, pts, speeds, cool, d1, a, b))

    if not discriminating_bins:
        print("\n  NONE — the ride didn't produce enough (fixed RPM+throttle, varying load) samples.")
        print("  Fallback: report the widest bins we DO have and see what they say.\n")

    # ----- within-bin correlations: target vs speed, target vs coolant
    print("\n## Within-bin correlations — does the target byte vary with speed (load proxy) at fixed RPM+throttle?")
    print("    Non-trivial r ⇒ target responds to something beyond RPM+throttle.")
    print("    Speed and coolant may both vary within a bin; report both.\n")
    print(f"  {'RPM bin':>10}  {'thr bin':>8}  {'n':>5}  "
          f"{'D1_540 v speed':>14}  {'D1_540 v cool':>14}  "
          f"{'A_121 v speed':>14}  {'B_121 v speed':>14}")
    for (key, pts, speeds, cool, d1, a, b) in discriminating_bins:
        r_bin, t_bin = key
        r_d1_s = pearson(speeds, d1)
        r_d1_c = pearson(cool, d1)
        r_a_s = pearson(speeds, a)
        r_b_s = pearson(speeds, b)
        def fmt(x):
            return f"{x:+.3f}" if x is not None else "n/a"
        print(f"  {r_bin:>4}-{r_bin+RPM_BIN:<4}   {t_bin:>3}-{t_bin+THROTTLE_BIN:<3}  {len(pts):>5}  "
              f"{fmt(r_d1_s):>14}  {fmt(r_d1_c):>14}  {fmt(r_a_s):>14}  {fmt(r_b_s):>14}")

    # ----- fallback: bins with enough n regardless of speed spread — show D1 behavior
    print("\n## `540 D1` vs (RPM, throttle) — all bins with n ≥ 200 (aggregate rolling behavior)")
    print("    Compare against the paddock-stand engine_load_scan.py setpoint table.\n")
    print(f"  {'RPM bin':>10}  {'thr bin':>8}  {'thr%':>5}  {'n':>6}  {'mean D1':>8}  {'σ D1':>6}  {'mean speed':>11}  {'mean coolant':>13}")
    big = [(k, pts) for k, pts in bins.items() if len(pts) >= 200]
    for key, pts in sorted(big):
        r_bin, t_bin = key
        d1 = [p["d540_d1"] for p in pts]
        speeds = [p["rear_kmh"] for p in pts]
        cool = [p["coolant"] for p in pts]
        thr_pct = t_bin * 100 / 254
        print(f"  {r_bin:>4}-{r_bin+RPM_BIN:<4}   {t_bin:>3}-{t_bin+THROTTLE_BIN:<3}  {thr_pct:5.1f}  "
              f"{len(pts):>6}  {statistics.mean(d1):8.2f}  {stddev(d1):6.2f}  "
              f"{statistics.mean(speeds):11.1f}  {statistics.mean(cool):13.1f}")


if __name__ == "__main__":
    sys.exit(main())
