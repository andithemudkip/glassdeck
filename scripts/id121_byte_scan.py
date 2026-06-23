#!/usr/bin/env python3
"""id121_byte_scan.py — value-distribution analysis of `121` D0..D6 per setpoint.

The engine_load_scan.py per-setpoint means for `121` D0..D3 showed
non-monotonic RPM-banded shapes (D0: 6.4 / 9.6 / 0 / 0 / 19.1 across B1..B5;
D2 dropping to near-zero mid-range; etc.).  Means alone are misleading on a
~50-frame window — a byte that's "0 most of the time, 50 occasionally" has
the same mean as a byte that's "10 always."

This script reports, for each `121` byte (D0..D6, D7 excluded as cycle hash)
and each setpoint/idle window:

  - n distinct values seen
  - top-3 values by frequency, with percentages
  - min / max / range

Windows include the RPM setpoints (B1..B5) and the idle reference windows
already used in idle_load_compare.py, so we can compare RPM-banded behaviour
against neutral-idle and in-gear-idle baselines in the same capture.
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

SKIP_S = 3.0
SETPOINT_LEN_S = 8.0


def parse_events(path):
    out = {}
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            out.setdefault(r["label"], t)
    return out


def parse_log(path, ids):
    out = {arb: [] for arb in ids}
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            arb = m.group(2).upper()
            if arb not in out:
                continue
            hex_data = m.group(3)
            if len(hex_data) != 16:
                continue
            out[arb].append((float(m.group(1)), bytes.fromhex(hex_data)))
    return out


def window(frames, t0, t1):
    return [(ts, d) for ts, d in frames if t0 <= ts <= t1]


def fmt_top(values, k=3):
    """Top-k value/percentage entries, e.g. '0x12(45%) 0x34(30%) 0x56(15%)'."""
    if not values:
        return "—"
    c = Counter(values)
    n = len(values)
    top = c.most_common(k)
    parts = [f"0x{v:02X}({100 * cnt / n:2.0f}%)" for v, cnt in top]
    rest = n - sum(cnt for _, cnt in top)
    if rest > 0:
        parts.append(f"+{len(c) - k}v({100 * rest / n:2.0f}%)")
    return " ".join(parts)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--session", default="logs/2026-06-23-engine-driven-rear-spin")
    args = p.parse_args()

    session = REPO_ROOT / args.session
    events = parse_events(session / "events.csv")
    frames = parse_log(session / "capture.log", {"120", "121"})

    # Windows: idle references + 5 setpoints.
    idle_set = events["idle settled (neutral)"]
    phase_a  = events["Phase A — idle in 1st"]
    b1       = events["B1 — ~2000 RPM in 1st"]
    b2       = events["B2 — ~2500 RPM in 1st"]
    b3       = events["B3 — ~3500 RPM in 1st"]
    b4       = events["B4 — ~4500 RPM in 1st"]
    b5       = events["B5 — ~5500 RPM in 1st"]
    phase_c  = events["Phase C — idle in 1st (post-sweep)"]
    to_n     = events["back to neutral"]
    kill     = events["kill switch"]

    windows = [
        ("idle-neutral (pre-sweep)",      idle_set + SKIP_S,   phase_a - 1.0),
        ("idle 1st (Phase A)",            phase_a + SKIP_S,    b1 - 1.0),
        ("B1 — ~2000 RPM",                b1 + SKIP_S,         b1 + SKIP_S + SETPOINT_LEN_S),
        ("B2 — ~2500 RPM",                b2 + SKIP_S,         b2 + SKIP_S + SETPOINT_LEN_S),
        ("B3 — ~3500 RPM",                b3 + SKIP_S,         b3 + SKIP_S + SETPOINT_LEN_S),
        ("B4 — ~4500 RPM",                b4 + SKIP_S,         b4 + SKIP_S + SETPOINT_LEN_S),
        ("B5 — ~5500 RPM",                b5 + SKIP_S,         b5 + SKIP_S + SETPOINT_LEN_S),
        ("idle 1st (Phase C post-sweep)", phase_c + SKIP_S,    to_n - 1.0),
        ("idle-neutral (return)",         to_n + SKIP_S,       kill - 1.0),
    ]

    print(f"# `121` byte value-distribution scan — {args.session}\n")

    # RPM mean per window for context.
    rpm_by_window = {}
    for name, t0, t1 in windows:
        rpm_frames = window(frames["120"], t0, t1)
        rpms = [(d[0] << 8) | d[1] for _, d in rpm_frames]
        rpm_by_window[name] = sum(rpms) / len(rpms) if rpms else 0

    # Per-byte tables.
    for bi in range(7):
        print(f"\n## `121` D{bi}\n")
        print(f"  {'window':<32}  {'RPM':>5}  {'n':>5}  {'#vals':>5}  {'range':>14}  top values")
        for name, t0, t1 in windows:
            win = window(frames["121"], t0, t1)
            if not win:
                continue
            vals = [d[bi] for _, d in win]
            rpm = rpm_by_window[name]
            n = len(vals)
            distinct = len(set(vals))
            rng = f"0x{min(vals):02X}..0x{max(vals):02X}"
            top = fmt_top(vals)
            print(f"  {name:<32}  {rpm:5.0f}  {n:5d}  {distinct:5d}  {rng:>14}  {top}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
