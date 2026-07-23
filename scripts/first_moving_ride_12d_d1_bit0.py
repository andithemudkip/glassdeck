#!/usr/bin/env python3
"""first_moving_ride_12d_d1_bit0.py — is 12D D1 bit 0 a flag or just a speed LSB?

Original finding: [[signal-12d-d1-bit0]] claimed bit 0 sets whenever rear
wheel speed ≥ 27 km/h and clears below. That was observed in engine-driven
rear-spin (front stationary throughout). With the front encoding rewritten
from 12-bit-in-16-bit to full uint16, bit 0 might now be the low bit of front
wheel speed rather than an independent flag.

Test:
  H1 (was): P(bit0=1 | rear_kmh < 27) ≈ 0, P(bit0=1 | rear_kmh ≥ 27) ≈ 1
  H2 (new hypothesis, "just a speed LSB"): bit0 distribution is speed-uniform
      — driven by parity of front raw u16, not by rear threshold
  H3 (mixed): bit0 = (speed LSB) XOR (some flag) — messier signature

Report:
  - Bit0 duty broken down by rear speed bin (across all moving files).
  - Bit0 duty broken down by front raw u16 low bit (which IS the same bit).
    This is a tautology if the two are the same, so it's a consistency check:
    is bit0 always == (D0<<8|D1) & 1? Yes by construction — the interesting
    question is what predicts that bit's value.
  - Bit0 vs rear speed in the front-STATIONARY frames from the corpus (rare
    in this ride but present in moving-1's initial ~90 s and possibly moving-5
    stopped intervals). This is the closest thing to the original observation
    regime.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSION = REPO_ROOT / "logs" / "2026-07-22-first-moving-ride"
LINE_RE = re.compile(r"\(([\d.]+)\)\s+t([0-9A-Fa-f]{3})([0-9A-Fa-f])([0-9A-Fa-f]*)")

LSB_FRONT = 1 / 162.0
LSB_REAR = 0.0565


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
    files = sorted(SESSION.glob("moving-*.log"))
    total = defaultdict(lambda: {"bit0=1": 0, "bit0=0": 0})
    total_front_static = defaultdict(lambda: {"bit0=1": 0, "bit0=0": 0})

    for f in files:
        for ts, arb, d in parse_frames(f):
            if arb != "12D" or len(d) < 7:
                continue
            raw_front = (d[0] << 8) | d[1]
            raw_rear = (d[5] << 8) | d[6]
            bit0 = d[1] & 1
            front_kmh = raw_front * LSB_FRONT
            rear_kmh = raw_rear * LSB_REAR

            bin_key = int(rear_kmh // 5) * 5
            total[bin_key][f"bit0={bit0}"] += 1

            # Front-stationary means raw_front == 0 (ECU floor)
            if raw_front == 0:
                total_front_static[bin_key][f"bit0={bit0}"] += 1

    def dump(label, table):
        print(f"\n## {label}")
        print(f"  {'rear km/h':>10}  {'n':>7}  {'bit0=1':>7}  {'bit0=0':>7}  {'P(bit0=1)':>10}")
        for b in sorted(table):
            one = table[b]["bit0=1"]
            zero = table[b]["bit0=0"]
            n = one + zero
            if n < 20:
                continue
            print(f"  {b:>3}-{b+5:<3}   {n:>7}  {one:>7}  {zero:>7}  {one/n:>10.3f}")

    dump("Bit0 duty across ALL frames binned by rear speed (all 5 captures combined)", total)
    dump("Bit0 duty in FRONT-STATIONARY frames only (raw_front == 0)", total_front_static)

    # Also report the overall picture
    grand_one = sum(t["bit0=1"] for t in total.values())
    grand_zero = sum(t["bit0=0"] for t in total.values())
    print(f"\nOverall: {grand_one + grand_zero} frames, P(bit0=1) = {grand_one / max(grand_one+grand_zero,1):.3f}")

    fs_one = sum(t["bit0=1"] for t in total_front_static.values())
    fs_zero = sum(t["bit0=0"] for t in total_front_static.values())
    print(f"Front-stationary only: {fs_one + fs_zero} frames, P(bit0=1) = {fs_one / max(fs_one+fs_zero,1):.3f}")


if __name__ == "__main__":
    sys.exit(main())
