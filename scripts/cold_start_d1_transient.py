#!/usr/bin/env python3
"""cold_start_d1_transient.py — D1 behavior across the engine-start transient.

Reuses 2026-06-17-engine-idle Run 1 (true cold start, engine off → starter
button → engine catches → idle settles) plus Runs 2 and 3 (hot restarts) as
free discriminators against the integrator-vs-lookup question raised by the
2026-07-22 D1 full scan.

Question: does D1 **ramp** from 0 to the coolant-floor value over ~1 s
(consistent with an integrator / running-average of instantaneous fuel or
injection quantity), or does it **pop** essentially instantly (consistent
with a slow-updated lookup table)?

Prints D1(t) at every `540` frame in a ±3 s window around the starter event
(from events.csv) for each run.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS = [
    "2026-06-17-engine-idle-run-1",
    "2026-06-17-engine-idle-run-2",
    "2026-06-17-engine-idle-run-3",
]
LINE_RE_CANDUMP = re.compile(r"\(([\d.]+)\)\s+\S+\s+([0-9A-Fa-f]{3,4})#([0-9A-Fa-f]*)")
LINE_RE_WIFI = re.compile(r"\(([\d.]+)\)\s+t([0-9A-Fa-f]{3})([0-9A-Fa-f])([0-9A-Fa-f]*)")


def parse_frames(path):
    with path.open() as f:
        for line in f:
            m = LINE_RE_WIFI.match(line)
            if m:
                arb = m.group(2).upper()
                length = int(m.group(3), 16)
                hex_data = m.group(4)
                if len(hex_data) < length * 2:
                    continue
                data = bytes.fromhex(hex_data[: length * 2])
                yield float(m.group(1)), arb, data
                continue
            m = LINE_RE_CANDUMP.match(line)
            if m:
                arb = m.group(2).upper()
                # strip trailing "R" flag and whitespace
                hex_data = m.group(3).strip()
                if len(hex_data) % 2:
                    hex_data = hex_data[:-1]
                try:
                    data = bytes.fromhex(hex_data)
                except ValueError:
                    continue
                yield float(m.group(1)), arb, data


def find_starter_ts(events_path):
    """The events.csv 'timestamp_monotonic' is not aligned to log's boot-relative time,
    but the log uses (sec.us) from log-file start. We need to align via the *start*
    row and pick a monotonic offset. Simpler: pick the first 120 frame after which
    RPM rises above 500 → that IS the engine-start moment in the log's own time base.
    Return that timestamp."""
    return None


def find_engine_start(path):
    """Return log-time at which RPM crosses 500."""
    prev_rpm = 0
    for ts, arb, d in parse_frames(path):
        if arb == "120" and len(d) >= 2:
            rpm = (d[0] << 8) | d[1]
            if prev_rpm < 500 and rpm >= 500:
                return ts
            prev_rpm = rpm
    return None


def collect_d1_and_rpm(path, t_lo, t_hi):
    """Return list of (ts, source, value) for D1 (540) and RPM (120) in window."""
    events = []
    for ts, arb, d in parse_frames(path):
        if ts < t_lo:
            continue
        if ts > t_hi:
            break
        if arb == "540" and len(d) >= 7:
            events.append((ts, "D1", d[1], ((d[5] << 8) | d[6]) * 0.1))
        elif arb == "120" and len(d) >= 3:
            rpm = (d[0] << 8) | d[1]
            events.append((ts, "RPM", rpm, d[2]))  # (rpm, throttle)
    return events


def main():
    for run in RUNS:
        log = REPO_ROOT / "logs" / run / "capture.log"
        if not log.exists():
            print(f"MISSING: {log}")
            continue
        t_start = find_engine_start(log)
        if t_start is None:
            print(f"{run}: RPM never crossed 500 — skipping")
            continue
        print(f"\n{'='*70}")
        print(f"{run}")
        print(f"  RPM crossed 500 at log-time {t_start:.3f} s")
        print(f"{'='*70}")
        # collect events in [t_start-2, t_start+5] window
        events = collect_d1_and_rpm(log, t_start - 2.0, t_start + 5.0)
        # interleave in time order for the trace
        print(f"  {'log t':>7}  {'Δ from start':>13}  {'source':>6}  {'value':>6}  {'coolant/thr':>10}")
        for ts, src, v, aux in events:
            marker = ""
            delta = ts - t_start
            if -0.03 < delta < 0.03:
                marker = "  ← engine start"
            if src == "D1":
                print(f"  {ts:7.3f}  {delta:+13.3f}  {'540 D1':>6}  {v:>6}  {aux:>10.1f} °C{marker}")
            else:
                print(f"  {ts:7.3f}  {delta:+13.3f}  {'120':>6}  RPM={v:<5}  thr={aux}{marker}")


if __name__ == "__main__":
    sys.exit(main())
