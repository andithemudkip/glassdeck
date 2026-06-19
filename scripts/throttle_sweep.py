#!/usr/bin/env python3
"""throttle_sweep.py — decode the throttle channel from an engine-off sweep capture.

Procedure assumed (matches docs/experiments/2026-06-18-throttle-sweep-engine-off.md):
  generic-mark "mark"        = key-on
  three "throttle blip" marks = phase 1 (slow sweep), phase 2 (step response), phase 3 (repeat slow sweep)

Outputs:
  - phase boundary table
  - per-phase summary for 120 D2 (throttle-position candidate): min/max/mean, ramp monotonicity
  - 12A D0 bit 1 transition table: 120 D2 value at each 0→1 / 1→0 flip
  - 12A D1 bit 6 distribution per phase
  - engine-off invariants: 120 D0,D1 (RPM should be 0x0000)
  - bus-wide candidate scan: bytes whose range across phase 1 exceeds a threshold (potential other throttle-derived signals)
  - writes 120_d2_timeseries.csv beside the capture for external plotting
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

KEY_ON_SETTLE_S = 5.0   # drop the dash self-test head before phase 1
PHASE_LABELS = ["slow-sweep", "step-response", "repeat-sweep"]


def parse_events(path: Path):
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            rows.append((t, r["key"], r["label"]))
    key_on = next(t for t, _, lab in rows if lab == "generic mark")
    blips = [t for t, _, lab in rows if lab == "throttle blip"]
    return key_on, blips, rows


def parse_log(path: Path):
    frames = []
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            ts = float(m.group(1))
            arb = m.group(2).upper()
            hex_data = m.group(3)
            if len(hex_data) % 2:
                continue
            data = bytes.fromhex(hex_data)
            if len(data) != 8:
                continue
            frames.append((ts, arb, data))
    return frames


def build_phases(key_on: float, blips: list[float], last_ts: float):
    """Return list of (label, t0, t1)."""
    if len(blips) < 3:
        print(f"warning: expected 3 throttle marks, got {len(blips)}", file=sys.stderr)
    boundaries = blips + [last_ts]
    return [(PHASE_LABELS[i], boundaries[i], boundaries[i + 1]) for i in range(min(3, len(blips)))]


def fmt_hex(b: int) -> str:
    return f"0x{b:02X}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--session", default="logs/2026-06-19-throttle-sweep-engine-off")
    p.add_argument("--range-threshold", type=int, default=20,
                   help="Min (max - min) per byte across phase 1 to flag as a candidate mover.")
    args = p.parse_args()

    session = REPO_ROOT / args.session
    key_on, blips, _ = parse_events(session / "events.csv")
    frames = parse_log(session / "capture.log")
    if not frames:
        print("no frames parsed", file=sys.stderr)
        return 1
    last_ts = frames[-1][0]
    phases = build_phases(key_on, blips, last_ts)

    print("# Phase windows")
    print(f"{'phase':>14}  {'t0':>10}  {'t1':>10}  {'dur_s':>6}  frames")
    phase_frames = []
    for label, t0, t1 in phases:
        pf = [(ts, arb, b) for ts, arb, b in frames if t0 <= ts < t1]
        phase_frames.append(pf)
        print(f"{label:>14}  {t0:>10.2f}  {t1:>10.2f}  {t1-t0:>6.2f}  {len(pf)}")
    print()

    # 120 D2 summary per phase
    print("# 120 D2 (throttle-position candidate) — per-phase summary")
    print(f"{'phase':>14}  {'n':>5}  {'min':>5}  {'max':>5}  {'mean':>7}  {'first':>6}  {'last':>6}")
    for (label, _, _), pf in zip(phases, phase_frames):
        d2 = [b[2] for _, arb, b in pf if arb == "120"]
        if not d2:
            print(f"{label:>14}  {0:>5}")
            continue
        print(f"{label:>14}  {len(d2):>5}  {min(d2):>5}  {max(d2):>5}  "
              f"{sum(d2)/len(d2):>7.1f}  {d2[0]:>6}  {d2[-1]:>6}")
    print()

    # Write 120 D2 timeseries beside capture for external plotting
    t0_all = frames[0][0]
    ts_csv = session / "120_d2_timeseries.decoded.csv"
    with ts_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_rel_s", "d2"])
        for ts, arb, b in frames:
            if arb == "120":
                w.writerow([f"{ts - t0_all:.4f}", b[2]])
    print(f"# wrote {ts_csv.relative_to(REPO_ROOT)}")
    print()

    # Engine-off invariant: 120 D0,D1 (RPM) should be 0x0000 throughout
    print("# Invariant: 120 D0,D1 should be 0x0000 (engine off)")
    nonzero = Counter()
    total_120 = 0
    for _, arb, b in frames:
        if arb != "120":
            continue
        total_120 += 1
        if b[0] != 0 or b[1] != 0:
            nonzero[(b[0], b[1])] += 1
    if not nonzero:
        print(f"  OK — all {total_120} `120` frames have D0,D1 = 0x00 0x00")
    else:
        print(f"  VIOLATION — {sum(nonzero.values())}/{total_120} frames non-zero")
        for (d0, d1), n in nonzero.most_common(5):
            print(f"    D0={fmt_hex(d0)} D1={fmt_hex(d1)} n={n}")
    print()

    # 12A D0 bit 1 — throttle-open flag candidate
    print("# 12A D0 bit 1 — throttle-open flag candidate")
    print("  transitions across the whole capture (with the latest 120 D2 value at flip time):")
    last_d2 = None
    last_bit = None
    flips_0to1 = []
    flips_1to0 = []
    for ts, arb, b in frames:
        if arb == "120":
            last_d2 = b[2]
        elif arb == "12A":
            bit1 = (b[0] >> 1) & 1
            if last_bit is not None and bit1 != last_bit and last_d2 is not None:
                if bit1 == 1:
                    flips_0to1.append((ts - t0_all, last_d2))
                else:
                    flips_1to0.append((ts - t0_all, last_d2))
            last_bit = bit1
    print(f"  0→1 flips: {len(flips_0to1)}")
    for t_rel, d2 in flips_0to1[:20]:
        print(f"    t={t_rel:6.2f}s  D2={d2:3d}")
    print(f"  1→0 flips: {len(flips_1to0)}")
    for t_rel, d2 in flips_1to0[:20]:
        print(f"    t={t_rel:6.2f}s  D2={d2:3d}")
    if flips_0to1 and flips_1to0:
        on_threshold = min(d2 for _, d2 in flips_0to1)
        on_threshold_med = sorted(d2 for _, d2 in flips_0to1)[len(flips_0to1)//2]
        off_threshold = max(d2 for _, d2 in flips_1to0)
        off_threshold_med = sorted(d2 for _, d2 in flips_1to0)[len(flips_1to0)//2]
        print(f"  ON  threshold (D2 at 0→1 flips): min={on_threshold} median={on_threshold_med}")
        print(f"  OFF threshold (D2 at 1→0 flips): max={off_threshold} median={off_threshold_med}")
    print()

    # 12A D1 bit 6 distribution per phase
    print("# 12A D1 bit 6 — map / RBW state candidate (per-phase distribution)")
    print(f"{'phase':>14}  {'n':>5}  {'0s':>6}  {'1s':>6}  {'frac1':>6}")
    for (label, _, _), pf in zip(phases, phase_frames):
        bits = [(b[1] >> 6) & 1 for _, arb, b in pf if arb == "12A"]
        if not bits:
            print(f"{label:>14}  {0:>5}")
            continue
        ones = sum(bits)
        zeros = len(bits) - ones
        print(f"{label:>14}  {len(bits):>5}  {zeros:>6}  {ones:>6}  {ones/len(bits):>6.2f}")
    print()

    # Correlation: 120 D7 vs 120 D2 (APP1/APP2 dual-sensor hypothesis)
    # Same frame → no time alignment needed.
    print("# Correlation check: 120 D7 vs 120 D2 (dual-sensor accelerator-pedal hypothesis)")
    pairs = [(b[2], b[7]) for _, arb, b in frames if arb == "120"]
    if pairs:
        n = len(pairs)
        sx = sum(x for x, _ in pairs)
        sy = sum(y for _, y in pairs)
        sxx = sum(x * x for x, _ in pairs)
        syy = sum(y * y for _, y in pairs)
        sxy = sum(x * y for x, y in pairs)
        mx, my = sx / n, sy / n
        var_x = sxx / n - mx * mx
        var_y = syy / n - my * my
        cov = sxy / n - mx * my
        r = cov / (var_x ** 0.5 * var_y ** 0.5) if var_x > 0 and var_y > 0 else 0.0
        slope = cov / var_x if var_x > 0 else 0.0
        intercept = my - slope * mx
        print(f"  n={n}  Pearson r={r:+.4f}")
        print(f"  linear fit: D7 ≈ {slope:.3f} * D2 + {intercept:.2f}")
        # Sample table: D7 stats binned by D2
        print(f"  binned summary (D7 stats per D2 range):")
        print(f"    {'D2 bin':>10}  {'n':>5}  {'D7 min':>6}  {'D7 max':>6}  {'D7 mean':>7}")
        bins = [(0, 0), (1, 31), (32, 63), (64, 95), (96, 127), (128, 159),
                (160, 191), (192, 223), (224, 253), (254, 254)]
        for lo, hi in bins:
            xs = [y for x, y in pairs if lo <= x <= hi]
            if xs:
                print(f"    {f'{lo}-{hi}':>10}  {len(xs):>5}  {min(xs):>6}  {max(xs):>6}  {sum(xs)/len(xs):>7.1f}")
    print()

    # Correlation: 541 D6 vs 120 D2 (zero-order hold — different IDs, different periods)
    print("# Correlation check: 541 D6 vs 120 D2 (small-range UNKNOWN candidate)")
    last_d2 = None
    pairs541 = []
    for _, arb, b in frames:
        if arb == "120":
            last_d2 = b[2]
        elif arb == "541" and last_d2 is not None:
            pairs541.append((last_d2, b[6]))
    if pairs541:
        n = len(pairs541)
        sx = sum(x for x, _ in pairs541)
        sy = sum(y for _, y in pairs541)
        sxx = sum(x * x for x, _ in pairs541)
        syy = sum(y * y for _, y in pairs541)
        sxy = sum(x * y for x, y in pairs541)
        mx, my = sx / n, sy / n
        var_x = sxx / n - mx * mx
        var_y = syy / n - my * my
        cov = sxy / n - mx * my
        r = cov / (var_x ** 0.5 * var_y ** 0.5) if var_x > 0 and var_y > 0 else 0.0
        print(f"  n={n}  Pearson r={r:+.4f}  (zero-order hold on D2)")
    print()

    # Bus-wide scan: any byte whose range across phase 1 is large
    print(f"# Bus-wide scan — bytes with (max - min) >= {args.range_threshold} during slow-sweep phase")
    if phase_frames:
        pf = phase_frames[0]
        by_id = {}
        for _, arb, b in pf:
            arr = by_id.setdefault(arb, [[] for _ in range(8)])
            for i in range(8):
                arr[i].append(b[i])
        print(f"  {'ID':>4}  {'B':>1}  {'min':>4}  {'max':>4}  {'range':>5}  {'uniq':>4}")
        for arb in sorted(by_id):
            for i in range(8):
                vals = by_id[arb][i]
                if not vals:
                    continue
                rng = max(vals) - min(vals)
                if rng < args.range_threshold:
                    continue
                print(f"  {arb:>4}  {i:>1}  {min(vals):>4}  {max(vals):>4}  {rng:>5}  {len(set(vals)):>4}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
