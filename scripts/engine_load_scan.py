#!/usr/bin/env python3
"""engine_load_scan.py — hunt for MAP / engine-load signals + retest warmup-index.

Uses the 2026-06-23-engine-driven-rear-spin capture (engine on, paddock stand,
RPM setpoint sweep from idle → ~5500 in 1st gear) to answer two questions in
one pass:

  Q1. Does `540` D1 (the warm-up index, [[signal-fuel-injection-setpoint]]) vary with RPM
      at constant coolant temperature?  Bike was at operating temp throughout
      this session, so any RPM-driven movement would discriminate the two
      remaining hypotheses (idle-bypass position vs cold-start enrichment
      factor) — idle-bypass would respond to load/RPM, pure-coolant-keyed
      enrichment would not.

  Q2. Which other non-static bytes correlate with RPM and/or throttle?  A MAP
      sensor reading or an engine-load index would show up as a high-|r|
      candidate against RPM, throttle, or their product.

For each setpoint mark in events.csv we take a steady-state window (skip the
first WINDOW_SKIP_S seconds, then sample WINDOW_LEN_S seconds) and compute the
mean of every byte of every always-on ID over that window.  Pearson r is then
computed across the 6-or-7 setpoint means.

D7 is excluded from the candidate scan (universal cycle hash, see
[[byte-d7-cycle-hash]]).  Bytes that are constant or near-constant across the
sweep are dropped.  Known signals are tagged in the output for context.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

ALWAYS_ON_IDS = ["120", "121", "129", "12A", "12D", "12E", "450", "540", "541", "5A0", "5B0"]

# (id, byte_index) → short tag for known signals.  Used only for output annotation.
KNOWN = {
    ("120", 0): "rpm-hi",   ("120", 1): "rpm-lo",
    ("120", 2): "throttle",
    ("12D", 2): "rear-wheel-coarse",
    ("12D", 5): "rear-wheel-hi",
    ("12D", 6): "rear-wheel-lo",
    ("540", 1): "warmup-index",
    ("540", 5): "coolant-hi", ("540", 6): "coolant-lo",
    ("540", 3): "side-stand+gear-mirror",
    ("541", 2): "kill-bits",   ("541", 4): "engine-on-counter",
    ("129", 0): "gear+clutch+shift",
    ("121", 5): "kill-mirror",
    ("5B0", 0): "kill-mirror",
}

WINDOW_SKIP_S = 3.0
WINDOW_LEN_S = 8.0


def parse_events(path):
    setpoints = []
    with path.open() as f:
        for r in csv.DictReader(f):
            if r["key"] != "setpoint":
                continue
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            setpoints.append((r["label"], t))
    return setpoints


def parse_log(path, ids_of_interest):
    out = {arb: [] for arb in ids_of_interest}
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            arb = m.group(2).upper()
            if arb not in out:
                continue
            hex_data = m.group(3)
            if len(hex_data) % 2 or len(hex_data) != 16:
                continue
            out[arb].append((float(m.group(1)), bytes.fromhex(hex_data)))
    return out


def window(frames, t0, t1):
    return [(ts, d) for ts, d in frames if t0 <= ts <= t1]


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return float("nan")
    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denom = math.sqrt(sxx * syy)
    return sxy / denom if denom else float("nan")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--session", default="logs/2026-06-23-engine-driven-rear-spin")
    p.add_argument("--top", type=int, default=20, help="show top-N correlated bytes")
    p.add_argument("--include-idle", action="store_true",
                   help="include the Phase A 'idle in 1st' and Phase C 'post-sweep idle' marks "
                        "(default: drop them so the sweep is monotone in RPM)")
    args = p.parse_args()

    session = REPO_ROOT / args.session
    setpoints = parse_events(session / "events.csv")
    if not args.include_idle:
        setpoints = [(lbl, t) for lbl, t in setpoints
                     if "B1" in lbl or "B2" in lbl or "B3" in lbl
                     or "B4" in lbl or "B5" in lbl]
    if not setpoints:
        print("no setpoint marks selected", file=sys.stderr)
        return 1

    frames = parse_log(session / "capture.log", set(ALWAYS_ON_IDS))

    # Per-setpoint window: mean of each byte of each ID, plus mean RPM & throttle.
    per_setpoint = []
    for label, mark in setpoints:
        t0, t1 = mark + WINDOW_SKIP_S, mark + WINDOW_SKIP_S + WINDOW_LEN_S
        win_120 = window(frames["120"], t0, t1)
        if not win_120:
            continue
        rpm = mean([(d[0] << 8) | d[1] for _, d in win_120])
        thr = mean([d[2] for _, d in win_120])
        row = {"label": label, "rpm": rpm, "throttle": thr, "bytes": {}}
        for arb in ALWAYS_ON_IDS:
            win = window(frames[arb], t0, t1)
            if not win:
                continue
            for bi in range(8):
                row["bytes"][(arb, bi)] = mean([d[bi] for _, d in win])
        per_setpoint.append(row)

    if len(per_setpoint) < 3:
        print(f"only {len(per_setpoint)} setpoints with data — too few for correlation", file=sys.stderr)
        return 1

    print(f"# Engine-load scan — {args.session}")
    print(f"# {len(per_setpoint)} setpoints, window t+{WINDOW_SKIP_S:.0f}..t+{WINDOW_SKIP_S+WINDOW_LEN_S:.0f} s after each mark\n")

    # --- Q1. Warmup-index vs RPM ----------------------------------------------
    print("## Q1 — `540` D1 (warmup-index) vs RPM")
    print("    Coolant was at operating temp throughout, so any RPM response distinguishes")
    print("    idle-bypass-style (responds) from coolant-keyed enrichment (doesn't).\n")
    print(f"  {'label':<36}  {'RPM':>6}  {'throttle':>8}  {'540 D1 μ':>10}")
    d1_vals = []
    rpm_vals = []
    for r in per_setpoint:
        d1 = r["bytes"].get(("540", 1))
        if d1 is None:
            continue
        print(f"  {r['label']:<36}  {r['rpm']:6.0f}  {r['throttle']:8.1f}  {d1:10.3f}")
        d1_vals.append(d1)
        rpm_vals.append(r["rpm"])
    rng = max(d1_vals) - min(d1_vals) if d1_vals else 0.0
    print(f"\n  → range across setpoints: {rng:.3f} LSB    Pearson r vs RPM: {pearson(rpm_vals, d1_vals):+.3f}")
    if rng < 0.5:
        verdict = ("FLAT across the RPM sweep — consistent with pure-coolant-keyed "
                   "enrichment, against idle-bypass.")
    elif rng < 2.0:
        verdict = ("small RPM-correlated wobble — ambiguous; could be measurement noise "
                   "or a real but secondary RPM input.")
    else:
        verdict = ("clear RPM response — consistent with idle-bypass / fast-idle position, "
                   "against pure-coolant lookup.")
    print(f"  → verdict: {verdict}\n")

    # --- Q2. Correlation scan over all non-static bytes -----------------------
    print("## Q2 — non-static bytes ranked by |r vs RPM|, |r vs throttle|, |r vs RPM·throttle|")
    print("    D7 excluded (cycle hash).  KNOWN tag = byte is already a documented signal.\n")
    rpm_series = [r["rpm"] for r in per_setpoint]
    thr_series = [r["throttle"] for r in per_setpoint]
    load_series = [r["rpm"] * r["throttle"] for r in per_setpoint]
    candidates = []
    for arb in ALWAYS_ON_IDS:
        for bi in range(7):  # exclude D7
            series = []
            for r in per_setpoint:
                v = r["bytes"].get((arb, bi))
                if v is None:
                    break
                series.append(v)
            if len(series) != len(per_setpoint):
                continue
            if max(series) - min(series) < 0.5:
                continue  # near-static across the sweep
            r_rpm = pearson(rpm_series, series)
            r_thr = pearson(thr_series, series)
            r_load = pearson(load_series, series)
            score = max(abs(r_rpm), abs(r_thr), abs(r_load))
            candidates.append({
                "id": arb, "byte": bi,
                "range": max(series) - min(series),
                "min": min(series), "max": max(series),
                "r_rpm": r_rpm, "r_thr": r_thr, "r_load": r_load,
                "score": score,
                "known": KNOWN.get((arb, bi), ""),
            })
    candidates.sort(key=lambda c: c["score"], reverse=True)

    print(f"  {'id':>4} {'byte':>4}  {'min..max':>14}  "
          f"{'r(RPM)':>7}  {'r(thr)':>7}  {'r(RPM·thr)':>10}  {'known':<28}")
    for c in candidates[: args.top]:
        rng_s = f"{c['min']:5.1f}..{c['max']:5.1f}"
        print(f"  {c['id']:>4} D{c['byte']:<3}  {rng_s:>14}  "
              f"{c['r_rpm']:+7.3f}  {c['r_thr']:+7.3f}  {c['r_load']:+10.3f}  {c['known']:<28}")

    # --- Q2b. Same table but unknowns only ------------------------------------
    print("\n## Q2b — same ranking, UNKNOWN bytes only (candidates for MAP / load / advance / etc.)\n")
    unk = [c for c in candidates if not c["known"]]
    print(f"  {'id':>4} {'byte':>4}  {'min..max':>14}  "
          f"{'r(RPM)':>7}  {'r(thr)':>7}  {'r(RPM·thr)':>10}")
    for c in unk[: args.top]:
        rng_s = f"{c['min']:5.1f}..{c['max']:5.1f}"
        print(f"  {c['id']:>4} D{c['byte']:<3}  {rng_s:>14}  "
              f"{c['r_rpm']:+7.3f}  {c['r_thr']:+7.3f}  {c['r_load']:+10.3f}")

    # --- Q2c. Per-setpoint trace for top-5 unknowns ---------------------------
    print("\n## Q2c — per-setpoint trace for top-5 unknowns (eyeball the shape)\n")
    header_labels = [r["label"].split("—")[0].strip() for r in per_setpoint]
    print(f"  {'byte':<10}  " + "  ".join(f"{h:>8}" for h in header_labels) + f"  {'RPM trend':>10}")
    rpms_fmt = "  ".join(f"{r['rpm']:8.0f}" for r in per_setpoint)
    print(f"  {'(RPM)':<10}  {rpms_fmt}")
    thrs_fmt = "  ".join(f"{r['throttle']:8.1f}" for r in per_setpoint)
    print(f"  {'(throttle)':<10}  {thrs_fmt}")
    for c in unk[:5]:
        key = (c["id"], c["byte"])
        trace = [r["bytes"].get(key, float("nan")) for r in per_setpoint]
        trace_fmt = "  ".join(f"{v:8.2f}" for v in trace)
        trend = "↑" if trace[-1] > trace[0] + 0.5 else ("↓" if trace[-1] < trace[0] - 0.5 else "·")
        print(f"  {c['id']} D{c['byte']:<5}  {trace_fmt}  {trend:>10}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
