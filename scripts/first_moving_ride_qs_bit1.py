#!/usr/bin/env python3
"""first_moving_ride_qs_bit1.py — does 121 D6 bit 1 mark downshift auto-blip?

Hypothesis: bit 0 fires on every quickshifter event (up or down); bit 1 also
fires on downshifts (auto-blip). Test: per-shift, was bit 1 = 1 anywhere in
the shift window?
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSION = REPO_ROOT / "logs" / "2026-07-22-first-moving-ride"
LINE_RE = re.compile(r"\(([\d.]+)\)\s+t([0-9A-Fa-f]{3})([0-9A-Fa-f])([0-9A-Fa-f]*)")

SHIFT_WINDOW_S = 0.4


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
    for path in sorted(SESSION.glob("moving-*.log")):
        gears = []
        d6 = []
        for ts, arb, d in parse_frames(path):
            if arb == "129":
                gears.append((ts, (d[0] >> 4) & 0x0F))
            elif arb == "121" and len(d) >= 7:
                d6.append((ts, d[6]))
        prev_g = gears[0][1] if gears else 0
        shifts = []
        for ts, g in gears:
            if g != prev_g:
                shifts.append((ts, prev_g, g))
                prev_g = g

        for ts, fg, tg in shifts:
            t_lo, t_hi = ts - SHIFT_WINDOW_S, ts + SHIFT_WINDOW_S
            in_win = [(t, v) for t, v in d6 if t_lo <= t <= t_hi and v != 0]
            b0_frames = sum(1 for _, v in in_win if v & 1)
            b1_frames = sum(1 for _, v in in_win if (v >> 1) & 1)
            values = sorted(set(v for _, v in in_win))
            direction = "up" if tg > fg and fg != 0 else ("down" if tg < fg and tg != 0 else "N↔")
            print(f"  {path.name:<14} t+{ts-gears[0][0]:>6.2f}  {fg}→{tg:<2} {direction:<4}  "
                  f"b0-frames={b0_frames:>2}  b1-frames={b1_frames:>2}  values={values}")


if __name__ == "__main__":
    sys.exit(main())
