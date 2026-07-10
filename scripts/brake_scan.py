#!/usr/bin/env python3
"""brake_scan.py — hunt front/rear brake signals in a brakes-stationary capture.

Reads a `brakes-stationary` session (see
docs/experiments/2026-07-10-brakes-stationary.md) and, for each
(arb_id, byte), summarises how many distinct values it took in each
labeled phase window:

  BASE   pre-brake baseline (20 s of key-on, hands off)
  FA     Phase A — front pulses (six escalating pulls)
  FB     Phase B — front sustained (12 s hold)
  RC     Phase C — rear pulses
  RD     Phase D — rear sustained
  BE     Phase E — both together

The candidate ranking is: bytes that were FLAT in BASE (n_values ≤ 1)
but MOVED in at least one brake window (n_values ≥ 2). Front-only
candidates additionally require RC/RD flat; rear-only vice-versa;
brake-agnostic candidates move in every brake window.

Usage:
    python scripts/brake_scan.py logs/2026-07-10-brakes-stationary
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from collections import defaultdict
from pathlib import Path

LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

PHASE_WINDOWS = [
    ("BASE", "pre-brake baseline start", 20.0),
    ("FA",   "front pulse 1 gentle (~30 %)", None),   # to end of last front pulse + settle
    ("FA_END", "front pulse 6 hard", 4.0),            # marker used below to close FA
    ("FB",   "front sustained medium (12 s hold start)", 12.0),
    ("RC",   "rear pulse 1 gentle (~30 %)", None),
    ("RC_END", "rear pulse 6 hard", 4.0),
    ("RD",   "rear sustained medium (12 s hold start)", 12.0),
    ("BE",   "both pulse 1 medium", None),
    ("BE_END", "both sustained medium (8 s hold start)", 8.0),
]


def load_events(path: Path) -> dict[str, float]:
    idx: dict[str, float] = {}
    with path.open() as f:
        for row in csv.DictReader(f):
            t = dt.datetime.fromisoformat(row["timestamp_iso"]).timestamp()
            idx[row["label"]] = t
    return idx


def build_windows(events: dict[str, float]) -> dict[str, tuple[float, float]]:
    """Turn the phase-window recipe into concrete (start, end) intervals."""
    out: dict[str, tuple[float, float]] = {}
    # Simple duration-based windows
    for name, label, dur in PHASE_WINDOWS:
        if dur is None or name.endswith("_END"):
            continue
        t0 = events[label]
        out[name] = (t0, t0 + dur)
    # Composite windows: FA = first-front-pulse .. last-front-pulse + 4 s
    out["FA"] = (events["front pulse 1 gentle (~30 %)"], events["front pulse 6 hard"] + 4.0)
    out["RC"] = (events["rear pulse 1 gentle (~30 %)"], events["rear pulse 6 hard"] + 4.0)
    out["BE"] = (events["both pulse 1 medium"], events["both sustained medium (8 s hold start)"] + 8.0)
    return out


def scan_log(log_path: Path, windows: dict[str, tuple[float, float]]):
    """Return {(arb_id, byte_idx): {window_name: set[byte_value]}}."""
    values: dict[tuple[str, int], dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    with log_path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            ts = float(m.group(1))
            arb = m.group(2).upper()
            hex_data = m.group(3)
            if len(hex_data) % 2 or not hex_data:
                continue
            data = bytes.fromhex(hex_data)
            for wname, (t0, t1) in windows.items():
                if t0 <= ts <= t1:
                    for i, b in enumerate(data):
                        values[(arb, i)][wname].add(b)
    return values


def rank_candidates(values, windows):
    """Return rows sorted so front-only candidates come first, then rear-only,
    then all-brake, then any-brake-with-baseline-noise."""
    rows = []
    for (arb, bi), by_window in values.items():
        counts = {w: len(by_window.get(w, set())) for w in windows}
        base = counts.get("BASE", 0)
        fa, fb = counts.get("FA", 0), counts.get("FB", 0)
        rc, rd = counts.get("RC", 0), counts.get("RD", 0)
        be = counts.get("BE", 0)
        front_active = max(fa, fb) >= 2
        rear_active = max(rc, rd) >= 2
        both_active = be >= 2
        # Skip totally flat rows
        if not (front_active or rear_active or both_active):
            continue
        if base <= 1:
            if front_active and not rear_active:
                cls = "FRONT-ONLY"
            elif rear_active and not front_active:
                cls = "REAR-ONLY"
            elif front_active and rear_active:
                cls = "ANY-BRAKE"
            else:
                cls = "BOTH-ONLY"
        else:
            cls = "BASELINE-NOISY"
        rows.append((cls, arb, bi, base, fa, fb, rc, rd, be))
    order = {"FRONT-ONLY": 0, "REAR-ONLY": 1, "ANY-BRAKE": 2, "BOTH-ONLY": 3, "BASELINE-NOISY": 4}
    rows.sort(key=lambda r: (order[r[0]], r[1], r[2]))
    return rows


def sample_values(values, arb, bi, wname, k=6):
    vs = sorted(values.get((arb, bi), {}).get(wname, set()))
    head = ", ".join(f"{v:02X}" for v in vs[:k])
    return head + (f", …(+{len(vs) - k})" if len(vs) > k else "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session", type=Path, help="logs/<date>-brakes-stationary")
    ap.add_argument("--show-values", action="store_true",
                    help="Print the distinct byte values seen in each window per candidate")
    args = ap.parse_args()

    log_path = args.session / "capture.log"
    events_path = args.session / "events.csv"
    if not log_path.is_file():
        print(f"missing {log_path}", file=sys.stderr); return 2
    if not events_path.is_file():
        print(f"missing {events_path}", file=sys.stderr); return 2

    events = load_events(events_path)
    windows = build_windows(events)
    print(f"# windows (rel to capture start)")
    t0 = min(t for t, _ in windows.values())
    for name, (a, b) in sorted(windows.items(), key=lambda kv: kv[1][0]):
        print(f"#   {name:5s} {a - t0:7.2f} → {b - t0:7.2f} s  ({b - a:5.1f} s)")

    values = scan_log(log_path, windows)

    rows = rank_candidates(values, windows)
    print()
    print(f"{'class':15s} {'ID':>3s} {'byte':>4s}   n_distinct: BASE   FA   FB   RC   RD   BE")
    print("-" * 68)
    for cls, arb, bi, base, fa, fb, rc, rd, be in rows:
        print(f"{cls:15s} {arb:>3s} {bi:>4d}   {'':^15s}  {base:>3d}  {fa:>3d}  {fb:>3d}  {rc:>3d}  {rd:>3d}  {be:>3d}")
        if args.show_values:
            for w in ("BASE", "FA", "FB", "RC", "RD", "BE"):
                print(f"    {w}: {sample_values(values, arb, bi, w)}")
    if not rows:
        print("(no bytes moved in any brake window — brake input likely not on this bus)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
