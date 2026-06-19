#!/usr/bin/env python3
"""kill_switch_scan.py — find the CAN bit that tracks the kill switch.

Partitions a kill-switch-toggle capture into the 7 toggle windows
(start-state, then six post-toggle windows), and for each (ID, byte, bit)
checks whether the dominant value alternates RUN/STOP/RUN/STOP/...
in lockstep with the toggle sequence.

Procedure assumed (matches docs/experiments/2026-06-18-kill-switch-toggle.md):
  generic-mark "mark" = key-on; kill starts in RUN.
  Six "kill" marks → seven windows alternating RUN, STOP, RUN, STOP, RUN, STOP, RUN.
  The first window's tail is steady-state RUN (drop the 25 s dash self-test head).
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
TRIM_HEAD_S = 0.30    # drop 300 ms after each toggle (debounce / propagation)


def parse_events(path: Path):
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            rows.append((t, r["key"], r["label"]))
    key_on = next(t for t, _, lab in rows if lab == "generic mark")
    kills = [t for t, _, lab in rows if lab == "kill switch"]
    return key_on, kills


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


def build_windows(key_on: float, kills: list[float], last_ts: float):
    """Return list of (label, state, t0, t1) — state in {'RUN','STOP'}."""
    boundaries = [key_on + SETTLE_HEAD_S] + kills + [last_ts]
    windows = []
    states = ["RUN", "STOP", "RUN", "STOP", "RUN", "STOP", "RUN"]
    for i, state in enumerate(states):
        t0 = boundaries[i] + (TRIM_HEAD_S if i > 0 else 0.0)
        t1 = boundaries[i + 1] - (TRIM_TAIL_S if i < len(states) - 1 else 0.0)
        windows.append((f"W{i}", state, t0, t1))
    return windows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--session",
        default="logs/2026-06-19-kill-switch-toggle",
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
    key_on, kills = parse_events(session / "events.csv")
    if len(kills) != 6:
        print(f"warning: expected 6 kill marks, got {len(kills)}", file=sys.stderr)

    frames = parse_log(session / "capture.log")
    last_ts = frames[-1][0]
    windows = build_windows(key_on, kills, last_ts)

    print("# Windows (state assumes kill starts RUN; toggles alternate)")
    print(f"{'win':>3}  {'state':>5}  {'t0':>10}  {'t1':>10}  {'dur_s':>6}  frames")
    win_frames = []
    for label, state, t0, t1 in windows:
        wf = [(ts, arb, b) for ts, arb, b in frames if t0 <= ts < t1]
        win_frames.append(wf)
        print(f"{label:>3}  {state:>5}  {t0:>10.2f}  {t1:>10.2f}  {t1-t0:>6.2f}  {len(wf)}")
    print()

    all_ids = sorted({arb for _, arb, _ in frames})
    states = [w[1] for w in windows]
    run_idx = [i for i, s in enumerate(states) if s == "RUN"]
    stop_idx = [i for i, s in enumerate(states) if s == "STOP"]

    print("# Bits whose dominant value alternates RUN/STOP across all 7 windows")
    print(f"  (per-window purity >= {args.purity:.2f}, RUN-mode != STOP-mode in every window)")
    print(f"{'ID':>4}  {'B':>1}  {'bit':>3}  {'RUN':>3}  {'STOP':>4}  per-window (W0..W6)")

    hits = []
    for arb in all_ids:
        for bidx in range(8):
            # collect bit values per window
            per_win_bits = []
            for wf in win_frames:
                bits = [(b[bidx] >> 0) & 1 for _, a, b in wf if a == arb]  # placeholder
                per_win_bits.append(bits)
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
                run_modes = {modes[i] for i in run_idx}
                stop_modes = {modes[i] for i in stop_idx}
                if len(run_modes) != 1 or len(stop_modes) != 1:
                    continue
                run_v = next(iter(run_modes))
                stop_v = next(iter(stop_modes))
                if run_v == stop_v:
                    continue
                pattern = "".join(str(m) for m in modes)
                purs = ",".join(f"{p:.2f}" for p in purities)
                print(f"{arb:>4}  {bidx:>1}  {bit:>3}  {run_v:>3}  {stop_v:>4}  {pattern}  purities=[{purs}]")
                hits.append((arb, bidx, bit, run_v, stop_v, pattern, purities))
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
                run_vals = {per_win_modes[i][0] for i in run_idx}
                stop_vals = {per_win_modes[i][0] for i in stop_idx}
                if len(run_vals) == 1 and len(stop_vals) == 1 and run_vals != stop_vals:
                    purs = ",".join(f"{p:.2f}" for _, p in per_win_modes)
                    seq = ",".join(f"0x{v:02X}" for v, _ in per_win_modes)
                    print(f"{arb}[{bidx}]  RUN=0x{next(iter(run_vals)):02X}  "
                          f"STOP=0x{next(iter(stop_vals)):02X}  seq={seq}  purities=[{purs}]")

    # Always print the targeted KTM check
    print()
    print("# Targeted check: 120 D3 bit 4 (KTM hypothesis)")
    for label, state, t0, t1 in windows:
        wf = [(ts, arb, b) for ts, arb, b in frames if t0 <= ts < t1 and arb == "120"]
        vals = [(b[3] >> 4) & 1 for _, _, b in wf]
        d3_bytes = Counter(b[3] for _, _, b in wf).most_common(3)
        if vals:
            ones = sum(vals)
            zeros = len(vals) - ones
            print(f"  {label} {state:>4}: bit4 0s={zeros}  1s={ones}  D3 top={d3_bytes}")
        else:
            print(f"  {label} {state:>4}: no frames")

    return 0


if __name__ == "__main__":
    sys.exit(main())
