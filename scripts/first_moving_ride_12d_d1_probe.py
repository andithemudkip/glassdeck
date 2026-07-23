#!/usr/bin/env python3
"""first_moving_ride_12d_d1_probe.py — inspect 12D raw values across speed bands.

The bit0-vs-speed-bin analysis surfaced a periodic banding pattern (bit0 ON in
25-50, 75-100 km/h; OFF in 50-75, 100+). That's not consistent with either
(a) a 27 km/h flag or (b) a random speed LSB. This script dumps sample
(raw_front, raw_rear, decoded_front, decoded_rear, D1 all 8 bits) across the
speed range to see what's actually structured.
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
    per_bin = defaultdict(list)  # bin → list of (raw_f, raw_r, D1)
    for f in sorted(SESSION.glob("moving-*.log")):
        for ts, arb, d in parse_frames(f):
            if arb != "12D" or len(d) < 7:
                continue
            raw_front = (d[0] << 8) | d[1]
            raw_rear = (d[5] << 8) | d[6]
            rear_kmh = raw_rear * LSB_REAR
            bin_key = int(rear_kmh // 5) * 5
            per_bin[bin_key].append((raw_front, raw_rear, d[1], d[0], d[3], d[4]))

    print("# Sample raw values per rear speed bin (first 3 frames per bin)")
    print(f"  {'bin':>6}  {'raw_f':>6}  {'raw_r':>6}  {'front':>6}  {'rear':>6}  "
          f"{'D0':>4}  {'D1':>4}  {'D3':>4}  {'D4':>4}  {'D1 bits':>10}  {'f/r':>6}")
    for b in sorted(per_bin):
        samples = per_bin[b][:3]
        for rf, rr, d1, d0, d3, d4 in samples:
            fr = rf * LSB_FRONT
            re_ = rr * LSB_REAR
            ratio = rf / rr if rr else 0
            d1_bits = format(d1, "08b")
            print(f"  {b:>3}-{b+5:<2}  {rf:>6}  {rr:>6}  {fr:>6.1f}  {re_:>6.1f}  "
                  f"0x{d0:02X}  0x{d1:02X}  0x{d3:02X}  0x{d4:02X}  {d1_bits:>10}  {ratio:>6.2f}")

    # Also compute the empirical raw_f / raw_r per bin more precisely
    print("\n## Precise raw_f / raw_r ratio per bin (mean of frames where rear > 3)")
    print(f"  {'bin':>6}  {'n':>6}  {'raw_f μ':>10}  {'raw_r μ':>10}  {'ratio':>8}")
    for b in sorted(per_bin):
        samples = [(rf, rr) for rf, rr, *_ in per_bin[b] if rr > 50]
        if len(samples) < 20:
            continue
        rf_mean = sum(rf for rf, _ in samples) / len(samples)
        rr_mean = sum(rr for _, rr in samples) / len(samples)
        print(f"  {b:>3}-{b+5:<2}  {len(samples):>6}  {rf_mean:>10.1f}  {rr_mean:>10.1f}  {rf_mean/rr_mean:>8.4f}")


if __name__ == "__main__":
    sys.exit(main())
