#!/usr/bin/env python3
"""verify_procedure.py — schema validator for a procedure.yaml sidecar.

Loads a `docs/experiments/<slug>.procedure.yaml` via the same code path
that capture.py / live_view.py use, expands all `repeat` blocks, and
prints the resulting flat step sequence plus a count of the auto-marks
the procedure would emit. PASS on a valid file, FAIL on a SchemaError.

Counterpart to verify_signals.py — use before a capture session to
sanity-check the procedure file the operator screen will drive.

Usage:
    python scripts/verify_procedure.py <procedure.yaml>
    python scripts/verify_procedure.py <procedure.yaml> --show-marks
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from procedure import SchemaError, auto_marks, load_procedure  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", type=Path, help="Path to a procedure.yaml file")
    ap.add_argument(
        "--show-marks",
        action="store_true",
        help="Also print just the auto-mark sequence (one per line) the procedure would emit",
    )
    args = ap.parse_args()

    if not args.path.is_file():
        print(f"FAIL: {args.path} not found", file=sys.stderr)
        return 2

    try:
        proc = load_procedure(args.path)
    except SchemaError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1

    print(f"# {proc.name}")
    print(f"# {proc.description}")
    print(f"# experiment: {proc.experiment}")
    print(f"# steps:      {len(proc.steps)}")
    print()

    marks = auto_marks(proc)
    for s in proc.steps:
        if s.duration_secs is None:
            dur = "manual"
        else:
            dur = f"{s.duration_secs:g}s"
        cd = f", ⏱{s.countdown_from}" if s.countdown_from else ""
        head = f"  [{s.source_index:02d}] ({dur}{cd})"
        line = f"{head}  {s.prompt}"
        if s.mark is not None:
            line += f"    → mark: {s.mark.key} {s.mark.label!r}"
        print(line)

    print()
    if args.show_marks:
        print("# auto-marks (in order):")
        for idx, mark in marks:
            print(f"  [{idx:02d}]  {mark.key:18s} {mark.label!r}")
        print()

    print(f"PASS: {len(proc.steps)} steps, {len(marks)} auto-marks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
