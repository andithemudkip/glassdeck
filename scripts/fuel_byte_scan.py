#!/usr/bin/env python3
"""fuel_byte_scan.py — hunt for a fuel-level byte across all sessions.

Strategy ([[docs/experiments fuel-level hunt]]):
  Fuel level has a distinctive cross-session fingerprint compared to
  every other slow-changing quantity on the bus:
    - LOW within-session variance (minutes of idle barely moves it)
    - HIGH between-session variance (sessions are at different levels)
    - Stair-stepped chronologically with one upward JUMP at the refuel
    - Stable across engine-on vs engine-off (tank level isn't engine state)

  We therefore:
    1. Walk every `logs/<session>/` directory.
    2. Find the most stable "operating" window in each session:
         - engine-on-steady if `120` RPM > 500 was sustained, else
         - engine-off (key-on, RPM=0).
    3. For each candidate (ID, byte) in the slow cohort + already-decoded
       carriers, compute median and std over that window.
    4. Rank bytes by cross_session_std / mean_within_session_std — fuel
       should pop because its within-session value is rock-stable while
       its across-session value moves cleanly.
    5. Print chronological per-session medians for the top N — eyeball
       for the refuel-step shape (small drops with one upward jump).

  Skips bytes we've already attributed (RPM, throttle, coolant, etc.)
  via SKIP_BYTES so the ranking isn't polluted.

  Read-only against logs/. Output to stdout (+ optional CSV via --csv).

Usage:
    python scripts/fuel_byte_scan.py
    python scripts/fuel_byte_scan.py --csv scratch/fuel_scan.csv
    python scripts/fuel_byte_scan.py --top 12
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import statistics
from collections import defaultdict
from pathlib import Path

LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

# All 11 always-on IDs per [[always-on-broadcast-ids]] — fuel could be
# hiding in any of them. We rank within engine-off and engine-on
# sub-populations separately so engine-state bits don't dominate.
CANDIDATE_IDS = (
    "120", "121", "129", "12A", "12D", "12E",
    "450", "540", "541", "5A0", "5B0",
)

# Bytes already attributed elsewhere — skip so they don't crowd the
# ranking. Keep in sync with docs/findings/can/signal-*.md.
SKIP_BYTES: set[tuple[str, int]] = {
    # 120 — rpm + throttle + d7 hash
    ("120", 0), ("120", 1),  # RPM hi/lo
    ("120", 2),              # throttle
    ("120", 7),              # cycle-hash byte (D7, high within-session churn)
    # 121 — twin int16 channels (engine-load-derived)
    ("121", 0), ("121", 1), ("121", 2), ("121", 3),
    # 129 — gear/clutch/shift-failed (whole-byte engine-state churn on D0)
    ("129", 0),
    # 12D — rear wheel speed
    ("12D", 2), ("12D", 5), ("12D", 6),
    # 540 — warmup, side stand, coolant
    ("540", 1), ("540", 3), ("540", 5), ("540", 6),
    # 541 — kill switch byte + engine-on counter
    ("541", 2), ("541", 4),
}

# Engine-on detection from already-known signal.
RPM_ID = "120"


def parse_log(path: Path):
    """Yield (ts, id_hex, payload_bytes) tuples from a candump-format log."""
    with path.open() as f:
        for line in f:
            m = LINE_RE.search(line)
            if not m:
                continue
            ts = float(m.group(1))
            arb = m.group(2).upper()
            payload_hex = m.group(3)
            if len(payload_hex) % 2:
                continue
            payload = bytes.fromhex(payload_hex) if payload_hex else b""
            yield ts, arb, payload


def session_iso_date(session_dir: Path) -> str:
    """Best-effort session datetime for chronological ordering.

    Use the first event row's ISO timestamp if available, else the
    directory name prefix YYYY-MM-DD, else the log mtime."""
    ev = session_dir / "events.csv"
    if ev.exists():
        with ev.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    return row["timestamp_iso"]
                except (KeyError, TypeError):
                    break
    name = session_dir.name
    m = re.match(r"(\d{4}-\d{2}-\d{2})", name)
    if m:
        return m.group(1) + "T00:00:00+00:00"
    log = session_dir / "capture.log"
    if log.exists():
        return dt.datetime.fromtimestamp(log.stat().st_mtime).isoformat()
    return "1970-01-01T00:00:00+00:00"


def find_operating_window(frames: list[tuple[float, str, bytes]]) -> tuple[float, float, str] | None:
    """Pick the longest stable RPM-on window, else fall back to engine-off.

    Returns (t_start, t_end, mode) where mode is 'on' or 'off'. Excludes
    cranking/decay edges by trimming 2 s off either end of an engine-on
    run. Returns None if neither window is usable."""
    if not frames:
        return None
    t0 = frames[0][0]
    t1 = frames[-1][0]

    # RPM samples from 120 D0:D1 BE uint16. Bin into 0.5 s buckets;
    # bucket is "engine on" if median RPM in that bucket > 500.
    rpm_samples: list[tuple[float, int]] = []
    for ts, arb, payload in frames:
        if arb == RPM_ID and len(payload) >= 2:
            rpm = (payload[0] << 8) | payload[1]
            rpm_samples.append((ts, rpm))

    if not rpm_samples:
        # No RPM frames at all — treat the middle 80% as engine-off.
        span = t1 - t0
        return (t0 + 0.1 * span, t1 - 0.1 * span, "off")

    # Find the longest contiguous on-run.
    bucket = 0.5
    by_bucket: dict[int, list[int]] = defaultdict(list)
    for ts, rpm in rpm_samples:
        by_bucket[int((ts - t0) / bucket)].append(rpm)
    states = sorted(by_bucket.items())
    on_run_best: tuple[float, float] | None = None
    cur_start: float | None = None
    cur_end: float | None = None
    for idx, rpms in states:
        on = statistics.median(rpms) > 500
        t_bucket = t0 + idx * bucket
        if on:
            if cur_start is None:
                cur_start = t_bucket
            cur_end = t_bucket + bucket
        else:
            if cur_start is not None and cur_end is not None:
                if on_run_best is None or (cur_end - cur_start) > (on_run_best[1] - on_run_best[0]):
                    on_run_best = (cur_start, cur_end)
            cur_start = None
            cur_end = None
    if cur_start is not None and cur_end is not None:
        if on_run_best is None or (cur_end - cur_start) > (on_run_best[1] - on_run_best[0]):
            on_run_best = (cur_start, cur_end)

    if on_run_best is not None and (on_run_best[1] - on_run_best[0]) >= 15:
        # Trim 2 s off each end to avoid cranking transients / kill ring-down.
        s, e = on_run_best
        return (s + 2.0, e - 2.0, "on")

    # No usable engine-on run — fall back to engine-off (RPM == 0)
    # middle band. Take the 20–80% slice of the session.
    span = t1 - t0
    if span < 5:
        return None
    return (t0 + 0.2 * span, t1 - 0.2 * span, "off")


def collect_byte_stats(
    frames: list[tuple[float, str, bytes]],
    t_start: float,
    t_end: float,
) -> dict[tuple[str, int], tuple[float, float, int]]:
    """For each candidate (ID, byte), return (median, stdev, n) within
    the window."""
    samples: dict[tuple[str, int], list[int]] = defaultdict(list)
    for ts, arb, payload in frames:
        if ts < t_start or ts > t_end:
            continue
        if arb not in CANDIDATE_IDS:
            continue
        for i, b in enumerate(payload):
            if (arb, i) in SKIP_BYTES:
                continue
            samples[(arb, i)].append(b)
    out: dict[tuple[str, int], tuple[float, float, int]] = {}
    for key, vals in samples.items():
        if len(vals) < 5:
            continue
        med = statistics.median(vals)
        sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        out[key] = (med, sd, len(vals))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--logs-dir", default="logs", help="root of session dirs (default: logs)")
    parser.add_argument("--csv", help="write per-session × per-byte rows to this path")
    parser.add_argument("--top", type=int, default=15, help="number of top-ranked bytes to display (default: 15)")
    parser.add_argument(
        "--min-sessions",
        type=int,
        default=3,
        help="byte must be present in at least this many sessions to rank (default: 3)",
    )
    args = parser.parse_args()

    logs_root = Path(args.logs_dir)
    if not logs_root.is_dir():
        print(f"no logs dir at {logs_root}")
        return 1

    # Walk sessions, sort chronologically.
    sessions = sorted(
        (d for d in logs_root.iterdir() if d.is_dir() and (d / "capture.log").exists()),
        key=session_iso_date,
    )
    if not sessions:
        print("no sessions with capture.log found")
        return 1

    # session_name -> (mode, iso, {(id, byte): (med, sd, n)})
    per_session: dict[str, tuple[str, str, dict[tuple[str, int], tuple[float, float, int]]]] = {}

    for session_dir in sessions:
        log_path = session_dir / "capture.log"
        frames = list(parse_log(log_path))
        if not frames:
            print(f"[skip] {session_dir.name}: empty log")
            continue
        win = find_operating_window(frames)
        if win is None:
            print(f"[skip] {session_dir.name}: no usable window")
            continue
        t_start, t_end, mode = win
        stats = collect_byte_stats(frames, t_start, t_end)
        per_session[session_dir.name] = (mode, session_iso_date(session_dir), stats)
        print(
            f"[ok]   {session_dir.name}: mode={mode} "
            f"window={t_end - t_start:.1f}s bytes={len(stats)}"
        )

    if not per_session:
        print("no usable sessions")
        return 1

    # Optional CSV — long format for downstream tools.
    if args.csv:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["session", "iso", "mode", "id", "byte", "median", "stdev", "n_frames"])
            for sess, (mode, iso, stats) in per_session.items():
                for (arb, byte_i), (med, sd, n) in sorted(stats.items()):
                    w.writerow([sess, iso, mode, arb, byte_i, f"{med:.2f}", f"{sd:.3f}", n])
        print(f"\nwrote {out}")

    keys: set[tuple[str, int]] = set()
    for _mode, _iso, stats in per_session.values():
        keys.update(stats.keys())

    def rank_within(target_mode: str):
        """Rank candidate bytes restricted to a single engine-state mode.

        cross_sd = stdev of per-session medians across sessions of this
        mode.  mean_within = mean of within-session stdevs.  Score =
        cross_sd / max(mean_within, 0.5), capped so a noise-free byte
        doesn't dominate purely from a tiny divisor."""
        rows = []
        for key in keys:
            medians: list[float] = []
            within: list[float] = []
            for _sess, (mode, _iso, stats) in per_session.items():
                if mode != target_mode:
                    continue
                v = stats.get(key)
                if v is None:
                    continue
                med, sd, _n = v
                medians.append(med)
                within.append(sd)
            if len(medians) < args.min_sessions:
                continue
            cross_sd = statistics.pstdev(medians)
            mean_within = statistics.fmean(within) if within else 0.0
            score = cross_sd / max(mean_within, 0.5)
            rows.append(
                {
                    "id": key[0],
                    "byte": key[1],
                    "n_sessions": len(medians),
                    "cross_sd": cross_sd,
                    "mean_within": mean_within,
                    "score": score,
                    "min_med": min(medians),
                    "max_med": max(medians),
                }
            )
        rows.sort(key=lambda r: r["score"], reverse=True)
        return rows

    session_order = sorted(per_session.keys(), key=lambda s: per_session[s][1])
    abbr = [s.replace("2026-", "") for s in session_order]
    col_w = max(7, max(len(a) for a in abbr) + 1)

    def print_table(title: str, rows: list, mode_filter: str | None):
        print(f"\n=== {title} ===")
        print(
            f"{'ID':>3}  {'B':>1}  {'#sess':>5}  {'cross_sd':>8}  {'within':>7}  "
            f"{'score':>7}  {'min_med':>7}  {'max_med':>7}"
        )
        for r in rows[: args.top]:
            print(
                f"{r['id']:>3}  {r['byte']:>1}  {r['n_sessions']:>5}  "
                f"{r['cross_sd']:>8.2f}  {r['mean_within']:>7.2f}  "
                f"{r['score']:>7.2f}  {r['min_med']:>7.1f}  {r['max_med']:>7.1f}"
            )
        # Chronological per-session medians (only sessions of this mode).
        sess_for_table = [
            s for s in session_order if mode_filter is None or per_session[s][0] == mode_filter
        ]
        abbr_for_table = [s.replace("2026-", "") for s in sess_for_table]
        col_w_local = max(7, max(len(a) for a in abbr_for_table) + 1) if abbr_for_table else 7
        print("\n(chronological per-session medians)")
        print(f"{'ID.B':>5}  " + "".join(f"{a:>{col_w_local}}" for a in abbr_for_table))
        for r in rows[: args.top]:
            cells = []
            for s in sess_for_table:
                v = per_session[s][2].get((r["id"], r["byte"]))
                cells.append(f"{v[0]:>{col_w_local}.1f}" if v else f"{'-':>{col_w_local}}")
            print(f"{r['id']}.{r['byte']:<2}  " + "".join(cells))

    rows_off = rank_within("off")
    rows_on = rank_within("on")

    if rows_off:
        print_table(
            "ENGINE-OFF sessions only — top candidates by score",
            rows_off,
            "off",
        )
    if rows_on:
        print_table(
            "ENGINE-ON sessions only — top candidates by score",
            rows_on,
            "on",
        )

    print(
        "\nLook for a row that's mostly flat-or-decreasing chronologically with "
        "ONE upward jump (the refuel). Confounders that also drift "
        "across days (ambient temp, baro, long-term fuel trim) won't show "
        "the upward step. A clean fuel byte should appear in BOTH the "
        "engine-off and engine-on rankings since tank level is engine-state "
        "independent."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
