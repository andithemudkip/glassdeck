#!/usr/bin/env python3
"""abs_lamp_crosscheck.py — cross-check the 6 ABS-lamp candidate bits across all captured sessions.

Six bits were identified as ABS-lamp candidates on 2026-07-22
([[signal-abs-lamp]]):

  12A D0 bit 4  HIGH = lit
  12A D1 bit 0  HIGH = lit
  12A D1 bit 2  HIGH = lit
  12A D5 bit 3  HIGH = lit
  12E D6 bit 4  LOW  = lit  (inverted)
  12E D6 bit 5  LOW  = lit  (inverted)

The interpretation "all 6 are the ABS lamp" is based on synchronized behavior
on the 2026-07-22 ride. But if any bit responds to a raw wheel-speed threshold
independently of engine state, it's not the lamp — the lamp requires engine-on
(per [[bike/dash-warning-lights]]).

Two crucial cross-checks:

  A. [[2026-06-24-front-wheel-hand-spin]]  engine OFF, front wheel spun to
     ~11 km/h on the dash. Lamp did NOT extinguish (rider observation).
     Question: did any of the 6 bits flip anyway? If so, that bit is
     wheel-speed-threshold-triggered independent of engine state — not the
     lamp.

  B. Cold-boot / stationary / early-post-boot sessions. In every "engine off,
     bike stationary" capture the lamp is LIT (or at least in its "lit"
     resting state). All 6 bits should read their "lit" polarity throughout.
     If some read "not lit" in these conditions, they're carrying something
     else.

Reports per (session × bit): initial value, final value, transition count,
transition timestamps.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGS = REPO_ROOT / "logs"

# Match both candump ((unix_ts) can0 ID#hex R) and SLCAN ((sec.us) t<ID><LEN><DATA>)
LINE_CANDUMP = re.compile(r"\(([\d.]+)\)\s+\S+\s+([0-9A-Fa-f]{3})#([0-9A-Fa-f]*)")
LINE_SLCAN = re.compile(r"\(([\d.]+)\)\s+t([0-9A-Fa-f]{3})([0-9A-Fa-f])([0-9A-Fa-f]*)")

CANDIDATES = [
    # (id, byte, bit, "lit polarity" as a string)
    ("12A", 0, 4, "HIGH"),
    ("12A", 1, 0, "HIGH"),
    ("12A", 1, 2, "HIGH"),
    ("12A", 5, 3, "HIGH"),
    ("12E", 6, 4, "LOW"),
    ("12E", 6, 5, "LOW"),
]


def parse_frames(path):
    with path.open() as f:
        for line in f:
            m = LINE_CANDUMP.match(line)
            if m:
                arb = m.group(2).upper()
                hex_data = m.group(3)
                if len(hex_data) < 2 or len(hex_data) % 2 != 0:
                    continue
                data = bytes.fromhex(hex_data)
                yield float(m.group(1)), arb, data
                continue
            m = LINE_SLCAN.match(line)
            if m:
                arb = m.group(2).upper()
                length = int(m.group(3), 16)
                hex_data = m.group(4)
                if len(hex_data) < length * 2:
                    continue
                data = bytes.fromhex(hex_data[: length * 2])
                yield float(m.group(1)), arb, data


def find_log_file(session_dir):
    """Return the primary log file for a session (either capture.log or
    the first moving-*.log)."""
    candidates = list(session_dir.glob("capture.log")) + list(session_dir.glob("moving-*.log"))
    return candidates[0] if candidates else None


def analyse_bit(log, arb, byte_i, bit):
    series = []
    for ts, id_, d in parse_frames(log):
        if id_ != arb or len(d) <= byte_i:
            continue
        v = (d[byte_i] >> bit) & 1
        series.append((ts, v))
    if not series:
        return None
    ts0 = series[0][0]
    first = series[0][1]
    last = series[-1][1]
    transitions = []
    prev = first
    for ts, v in series[1:]:
        if v != prev:
            transitions.append((ts - ts0, prev, v))
            prev = v
    return {
        "n_frames": len(series),
        "first_val": first,
        "last_val": last,
        "n_transitions": len(transitions),
        "transitions": transitions[:8],  # cap
        "count_one": sum(1 for _, v in series if v == 1),
        "count_zero": sum(1 for _, v in series if v == 0),
    }


def main():
    sessions = [d for d in sorted(LOGS.iterdir())
                if d.is_dir() and d.name != "README.md"]
    print(f"# ABS-lamp candidate cross-check across {len(sessions)} sessions\n")

    # Per session, dump the 6 bits' states.
    for session in sessions:
        log = find_log_file(session)
        if log is None:
            continue
        print(f"## {session.name}")

        for arb, bi, bit, pol in CANDIDATES:
            result = analyse_bit(log, arb, bi, bit)
            if result is None:
                continue
            expected_lit = 1 if pol == "HIGH" else 0
            first_is_lit = "LIT" if result["first_val"] == expected_lit else "not-lit"
            last_is_lit = "LIT" if result["last_val"] == expected_lit else "not-lit"
            tx_str = ""
            if result["n_transitions"]:
                tx_str = "  transitions@ " + ", ".join(
                    f"t+{t:.1f}s→{v}" for t, _, v in result["transitions"]
                )
            print(f"  {arb} D{bi} b{bit} ({pol}=lit)  "
                  f"first={result['first_val']}({first_is_lit})  "
                  f"last={result['last_val']}({last_is_lit})  "
                  f"1={result['count_one']}/0={result['count_zero']}  "
                  f"tx={result['n_transitions']}{tx_str}")


if __name__ == "__main__":
    sys.exit(main())
