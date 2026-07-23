#!/usr/bin/env python3
"""first_moving_ride_abs_verify.py — verify the 6 ABS-lamp candidates.

Candidates from `first_moving_ride_abs.py` on moving-1:
  12A D0 b4, 12A D1 b0, 12A D1 b2, 12A D5 b3  (HIGH before → LOW after)
  12E D6 b4, 12E D6 b5                        (LOW before → HIGH after)

If these carry ABS-lamp state, then across moving-2..5 (each a fresh
wifi-bridge session on the phone but NOT necessarily a bike key-cycle), the
bits should read the post-cross state throughout — bike was moving at all
those capture starts, so ABS should already be off.

Reports: initial value in each capture, count of transitions across each
capture, and unique values overall.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from collections import Counter

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSION = REPO_ROOT / "logs" / "2026-07-22-first-moving-ride"
LINE_RE = re.compile(r"\(([\d.]+)\)\s+t([0-9A-Fa-f]{3})([0-9A-Fa-f])([0-9A-Fa-f]*)")

CANDIDATES = [
    # (id, byte, bit, polarity_desc)
    ("12A", 0, 4, "HIGH→LOW"),
    ("12A", 1, 0, "HIGH→LOW"),
    ("12A", 1, 2, "HIGH→LOW"),
    ("12A", 5, 3, "HIGH→LOW"),
    ("12E", 6, 4, "LOW→HIGH"),
    ("12E", 6, 5, "LOW→HIGH"),
]


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


def collect(path, id_of, byte_of, bit_of):
    series = []
    for ts, arb, d in parse_frames(path):
        if arb == id_of and len(d) > byte_of:
            series.append((ts, (d[byte_of] >> bit_of) & 1))
    return series


def main():
    print("# ABS-lamp candidate verification across the 2026-07-22 moving corpus\n")
    files = sorted(SESSION.glob("moving-*.log"))
    for arb, b, bit, pol in CANDIDATES:
        print(f"\n## {arb} D{b} bit{bit}  ({pol})")
        for f in files:
            series = collect(f, arb, b, bit)
            if not series:
                print(f"  {f.name}: no frames")
                continue
            first = series[0][1]
            counter = Counter(v for _, v in series)
            transitions = 0
            prev = first
            for _, v in series[1:]:
                if v != prev:
                    transitions += 1
                    prev = v
            values = " ".join(f"{v}:{c}" for v, c in sorted(counter.items()))
            print(f"  {f.name}: first={first}  transitions={transitions}  n={len(series)}  values [{values}]")


if __name__ == "__main__":
    sys.exit(main())
