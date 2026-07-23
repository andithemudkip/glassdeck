#!/usr/bin/env python3
"""first_moving_ride_torque_during_cut.py — 121_A across the shift-cut window.

If 121_A is signed engine torque, during a shift-cut (ignition cut, no
combustion → no positive torque, only drivetrain drag) it should momentarily
drop toward zero or slightly-negative and then recover. That's a completely
independent test of the signed-torque hypothesis: the sign-flip under overrun
(shown ride-integrated) and now the transient dip during ignition cut.

For each of the ~ 60 real gear transitions:
  - Extract 121_A across ±200 ms of the shift-cut onset (the moment
    121 D6 bit 0 rose).
  - Track: (a) pre-cut 121_A (~3 frames before), (b) in-cut 121_A (frames where
    D6 bit 0 = 1), (c) post-cut 121_A (~3 frames after).
  - Aggregate the pre→cut delta across up- and downshifts separately.
"""

from __future__ import annotations

import re
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSION = REPO_ROOT / "logs" / "2026-07-22-first-moving-ride"
LINE_RE = re.compile(r"\(([\d.]+)\)\s+t([0-9A-Fa-f]{3})([0-9A-Fa-f])([0-9A-Fa-f]*)")

WINDOW_S = 0.20
FRAMES_ADJACENT = 3


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
    """Return synchronized 121 frames: (ts, A, cut_bit, blip_bit)."""
    out = []
    for ts, arb, d in parse_frames(path):
        if arb == "121" and len(d) >= 7:
            a = int.from_bytes(d[0:2], "big", signed=True)
            cut_bit = d[6] & 1
            blip_bit = (d[6] >> 1) & 1
            out.append((ts, a, cut_bit, blip_bit))
    return out


def gear_transitions(path):
    """Return (ts, from_gear, to_gear) for stable transitions."""
    gears = []
    for ts, arb, d in parse_frames(path):
        if arb == "129" and len(d) >= 1:
            gears.append((ts, (d[0] >> 4) & 0x0F))
    if not gears:
        return []
    out = []
    prev = gears[0][1]
    prev_ts = gears[0][0]
    for ts, g in gears:
        if g != prev:
            # both ends held 200 ms
            held_before = all(gg == prev for tt, gg in gears if prev_ts <= tt < ts and tt >= ts - 0.2)
            held_after = all(gg == g for tt, gg in gears if ts <= tt < ts + 0.2)
            if held_before and held_after:
                out.append((ts, prev, g))
            prev = g
            prev_ts = ts
    return out


def analyse_shift(shift_ts, frames_121):
    """Given a shift timestamp and the 121 series, find the cut window and
    report pre / in-cut / post 121_A values."""
    t_lo = shift_ts - WINDOW_S
    t_hi = shift_ts + WINDOW_S
    window = [(ts, a, cut, blip) for (ts, a, cut, blip) in frames_121 if t_lo <= ts <= t_hi]
    if not window:
        return None

    # Frames where the cut bit is HIGH
    in_cut = [(ts, a) for ts, a, cut, blip in window if cut]
    if not in_cut:
        return None
    cut_start = in_cut[0][0]
    cut_end = in_cut[-1][0]

    # Pre-cut: last few frames before cut_start
    pre_cut = [(ts, a) for ts, a, cut, blip in window if ts < cut_start][-FRAMES_ADJACENT:]
    # Post-cut: first few frames after cut_end
    post_cut = [(ts, a) for ts, a, cut, blip in window if ts > cut_end][:FRAMES_ADJACENT]

    return {
        "shift_ts": shift_ts,
        "cut_frames": [a for _, a in in_cut],
        "pre_frames": [a for _, a in pre_cut],
        "post_frames": [a for _, a in post_cut],
    }


def main():
    up_deltas = []
    down_deltas = []
    all_stats = []
    for path in sorted(SESSION.glob("moving-*.log")):
        frames_121 = collect(path)
        shifts = gear_transitions(path)
        for shift_ts, fg, tg in shifts:
            if fg == 0 or tg == 0:
                continue  # skip N-engagements
            result = analyse_shift(shift_ts, frames_121)
            if result is None or not result["pre_frames"] or not result["post_frames"]:
                continue
            pre_avg = statistics.mean(result["pre_frames"])
            post_avg = statistics.mean(result["post_frames"])
            cut_avg = statistics.mean(result["cut_frames"])
            cut_min = min(result["cut_frames"])

            direction = "up" if tg > fg else "down"
            all_stats.append((path.name, shift_ts, fg, tg, direction,
                              pre_avg, cut_avg, cut_min, post_avg,
                              len(result["cut_frames"])))
            if direction == "up":
                up_deltas.append((pre_avg, cut_avg, cut_min, post_avg))
            else:
                down_deltas.append((pre_avg, cut_avg, cut_min, post_avg))

    # Per-shift table
    print(f"# 121_A behavior during shift-cut windows (± {WINDOW_S*1000:.0f} ms)")
    print(f"  {'file':<14} {'shift':<8} {'dir':<4} {'pre μ':>7} {'in-cut μ':>9} {'in-cut min':>10} {'post μ':>7} {'n cut':>6}")
    for name, ts, fg, tg, direction, pre, cut, cmin, post, n in all_stats:
        print(f"  {name:<14} {fg}→{tg:<3}   {direction:<4} {pre:+7.1f} {cut:+9.1f} {cmin:+10.1f} {post:+7.1f} {n:>6}")

    # Aggregates
    print(f"\n# Aggregate deltas ({len(up_deltas)} upshifts, {len(down_deltas)} downshifts)")

    def dump(label, data):
        if not data:
            return
        pre = [d[0] for d in data]
        cut = [d[1] for d in data]
        cut_min = [d[2] for d in data]
        post = [d[3] for d in data]
        pre_to_cut = [c - p for p, c, _, _ in data]
        pre_to_min = [m - p for p, _, m, _ in data]
        print(f"\n  {label}:")
        print(f"    pre  μ = {statistics.mean(pre):+6.1f}  (median {statistics.median(pre):+6.1f})")
        print(f"    cut  μ = {statistics.mean(cut):+6.1f}  (median {statistics.median(cut):+6.1f})")
        print(f"    cut-min μ = {statistics.mean(cut_min):+6.1f}  (worst case per shift)")
        print(f"    post μ = {statistics.mean(post):+6.1f}  (median {statistics.median(post):+6.1f})")
        print(f"    Δ (cut-avg − pre) mean = {statistics.mean(pre_to_cut):+6.1f}  → cut moves torque DOWN by this amount on avg")
        print(f"    Δ (cut-min − pre) mean = {statistics.mean(pre_to_min):+6.1f}  → worst-case cut moves torque DOWN by this")

    dump("Upshifts (drive-into-drive, brief cut only)", up_deltas)
    dump("Downshifts (drive-into-drive, cut + auto-blip)", down_deltas)


if __name__ == "__main__":
    sys.exit(main())
