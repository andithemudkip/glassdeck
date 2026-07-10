#!/usr/bin/env python3
"""brake_bit_scan.py — bit-level companion to brake_scan.py.

For every (arb_id, byte, bit) in the always-on set, count how many
transitions happen inside each phase window of a brakes-stationary
capture. Ranks bits that transitioned in FA/FB and RC/RD but not in
BASE — a single-bit brake-switch signal would surface here even if
the surrounding byte is noisy for other reasons (e.g. `541` D6 D7).

Usage:
    python scripts/brake_bit_scan.py logs/2026-07-10-brakes-stationary
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from collections import defaultdict
from pathlib import Path

LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")


def load_events(path: Path) -> dict[str, float]:
    idx: dict[str, float] = {}
    with path.open() as f:
        for row in csv.DictReader(f):
            t = dt.datetime.fromisoformat(row["timestamp_iso"]).timestamp()
            idx[row["label"]] = t
    return idx


def build_windows(events: dict[str, float]) -> dict[str, tuple[float, float]]:
    return {
        "BASE": (events["pre-brake baseline start"], events["pre-brake baseline start"] + 20.0),
        "FA":   (events["front pulse 1 gentle (~30 %)"], events["front pulse 6 hard"] + 4.0),
        "FB":   (events["front sustained medium (12 s hold start)"],
                 events["front sustained medium (12 s hold start)"] + 12.0),
        "RC":   (events["rear pulse 1 gentle (~30 %)"], events["rear pulse 6 hard"] + 4.0),
        "RD":   (events["rear sustained medium (12 s hold start)"],
                 events["rear sustained medium (12 s hold start)"] + 12.0),
        "BE":   (events["both pulse 1 medium"],
                 events["both sustained medium (8 s hold start)"] + 8.0),
    }


def scan(log_path: Path, windows):
    # For each (arb, byte), track previous value + previous-window; count
    # per-bit transitions bucketed by the window they fell in.
    prev_val: dict[tuple[str, int], int] = {}
    trans: dict[tuple[str, int, int], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    with log_path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            ts = float(m.group(1))
            arb = m.group(2).upper()
            hex_data = m.group(3)
            if len(hex_data) % 2 or not hex_data:
                continue
            data = bytes.fromhex(hex_data)
            # Which window (if any) contains ts?
            w = None
            for wname, (t0, t1) in windows.items():
                if t0 <= ts <= t1:
                    w = wname
                    break
            for bi, b in enumerate(data):
                key = (arb, bi)
                p = prev_val.get(key)
                if p is not None and w is not None:
                    diff = p ^ b
                    if diff:
                        for bit in range(8):
                            if diff & (1 << bit):
                                trans[(arb, bi, bit)][w] += 1
                prev_val[key] = b
    return trans


def rank(trans, windows):
    rows = []
    for (arb, bi, bit), by_w in trans.items():
        counts = {w: by_w.get(w, 0) for w in windows}
        base = counts["BASE"]
        fa, fb = counts["FA"], counts["FB"]
        rc, rd = counts["RC"], counts["RD"]
        be = counts["BE"]
        active_brake = max(fa, fb, rc, rd, be)
        if active_brake < 2:
            continue  # not a real signal
        # Ratio: how much brake windows vs. baseline?
        # (Rough — window durations differ.)
        if base == 0 and active_brake >= 2:
            cls = "CLEAN"
        elif base < active_brake / 3:
            cls = "STRONG"
        elif base < active_brake:
            cls = "WEAK"
        else:
            cls = "NOISE"
        rows.append((cls, arb, bi, bit, base, fa, fb, rc, rd, be))
    order = {"CLEAN": 0, "STRONG": 1, "WEAK": 2, "NOISE": 3}
    rows.sort(key=lambda r: (order[r[0]], r[1], r[2], r[3]))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session", type=Path)
    ap.add_argument("--drop-d7", action="store_true", default=True,
                    help="Skip D7 (byte 7) — churns deterministically per byte-d7-cycle-hash")
    ap.add_argument("--include-d7", dest="drop_d7", action="store_false")
    ap.add_argument("--max-rows", type=int, default=40)
    args = ap.parse_args()

    events = load_events(args.session / "events.csv")
    windows = build_windows(events)
    trans = scan(args.session / "capture.log", windows)
    rows = rank(trans, windows)
    if args.drop_d7:
        rows = [r for r in rows if r[2] != 7]
    print(f"# transitions per (ID, byte, bit) per window")
    print(f"# 'CLEAN' = zero transitions in BASE, ≥2 in some brake window")
    print()
    print(f"{'class':7s} {'ID':>3s} {'byte':>4s} {'bit':>3s}   BASE   FA   FB   RC   RD   BE")
    print("-" * 60)
    for cls, arb, bi, bit, base, fa, fb, rc, rd, be in rows[:args.max_rows]:
        print(f"{cls:7s} {arb:>3s} {bi:>4d} {bit:>3d}   {base:>4d}  {fa:>3d}  {fb:>3d}  {rc:>3d}  {rd:>3d}  {be:>3d}")
    if len(rows) > args.max_rows:
        print(f"... {len(rows) - args.max_rows} more rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
