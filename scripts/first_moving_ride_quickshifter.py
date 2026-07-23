#!/usr/bin/env python3
"""first_moving_ride_quickshifter.py — quickshifter vs clutched-shift analysis.

The rider used the quickshifter for some shifts during the 2026-07-22 ride
(rider note). Quickshifter on the Svartpilen 401 lets the rider upshift without
pulling the clutch; the ECU cuts ignition briefly (~50-100 ms) during the shift
to unload the dogs. Distinguishing signatures:

  - Clutched shift:  gear_position steps up, clutch bit = 1 in the ~1 s window
                     around the transition, RPM drops smoothly through the ratio.
  - Quickshifter:    gear_position steps up, clutch bit STAYS 0, RPM shows a
                     brief dip during the ignition-cut, then settles at the new
                     ratio.

Report:
  1. Every gear-position transition across moving-1..5 (up-shifts and down-shifts).
  2. For each transition: RPM before/after, min RPM inside the window, and the
     clutch bit's max value during the shift window.
  3. Classify: quickshifter (clutch never pulled), clutched, ambiguous.
  4. Hunt for a "quickshifter engaged" bit — any bit that flips only during QS
     shifts.
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

SHIFT_WINDOW_S = 1.5  # look this far before/after the gear-change frame


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
    gears = []    # (ts, gear_int, clutch_bit, shift_failed_bit)
    rpm = []      # (ts, rpm)
    frames_all = defaultdict(list)  # (id, byte, bit) → [(ts, val), ...]
    for ts, arb, d in parse_frames(path):
        if arb == "129" and len(d) >= 1:
            gears.append((ts, (d[0] >> 4) & 0x0F, (d[0] >> 3) & 1, (d[0] >> 1) & 1))
        elif arb == "120" and len(d) >= 2:
            rpm.append((ts, (d[0] << 8) | d[1]))
        # every bit for the "QS-engaged bit" hunt
        for b_idx, byte in enumerate(d):
            for bit in range(8):
                frames_all[(arb, b_idx, bit)].append((ts, (byte >> bit) & 1))
    return gears, rpm, frames_all


def rpm_around(rpm_series, t_lo, t_hi):
    return [(t, r) for t, r in rpm_series if t_lo <= t <= t_hi]


def clutch_max_in_window(gears, t_lo, t_hi):
    return max((c for t, _, c, _ in gears if t_lo <= t <= t_hi), default=0)


def gear_at(gears, t):
    prev = None
    for ts, g, _, _ in gears:
        if ts > t:
            break
        prev = g
    return prev


def find_gear_transitions(gears):
    """Return (ts, from_gear, to_gear) for every gear change."""
    out = []
    prev = gears[0][1]
    prev_ts = gears[0][0]
    for ts, g, _, _ in gears[1:]:
        if g != prev:
            out.append((ts, prev, g))
            prev = g
            prev_ts = ts
    return out


def label_transition(from_g, to_g):
    if from_g == 0 or to_g == 0:
        return f"N↔{max(from_g, to_g)}"
    if to_g > from_g:
        return f"{from_g}→{to_g} up"
    if to_g < from_g:
        return f"{from_g}→{to_g} down"
    return f"{from_g}→{to_g}"


def main():
    all_transitions = []  # dicts with per-shift stats

    for path in sorted(SESSION.glob("moving-*.log")):
        print(f"\n## {path.name}")
        gears, rpm, frames_all = collect(path)
        if not gears or not rpm:
            print("  no gear/rpm data")
            continue
        ts0 = gears[0][0]

        transitions = find_gear_transitions(gears)
        # filter out gear-change flurries: keep only transitions where both
        # from_gear and to_gear held for > 200 ms
        stable = []
        for ts, fg, tg in transitions:
            # gear_position at ts-0.2 = fg; at ts+0.2 = tg
            if gear_at(gears, ts - 0.2) == fg and gear_at(gears, ts + 0.2) == tg:
                stable.append((ts, fg, tg))

        print(f"  {len(transitions)} raw gear changes, {len(stable)} after stability filter (both ends held ≥ 200 ms)")

        for ts, fg, tg in stable:
            t_lo = ts - SHIFT_WINDOW_S
            t_hi = ts + SHIFT_WINDOW_S
            rpm_win = rpm_around(rpm, t_lo, t_hi)
            if not rpm_win:
                continue
            # RPM before/after — median of the 5 frames just before/after
            rpm_before = statistics.median(r for t, r in rpm_win if t < ts - 0.05)[:5] if False else None
            before_vals = [r for t, r in rpm_win if ts - 0.5 <= t < ts - 0.05][-10:]
            after_vals = [r for t, r in rpm_win if ts + 0.05 <= t <= ts + 0.5][:10]
            rpm_before = statistics.median(before_vals) if before_vals else None
            rpm_after = statistics.median(after_vals) if after_vals else None
            rpm_min = min(r for t, r in rpm_win)
            rpm_max = max(r for t, r in rpm_win)
            clutch_max = clutch_max_in_window(gears, t_lo, t_hi)

            if rpm_before is None or rpm_after is None:
                continue

            # RPM dip = how far below the linear before→after RPM at ts+0
            dip_from_before = rpm_before - rpm_min

            classification = "quickshifter" if clutch_max == 0 else "clutched"
            all_transitions.append({
                "file": path.name, "ts": ts, "ts_norm": ts - ts0,
                "from_g": fg, "to_g": tg,
                "rpm_before": rpm_before, "rpm_after": rpm_after,
                "rpm_min": rpm_min, "rpm_max": rpm_max,
                "dip_from_before": dip_from_before,
                "clutch_max": clutch_max,
                "class": classification,
                "frames_all": frames_all,
                "t_lo": t_lo, "t_hi": t_hi,
            })

    # -------- Report all transitions
    print(f"\n\n# All stable gear transitions ({len(all_transitions)} total)")
    print(f"  {'file':<14} {'t+s':>7}  {'shift':<8}  {'RPM before':>10}  {'RPM after':>9}  "
          f"{'RPM min':>7}  {'dip':>5}  {'clutch':>6}  {'class':<15}")
    for t in all_transitions:
        print(f"  {t['file']:<14} {t['ts_norm']:>7.2f}  {label_transition(t['from_g'], t['to_g']):<8}  "
              f"{t['rpm_before']:>10.0f}  {t['rpm_after']:>9.0f}  "
              f"{t['rpm_min']:>7.0f}  {t['dip_from_before']:>5.0f}  {t['clutch_max']:>6}  {t['class']:<15}")

    # -------- Aggregate by class
    print(f"\n\n# By class")
    qs = [t for t in all_transitions if t["class"] == "quickshifter"]
    cl = [t for t in all_transitions if t["class"] == "clutched"]
    print(f"  quickshifter: {len(qs)}")
    print(f"  clutched:     {len(cl)}")
    for label, group in [("quickshifter", qs), ("clutched", cl)]:
        if not group:
            continue
        dips = [g["dip_from_before"] for g in group]
        print(f"  {label} RPM dip stats:  min {min(dips):4.0f}  median {statistics.median(dips):4.0f}  max {max(dips):4.0f}")

    # -------- Hunt for a "QS engaged" bit
    print(f"\n\n# 'Quickshifter engaged' bit hunt")
    print(f"  Look for bits that fire (transition from 0 to 1 and back) inside the shift window")
    print(f"  for quickshifter shifts but not for clutched shifts.")

    # Get all bits, count firing windows per class
    if not all_transitions:
        return

    # For efficiency, use one file's frames_all — but shifts happen across files,
    # so process per-transition using that file's frames_all.
    def bit_activity_in_window(frames_all, key, t_lo, t_hi):
        """Return True if the bit had any 0→1 transition in the window."""
        prev_val = None
        rose = False
        for ts, v in frames_all[key]:
            if ts < t_lo:
                prev_val = v
                continue
            if ts > t_hi:
                break
            if prev_val is not None and v == 1 and prev_val == 0:
                rose = True
                break
            prev_val = v
        return rose

    # Collect all (id, byte, bit) keys
    all_keys = set()
    for t in all_transitions:
        all_keys.update(t["frames_all"].keys())

    qs_hits = defaultdict(int)
    cl_hits = defaultdict(int)
    for t in all_transitions:
        for key in all_keys:
            if key not in t["frames_all"]:
                continue
            if bit_activity_in_window(t["frames_all"], key, t["t_lo"], t["t_hi"]):
                if t["class"] == "quickshifter":
                    qs_hits[key] += 1
                else:
                    cl_hits[key] += 1

    # Candidates: bits that fire in most QS shifts but not most clutched shifts
    candidates = []
    for key in all_keys:
        qs_frac = qs_hits[key] / len(qs) if qs else 0
        cl_frac = cl_hits[key] / len(cl) if cl else 0
        if qs_frac >= 0.5 and cl_frac <= 0.2:
            candidates.append((qs_frac - cl_frac, key, qs_hits[key], cl_hits[key]))
    candidates.sort(reverse=True)

    print(f"  ({len(qs)} QS shifts, {len(cl)} clutched shifts examined)\n")
    print(f"  {'ID':>4} {'byte':>4} {'bit':>3}  {'in QS':>6}  {'in clutched':>11}  {'QS%':>5}  {'CL%':>5}")
    if not candidates:
        print(f"  NONE — no bit systematically fires during QS shifts but not clutched shifts.")
        # Also show the reverse: bits that fire in clutched but not QS (i.e., a "clutch engaged" signal we haven't decoded)
        print(f"\n  Reverse check — bits firing more in clutched than QS shifts:")
        rev_candidates = []
        for key in all_keys:
            qs_frac = qs_hits[key] / len(qs) if qs else 0
            cl_frac = cl_hits[key] / len(cl) if cl else 0
            if cl_frac >= 0.5 and qs_frac <= 0.2:
                rev_candidates.append((cl_frac - qs_frac, key, qs_hits[key], cl_hits[key]))
        rev_candidates.sort(reverse=True)
        for delta, (arb, b, bit), qh, ch in rev_candidates[:15]:
            qs_frac = qh / len(qs) * 100 if qs else 0
            cl_frac = ch / len(cl) * 100 if cl else 0
            print(f"  {arb:>4} {b:>4} {bit:>3}  {qh:>6}  {ch:>11}  {qs_frac:>4.0f}%  {cl_frac:>4.0f}%")
    else:
        for delta, (arb, b, bit), qh, ch in candidates[:15]:
            qs_frac = qh / len(qs) * 100 if qs else 0
            cl_frac = ch / len(cl) * 100 if cl else 0
            print(f"  {arb:>4} {b:>4} {bit:>3}  {qh:>6}  {ch:>11}  {qs_frac:>4.0f}%  {cl_frac:>4.0f}%")


if __name__ == "__main__":
    sys.exit(main())
