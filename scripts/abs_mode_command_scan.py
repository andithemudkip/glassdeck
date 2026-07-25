#!/usr/bin/env python3
"""abs_mode_command_scan.py — hunt for a command frame/burst/hold-bit that
could explain the ROAD/SUPERMOTO toggle beyond the two known state bits.

abs_mode_scan.py established the state bits (12A D2 b1, 450 D4 b7) via
per-window majorities on the 6 slow-decay IDs. It is blind to:

  1. IDs that only appear near a toggle mark (UDS/ISO-TP, one-shot command).
  2. Byte values that only appear in hold windows (bursts on existing IDs).
  3. Bits that are elevated across the 3s hold and quiet otherwise, on any ID.
  4. Bits that fire briefly within a ±0.5s burst window around each mark.

Bytes with high value-entropy (counters, hashes) are excluded from (2) —
a slow counter hits any given value only in one contiguous slice of the
capture and produces spurious "value only appears in hold X" hits.

Usage:
    python scripts/abs_mode_command_scan.py logs/2026-07-24-abs-mode-toggle-3
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# Cluster commits the toggle ~3.0-3.5s after the SET-hold-start mark.
# Rider was told to hold 3-5s. Use 3.0 to isolate the "button definitely
# held, pre-flip" window; beyond 3s the state has flipped and rider release
# is uncertain.
HOLD_SECS = 3.0

# Narrow "press instant" window either side of each mark — catches a
# one-shot command sent on press-down.
BURST_SECS = 0.5

# From signal-ride-mode — excluded from hold-active bit hits so their
# pattern doesn't clutter the output.
KNOWN_STATE_BITS = {("12A", 2, 1), ("450", 4, 7)}

FRAME_RE = re.compile(r"^\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]+)")


def parse_capture(path):
    frames = []
    with path.open() as f:
        for line in f:
            m = FRAME_RE.match(line)
            if not m:
                continue
            frames.append((float(m.group(1)), m.group(2).upper(), bytes.fromhex(m.group(3))))
    return frames


def parse_events(path):
    marks = []
    with path.open() as f:
        for row in csv.DictReader(f):
            wall = datetime.fromisoformat(row["timestamp_iso"]).timestamp()
            marks.append((wall, row["key"], row["label"]))
    return marks


def in_any(ts, windows):
    return any(s <= ts < e for s, e in windows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session_dir", type=Path)
    args = ap.parse_args()

    session = args.session_dir
    frames = parse_capture(session / "capture.log")
    marks = parse_events(session / "events.csv")

    mode_marks = [m for m in marks if m[1] == "mode"]
    if len(mode_marks) != 4:
        print(f"expected 4 mode marks, got {len(mode_marks)}", file=sys.stderr)
        sys.exit(1)

    baseline_mark = next(m for m in marks if m[1] == "mark")
    mode_ts = [m[0] for m in mode_marks]
    t0 = baseline_mark[0]
    t1 = frames[-1][0]

    hold_windows = [(t, t + HOLD_SECS) for t in mode_ts]
    burst_windows = [(t - BURST_SECS, t + BURST_SECS) for t in mode_ts]
    frames = [f for f in frames if t0 <= f[0] <= t1]

    hold_secs = sum(e - s for s, e in hold_windows)
    burst_secs = sum(e - s for s, e in burst_windows)
    base_secs = (t1 - t0) - hold_secs

    print(f"Analysis range: {t1 - t0:.1f}s  (baseline {base_secs:.1f}s, hold {hold_secs:.1f}s, burst {burst_secs:.1f}s)")
    print(f"Hold windows (mark -> mark+{HOLD_SECS}s):")
    for i, (s, e) in enumerate(hold_windows):
        print(f"  H{i+1}: rel {s - t0:>7.2f} -> {e - t0:>7.2f}")
    print()

    # === (1) Per-ID appearance profile ============================================
    id_base = Counter()
    id_hold = Counter()
    id_burst = Counter()
    all_ids = set()
    for ts, can_id, _ in frames:
        all_ids.add(can_id)
        if in_any(ts, hold_windows):
            id_hold[can_id] += 1
        else:
            id_base[can_id] += 1
        if in_any(ts, burst_windows):
            id_burst[can_id] += 1

    print("=== (1) Per-ID appearance profile ===")
    print(f"  {'ID':<6}  {'base':>6}  {'hold':>6}  {'burst':>6}  {'base_hz':>8}  {'hold_hz':>8}  note")
    flagged1 = []
    for can_id in sorted(all_ids):
        b, h, br = id_base[can_id], id_hold[can_id], id_burst[can_id]
        b_hz = b / base_secs if base_secs > 0 else 0
        h_hz = h / hold_secs if hold_secs > 0 else 0
        note = ""
        if b == 0 and h > 0:
            note = "*** hold-only ID"
            flagged1.append(can_id)
        elif b == 0 and br > 0:
            note = "*** burst-only ID"
            flagged1.append(can_id)
        elif h_hz > 2 * b_hz and h >= 4:
            note = "hold-elevated rate"
            flagged1.append(can_id)
        print(f"  {can_id:<6}  {b:>6}  {h:>6}  {br:>6}  {b_hz:>8.2f}  {h_hz:>8.2f}  {note}")
    print()

    # === (2) Per-(ID, byte) rare-value scan ======================================
    hold_bv = defaultdict(lambda: defaultdict(Counter))  # id -> byte -> Counter(val)
    base_bv = defaultdict(lambda: defaultdict(Counter))
    for ts, can_id, payload in frames:
        target = hold_bv if in_any(ts, hold_windows) else base_bv
        for i, b in enumerate(payload):
            target[can_id][i][b] += 1

    # Bytes with high value-entropy (counter, hash) skew this scan — a slow
    # counter is guaranteed to have some value that only appears in one
    # window slice. Filter them out.
    def is_counter_like(can_id, byte_idx):
        combined = Counter()
        combined.update(base_bv[can_id].get(byte_idx, Counter()))
        combined.update(hold_bv[can_id].get(byte_idx, Counter()))
        total = sum(combined.values())
        return total >= 20 and len(combined) > 32

    print("=== (2) Byte values in HOLD windows that are rare/absent in BASELINE ===")
    hits2 = []
    skipped_counters = []
    for can_id in sorted(all_ids):
        for byte_idx, hc in hold_bv[can_id].items():
            if is_counter_like(can_id, byte_idx):
                skipped_counters.append((can_id, byte_idx))
                continue
            bc = base_bv[can_id].get(byte_idx, Counter())
            b_tot = sum(bc.values())
            h_tot = sum(hc.values())
            if h_tot < 4:
                continue
            for val, h_n in hc.items():
                b_n = bc.get(val, 0)
                b_freq = b_n / b_tot if b_tot else 0
                h_freq = h_n / h_tot
                if b_freq < 0.01 and h_freq > 0.1 and h_n >= 3:
                    hits2.append((can_id, byte_idx, val, b_n, b_tot, h_n, h_tot))
    if skipped_counters:
        print(f"  (skipped counter/hash-like bytes: {', '.join(f'{c} D{b}' for c, b in skipped_counters)})")

    if not hits2:
        print("  (none)")
    else:
        print(f"  {'ID':<6}  {'byte':>4}  {'val':>5}  {'base':>12}  {'hold':>12}")
        for can_id, byte_idx, val, b_n, b_tot, h_n, h_tot in hits2:
            print(f"  {can_id:<6}  {byte_idx:>4}  0x{val:02X}   {b_n:>5}/{b_tot:<5}  {h_n:>5}/{h_tot:<5}")
    print()

    # === (3) Hold-active bit scan across ALL IDs =================================
    # Per (ID, byte, bit): ones/total during each of the 4 hold windows, and
    # during baseline. Flag bits that are ~1 across ALL 4 holds and ~0 in
    # baseline (or the inverse).
    per_hold = defaultdict(lambda: [defaultdict(lambda: [0, 0]) for _ in hold_windows])
    per_base = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for ts, can_id, payload in frames:
        hidx = next((i for i, (s, e) in enumerate(hold_windows) if s <= ts < e), None)
        for bidx, byte in enumerate(payload):
            for bit in range(8):
                v = (byte >> bit) & 1
                key = (bidx, bit)
                bucket = per_hold[can_id][hidx][key] if hidx is not None else per_base[can_id][key]
                bucket[0] += v
                bucket[1] += 1

    # Relaxed thresholds: a hold-active bit with edge wobble might not hit
    # >0.9 across every hold. Require elevation (delta vs baseline) rather
    # than absolute purity, consistent across all 4 holds.
    print("=== (3) Bits with elevated 1-frequency across all 4 hold windows vs baseline (or inverse) ===")
    hits3 = []
    for can_id in sorted(all_ids):
        keys = set()
        for hd in per_hold[can_id]:
            keys.update(hd.keys())
        keys.update(per_base[can_id].keys())
        for key in sorted(keys):
            bidx, bit = key
            b_ones, b_tot = per_base[can_id].get(key, [0, 0])
            if b_tot < 20:
                continue
            b_freq = b_ones / b_tot
            hf = []
            for hd in per_hold[can_id]:
                ones, total = hd.get(key, [0, 0])
                hf.append(ones / total if total >= 2 else None)
            if any(f is None for f in hf):
                continue
            if (can_id, bidx, bit) in KNOWN_STATE_BITS:
                continue
            if all(f - b_freq > 0.3 for f in hf):
                hits3.append((can_id, bidx, bit, "HIGH-in-hold", b_freq, hf))
            elif all(b_freq - f > 0.3 for f in hf):
                hits3.append((can_id, bidx, bit, "LOW-in-hold", b_freq, hf))

    if not hits3:
        print("  (none)")
    else:
        print(f"  {'ID':<6}  {'byte':>4}  {'bit':>3}  {'kind':<13}  {'base':>6}  holds")
        for can_id, bidx, bit, kind, bf, hf in hits3:
            hf_s = " ".join(f"{f:.2f}" for f in hf)
            print(f"  {can_id:<6}  {bidx:>4}  {bit:>3}  {kind:<13}  {bf:>6.3f}  [{hf_s}]")
    print()

    # === (4) Burst-active bit scan (±0.5s around each mark) =====================
    per_burst = defaultdict(lambda: [defaultdict(lambda: [0, 0]) for _ in burst_windows])
    for ts, can_id, payload in frames:
        bidx_win = next((i for i, (s, e) in enumerate(burst_windows) if s <= ts < e), None)
        if bidx_win is None:
            continue
        for bidx, byte in enumerate(payload):
            for bit in range(8):
                v = (byte >> bit) & 1
                per_burst[can_id][bidx_win][(bidx, bit)][0] += v
                per_burst[can_id][bidx_win][(bidx, bit)][1] += 1

    print("=== (4) Bits with elevated 1-frequency in the ±0.5s burst around each mark ===")
    hits4 = []
    for can_id in sorted(all_ids):
        keys = set()
        for bd in per_burst[can_id]:
            keys.update(bd.keys())
        for key in sorted(keys):
            bidx, bit = key
            b_ones, b_tot = per_base[can_id].get(key, [0, 0])
            if b_tot < 20:
                continue
            b_freq = b_ones / b_tot
            bf_win = []
            for bd in per_burst[can_id]:
                ones, total = bd.get(key, [0, 0])
                bf_win.append(ones / total if total >= 2 else None)
            if any(f is None for f in bf_win):
                continue
            if (can_id, bidx, bit) in KNOWN_STATE_BITS:
                continue
            if all(f - b_freq > 0.3 for f in bf_win):
                hits4.append((can_id, bidx, bit, "HIGH-in-burst", b_freq, bf_win))
            elif all(b_freq - f > 0.3 for f in bf_win):
                hits4.append((can_id, bidx, bit, "LOW-in-burst", b_freq, bf_win))

    if not hits4:
        print("  (none)")
    else:
        print(f"  {'ID':<6}  {'byte':>4}  {'bit':>3}  {'kind':<14}  {'base':>6}  bursts")
        for can_id, bidx, bit, kind, bf, bw in hits4:
            bw_s = " ".join(f"{f:.2f}" for f in bw)
            print(f"  {can_id:<6}  {bidx:>4}  {bit:>3}  {kind:<14}  {bf:>6.3f}  [{bw_s}]")
    print()

    print(f"Summary: {len(flagged1)} ID-profile flags, {len(hits2)} rare-value hits, "
          f"{len(hits3)} hold-active bit hits, {len(hits4)} burst-active bit hits")


if __name__ == "__main__":
    main()
