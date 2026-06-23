#!/usr/bin/env python3
"""id121_int16_verify.py — confirm `121` D0:D1 + D2:D3 are signed int16 BE.

The byte-distribution scan turned up D0 and D2 as bimodal {0x00, 0xFF} —
classic sign-byte of an int16.  This script verifies by:

  1. Decoding D0:D1 and D2:D3 as signed int16 BE and reporting per-window
     mean ± std plus min/max.  Expectation: small wobble around 0 at idle,
     positive ramp through B1..B5 with a peak in the mid-range.
  2. Cross-checking: per-frame, is D0 = 0xFF iff D1 ≥ 0x80?  If yes, the
     pair really is a two's-complement signed int16; the high byte is just
     the sign extension.
  3. Per-frame comparison of (D0:D1) vs (D2:D3): are they the same value?
     a filtered / lagged version of each other?  or independent quantities
     with similar shape?

If both pairs decode cleanly, we know `121` carries two int16 channels —
candidates for ignition advance correction, fuel trim, idle error, etc.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

SKIP_S = 3.0
SETPOINT_LEN_S = 8.0


def parse_events(path):
    out = {}
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            out.setdefault(r["label"], t)
    return out


def parse_log(path, ids):
    out = {arb: [] for arb in ids}
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            arb = m.group(2).upper()
            if arb not in out:
                continue
            hex_data = m.group(3)
            if len(hex_data) != 16:
                continue
            out[arb].append((float(m.group(1)), bytes.fromhex(hex_data)))
    return out


def window(frames, t0, t1):
    return [(ts, d) for ts, d in frames if t0 <= ts <= t1]


def s16_be(hi, lo):
    v = (hi << 8) | lo
    return v - 65536 if v >= 32768 else v


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denom = (sxx * syy) ** 0.5
    return sxy / denom if denom else float("nan")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--session", default="logs/2026-06-23-engine-driven-rear-spin")
    args = p.parse_args()

    session = REPO_ROOT / args.session
    events = parse_events(session / "events.csv")
    frames = parse_log(session / "capture.log", {"120", "121"})

    idle_set = events["idle settled (neutral)"]
    phase_a  = events["Phase A — idle in 1st"]
    b1       = events["B1 — ~2000 RPM in 1st"]
    b2       = events["B2 — ~2500 RPM in 1st"]
    b3       = events["B3 — ~3500 RPM in 1st"]
    b4       = events["B4 — ~4500 RPM in 1st"]
    b5       = events["B5 — ~5500 RPM in 1st"]
    phase_c  = events["Phase C — idle in 1st (post-sweep)"]
    to_n     = events["back to neutral"]
    kill     = events["kill switch"]

    windows = [
        ("idle-neutral (pre-sweep)",      idle_set + SKIP_S,   phase_a - 1.0),
        ("idle 1st (Phase A)",            phase_a + SKIP_S,    b1 - 1.0),
        ("B1 — ~2000 RPM",                b1 + SKIP_S,         b1 + SKIP_S + SETPOINT_LEN_S),
        ("B2 — ~2500 RPM",                b2 + SKIP_S,         b2 + SKIP_S + SETPOINT_LEN_S),
        ("B3 — ~3500 RPM",                b3 + SKIP_S,         b3 + SKIP_S + SETPOINT_LEN_S),
        ("B4 — ~4500 RPM",                b4 + SKIP_S,         b4 + SKIP_S + SETPOINT_LEN_S),
        ("B5 — ~5500 RPM",                b5 + SKIP_S,         b5 + SKIP_S + SETPOINT_LEN_S),
        ("idle 1st (Phase C post-sweep)", phase_c + SKIP_S,    to_n - 1.0),
        ("idle-neutral (return)",         to_n + SKIP_S,       kill - 1.0),
    ]

    print(f"# `121` int16 hypothesis check — {args.session}\n")

    # --- Test 1: sign-byte consistency --------------------------------------
    # If D0:D1 is signed int16 BE, then per-frame D0==0xFF ⇔ D1>=0x80.
    print("## Test 1 — sign-byte consistency (per-frame D0==0xFF ⇔ D1≥0x80; same for D2:D3)\n")
    print(f"  {'window':<32}  {'n':>5}  {'D0:D1 sign-agree':>18}  {'D2:D3 sign-agree':>18}")
    for name, t0, t1 in windows:
        win = window(frames["121"], t0, t1)
        if not win:
            continue
        ok01 = sum(1 for _, d in win if (d[0] == 0xFF) == (d[1] >= 0x80))
        ok23 = sum(1 for _, d in win if (d[2] == 0xFF) == (d[3] >= 0x80))
        n = len(win)
        print(f"  {name:<32}  {n:5d}  {ok01:>10}/{n:<5} ({100*ok01/n:4.1f}%)  "
              f"{ok23:>10}/{n:<5} ({100*ok23/n:4.1f}%)")

    # --- Test 2: signed-int16 mean ± std per window -------------------------
    print("\n## Test 2 — signed int16 BE per window (D0:D1 and D2:D3)\n")
    print(f"  {'window':<32}  {'RPM':>5}  "
          f"{'D0:D1 mean±std':>20}  {'D0:D1 range':>16}  "
          f"{'D2:D3 mean±std':>20}  {'D2:D3 range':>16}")
    series_by_window = {}
    for name, t0, t1 in windows:
        win121 = window(frames["121"], t0, t1)
        win120 = window(frames["120"], t0, t1)
        if not win121:
            continue
        rpm = sum((d[0] << 8) | d[1] for _, d in win120) / len(win120) if win120 else 0
        v01 = [s16_be(d[0], d[1]) for _, d in win121]
        v23 = [s16_be(d[2], d[3]) for _, d in win121]
        m01, s01 = sum(v01) / len(v01), statistics.pstdev(v01)
        m23, s23 = sum(v23) / len(v23), statistics.pstdev(v23)
        r01 = f"{min(v01):+5d}..{max(v01):+5d}"
        r23 = f"{min(v23):+5d}..{max(v23):+5d}"
        print(f"  {name:<32}  {rpm:5.0f}  "
              f"{m01:+8.2f} ± {s01:6.2f}    {r01:>16}  "
              f"{m23:+8.2f} ± {s23:6.2f}    {r23:>16}")
        series_by_window[name] = (v01, v23)

    # --- Test 3: D0:D1 vs D2:D3 — same quantity? ----------------------------
    print("\n## Test 3 — per-frame D0:D1 vs D2:D3 (per window)\n")
    print(f"  {'window':<32}  {'Pearson r':>10}  {'mean diff':>10}  {'equal frames':>14}")
    for name, (v01, v23) in series_by_window.items():
        r = pearson(v01, v23)
        diff = sum(a - b for a, b in zip(v01, v23)) / len(v01)
        eq = sum(1 for a, b in zip(v01, v23) if a == b)
        print(f"  {name:<32}  {r:+10.3f}  {diff:+10.3f}  {eq:>5}/{len(v01):<5} ({100*eq/len(v01):4.1f}%)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
