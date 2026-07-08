#!/usr/bin/env python3
"""inventory_ids.py — summarise the unique CAN IDs in a capture session.

Reads `logs/<session>/capture.log` (candump format with host timestamps)
and, optionally, the matching `events.csv` to anchor times against a
named event mark (default: the first `generic mark`, i.e. the spacebar
keystroke convention). Prints one row per arbitration ID with:

  * count                 — number of frames seen
  * first_rel / last_rel  — seconds relative to the anchor mark
  * med_dt / min_dt / max_dt — inter-arrival times in milliseconds
  * classification        — `BOOT-ONLY` (gone within first 10 s and
                            present <30 s total), `continuous`
                            (active across >70% of the post-first-frame
                            span), or `intermittent`.

Host-timestamp dispersion is large because USB-CDC bunches frames — the
median is the load-bearing periodicity figure; min/max reflect host
timestamping jitter, not necessarily real bus jitter (see ADR 0004).

Usage:
    python scripts/inventory_ids.py logs/2026-06-17-key-on-cold-boot
    python scripts/inventory_ids.py <session-dir> --anchor-label "generic mark"
    python scripts/inventory_ids.py <session-dir> --no-anchor   # raw epoch times

Exit code is 0 even if the session is empty; an empty inventory still
prints a one-line summary.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")
# wifi-bridge M4 (ADR 0018) prepends a `# GAP <ms>` marker into the log
# whenever a WS reconnect couldn't be covered by the firmware ring. Log it to
# stderr so an operator scanning inventory output sees the gap without it
# polluting the per-ID table. `# MARK` lines still fall through silently —
# see `--anchor-label` for the events.csv-driven mark path.
GAP_RE = re.compile(r"^#\s*GAP\s+(\d+)")


def find_anchor(events_csv: Path, label: str) -> float | None:
    if not events_csv.exists():
        return None
    with events_csv.open() as f:
        for row in csv.DictReader(f):
            if row["label"] == label:
                return dt.datetime.fromisoformat(row["timestamp_iso"]).timestamp()
    return None


def parse_log(log: Path) -> dict[str, list[float]]:
    ids: dict[str, list[float]] = defaultdict(list)
    with log.open() as f:
        for line in f:
            gm = GAP_RE.match(line)
            if gm is not None:
                sys.stderr.write(f"# GAP {gm.group(1)} ms (unrecovered window in capture)\n")
                continue
            m = LINE_RE.match(line)
            if not m:
                continue
            ids[m.group(2).upper()].append(float(m.group(1)))
    return ids


def classify(first_rel: float, last_rel: float, span: float) -> str:
    duration = last_rel - first_rel
    if last_rel < 10 and duration < 30:
        return "BOOT-ONLY"
    if span > 0 and duration > span * 0.7:
        return "continuous"
    return "intermittent"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("session", type=Path, help="Path to logs/<session>/ directory")
    p.add_argument(
        "--anchor-label",
        default="generic mark",
        help="events.csv label to use as t=0 (default: 'generic mark')",
    )
    p.add_argument(
        "--no-anchor",
        action="store_true",
        help="Print absolute epoch times instead of anchor-relative",
    )
    args = p.parse_args()

    log = args.session / "capture.log"
    events = args.session / "events.csv"
    if not log.exists():
        sys.exit(f"no capture.log under {args.session}")

    ids = parse_log(log)
    total = sum(len(v) for v in ids.values())
    if not ids:
        print(f"{log}: 0 frames, 0 IDs")
        return 0

    anchor = None if args.no_anchor else find_anchor(events, args.anchor_label)
    if anchor is None and not args.no_anchor:
        sys.stderr.write(
            f"warning: no '{args.anchor_label}' in {events}, using absolute times\n"
        )

    first_ts = min(v[0] for v in ids.values())
    last_ts = max(v[-1] for v in ids.values())
    span = last_ts - first_ts

    base = anchor if anchor is not None else 0.0
    print(f"{log}")
    print(f"  total frames: {total}")
    print(f"  unique IDs:   {len(ids)}")
    if anchor is not None:
        print(f"  anchor:       '{args.anchor_label}' @ {anchor:.6f}")
        print(f"  first frame:  {first_ts - anchor:+.3f}s vs anchor")
        print(f"  last frame:   {last_ts - anchor:+.3f}s vs anchor")
    else:
        print(f"  first frame:  t={first_ts:.6f}")
        print(f"  last frame:   t={last_ts:.6f}")
    print(f"  active span:  {span:.2f}s")
    print()

    cols = ("ID", "count", "first_rel", "last_rel", "med_dt_ms", "min_dt_ms", "max_dt_ms", "class")
    print(f"{cols[0]:>4}  {cols[1]:>7}  {cols[2]:>10}  {cols[3]:>10}  {cols[4]:>10}  {cols[5]:>9}  {cols[6]:>9}  {cols[7]}")

    for arb in sorted(ids.keys(), key=lambda k: ids[k][0]):
        ts_list = ids[arb]
        first_rel = ts_list[0] - base
        last_rel = ts_list[-1] - base
        if len(ts_list) > 1:
            diffs = [(ts_list[i + 1] - ts_list[i]) * 1000 for i in range(len(ts_list) - 1)]
            med = statistics.median(diffs)
            mn, mx = min(diffs), max(diffs)
        else:
            med = mn = mx = float("nan")
        cls = classify(ts_list[0] - first_ts, ts_list[-1] - first_ts, span)
        print(
            f"{arb:>4}  {len(ts_list):>7}  {first_rel:>+9.3f}s  {last_rel:>+9.3f}s  "
            f"{med:>10.2f}  {mn:>9.2f}  {mx:>9.2f}  {cls}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
