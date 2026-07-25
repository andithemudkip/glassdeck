#!/usr/bin/env python3
"""abs_mode_scan.py — hunt the ROAD/SUPERMOTO mode bit in an abs-mode-toggle session.

For each of the 5 stable windows (pre-toggle baseline + 4 post-toggle
plateaus), computes the majority value of every bit in every payload
byte of the 6 slow-decay-group IDs. Any bit whose majority alternates
0-1-0-1-0 or 1-0-1-0-1 across the windows is a mode-toggle candidate.

Windows use a settling buffer after each SET-hold-start mark
(SETTLE_SECS below) so the toggle transition itself is excluded — the
dash flips the mode ~3-6 s after the mark (hold duration + release +
dash refresh), so the pre-buffer window is the OLD mode, post-buffer is
the NEW.

Usage:
    python scripts/abs_mode_scan.py logs/2026-07-24-abs-mode-toggle
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SLOW_DECAY_IDS = {"12A", "12D", "12E", "450", "541", "5A0"}
SETTLE_SECS = 6.0

FRAME_RE = re.compile(r"^\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]+)")


def parse_capture(path: Path):
    frames = []
    with path.open() as f:
        for line in f:
            m = FRAME_RE.match(line)
            if not m:
                continue
            ts = float(m.group(1))
            can_id = m.group(2).upper()
            payload = bytes.fromhex(m.group(3))
            frames.append((ts, can_id, payload))
    return frames


def parse_events(path: Path):
    marks = []
    with path.open() as f:
        for row in csv.DictReader(f):
            wall = datetime.fromisoformat(row["timestamp_iso"]).timestamp()
            marks.append((wall, row["key"], row["label"]))
    return marks


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
    mode_ts_wall = [m[0] for m in mode_marks]
    baseline_end_wall = baseline_mark[0]

    capture_end = frames[-1][0]

    # Windows: (label, start_ts, end_ts)
    # Window 0: baseline (post-key-on ... first toggle mark).
    #           This is ROAD (starting mode per rider).
    # Windows 1-4: post-toggle plateau. Start = toggle_mark + SETTLE_SECS,
    #              end = next toggle mark (or capture end for #4).
    windows = [("W0 pre-toggle (ROAD)", baseline_end_wall + SETTLE_SECS, mode_ts_wall[0])]
    for i in range(4):
        start = mode_ts_wall[i] + SETTLE_SECS
        end = mode_ts_wall[i + 1] if i + 1 < 4 else capture_end
        windows.append((f"W{i+1} post-toggle {i+1}", start, end))

    print("Windows:")
    for label, s, e in windows:
        print(f"  {label}: {s:.2f} -> {e:.2f} ({e-s:.1f} s)")
    print()

    # Collect payloads per ID per window.
    per_win_bytes = [defaultdict(list) for _ in windows]  # per_win_bytes[w_idx][id] = list[payload]
    for ts, can_id, payload in frames:
        for i, (_, s, e) in enumerate(windows):
            if s <= ts < e:
                per_win_bytes[i][can_id].append(payload)
                break

    # For each ID, byte, bit: compute per-window majority value.
    # Report bits that alternate 0,1,0,1,0 or 1,0,1,0,1.
    all_ids = set()
    for w in per_win_bytes:
        all_ids.update(w.keys())

    expected_alt = [(0, 1, 0, 1, 0), (1, 0, 1, 0, 1)]

    candidates = []
    for can_id in sorted(all_ids):
        # Payload length assumed constant per ID.
        first_payload = next((p for w in per_win_bytes for p in w[can_id]), None)
        if first_payload is None:
            continue
        payload_len = len(first_payload)

        for byte_idx in range(payload_len):
            for bit in range(8):
                majorities = []
                purities = []
                for w in per_win_bytes:
                    payloads = w[can_id]
                    if not payloads:
                        majorities.append(None)
                        purities.append(None)
                        continue
                    bits = [(p[byte_idx] >> bit) & 1 for p in payloads]
                    ones = sum(bits)
                    n = len(bits)
                    dom = 1 if ones > n / 2 else 0
                    purity = max(ones, n - ones) / n
                    majorities.append(dom)
                    purities.append(purity)

                if None in majorities:
                    continue

                key_in_scope = can_id in SLOW_DECAY_IDS
                pattern = tuple(majorities)
                if pattern in expected_alt:
                    candidates.append((can_id, byte_idx, bit, pattern, purities, key_in_scope))

    # Print slow-decay hits first, then the rest.
    print(f"Candidates that alternate across the 5 windows (settle={SETTLE_SECS}s):")
    print(f"  {'ID':<4}  {'byte':>4}  {'bit':>3}  {'pattern':<20}  min_purity  scope")
    for hit_scope in (True, False):
        for can_id, byte_idx, bit, pattern, purities, in_scope in candidates:
            if in_scope != hit_scope:
                continue
            scope = "slow-decay" if in_scope else "other"
            min_pur = min(purities)
            print(f"  {can_id:<4}  {byte_idx:>4}  {bit:>3}  {str(pattern):<20}  {min_pur:>10.3f}  {scope}")

    print()
    # Spotlight: 12A D1 bit 6 (KTM-adjacent decoder evidence).
    print("Spotlight — 12A D1 bit 6 (per-window majority + purity):")
    for i, w in enumerate(per_win_bytes):
        payloads = w.get("12A", [])
        if not payloads:
            print(f"  W{i}: no frames")
            continue
        bits = [(p[1] >> 6) & 1 for p in payloads]
        ones = sum(bits)
        n = len(bits)
        dom = 1 if ones > n / 2 else 0
        purity = max(ones, n - ones) / n
        print(f"  W{i}: n={n}, ones={ones}, majority={dom}, purity={purity:.3f}")


if __name__ == "__main__":
    main()
