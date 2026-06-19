#!/usr/bin/env python3
"""clutch_scan.py — find the CAN bit that tracks the clutch lever.

Phase-A capture: bike in neutral, engine off, five slow clutch pumps. We
do not know whether each `c` mark is a single edge (in only) or a paired
in/out; the scan does not depend on it. We just look at which bits in
the always-on payload move during the active window, and rank them by
edge count. A "good" clutch bit should:

  * be static during the settle phase (before the first `c`)
  * flip multiple times during the active window (5 pumps → ≥ 5 edges)
  * settle back to its rest value after the last `c`

Procedure assumed (matches docs/experiments/2026-06-18-gear-cycle-clutch.md
Phase A): generic-mark "mark" = key-on; subsequent `c` marks bracket the
clutch activity.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

SETTLE_HEAD_S = 25.0  # drop dash self-test after key-on
ACTIVE_PAD_S = 2.0    # extend active window 2 s past last `c` for the trailing release


def parse_events(path: Path):
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            rows.append((t, r["key"], r["label"]))
    key_on = next(t for t, _, lab in rows if lab == "generic mark")
    c_marks = [t for t, k, _ in rows if k == "c"]
    return key_on, c_marks


def parse_log(path: Path):
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


def count_transitions(frames, arb_filter, t0, t1):
    """For frames in [t0, t1) of one ID, count per-(byte,bit) transitions.

    Returns dict[(byte,bit)] = (transitions, rest_value, n_frames).
    rest_value is the first observed bit value in the window.
    """
    result = {}
    last = {}
    counts = {}
    rest = {}
    nframes = 0
    for ts, arb, b in frames:
        if arb != arb_filter or not (t0 <= ts < t1):
            continue
        nframes += 1
        for byte in range(8):
            v = b[byte]
            for bit in range(8):
                bv = (v >> bit) & 1
                key = (byte, bit)
                if key not in last:
                    last[key] = bv
                    rest[key] = bv
                    counts[key] = 0
                else:
                    if bv != last[key]:
                        counts[key] += 1
                        last[key] = bv
    for key, c in counts.items():
        result[key] = (c, rest[key], nframes)
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--session",
        default="logs/2026-06-19-gear-cycle-clutch-A-clutch-only",
        help="Path to capture session directory (relative to repo root).",
    )
    p.add_argument(
        "--top",
        type=int,
        default=15,
        help="How many top-ranked (ID, byte, bit) candidates to show.",
    )
    p.add_argument(
        "--exclude-d7",
        action="store_true",
        help="Exclude byte D7 (known checksum/counter — see byte-d7-checksum-hypothesis).",
    )
    args = p.parse_args()

    session = REPO_ROOT / args.session
    key_on, c_marks = parse_events(session / "events.csv")
    if not c_marks:
        print("no `c` marks in events.csv — nothing to scan", file=sys.stderr)
        return 1

    frames = parse_log(session / "capture.log")
    last_ts = frames[-1][0]
    settle_t = key_on + SETTLE_HEAD_S
    active_t0 = c_marks[0]
    active_t1 = min(c_marks[-1] + ACTIVE_PAD_S, last_ts)

    print("# Windows")
    print(f"  key-on       : {key_on:.2f}")
    print(f"  settle ends  : {settle_t:.2f}   (+{SETTLE_HEAD_S:.0f} s after key-on)")
    print(f"  first `c`    : {active_t0:.2f}   (+{active_t0-key_on:.2f} s after key-on)")
    print(f"  last  `c`    : {c_marks[-1]:.2f}   (+{c_marks[-1]-key_on:.2f} s after key-on)")
    print(f"  active ends  : {active_t1:.2f}   (last `c` + {ACTIVE_PAD_S:.0f} s)")
    print(f"  capture ends : {last_ts:.2f}")
    print()
    print(f"# `c` marks: {len(c_marks)}  (relative to key-on)")
    for i, t in enumerate(c_marks):
        print(f"    c[{i}] @ +{t-key_on:.2f} s")
    print()

    all_ids = sorted({arb for _, arb, _ in frames})

    # Per-ID per-bit transition counts in settle window (should be ~0) and active window
    ranked = []  # (active_count, settle_count, arb, byte, bit, rest_in_settle)
    for arb in all_ids:
        settle = count_transitions(frames, arb, settle_t, active_t0)
        active = count_transitions(frames, arb, active_t0, active_t1)
        for (byte, bit), (c_active, rest_active, _) in active.items():
            c_settle, rest_settle, _ = settle.get((byte, bit), (0, rest_active, 0))
            ranked.append((c_active, c_settle, arb, byte, bit, rest_settle))
    if args.exclude_d7:
        ranked = [r for r in ranked if r[3] != 7]
    # Sort: most active transitions, fewest settle transitions
    ranked.sort(key=lambda r: (-r[0], r[1]))

    print(f"# Top {args.top} bits ranked by transitions in active window")
    print(f"  (settle window = {SETTLE_HEAD_S:.0f} s after key-on; active = first `c` to last `c` + {ACTIVE_PAD_S:.0f} s)")
    print(f"{'ID':>4}  {'B':>1}  {'bit':>3}  {'rest':>4}  {'tr_active':>9}  {'tr_settle':>9}")
    for c_act, c_set, arb, byte, bit, rest in ranked[: args.top]:
        if c_act == 0:
            continue
        print(f"{arb:>4}  {byte:>1}  {bit:>3}  {rest:>4}  {c_act:>9}  {c_set:>9}")
    print()

    # KTM hypothesis: 129 D0 bit 3
    print("# Targeted check: 129 D0 bit 3 (KTM hypothesis — clutch lever)")
    print(f"  rest value (during settle): ", end="")
    settle_vals = []
    for ts, arb, b in frames:
        if arb == "129" and settle_t <= ts < active_t0:
            settle_vals.append((b[0] >> 3) & 1)
    if settle_vals:
        ones = sum(settle_vals)
        print(f"0s={len(settle_vals)-ones}  1s={ones}  n={len(settle_vals)}")
    else:
        print("no settle frames")

    # Print every transition timestamp of 129 D0 bit 3 in the active window
    print("\n  transitions in active window (timestamps relative to key-on):")
    last_bit = None
    transitions = []
    for ts, arb, b in frames:
        if arb != "129" or not (active_t0 <= ts < active_t1):
            continue
        bv = (b[0] >> 3) & 1
        if last_bit is None:
            last_bit = bv
            print(f"    {ts-key_on:>7.2f} s  start state = {bv}")
            continue
        if bv != last_bit:
            transitions.append((ts, last_bit, bv))
            last_bit = bv

    # Interleave transitions with `c` marks for visual alignment
    events_combined = []
    for ts, frm, to in transitions:
        events_combined.append((ts, "TRANSITION", f"{frm}->{to}"))
    for i, t in enumerate(c_marks):
        events_combined.append((t, "C-MARK", f"c[{i}]"))
    events_combined.sort()
    for ts, kind, payload in events_combined:
        if not (active_t0 <= ts < active_t1):
            continue
        marker = "*" if kind == "C-MARK" else " "
        print(f"  {marker} {ts-key_on:>7.2f} s  {kind:<10}  {payload}")

    # Also show 129 D0 byte-level distribution per period (rest vs active)
    print()
    print("# 129 D0 byte distribution (top 5 values per window)")
    from collections import Counter
    for label, t0, t1 in [("settle", settle_t, active_t0), ("active", active_t0, active_t1)]:
        cnt = Counter(b[0] for ts, arb, b in frames if arb == "129" and t0 <= ts < t1)
        top = cnt.most_common(5)
        formatted = ", ".join(f"0x{v:02X}×{n}" for v, n in top)
        print(f"  {label:>6}: {formatted}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
