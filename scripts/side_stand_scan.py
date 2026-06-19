#!/usr/bin/env python3
"""side_stand_scan.py — find the CAN bit that tracks the side-stand switch.

Partitions a side-stand-toggle capture into the 7 toggle windows
(start-state, then six post-toggle windows), and for each (ID, byte, bit)
checks whether the dominant value alternates DOWN/UP/DOWN/UP/...
in lockstep with the toggle sequence.

Procedure assumed (matches docs/experiments/2026-06-19-side-stand-toggle.md):
  generic-mark "mark" = key-on; stand starts DOWN.
  Six `j` marks → seven windows alternating DOWN, UP, DOWN, UP, DOWN, UP, DOWN.
  The first window's tail is steady-state DOWN (drop the 25 s dash self-test head).
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

SETTLE_HEAD_S = 25.0  # drop first 25 s of window 0 (dash self-test)
TRIM_TAIL_S = 0.30    # drop 300 ms before each toggle (rider hand pre-flick)
TRIM_HEAD_S = 1.20    # drop 1.2 s after each toggle. Press-to-flip is 0.6 – 1.0 s
                      # but that is rider-press → stand-travel-complete time, not
                      # bus latency: the rider keys `j` at the moment of intent to
                      # flick the stand, and physical travel is what takes ~1 s.
                      # The trim just clears those stale-state frames before the
                      # steady-state purity check.


def parse_events(path: Path):
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            rows.append((t, r["key"], r["label"]))
    key_on = next(t for t, _, lab in rows if lab == "generic mark")
    js = [t for t, k, _ in rows if k == "j"]
    return key_on, js


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


def build_windows(key_on: float, toggles: list[float], last_ts: float):
    """Return list of (label, state, t0, t1) — state in {'DOWN','UP'}."""
    boundaries = [key_on + SETTLE_HEAD_S] + toggles + [last_ts]
    windows = []
    states = ["DOWN", "UP", "DOWN", "UP", "DOWN", "UP", "DOWN"]
    for i, state in enumerate(states):
        t0 = boundaries[i] + (TRIM_HEAD_S if i > 0 else 0.0)
        t1 = boundaries[i + 1] - (TRIM_TAIL_S if i < len(states) - 1 else 0.0)
        windows.append((f"W{i}", state, t0, t1))
    return windows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--session",
        default="logs/2026-06-19-side-stand-toggle",
        help="Path to capture session directory (relative to repo root).",
    )
    p.add_argument(
        "--purity",
        type=float,
        default=0.95,
        help="Minimum per-window bit purity (dominant fraction) to count as clean.",
    )
    args = p.parse_args()

    session = REPO_ROOT / args.session
    key_on, toggles = parse_events(session / "events.csv")
    if len(toggles) != 6:
        print(f"warning: expected 6 `j` marks, got {len(toggles)}", file=sys.stderr)

    frames = parse_log(session / "capture.log")
    last_ts = frames[-1][0]
    windows = build_windows(key_on, toggles, last_ts)

    print("# Windows (state assumes stand starts DOWN; toggles alternate)")
    print(f"{'win':>3}  {'state':>5}  {'t0':>10}  {'t1':>10}  {'dur_s':>6}  frames")
    win_frames = []
    for label, state, t0, t1 in windows:
        wf = [(ts, arb, b) for ts, arb, b in frames if t0 <= ts < t1]
        win_frames.append(wf)
        print(f"{label:>3}  {state:>5}  {t0:>10.2f}  {t1:>10.2f}  {t1-t0:>6.2f}  {len(wf)}")
    print()

    all_ids = sorted({arb for _, arb, _ in frames})
    states = [w[1] for w in windows]
    down_idx = [i for i, s in enumerate(states) if s == "DOWN"]
    up_idx = [i for i, s in enumerate(states) if s == "UP"]

    print("# Bits whose dominant value alternates DOWN/UP across all 7 windows")
    print(f"  (per-window purity >= {args.purity:.2f}, DOWN-mode != UP-mode in every window)")
    print(f"{'ID':>4}  {'B':>1}  {'bit':>3}  {'DOWN':>4}  {'UP':>2}  per-window (W0..W6)")

    hits = []
    for arb in all_ids:
        for bidx in range(8):
            for bit in range(8):
                modes = []
                purities = []
                ok = True
                for wf in win_frames:
                    vals = [(b[bidx] >> bit) & 1 for _, a, b in wf if a == arb]
                    if not vals:
                        ok = False
                        break
                    ones = sum(vals)
                    zeros = len(vals) - ones
                    if ones >= zeros:
                        mode, purity = 1, ones / len(vals)
                    else:
                        mode, purity = 0, zeros / len(vals)
                    modes.append(mode)
                    purities.append(purity)
                    if purity < args.purity:
                        ok = False
                if not ok:
                    continue
                down_modes = {modes[i] for i in down_idx}
                up_modes = {modes[i] for i in up_idx}
                if len(down_modes) != 1 or len(up_modes) != 1:
                    continue
                down_v = next(iter(down_modes))
                up_v = next(iter(up_modes))
                if down_v == up_v:
                    continue
                pattern = "".join(str(m) for m in modes)
                purs = ",".join(f"{p:.2f}" for p in purities)
                print(f"{arb:>4}  {bidx:>1}  {bit:>3}  {down_v:>4}  {up_v:>2}  {pattern}  purities=[{purs}]")
                hits.append((arb, bidx, bit, down_v, up_v, pattern, purities))
    print()
    if not hits:
        print("# No clean bit found — falling back to whole-byte dominant-value scan")
        for arb in all_ids:
            for bidx in range(8):
                per_win_modes = []
                ok = True
                for wf in win_frames:
                    vals = [b[bidx] for _, a, b in wf if a == arb]
                    if not vals:
                        ok = False
                        break
                    mode_v, mode_n = Counter(vals).most_common(1)[0]
                    purity = mode_n / len(vals)
                    per_win_modes.append((mode_v, purity))
                if not ok:
                    continue
                down_vals = {per_win_modes[i][0] for i in down_idx}
                up_vals = {per_win_modes[i][0] for i in up_idx}
                if len(down_vals) == 1 and len(up_vals) == 1 and down_vals != up_vals:
                    purs = ",".join(f"{p:.2f}" for _, p in per_win_modes)
                    seq = ",".join(f"0x{v:02X}" for v, _ in per_win_modes)
                    print(f"{arb}[{bidx}]  DOWN=0x{next(iter(down_vals)):02X}  "
                          f"UP=0x{next(iter(up_vals)):02X}  seq={seq}  purities=[{purs}]")

    # Targeted KTM check
    print()
    print("# Targeted check: 540 D4 bit 0 (KTM hypothesis)")
    for label, state, t0, t1 in windows:
        wf = [(ts, arb, b) for ts, arb, b in frames if t0 <= ts < t1 and arb == "540"]
        vals = [(b[4] >> 0) & 1 for _, _, b in wf]
        d4_bytes = Counter(b[4] for _, _, b in wf).most_common(3)
        if vals:
            ones = sum(vals)
            zeros = len(vals) - ones
            print(f"  {label} {state:>4}: bit0 0s={zeros}  1s={ones}  D4 top={d4_bytes}")
        else:
            print(f"  {label} {state:>4}: no frames")

    # Best-hit check: 540 D3 byte distribution per window
    print()
    print("# 540 D3 byte distribution per window (the surfaced hit)")
    for label, state, t0, t1 in windows:
        cnt = Counter(b[3] for ts, arb, b in frames if arb == "540" and t0 <= ts < t1)
        formatted = ", ".join(f"0x{v:02X}×{n}" for v, n in cnt.most_common(4))
        print(f"  {label} {state:>4}: {formatted}")

    # Latency: time from each `j` to the first 540 frame with the new bit value
    print()
    print("# Latency: first 540 frame after each `j` whose D3 bit 0 differs from pre-toggle dominant")
    for i, t in enumerate(toggles):
        pre = [(b[3] >> 0) & 1 for ts, arb, b in frames if arb == "540" and t - 2.0 <= ts < t]
        if not pre:
            print(f"  j[{i}] @ +{t-key_on:6.2f} s: no pre-toggle 540 frames")
            continue
        pre_mode, _ = Counter(pre).most_common(1)[0]
        post = [(ts, (b[3] >> 0) & 1) for ts, arb, b in frames if arb == "540" and t <= ts < t + 1.0]
        flip = next(((ts, v) for ts, v in post if v != pre_mode), None)
        if flip is None:
            print(f"  j[{i}] @ +{t-key_on:6.2f} s: pre={pre_mode}  no flip in next 1 s")
        else:
            ts_flip, v_flip = flip
            print(f"  j[{i}] @ +{t-key_on:6.2f} s: pre={pre_mode}  "
                  f"flip to {v_flip} at +{(ts_flip-t)*1000:.0f} ms")

    return 0


if __name__ == "__main__":
    sys.exit(main())
