#!/usr/bin/env python3
"""gear_scan.py — find the CAN field that carries gear position.

Reads a capture session with `gear` / `neutral` event marks bracketing
distinct held-gear windows. Tabulates candidate fields per window —
the KTM hypotheses `129` D0 hi nibble and `540` D3 lo nibble first,
then a broad scan over all (ID, byte, nibble) for any field whose
dominant value differs across windows.

Window model: each window is one inter-mark span, labelled with the
mark that started it. The first window (key-on settle → first gear/n
mark) is the initial neutral baseline. The active span is from the
first gear-action mark to the last frame (or last-mark + pad).

Procedure assumed (matches docs/experiments/2026-06-18-gear-cycle-clutch.md
Phase B): generic-mark "mark" = key-on; subsequent `g` / `n` marks
bracket held-gear windows. Clutch marks (`c`) are ignored — clutch
state isn't visible on this bus (see Phase A null result).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

SETTLE_HEAD_S = 25.0
TRIM_HEAD_S = 0.30   # drop 300 ms after each mark (mechanical settling)
TRIM_TAIL_S = 0.30
TAIL_PAD_S = 3.0     # final window extends 3 s past last mark


def parse_events(path: Path):
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            rows.append((t, r["key"], r["label"]))
    key_on = next(t for t, _, lab in rows if lab == "generic mark")
    # gear-related marks only: g (gear shift) + n (neutral). Drop c (clutch).
    shifts = [(t, k) for t, k, _ in rows if k in ("g", "n", "gear", "neutral")]
    return key_on, shifts


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


def hi_nibble(b: int) -> int:
    return (b >> 4) & 0x0F


def lo_nibble(b: int) -> int:
    return b & 0x0F


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--session",
        default="logs/2026-06-19-gear-cycle-clutch-B-gear-cycle",
        help="Path to capture session directory (relative to repo root).",
    )
    p.add_argument(
        "--purity",
        type=float,
        default=0.80,
        help="Min per-window dominant-value purity to count a field as 'stable in window'.",
    )
    p.add_argument(
        "--min-windows-distinct",
        type=int,
        default=3,
        help="Broad scan: min number of windows whose dominant values are all distinct.",
    )
    args = p.parse_args()

    session = REPO_ROOT / args.session
    key_on, shifts = parse_events(session / "events.csv")
    frames = parse_log(session / "capture.log")
    last_ts = frames[-1][0]

    settle_t = key_on + SETTLE_HEAD_S

    # Build windows. The pre-shift window is [settle_t, first_shift]; each shift opens a new window.
    bounds = [settle_t] + [t for t, _ in shifts] + [last_ts]
    labels = ["W0:pre"] + [f"W{i+1}:{k}@{t-key_on:.1f}s" for i, (t, k) in enumerate(shifts)]
    windows = []
    for i, label in enumerate(labels):
        t0 = bounds[i] + (TRIM_HEAD_S if i > 0 else 0.0)
        t1 = bounds[i + 1] - (TRIM_TAIL_S if i < len(labels) - 1 else 0.0)
        if i == len(labels) - 1:
            t1 = min(bounds[i] + TAIL_PAD_S + (last_ts - bounds[i]), last_ts) - TRIM_TAIL_S
        if t1 <= t0:
            continue
        windows.append((label, t0, t1))

    print("# Windows (each bounded by gear/neutral marks)")
    print(f"{'label':<24}  {'t0_rel':>8}  {'t1_rel':>8}  {'dur_s':>6}  frames")
    win_frames = []
    for label, t0, t1 in windows:
        wf = [(ts, arb, b) for ts, arb, b in frames if t0 <= ts < t1]
        win_frames.append(wf)
        print(f"{label:<24}  {t0-key_on:>8.2f}  {t1-key_on:>8.2f}  {t1-t0:>6.2f}  {len(wf)}")
    print()

    all_ids = sorted({arb for _, arb, _ in frames})

    # --- Targeted KTM hypothesis check ---
    def dominant_nibble(wf, arb, byte, extractor):
        vals = [extractor(b[byte]) for ts, a, b in wf if a == arb]
        if not vals:
            return None, 0.0, 0
        cnt = Counter(vals)
        v, n = cnt.most_common(1)[0]
        return v, n / len(vals), len(vals)

    print("# Targeted KTM hypothesis 1: gear at `129` D0 hi nibble")
    print(f"{'window':<24}  {'mode_val':>8}  {'purity':>7}  {'n':>5}  top3")
    for (label, _, _), wf in zip(windows, win_frames):
        vals = [hi_nibble(b[0]) for ts, a, b in wf if a == "129"]
        if not vals:
            print(f"{label:<24}  -- no frames --")
            continue
        cnt = Counter(vals)
        v, n = cnt.most_common(1)[0]
        top3 = ", ".join(f"0x{vv:X}×{nn}" for vv, nn in cnt.most_common(3))
        print(f"{label:<24}  0x{v:>6X}  {n/len(vals):>7.2%}  {len(vals):>5}  {top3}")
    print()

    print("# Targeted KTM hypothesis 2: gear at `540` D3 lo nibble")
    print(f"{'window':<24}  {'mode_val':>8}  {'purity':>7}  {'n':>5}  top3")
    for (label, _, _), wf in zip(windows, win_frames):
        vals = [lo_nibble(b[3]) for ts, a, b in wf if a == "540"]
        if not vals:
            print(f"{label:<24}  -- no frames --")
            continue
        cnt = Counter(vals)
        v, n = cnt.most_common(1)[0]
        top3 = ", ".join(f"0x{vv:X}×{nn}" for vv, nn in cnt.most_common(3))
        print(f"{label:<24}  0x{v:>6X}  {n/len(vals):>7.2%}  {len(vals):>5}  {top3}")
    print()

    # Also print FULL byte for `540` D3 hi nibble (the LOW-CARD(4) from idle baseline)
    print("# `540` D3 hi nibble per window (does this also move with gear?)")
    print(f"{'window':<24}  {'mode_val':>8}  {'purity':>7}  {'n':>5}  top3")
    for (label, _, _), wf in zip(windows, win_frames):
        vals = [hi_nibble(b[3]) for ts, a, b in wf if a == "540"]
        if not vals:
            print(f"{label:<24}  -- no frames --")
            continue
        cnt = Counter(vals)
        v, n = cnt.most_common(1)[0]
        top3 = ", ".join(f"0x{vv:X}×{nn}" for vv, nn in cnt.most_common(3))
        print(f"{label:<24}  0x{v:>6X}  {n/len(vals):>7.2%}  {len(vals):>5}  {top3}")
    print()

    # --- Broad scan: any (ID, byte, nibble) where dominant value differs across >= N windows ---
    print(f"# Broad scan: (ID, byte, nibble) fields whose dominant values are distinct in >= {args.min_windows_distinct} windows")
    print(f"  (per-window purity >= {args.purity:.2f}; D7 excluded — known checksum)")
    print(f"{'ID':>4}  {'B':>1}  {'half':>4}  {'distinct':>8}  per-window dominant values")
    candidates = []
    for arb in all_ids:
        for byte in range(7):  # exclude D7
            for half_label, extractor in (("hi", hi_nibble), ("lo", lo_nibble)):
                per_win = []
                ok = True
                for wf in win_frames:
                    vals = [extractor(b[byte]) for ts, a, b in wf if a == arb]
                    if not vals:
                        ok = False
                        break
                    cnt = Counter(vals)
                    v, n = cnt.most_common(1)[0]
                    purity = n / len(vals)
                    if purity < args.purity:
                        ok = False
                        break
                    per_win.append(v)
                if not ok:
                    continue
                distinct = len(set(per_win))
                if distinct >= args.min_windows_distinct:
                    seq = "  ".join(f"0x{v:X}" for v in per_win)
                    print(f"{arb:>4}  {byte:>1}  {half_label:>4}  {distinct:>8}  {seq}")
                    candidates.append((arb, byte, half_label, per_win))
    print()

    # Same scan at byte level (no nibble split) — gear might be in the full byte
    print(f"# Broad scan: full bytes whose dominant values are distinct in >= {args.min_windows_distinct} windows")
    print(f"{'ID':>4}  {'B':>1}  {'distinct':>8}  per-window dominant values")
    for arb in all_ids:
        for byte in range(7):
            per_win = []
            ok = True
            for wf in win_frames:
                vals = [b[byte] for ts, a, b in wf if a == arb]
                if not vals:
                    ok = False
                    break
                cnt = Counter(vals)
                v, n = cnt.most_common(1)[0]
                purity = n / len(vals)
                if purity < args.purity:
                    ok = False
                    break
                per_win.append(v)
            if not ok:
                continue
            distinct = len(set(per_win))
            if distinct >= args.min_windows_distinct:
                seq = "  ".join(f"0x{v:02X}" for v in per_win)
                print(f"{arb:>4}  {byte:>1}  {distinct:>8}  {seq}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
