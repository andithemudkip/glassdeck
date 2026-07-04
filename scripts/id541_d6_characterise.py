#!/usr/bin/env python3
"""id541_d6_characterise.py — characterise 541 D6 across all sessions.

The 2026-06-30 corpus sweep flagged 541 D6 as the most-active byte in the bus
(moves in 14/14 sessions, no known-signal correlation passed |r| ≥ 0.9). The
byte was informally tagged "key-on-ramp-counter" in battery_voltage_scan.py
but never properly characterised.

Pulls per-session 541 D6 time-series and prints:
  - per-second bin mean / min / max
  - engine-off vs engine-on contrast
  - first-frame value, time to first non-zero, value at engine-start, etc.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
import statistics as stats
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

SESSIONS = [
    ("idle-1",      "logs/2026-06-17-engine-idle-run-1"),
    ("idle-2",      "logs/2026-06-17-engine-idle-run-2"),
    ("idle-3",      "logs/2026-06-17-engine-idle-run-3"),
    ("cold-boot",   "logs/2026-06-17-key-on-cold-boot"),
    ("clutch-A",    "logs/2026-06-19-gear-cycle-clutch-A-clutch-only"),
    ("gear-B",      "logs/2026-06-19-gear-cycle-clutch-B-gear-cycle"),
    ("kill",        "logs/2026-06-19-kill-switch-toggle"),
    ("stand",       "logs/2026-06-19-side-stand-toggle"),
    ("throttle",    "logs/2026-06-19-throttle-sweep-engine-off"),
    ("paddock",     "logs/2026-06-22-wheel-spin-paddock-stand"),
    ("rear-spin",   "logs/2026-06-23-engine-driven-rear-spin"),
    ("shift-lever", "logs/2026-06-23-shift-lever-vs-clutch"),
    ("decay-mark",  "logs/2026-06-24-front-wheel-decay-mark"),
    ("hand-spin",   "logs/2026-06-24-front-wheel-hand-spin"),
]


def parse_541_d6(path):
    out = []
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m or m.group(2).upper() != "541":
                continue
            hexd = m.group(3)
            if len(hexd) != 16:
                continue
            d = bytes.fromhex(hexd)
            out.append((float(m.group(1)), d[6]))
    return out


def parse_events(path):
    if not path.exists():
        return {"start": None, "kill": None}
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            rows.append({"t": t, "key": r["key"]})
    return {
        "start": next((r["t"] for r in rows if r["key"] == "start"), None),
        "kill": next((r["t"] for r in rows if r["key"] == "kill"), None),
    }


def main():
    print("# 541 D6 — per-session time-series shape\n")
    for key, rel in SESSIONS:
        sess = REPO_ROOT / rel
        series = parse_541_d6(sess / "capture.log")
        if not series:
            continue
        events = parse_events(sess / "events.csv")
        t0 = series[0][0]
        rel_t = [(t - t0, v) for t, v in series]
        # 5-second bin medians
        bins: dict[int, list[int]] = {}
        for t, v in rel_t:
            b = int(t // 5)
            bins.setdefault(b, []).append(v)
        bin_meds = [(b * 5, stats.median(bins[b]), min(bins[b]), max(bins[b]), len(bins[b]))
                    for b in sorted(bins.keys())]

        start_rel = (events["start"] - t0) if events["start"] else None
        kill_rel = (events["kill"] - t0) if events["kill"] else None

        # value at start / kill
        val_at_start = None
        val_at_kill = None
        if start_rel is not None:
            near = [v for t, v in rel_t if abs(t - start_rel) < 0.5]
            val_at_start = stats.median(near) if near else None
        if kill_rel is not None:
            near = [v for t, v in rel_t if abs(t - kill_rel) < 0.5]
            val_at_kill = stats.median(near) if near else None

        # first non-zero
        first_nz = next(((t, v) for t, v in rel_t if v != 0), None)
        # final value
        final_v = rel_t[-1][1]
        final_t = rel_t[-1][0]

        print(f"## {key}")
        print(f"  frames: {len(series)}   duration: {rel_t[-1][0]:.1f} s   "
              f"engine: {'on (starter@%.1fs, kill@%.1fs)' % (start_rel, kill_rel) if start_rel else 'off'}")
        if first_nz:
            print(f"  first non-zero: D6={first_nz[1]} at t={first_nz[0]:.2f} s")
        else:
            print(f"  first non-zero: never")
        if val_at_start is not None:
            print(f"  value at starter press:  D6={val_at_start:.0f}")
        if val_at_kill is not None:
            print(f"  value at kill toggle:    D6={val_at_kill:.0f}")
        print(f"  final value (t={final_t:.1f}s): D6={final_v}")
        print(f"  per 5-s bin: time | median | min | max | n")
        for t_lo, med, lo, hi, n in bin_meds[:20]:
            tag = ""
            if start_rel is not None and t_lo <= start_rel < t_lo + 5:
                tag = " ← starter"
            if kill_rel is not None and t_lo <= kill_rel < t_lo + 5:
                tag = " ← kill"
            print(f"    {t_lo:5.0f}s   {med:6.0f}   {lo:5d}   {hi:5d}   {n:5d}{tag}")
        if len(bin_meds) > 20:
            print(f"    ... ({len(bin_meds) - 20} more bins)")
            t_lo, med, lo, hi, n = bin_meds[-1]
            print(f"    {t_lo:5.0f}s   {med:6.0f}   {lo:5d}   {hi:5d}   {n:5d}  (last bin)")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
