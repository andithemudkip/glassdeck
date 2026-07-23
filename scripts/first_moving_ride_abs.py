#!/usr/bin/env python3
"""first_moving_ride_abs.py — hunt for the ABS warning-lamp bit in moving-1.

Rider observation ([[bike/dash-warning-lights]]): ABS lamp lit at key-on and
held; extinguishes ~6 km/h with engine running (provisional). moving-1 is the
first capture where engine is running AND wheel speed crosses 6 km/h — no bit
has been located for the ABS lamp yet.

Strategy: find the moment the OEM-relevant wheel speed (front, per
[[signal-wheel-speed-front]]) first crosses ~6 km/h. Look for bits that:
  - are 1 (or 0, both polarities tried) at the very start of the capture,
  - transition once to the opposite value within a small tolerance of that
    crossing,
  - stay there for the rest of the pre-first-stop portion of the ride.

Also plot the wheel-speed timeline around the first crossing, to give a sanity
check on which candidate looks most like a monotonic "gate off" transition.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG = REPO_ROOT / "logs" / "2026-07-22-first-moving-ride" / "moving-1.log"
LINE_RE = re.compile(r"\(([\d.]+)\)\s+t([0-9A-Fa-f]{3})([0-9A-Fa-f])([0-9A-Fa-f]*)")

# Working LSBs from the 2026-07-22 wheel-speed rewrite.
LSB_FRONT = 1 / 162.0
LSB_REAR = 0.0565

ABS_THRESHOLD_KMH = 6.0
CROSS_TOL_S = 2.0


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


def wheel_series(path):
    """Return (front_kmh_series, rear_kmh_series) as [(ts, kmh), ...]."""
    front, rear = [], []
    for ts, arb, d in parse_frames(path):
        if arb == "12D" and len(d) >= 7:
            front.append((ts, ((d[0] << 8) | d[1]) * LSB_FRONT))
            rear.append((ts, ((d[5] << 8) | d[6]) * LSB_REAR))
    return front, rear


def find_rising_crossings(series, threshold):
    """Return timestamps where series goes from below to at-or-above threshold."""
    out = []
    prev_c = series[0][1]
    for t, c in series[1:]:
        if prev_c < threshold and c >= threshold:
            out.append(t)
        prev_c = c
    return out


def bit_series(path):
    """Yield ((id, byte, bit), [(ts, val), ...]) — full time-series per bit."""
    latest = defaultdict(list)
    for ts, arb, data in parse_frames(path):
        for b_idx, byte in enumerate(data):
            for bit in range(8):
                latest[(arb, b_idx, bit)].append((ts, (byte >> bit) & 1))
    return latest


def main():
    print(f"# ABS-lamp hunt — {LOG.name}\n")

    front, rear = wheel_series(LOG)
    if not front:
        print("no 12D frames.")
        return 1

    ts0 = front[0][0]
    print(f"Wheel-speed span: front {front[0][1]:.1f} → peak {max(v for _, v in front):.1f} km/h,"
          f" rear {rear[0][1]:.1f} → peak {max(v for _, v in rear):.1f} km/h"
          f"  ({len(front)} 12D frames, {front[-1][0] - ts0:.1f} s)")

    # Find the very first crossing of 6 km/h — front and rear separately.
    front_cross = find_rising_crossings(front, ABS_THRESHOLD_KMH)
    rear_cross = find_rising_crossings(rear, ABS_THRESHOLD_KMH)
    print(f"\nFront crossings of {ABS_THRESHOLD_KMH} km/h (rising):")
    for t in front_cross[:5]:
        print(f"  t+{t - ts0:.2f} s")
    print(f"Rear crossings of {ABS_THRESHOLD_KMH} km/h (rising):")
    for t in rear_cross[:5]:
        print(f"  t+{t - ts0:.2f} s")

    if not front_cross:
        print("Front never crossed the threshold. Aborting.")
        return 1

    first_cross = front_cross[0]
    print(f"\nUsing first FRONT crossing t+{first_cross - ts0:.2f} s as the ABS-extinguish anchor "
          f"(±{CROSS_TOL_S} s tolerance).")

    # ---- scan bits: find candidates that transition once (or few times) near
    #      the anchor with polarity 1→0 (ABS lit = 1, off = 0) or 0→1 (opposite).
    bits = bit_series(LOG)

    def transitions(series):
        prev = series[0][1]
        out = []
        for t, v in series[1:]:
            if v != prev:
                out.append((t, v))
                prev = v
        return out

    candidates_hi = []  # bit starts HIGH, goes LOW near cross → ABS lit=1, off=0
    candidates_lo = []
    for key, series in bits.items():
        if not series:
            continue
        first_val = series[0][1]
        tx = transitions(series)
        # For a plausible ABS bit: the transition to the target polarity should
        # exist near first_cross; total transitions in the pre-first-stop window
        # should be small. Cap at 20 total transitions across the whole file to
        # kill counters / checksums but stay generous on multi-stop rides.
        if len(tx) > 20 or len(tx) == 0:
            continue

        # HI candidates
        if first_val == 1:
            near = [(t, v) for t, v in tx if v == 0 and abs(t - first_cross) <= CROSS_TOL_S]
            if near:
                dt = min(near, key=lambda p: abs(p[0] - first_cross))[0] - first_cross
                candidates_hi.append((abs(dt), dt, key, tx))
        # LO candidates
        if first_val == 0:
            near = [(t, v) for t, v in tx if v == 1 and abs(t - first_cross) <= CROSS_TOL_S]
            if near:
                dt = min(near, key=lambda p: abs(p[0] - first_cross))[0] - first_cross
                candidates_lo.append((abs(dt), dt, key, tx))

    def dump(label, cands):
        cands.sort()
        print(f"\n## {label}  ({len(cands)} matches)")
        if not cands:
            print("  (none)")
            return
        for abs_dt, dt, (arb, b, bit), tx in cands[:15]:
            tx_str = " ".join(f"t+{t-ts0:.1f}→{v}" for t, v in tx)
            print(f"  {arb} D{b} bit{bit}  offset={dt:+.2f}s  transitions=({len(tx)}) {tx_str}")

    dump(f"Candidates: bit HIGH at start, transitions 1→0 within ±{CROSS_TOL_S}s of first cross (ABS lit=1, off=0)",
         candidates_hi)
    dump(f"Candidates: bit LOW at start, transitions 0→1 within ±{CROSS_TOL_S}s of first cross (inverted polarity)",
         candidates_lo)


if __name__ == "__main__":
    sys.exit(main())
