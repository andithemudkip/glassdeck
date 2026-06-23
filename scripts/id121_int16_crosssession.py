#!/usr/bin/env python3
"""id121_int16_crosssession.py — verify the `121` int16 encoding across sessions.

Runs the same sign-byte-consistency + int16-mean checks as id121_int16_verify.py
but across multiple engine-on idle captures, to confirm the encoding generalises
beyond the rear-spin session it was discovered in.

For each session, splits into engine-off (pre-start) and engine-on (post-start
+ settle, to kill - settle) windows and reports:
  - sign-byte consistency for D0:D1 and D2:D3
  - int16 BE mean ± std for both pairs
  - Pearson r between the two channels

A clean encoding gives 100% sign agreement in every session and small ±0..2 LSB
idle wobble around 0.
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

SETTLE_S = 10.0  # skip after starter, skip before kill


def parse_events(path):
    out = {}
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            out.setdefault(r["key"], []).append(t)
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


def analyze_window(win121):
    n = len(win121)
    if n == 0:
        return None
    ok01 = sum(1 for _, d in win121 if (d[0] == 0xFF) == (d[1] >= 0x80))
    ok23 = sum(1 for _, d in win121 if (d[2] == 0xFF) == (d[3] >= 0x80))
    v01 = [s16_be(d[0], d[1]) for _, d in win121]
    v23 = [s16_be(d[2], d[3]) for _, d in win121]
    return {
        "n": n,
        "sign01": ok01, "sign23": ok23,
        "v01_mean": sum(v01) / n, "v01_std": statistics.pstdev(v01),
        "v01_min": min(v01), "v01_max": max(v01),
        "v23_mean": sum(v23) / n, "v23_std": statistics.pstdev(v23),
        "v23_min": min(v23), "v23_max": max(v23),
        "r": pearson(v01, v23),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("sessions", nargs="+", help="session directory paths (relative to repo root)")
    args = p.parse_args()

    print(f"# `121` int16 cross-session sanity check\n")
    print(f"  sign-agreement: per-frame test that D0==0xFF ⇔ D1≥0x80 (and same for D2:D3)")
    print(f"  ✓ 100% across all sessions ⇒ encoding generalises\n")

    for session_path in args.sessions:
        session = REPO_ROOT / session_path
        events = parse_events(session / "events.csv")
        frames = parse_log(session / "capture.log", {"121"})

        starts = events.get("start", [])
        kills = events.get("kill", [])
        if not starts or not kills:
            print(f"## {session_path}\n  (skipping — no start/kill events)\n")
            continue
        start_ts = starts[0]
        kill_ts = kills[-1]

        # Engine-off pre-start window: from first frame to start
        first_ts = frames["121"][0][0] if frames["121"] else start_ts
        off_win = window(frames["121"], first_ts, start_ts - 1.0)
        on_win = window(frames["121"], start_ts + SETTLE_S, kill_ts - SETTLE_S)

        print(f"## {session_path}")
        print(f"  engine-off:  {start_ts - first_ts:5.1f} s window")
        print(f"  engine-on:   {kill_ts - start_ts - 2*SETTLE_S:5.1f} s window (skip ±{SETTLE_S:.0f} s settle)\n")

        for label, win in [("engine-off", off_win), ("engine-on", on_win)]:
            r = analyze_window(win)
            if r is None:
                print(f"  {label}: (no frames)")
                continue
            sign01_pct = 100 * r["sign01"] / r["n"]
            sign23_pct = 100 * r["sign23"] / r["n"]
            print(f"  {label}:  n={r['n']:>6d}  "
                  f"sign01={sign01_pct:5.1f}%  sign23={sign23_pct:5.1f}%  "
                  f"D0:D1 = {r['v01_mean']:+6.2f} ± {r['v01_std']:5.2f}  "
                  f"({r['v01_min']:+d}..{r['v01_max']:+d})  "
                  f"D2:D3 = {r['v23_mean']:+6.2f} ± {r['v23_std']:5.2f}  "
                  f"({r['v23_min']:+d}..{r['v23_max']:+d})  "
                  f"r={r['r']:+.3f}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
