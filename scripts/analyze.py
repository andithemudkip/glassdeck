#!/usr/bin/env python3
"""analyze.py — one-command analysis pipeline for a fresh capture.

Reads <session>/events.csv, decides which per-input analyzers apply
based on the event marks present, runs them in sequence (always
preceded by inventory_ids), and writes a consolidated text report
to <session>/analyze_report.txt.

Dispatch rules (thresholds match each scanner's documented procedure
so we don't run a toggle scanner against an idle baseline whose only
kill mark is the end-of-run engine-stop):

  always                                  inventory_ids.py
  kill switch marks  >= 6                 kill_switch_scan.py
  throttle blip      >= 3                 throttle_sweep.py
  j keys             >= 6                 side_stand_scan.py
  c keys             >= 5                 clutch_scan.py
  g + n keys         >= 2                 gear_scan.py
  starter button + no per-input above     verify_signals.py

Usage:
    python scripts/analyze.py logs/2026-06-25-new-capture
    python scripts/analyze.py <session> --stdout-only
    python scripts/analyze.py <session> --out path.txt
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"


def read_event_marks(events_csv: Path) -> tuple[Counter[str], Counter[str]]:
    keys: Counter[str] = Counter()
    labels: Counter[str] = Counter()
    if not events_csv.exists():
        return keys, labels
    with events_csv.open() as f:
        for row in csv.DictReader(f):
            if row.get("key"):
                keys[row["key"]] += 1
            if row.get("label"):
                labels[row["label"]] += 1
    return keys, labels


def plan(session: Path) -> tuple[list[tuple[str, list[str], str]], list[str]]:
    """Return (steps, skipped_notes). Each step is (script, argv, label)."""
    keys, labels = read_event_marks(session / "events.csv")
    steps: list[tuple[str, list[str], str]] = []
    skipped: list[str] = []

    steps.append(("inventory_ids.py", [str(session)], "inventory_ids"))

    per_input_ran = False

    if labels["kill switch"] >= 6:
        steps.append(("kill_switch_scan.py", ["--session", str(session)], "kill_switch_scan"))
        per_input_ran = True
    elif labels["kill switch"]:
        skipped.append(
            f"kill_switch_scan: only {labels['kill switch']} kill mark(s) "
            "(scanner needs 6 — looks like an end-of-run mark, not a toggle session)")

    if labels["throttle blip"] >= 3:
        steps.append(("throttle_sweep.py", ["--session", str(session)], "throttle_sweep"))
        per_input_ran = True
    elif labels["throttle blip"]:
        skipped.append(
            f"throttle_sweep: only {labels['throttle blip']} throttle-blip mark(s) "
            "(scanner needs 3 phase markers)")

    if keys["j"] >= 6:
        steps.append(("side_stand_scan.py", ["--session", str(session)], "side_stand_scan"))
        per_input_ran = True
    elif keys["j"]:
        skipped.append(
            f"side_stand_scan: only {keys['j']} 'j' mark(s) (scanner needs 6 toggles)")

    if keys["c"] >= 5:
        steps.append(("clutch_scan.py", ["--session", str(session)], "clutch_scan"))
        per_input_ran = True
    elif keys["c"]:
        skipped.append(
            f"clutch_scan: only {keys['c']} 'c' mark(s) (scanner needs 5 pumps)")

    gear_n = keys["g"] + keys["n"]
    if gear_n >= 2:
        steps.append(("gear_scan.py", ["--session", str(session)], "gear_scan"))
        per_input_ran = True
    elif gear_n:
        skipped.append(
            f"gear_scan: only {gear_n} 'g'/'n' mark(s) (need >=2 to define windows)")

    # verify_signals expects an idle-style capture. Run it only if no per-input
    # scanner ran AND the session contains an engine start (starter button) —
    # otherwise EXPECTATIONS (kill=RUN, gear=N, etc.) will trip on a transient
    # window. An end-of-run "kill switch" mark in an idle baseline is fine; the
    # check inside verify_signals stops at that boundary.
    if not per_input_ran and labels["starter button"]:
        steps.append(("verify_signals.py", ["--session", str(session)], "verify_signals"))
    elif not per_input_ran:
        skipped.append(
            "verify_signals: no 'starter button' mark — not an idle/engine-on session")

    return steps, skipped


def run_script(name: str, *args: str) -> tuple[int, str]:
    cmd = [sys.executable, str(SCRIPTS / name), *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    out = result.stdout
    if result.stderr.strip():
        out = (out.rstrip() + "\n\n--- stderr ---\n" + result.stderr).lstrip("\n")
    return result.returncode, out


def section(title: str, body: str) -> str:
    bar = "=" * 78
    return f"\n{bar}\n  {title}\n{bar}\n\n{body.rstrip()}\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("session", type=Path, help="logs/<session>/ directory")
    p.add_argument("--out", type=Path, default=None,
                   help="report path (default: <session>/analyze_report.txt)")
    p.add_argument("--stdout-only", action="store_true",
                   help="print the report only, do not write a file")
    args = p.parse_args()

    session = args.session.resolve()
    if not (session / "capture.log").exists():
        print(f"no capture.log in {session}", file=sys.stderr)
        return 2

    steps, skipped = plan(session)

    print(f"analyze.py: {len(steps)} step(s) on {session.name}", file=sys.stderr)
    for _, _, label in steps:
        print(f"  - {label}", file=sys.stderr)
    for note in skipped:
        print(f"  ~ skip {note}", file=sys.stderr)
    print(file=sys.stderr)

    chunks: list[str] = [f"# Analysis report — {session.name}\n",
                         "_Generated by `scripts/analyze.py`._\n"]
    if skipped:
        chunks.append("\nSkipped scanners (preconditions not met):\n")
        for note in skipped:
            chunks.append(f"  - {note}\n")

    fail = 0
    for script, scr_args, label in steps:
        sys.stderr.write(f"[analyze] {label}...\n")
        rc, out = run_script(script, *scr_args)
        title = label if rc == 0 else f"{label}  (exit {rc})"
        if rc != 0:
            fail += 1
        chunks.append(section(title, out))

    report = "".join(chunks)
    sys.stdout.write(report)

    if not args.stdout_only:
        out_path = args.out or (session / "analyze_report.txt")
        out_path.write_text(report)
        sys.stderr.write(f"[analyze] wrote {out_path}\n")

    if fail:
        sys.stderr.write(f"[analyze] {fail} step(s) exited non-zero\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
