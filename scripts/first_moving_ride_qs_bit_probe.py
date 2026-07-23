#!/usr/bin/env python3
"""first_moving_ride_qs_bit_probe.py — characterise 121 D6 bit 0 as a QS marker.

Reports per-shift:
  - shift ts, from→to gears (up or down)
  - fires? (0/1) — whether 121 D6 bit 0 was 1 anywhere in ±0.4 s
  - fire duration in the window (ms) and offset of the fire onset from shift ts

Then reports globally:
  - fraction of frames where the bit is 1 OUTSIDE any shift window
  - upshift vs downshift fire rate
"""

from __future__ import annotations

import re
import statistics
import sys
from pathlib import Path
from collections import defaultdict

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


def collect(path):
    gears = []
    bit_series = []
    for ts, arb, d in parse_frames(path):
        if arb == "129" and len(d) >= 1:
            gears.append((ts, (d[0] >> 4) & 0x0F, (d[0] >> 3) & 1))
        elif arb == "121" and len(d) >= 7:
            bit_series.append((ts, d[6] & 1, d[6]))  # (ts, bit0_of_d6, whole_d6)
    return gears, bit_series


def find_shifts(gears):
    if not gears:
        return []
    out = []
    prev_g = gears[0][1]
    for ts, g, c in gears:
        if g != prev_g:
            out.append((ts, prev_g, g, c))
            prev_g = g
    return out


def main():
    all_shift_stats = []
    total_bit_frames = 0
    total_bit_on = 0
    total_bit_on_in_shift = 0

    for path in sorted(SESSION.glob("moving-*.log")):
        print(f"\n## {path.name}")
        gears, series = collect(path)
        shifts = find_shifts(gears)

        # Compute out-of-window baseline
        shift_windows = [(ts - SHIFT_WINDOW_S, ts + SHIFT_WINDOW_S) for ts, _, _, _ in shifts]

        def in_any_shift(t):
            for lo, hi in shift_windows:
                if lo <= t <= hi:
                    return True
            return False

        for ts, bit, byte in series:
            total_bit_frames += 1
            if bit:
                total_bit_on += 1
                if in_any_shift(ts):
                    total_bit_on_in_shift += 1

        # Per-shift stats
        for ts, fg, tg, clutch in shifts:
            t_lo, t_hi = ts - SHIFT_WINDOW_S, ts + SHIFT_WINDOW_S
            window_frames = [(t, b) for t, b, _ in series if t_lo <= t <= t_hi]
            on_frames = [(t, b) for t, b in window_frames if b == 1]
            fires = len(on_frames) > 0
            if fires:
                first_on = on_frames[0][0]
                last_on = on_frames[-1][0]
                # duration in ms (broadcast is 20 ms, so duration ≈ (n_on_frames + 1) × 20)
                duration_ms = (last_on - first_on) * 1000 + 20
                offset_ms = (first_on - ts) * 1000
            else:
                duration_ms = 0
                offset_ms = 0
            direction = "up" if tg > fg and fg != 0 else ("down" if tg < fg and tg != 0 else "N↔")
            all_shift_stats.append({
                "file": path.name, "ts_norm": ts - gears[0][0], "from_g": fg, "to_g": tg,
                "direction": direction, "clutch": clutch, "fires": fires,
                "duration_ms": duration_ms, "offset_ms": offset_ms,
                "n_on": len(on_frames),
            })

    # -------- Report per-shift
    print(f"\n\n# Per-shift: does 121 D6 bit 0 fire in ±{SHIFT_WINDOW_S*1000:.0f} ms around each gear change?")
    print(f"  {'file':<14} {'t+s':>7}  {'shift':<8}  {'dir':<4}  {'clutch':>6}  "
          f"{'fires':>5}  {'onset (ms)':>10}  {'dur (ms)':>8}")
    for s in all_shift_stats:
        print(f"  {s['file']:<14} {s['ts_norm']:>7.2f}  "
              f"{s['from_g']}→{s['to_g']:<3}  {s['direction']:<4}  {s['clutch']:>6}  "
              f"{('YES' if s['fires'] else 'no'):>5}  "
              f"{s['offset_ms']:>10.0f}  {s['duration_ms']:>8.0f}")

    # -------- Aggregate
    print(f"\n\n# Aggregate")
    n_total = len(all_shift_stats)
    n_fires = sum(1 for s in all_shift_stats if s["fires"])
    print(f"  Total shifts: {n_total}, bit fires: {n_fires} ({n_fires*100/n_total:.1f}%)")

    ups = [s for s in all_shift_stats if s["direction"] == "up"]
    downs = [s for s in all_shift_stats if s["direction"] == "down"]
    ns = [s for s in all_shift_stats if s["direction"] == "N↔"]
    for label, group in [("upshifts", ups), ("downshifts", downs), ("N↔ engagements", ns)]:
        if not group:
            continue
        fired = [s for s in group if s["fires"]]
        print(f"  {label}: {len(group)} total, {len(fired)} fired ({len(fired)*100/len(group):.1f}%)")
        if fired:
            durs = [s["duration_ms"] for s in fired]
            offsets = [s["offset_ms"] for s in fired]
            print(f"    duration: min={min(durs):.0f} median={statistics.median(durs):.0f} max={max(durs):.0f} ms")
            print(f"    onset offset from gear-change moment: min={min(offsets):.0f} median={statistics.median(offsets):.0f} max={max(offsets):.0f} ms")

    # -------- Out-of-window baseline
    print(f"\n  Bit-on frames: {total_bit_on} total across all files ({total_bit_on*100/total_bit_frames:.3f}% duty)")
    print(f"  Of those, {total_bit_on_in_shift} inside shift windows ({total_bit_on_in_shift*100/total_bit_on:.1f}%)")
    print(f"  Out-of-window fires: {total_bit_on - total_bit_on_in_shift}")


if __name__ == "__main__":
    sys.exit(main())
