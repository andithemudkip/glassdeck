#!/usr/bin/env python3
"""wheel_spin_scan.py — find the CAN bytes that track wheel rotation.

Reads a wheel-spin-paddock-stand capture. For each `spin` event mark,
summarises the [-1, +6] s window per candidate byte (default `12D` D2,
D6): peak value, peak timestamp, envelope duration, frame count, plus
`12D` D2 bit 6 ON-frames as a proxy for the auto-headlight transition
(no dedicated `b` marks landed in the events log — the rider couldn't
push and key-press at the same time, see experiment Result section).

Then scans every (ID, byte, bit) for "0 in baseline + Phase A + rest,
mixed in Phase B" — the headlight-bit search shape.

Procedure assumed (matches docs/experiments/2026-06-22-wheel-spin-paddock-stand.md):
  6 `spin REAR gentle push` marks (Phase A), then 8 `spin REAR hard push` marks
  (Phase B). Phase C (front wheel) is optional and was not run in this session.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

PUSH_WINDOW_PRE_S = 1.0
PUSH_WINDOW_POST_S = 6.0


def parse_events(path: Path):
    """Return (key_on_ts, phase_a_marks, phase_b_marks) in unix-epoch seconds.

    Filters out procedure-rewind events and any pre-rewind duplicate marks
    by taking the LAST occurrence of each unique label.
    """
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            rows.append((t, r["key"], r["label"]))
    # Take last occurrence of each (key, label) pair — survives rewinds.
    by_label: dict[tuple[str, str], float] = {}
    for t, k, lab in rows:
        if k == "procedure-rewind":
            continue
        by_label[(k, lab)] = t
    key_on = by_label[("mark", "key on")]
    phase_a = sorted(t for (k, lab), t in by_label.items()
                     if k == "spin" and "gentle" in lab)
    phase_b = sorted(t for (k, lab), t in by_label.items()
                     if k == "spin" and "hard" in lab)
    return key_on, phase_a, phase_b


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


def summarise_push(frames, target_id, mark, label, pre=PUSH_WINDOW_PRE_S, post=PUSH_WINDOW_POST_S):
    """Compute peak D2/D6, envelope start/end, frame count for one push."""
    window = [(ts, d) for ts, arb, d in frames
              if arb == target_id and mark - pre <= ts <= mark + post]
    nonzero = [(ts, d) for ts, d in window if d[2] != 0 or d[6] != 0]
    if not nonzero:
        return None
    first_t = nonzero[0][0] - mark
    last_t = nonzero[-1][0] - mark
    peak_d2 = max(d[2] for _, d in nonzero)
    peak_d6 = max(d[6] for _, d in nonzero)
    peak_idx = max(range(len(nonzero)), key=lambda i: nonzero[i][1][2])
    peak_dt = nonzero[peak_idx][0] - mark
    d2_bit6_on = sum(1 for _, d in nonzero if (d[2] >> 6) & 1)
    return {
        "label": label,
        "mark_unix": mark,
        "first_dt": first_t,
        "last_dt": last_t,
        "peak_dt": peak_dt,
        "peak_d2": peak_d2,
        "peak_d6": peak_d6,
        "n_frames": len(nonzero),
        "d2_bit6_on_frames": d2_bit6_on,
    }


def in_any_push_window(ts, marks, pre=PUSH_WINDOW_PRE_S, post=PUSH_WINDOW_POST_S):
    return any(m - pre <= ts <= m + post for m in marks)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--session",
                   default="logs/2026-06-22-wheel-spin-paddock-stand",
                   help="Path to capture session directory (relative to repo root).")
    p.add_argument("--target", default="12D",
                   help="Arbitration ID to inspect for wheel-speed bytes.")
    args = p.parse_args()

    session = REPO_ROOT / args.session
    key_on, phase_a, phase_b = parse_events(session / "events.csv")
    if len(phase_a) != 6 or len(phase_b) != 8:
        print(f"warning: expected 6 gentle + 8 hard marks, got "
              f"{len(phase_a)} + {len(phase_b)}", file=sys.stderr)

    frames = parse_log(session / "capture.log")
    last_ts = frames[-1][0]

    # ----------------------------- per-push summary on the target ID
    print(f"# Per-push summary on {args.target}")
    print(f"  ({len(phase_a)} gentle + {len(phase_b)} hard pushes)\n")
    print(f"  {'label':>4}  {'peak D2':>8}  {'peak D6':>8}  "
          f"{'peak@':>6}  {'envelope':>16}  {'frames':>6}  {'D2.b6 ON':>8}")
    all_marks = [(t, f"A{i+1}") for i, t in enumerate(phase_a)] + \
                [(t, f"B{i+1}") for i, t in enumerate(phase_b)]
    for mark, label in all_marks:
        s = summarise_push(frames, args.target, mark, label)
        if s is None:
            print(f"  {label:>4}  {'—':>8}  {'—':>8}  {'—':>6}  {'no motion':>16}  {'0':>6}  {'0':>8}")
            continue
        env = f"t+{s['first_dt']:.2f}→t+{s['last_dt']:.2f}"
        print(f"  {label:>4}  "
              f"0x{s['peak_d2']:02X} ({s['peak_d2']:>3})  "
              f"0x{s['peak_d6']:02X} ({s['peak_d6']:>3})  "
              f"+{s['peak_dt']:.2f}  {env:>16}  {s['n_frames']:>6}  {s['d2_bit6_on_frames']:>8}")

    # ----------------------------- motion frames outside any push window
    print(f"\n# Motion frames on {args.target} outside any push window")
    all_motion = [(ts, d) for ts, arb, d in frames
                  if arb == args.target and (d[2] != 0 or d[6] != 0)]
    outside = [(ts, d) for ts, d in all_motion
               if not in_any_push_window(ts, phase_a + phase_b)
               and ts > key_on]
    print(f"  total motion frames: {len(all_motion)}")
    print(f"  outside push windows: {len(outside)}")
    if outside:
        first = outside[0][0] - key_on
        last = outside[-1][0] - key_on
        peak_d2 = max(d[2] for _, d in outside)
        peak_d6 = max(d[6] for _, d in outside)
        print(f"  span (from key-on): +{first:.1f}s → +{last:.1f}s  "
              f"peak D2=0x{peak_d2:02X}  peak D6=0x{peak_d6:02X}")

    # ----------------------------- headlight-bit hunt: bits ON only in Phase B
    print(f"\n# Headlight-bit candidates (bit value differs in Phase B vs everywhere else)")

    def in_baseline(ts): return key_on <= ts < phase_a[0]
    def in_phase_a(ts):  return phase_a[0] - PUSH_WINDOW_PRE_S <= ts < phase_a[-1] + PUSH_WINDOW_POST_S
    def in_rest(ts):     return phase_a[-1] + PUSH_WINDOW_POST_S <= ts < phase_b[0] - PUSH_WINDOW_PRE_S
    def in_phase_b(ts):  return phase_b[0] - PUSH_WINDOW_PRE_S <= ts < phase_b[-1] + PUSH_WINDOW_POST_S

    bit_stats = defaultdict(lambda: {"base": [0, 0], "A": [0, 0], "rest": [0, 0], "B": [0, 0]})
    for ts, arb, data in frames:
        if in_baseline(ts):  bucket = "base"
        elif in_phase_a(ts): bucket = "A"
        elif in_rest(ts):    bucket = "rest"
        elif in_phase_b(ts): bucket = "B"
        else:                continue
        for bi, b in enumerate(data[:8]):
            for bit in range(8):
                v = (b >> bit) & 1
                bit_stats[(arb, bi, bit)][bucket][v] += 1

    hits = []
    for k, s in bit_stats.items():
        if not (sum(s["base"]) and sum(s["A"]) and sum(s["rest"]) and sum(s["B"])):
            continue
        # candidate A: bit is 0 in base+A+rest, mixed in B
        if s["base"][1] == 0 and s["A"][1] == 0 and s["rest"][1] == 0 \
                and s["B"][1] > 0 and s["B"][0] > 0:
            hits.append((k, "0→1 only in PhB", s))
        # candidate B: inverse polarity
        if s["base"][0] == 0 and s["A"][0] == 0 and s["rest"][0] == 0 \
                and s["B"][0] > 0 and s["B"][1] > 0:
            hits.append((k, "1→0 only in PhB", s))
    if not hits:
        print("  none — no bit toggles cleanly only in Phase B")
    else:
        for k, kind, s in hits:
            arb, bi, bit = k
            print(f"  {arb}  D{bi}  b{bit} ({kind}): "
                  f"base={s['base']}  A={s['A']}  rest={s['rest']}  B={s['B']}")
        print("\n  NOTE: 12D D2 bit 6 is the high bit of the speed byte itself —")
        print("        set whenever D2 >= 0x40. Not a separate headlight signal.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
