#!/usr/bin/env python3
"""first_moving_ride_quickshifter_v2.py — tighter QS-bit hunt.

Refines the v1 hunt: look for bits that are 0 most of the ride (< 5% duty) but
flip to 1 inside shift windows for the majority of shifts. A quickshifter
"engaged" or "ignition cut" flag is exactly this shape — low overall duty,
firing briefly (~50-100 ms) at every shift.

Also: dig into what happens *inside* a single QS event. RPM dip below new-gear
trend, throttle position during shift, and shift-failed flag ([[signal-shift-failed]])
behaviour.
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

SHIFT_WINDOW_S = 0.4  # tighter — QS cut is ~50-100 ms
DUTY_MAX = 0.05        # candidate bit must be 1 in ≤ 5% of file frames


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


def analyse(path):
    gears = []
    rpm = []
    throttle = []
    bits = defaultdict(list)
    for ts, arb, d in parse_frames(path):
        if arb == "129" and len(d) >= 1:
            gears.append((ts, (d[0] >> 4) & 0x0F, (d[0] >> 3) & 1, (d[0] >> 1) & 1))
        elif arb == "120" and len(d) >= 3:
            rpm.append((ts, (d[0] << 8) | d[1]))
            throttle.append((ts, d[2]))
        for bi, byte in enumerate(d):
            for b in range(8):
                bits[(arb, bi, b)].append((ts, (byte >> b) & 1))
    return gears, rpm, throttle, bits


def find_shifts(gears):
    """Return (ts, from_gear, to_gear) for stable transitions (both ends held 200 ms)."""
    if not gears:
        return []
    out = []
    prev_g = gears[0][1]
    prev_ts = gears[0][0]
    for i, (ts, g, _, _) in enumerate(gears):
        if g != prev_g:
            # verify held for 200 ms before and after
            held_before = all(gg == prev_g for tt, gg, _, _ in gears if prev_ts <= tt < ts and tt >= ts - 0.2)
            held_after = all(gg == g for tt, gg, _, _ in gears if ts <= tt < ts + 0.2)
            if held_before and held_after:
                out.append((ts, prev_g, g))
            prev_g = g
            prev_ts = ts
    return out


def bit_duty(series):
    if not series:
        return 0
    return sum(v for _, v in series) / len(series)


def bit_fires_in_window(series, t_lo, t_hi):
    """Return True if the bit is 1 at any point in the window."""
    for ts, v in series:
        if ts < t_lo:
            continue
        if ts > t_hi:
            break
        if v == 1:
            return True
    return False


def main():
    total_shifts = 0
    per_file_stats = []
    all_candidates = defaultdict(lambda: {"qs_fires": 0, "qs_total": 0, "duty": []})

    for path in sorted(SESSION.glob("moving-*.log")):
        gears, rpm, throttle, bits = analyse(path)
        shifts = find_shifts(gears)
        if not shifts:
            continue

        # QS shifts = clutch bit stayed 0 in ±SHIFT_WINDOW_S
        qs_shifts = []
        for ts, fg, tg in shifts:
            t_lo, t_hi = ts - SHIFT_WINDOW_S, ts + SHIFT_WINDOW_S
            clutch_max = max((c for tt, _, c, _ in gears if t_lo <= tt <= t_hi), default=0)
            if clutch_max == 0:
                qs_shifts.append((ts, fg, tg))
        per_file_stats.append((path.name, len(shifts), len(qs_shifts)))
        total_shifts += len(qs_shifts)

        # Only include low-duty bits as candidates
        for key, series in bits.items():
            duty = bit_duty(series)
            if duty > DUTY_MAX or duty == 0:
                continue
            all_candidates[key]["duty"].append(duty)
            for ts, _, _ in qs_shifts:
                all_candidates[key]["qs_total"] += 1
                if bit_fires_in_window(series, ts - SHIFT_WINDOW_S, ts + SHIFT_WINDOW_S):
                    all_candidates[key]["qs_fires"] += 1

    print(f"# Tightened QS-bit hunt across 2026-07-22 moving corpus")
    print(f"\nPer-file shift counts:")
    for name, total, qs in per_file_stats:
        print(f"  {name}: {total} shifts, {qs} classified quickshifter (clutch bit 0)")
    print(f"\nTotal QS shifts: {total_shifts}")
    print(f"Candidate bit criteria: duty ≤ {DUTY_MAX*100:.0f}% overall AND fires in ≥ 50% of QS windows (±{SHIFT_WINDOW_S:.2f} s)\n")

    ranked = []
    for key, stats in all_candidates.items():
        if stats["qs_total"] == 0:
            continue
        fire_rate = stats["qs_fires"] / stats["qs_total"]
        if fire_rate < 0.5:
            continue
        avg_duty = statistics.mean(stats["duty"])
        ranked.append((fire_rate, avg_duty, key, stats["qs_fires"], stats["qs_total"]))
    ranked.sort(key=lambda r: (-r[0], r[1]))

    if not ranked:
        print("  No bit fits: low-duty + fires at ≥ 50% of QS shifts.")
        # relax: show anything with duty < 5% and any QS association
        print("\n  Relaxed view — top 20 bits by (QS-fire-rate × 1/duty):")
        loose = []
        for key, stats in all_candidates.items():
            if stats["qs_total"] == 0 or stats["qs_fires"] == 0:
                continue
            fire_rate = stats["qs_fires"] / stats["qs_total"]
            avg_duty = statistics.mean(stats["duty"])
            loose.append((fire_rate / max(avg_duty, 0.001), fire_rate, avg_duty, key, stats["qs_fires"], stats["qs_total"]))
        loose.sort(reverse=True)
        for score, fr, duty, (arb, b, bit), qh, qt in loose[:20]:
            print(f"  {arb} D{b} bit{bit}  duty={duty*100:5.2f}%  QS-fire-rate={fr*100:5.1f}% ({qh}/{qt})")
        return

    print(f"  {'ID':>4} {'byte':>4} {'bit':>3}  {'duty':>6}  {'QS fires / total':>18}  {'QS %':>5}")
    for fr, duty, (arb, b, bit), qh, qt in ranked[:20]:
        print(f"  {arb:>4} {b:>4} {bit:>3}  {duty*100:5.2f}%  {qh:>8} / {qt:<7}  {fr*100:5.1f}%")


if __name__ == "__main__":
    sys.exit(main())
