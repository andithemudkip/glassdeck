#!/usr/bin/env python3
"""front_wheel_decay_mark.py — pin the front wheel LSB via dash 3->0 transitions.

Reads a hand-spin session where the rider pressed `b` the moment the dash
flipped from 3 km/h to 0 on each decay tail. The raw uint16 at the moment
of the dash flip equals (3.0 / LSB), giving a clean per-push anchor.

Reaction-time correction: the rider sees the dash flip then presses `b`
~200-300 ms later, by which time the raw value has dropped further. We
correct by looking at the raw uint16 a quarter-second before each mark
and also report the decay rate so the rider's actual reaction time can be
backed out if it differs.

Mis-press handling: if two `b` marks are within 2 s of each other, treat
only the LATER one as the answer (per user note: pressed it again on the
last round when the dash actually flipped).

Usage:
  python scripts/front_wheel_decay_mark.py
"""

from __future__ import annotations

import csv
import datetime as dt
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSION = REPO_ROOT / "logs" / "2026-06-24-front-wheel-decay-mark"
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

DASH_CUTOFF_KMH = 3.0           # threshold at which dash flips between 0 and 3
REACTION_TIME_S = 0.25          # typical visual reaction
MERGE_WINDOW_S = 2.0            # marks within this gap are the same push


def parse_log(path):
    frames = []
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            ts = float(m.group(1))
            arb = m.group(2).upper()
            hex_data = m.group(3)
            if len(hex_data) % 2:
                continue
            data = bytes.fromhex(hex_data)
            if len(data) != 8:
                continue
            frames.append((ts, arb, data))
    return frames


def parse_b_marks(path):
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            if r["key"] != "beam":
                continue
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            rows.append(t)
    rows.sort()
    return rows


def merge_misperss(marks, window=MERGE_WINDOW_S):
    """If two marks are within `window`, keep only the later one."""
    if not marks:
        return marks
    out = [marks[0]]
    for t in marks[1:]:
        if t - out[-1] < window:
            out[-1] = t      # replace with the corrective press
        else:
            out.append(t)
    return out


def raw_at(frames_12d, t, default=0):
    """Return the (D0<<8|D1) of the LAST 12D frame at or before time t."""
    last = default
    for ts, _, d in frames_12d:
        if ts > t:
            break
        last = (d[0] << 8) | d[1]
    return last


def decay_rate_near(frames_12d, t, window_s=1.0):
    """Linear fit of raw u16 over [t - window_s, t]. Returns dRaw/dt (LSB/s)."""
    pts = [(ts, (d[0] << 8) | d[1])
           for ts, _, d in frames_12d
           if t - window_s <= ts <= t]
    if len(pts) < 5:
        return None
    n = len(pts)
    sx = sum(ts for ts, _ in pts)
    sy = sum(y for _, y in pts)
    sxx = sum(ts * ts for ts, _ in pts)
    sxy = sum(ts * y for ts, y in pts)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    return (n * sxy - sx * sy) / denom   # slope (raw LSB per second)


def main():
    frames = parse_log(SESSION / "capture.log")
    frames_12d = [(ts, arb, d) for ts, arb, d in frames if arb == "12D"]
    marks = parse_b_marks(SESSION / "events.csv")
    print(f"# {len(marks)} raw `b` marks; after mis-press merge:")
    marks = merge_misperss(marks)
    print(f"# {len(marks)} push marks\n")

    t0 = frames[0][0]
    print(f"  {'#':>2}  {'t+':>6}  "
          f"{'raw @mark':>10}  {'raw -250ms':>11}  "
          f"{'decay (LSB/s)':>14}  "
          f"{'LSB (lower)':>12}  {'LSB (250ms corr)':>17}  "
          f"{'1/LSB (lower)':>14}  {'1/LSB (corr)':>13}")

    lsb_lower_vals = []   # using raw at mark time
    lsb_corr_vals = []    # using raw at mark - reaction_time
    for i, mt in enumerate(marks):
        raw_at_mark = raw_at(frames_12d, mt)
        raw_before = raw_at(frames_12d, mt - REACTION_TIME_S)
        slope = decay_rate_near(frames_12d, mt, window_s=1.0)
        slope_str = f"{slope:.1f}" if slope is not None else "  —  "

        if raw_at_mark > 0:
            lsb_lower = DASH_CUTOFF_KMH / raw_at_mark
            lsb_lower_vals.append(lsb_lower)
            inv_lower = 1 / lsb_lower
        else:
            lsb_lower = None
            inv_lower = None

        if raw_before > 0:
            lsb_corr = DASH_CUTOFF_KMH / raw_before
            lsb_corr_vals.append(lsb_corr)
            inv_corr = 1 / lsb_corr
        else:
            lsb_corr = None
            inv_corr = None

        lsb_lower_str = f"{lsb_lower:.5f}" if lsb_lower else "—"
        lsb_corr_str = f"{lsb_corr:.5f}" if lsb_corr else "—"
        inv_lower_str = f"{inv_lower:.2f}" if inv_lower else "—"
        inv_corr_str = f"{inv_corr:.2f}" if inv_corr else "—"

        print(f"  {i+1:>2}  {mt-t0:>6.2f}  "
              f"{raw_at_mark:>10}  {raw_before:>11}  "
              f"{slope_str:>14}  "
              f"{lsb_lower_str:>12}  {lsb_corr_str:>17}  "
              f"{inv_lower_str:>14}  {inv_corr_str:>13}")

    # ---------- distribution of low raw values across the whole capture
    print("# Distribution of low raw u16 values on 12D (full capture, raw > 0, < 1000)")
    from collections import Counter
    low_vals = Counter()
    for ts, _, d in frames_12d:
        raw = (d[0] << 8) | d[1]
        if 0 < raw < 1000:
            low_vals[raw] += 1
    for v, c in sorted(low_vals.items())[:30]:
        print(f"  raw = {v:>4}  count = {c}")

    # ---------- decay sequence just before each mark
    print("\n# Last 20 frames before each mark (12D, time relative to mark, raw u16)")
    for i, mt in enumerate(marks):
        print(f"\n  Push #{i+1}:")
        recent = [(ts, (d[0] << 8) | d[1]) for ts, _, d in frames_12d
                  if mt - 3.0 <= ts <= mt + 0.5]
        # Show only frames where raw changes from previous frame
        last_raw = None
        shown = 0
        for ts, raw in recent:
            if raw != last_raw and shown < 25:
                print(f"    t-mark = {ts-mt:+.3f}s  raw = {raw:>4}")
                last_raw = raw
                shown += 1
        if shown == 0:
            print("    (no frames in window)")

    # ---------- diagnostic: when did raw last go non-zero before each mark?
    print("\n# Diagnostic: last non-zero raw before each mark")
    print(f"  {'#':>2}  {'t-of-last-nonzero':>18}  {'lag (s)':>8}  {'last raw':>8}")
    for i, mt in enumerate(marks):
        last_nonzero_ts = None
        last_nonzero_raw = 0
        for ts, _, d in frames_12d:
            if ts > mt:
                break
            raw = (d[0] << 8) | d[1]
            if raw > 0:
                last_nonzero_ts = ts
                last_nonzero_raw = raw
        if last_nonzero_ts is None:
            print(f"  {i+1:>2}  {'(none)':>18}  {'—':>8}  {'—':>8}")
        else:
            lag = mt - last_nonzero_ts
            print(f"  {i+1:>2}  {last_nonzero_ts-t0:>18.3f}  {lag:>8.3f}  {last_nonzero_raw:>8}")

    def stats(vals, name):
        if not vals:
            return
        mean = sum(vals) / len(vals)
        sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        print(f"\n  {name}: mean LSB = {mean:.5f} km/h (1/LSB = {1/mean:.2f}), "
              f"sd = {sd:.5f} (rel {sd/mean*100:.1f}%)")

    stats(lsb_lower_vals, "Lower-bound estimate (no reaction-time correction)")
    stats(lsb_corr_vals,  f"Reaction-time corrected ({int(REACTION_TIME_S*1000)} ms)")

    # ---------- candidate LSB comparison
    if lsb_corr_vals:
        mean_corr = sum(lsb_corr_vals) / len(lsb_corr_vals)
        inv = 1 / mean_corr
        print(f"\n  Most likely 1/LSB family (corrected): ~{inv:.0f}")
        print(f"\n  Candidate          1/LSB     km/h/LSB    fit residual on this mean")
        for cand in [128, 144, 150, 160, 168, 180, 192, 200, 256]:
            cand_lsb = 1 / cand
            err_kmh = (cand_lsb - mean_corr) * (3.0 / mean_corr)  # in km/h at 3 km/h
            print(f"  1/{cand:>3} ({cand_lsb:.5f})    {cand:>5}    "
                  f"{cand_lsb:.5f}     Δ = {err_kmh:+.3f} km/h at 3 km/h")

    print("\n  Note: rider reported being 'a tiny bit late' on every press.")
    print("        That means the lower-bound column is biased LOW (raw too small),")
    print("        so the corrected column is the truer estimate. If reaction time was")
    print("        more like 400 ms, the LSB would shift further toward larger 1/LSB.")


if __name__ == "__main__":
    main()
