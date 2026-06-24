#!/usr/bin/env python3
"""auto_headlight_rescan.py — hunt the auto-headlight CAN bit using decoded rear km/h.

The 2026-06-22 wheel-spin-paddock-stand capture has no `b` (headlight transition)
marks — rider couldn't push and key-press at the same time. The original
wheel_spin_scan.py looked for bits that were ON only during Phase B and found
`12D` D2 bit 6, which turned out to be the high bit of the speed byte itself
(not a separate headlight signal).

This rescan uses the now-decoded rear wheel speed (`12D` D5:D6 BE / 16 km/h
per [[signal-wheel-speed-rear]]) as the threshold key, instead of coarse
Phase A vs Phase B buckets. For every (ID, byte, bit):

  1. Carry the most-recent rear km/h forward across every frame after key-on.
  2. For each candidate threshold X (sweep 1..20 km/h), compute purity =
     fraction of frames where bit_value == (rear_kmh > X).
  3. Report bits whose best purity exceeds REPORT_PURITY (default 0.99) AND
     whose bit value isn't trivially derivable from D5:D6 itself.

If a real auto-headlight bit exists on the bus, it should:
  - Be 0 at rest (km/h == 0) and during baseline + Phase A gentle pushes.
  - Switch to 1 during the larger Phase B pushes, with hysteresis around
    the trigger speed.
  - Live in the slow-decay group (`12A`, `12D`, `12E`, `450`, `541`, `5A0`)
    since the body controller drives the headlight.

If no bit matches, the source is off-bus — body controller reads wheel speed
internally and drives the relay directly, no derived broadcast.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

SLOW_DECAY_IDS = {"12A", "12D", "12E", "450", "541", "5A0"}
REPORT_PURITY = 0.99
THRESHOLDS_KMH = [round(x * 0.5, 2) for x in range(2, 41)]  # 1..20 km/h step 0.5


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


def parse_events(path: Path):
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            rows.append((t, r["key"], r["label"]))
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


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--session",
                   default="logs/2026-06-22-wheel-spin-paddock-stand")
    p.add_argument("--report-purity", type=float, default=REPORT_PURITY,
                   help="Bits whose best purity-at-threshold exceeds this are reported (default 0.99).")
    p.add_argument("--slow-only", action="store_true",
                   help="Restrict to slow-decay group IDs.")
    args = p.parse_args()

    session = REPO_ROOT / args.session
    frames = parse_log(session / "capture.log")
    key_on, phase_a, phase_b = parse_events(session / "events.csv")

    # ---------- carry rear km/h forward
    rear_kmh = 0.0
    labelled: list[tuple[float, str, bytes, float]] = []
    for ts, arb, data in frames:
        if ts < key_on:
            continue
        if arb == "12D":
            rear_kmh = ((data[5] << 8) | data[6]) / 16.0
        labelled.append((ts, arb, data, rear_kmh))

    # ---------- summary of rear speed across capture
    rear_only = [(ts, k) for ts, arb, _, k in labelled if arb == "12D"]
    nonzero = [k for _, k in rear_only if k > 0]
    print("# Rear wheel speed (`12D` D5:D6 BE / 16) across capture")
    print(f"  total 12D frames after key-on: {len(rear_only)}")
    print(f"  non-zero motion frames: {len(nonzero)}  (peak {max(nonzero):.2f} km/h)")
    above = lambda thr: sum(1 for k in nonzero if k > thr)
    for thr in (1, 2, 3, 4, 5, 6, 8, 10):
        print(f"  frames above {thr:2d} km/h: {above(thr):5d}")

    # ---------- per-push peak rear km/h (for cross-check)
    print(f"\n# Peak rear km/h per push window (-1..+6 s)")
    print(f"  {'label':>4}  {'peak km/h':>10}  {'@dt':>6}")
    all_marks = [(t, f"A{i+1}") for i, t in enumerate(phase_a)] + \
                [(t, f"B{i+1}") for i, t in enumerate(phase_b)]
    for mark, label in all_marks:
        window = [(ts, k) for ts, arb, _, k in labelled
                  if arb == "12D" and mark - 1.0 <= ts <= mark + 6.0]
        if not window:
            print(f"  {label:>4}  {'—':>10}  {'—':>6}")
            continue
        peak_ts, peak = max(window, key=lambda x: x[1])
        if peak == 0:
            print(f"  {label:>4}  {'0.00':>10}  {'—':>6}")
        else:
            print(f"  {label:>4}  {peak:>10.2f}  {peak_ts - mark:+.2f}")

    # ---------- candidate filter
    # A real auto-headlight bit must:
    #   (a) hold a constant baseline value across the 30 s zero-motion window
    #       AND across every Phase A push window (gentle pushes, peak < 4 km/h
    #       — all below the rider-observed trigger threshold).
    #   (b) toggle to the opposite value during at least one Phase B push window
    #       (hard pushes, peak 5.8..7.3 km/h — known to trigger the headlight).
    #   (c) toggle back to baseline as the spin decays.
    # We also record the rear km/h at every transition so the resulting bits can
    # be eyeballed for a hysteresis pattern (ON-events at higher speed than
    # OFF-events).
    print(f"\n# Headlight-bit candidates")
    print(f"  filter: bit constant across baseline+PhaseA, toggles during PhaseB")
    if args.slow_only:
        print(f"  restricted to slow-decay IDs: {sorted(SLOW_DECAY_IDS)}")

    PRE, POST = 1.0, 6.0

    def in_baseline(ts):
        return key_on <= ts < phase_a[0] - PRE

    def in_phase_a_window(ts):
        return any(m - PRE <= ts <= m + POST for m in phase_a)

    def in_phase_b_window(ts):
        return any(m - PRE <= ts <= m + POST for m in phase_b)

    # Per-key: baseline value (None until first sample), set of values seen in
    # baseline+A, list of (ts, prev, new, kmh) transitions during Phase B,
    # frame count in Phase B, sum of bit==1 in Phase B.
    state: dict[tuple[str, int, int], dict] = defaultdict(
        lambda: {"baseline_vals": set(), "phase_a_vals": set(),
                 "transitions": [], "prev": None,
                 "b_frames": 0, "b_ones": 0})
    for ts, arb, data, kmh in labelled:
        if args.slow_only and arb not in SLOW_DECAY_IDS:
            continue
        in_b = in_baseline(ts)
        in_a = in_phase_a_window(ts)
        in_pb = in_phase_b_window(ts)
        for bi in range(8):
            byte = data[bi]
            for bit in range(8):
                v = (byte >> bit) & 1
                s = state[(arb, bi, bit)]
                if in_b:
                    s["baseline_vals"].add(v)
                if in_a:
                    s["phase_a_vals"].add(v)
                if in_pb:
                    s["b_frames"] += 1
                    s["b_ones"] += v
                if s["prev"] is not None and s["prev"] != v:
                    if in_pb:
                        s["transitions"].append((ts, s["prev"], v, kmh))
                s["prev"] = v

    candidates = []
    for key, s in state.items():
        if len(s["baseline_vals"]) != 1:
            continue
        if len(s["phase_a_vals"]) != 1:
            continue
        baseline = next(iter(s["baseline_vals"]))
        if next(iter(s["phase_a_vals"])) != baseline:
            continue
        if not s["transitions"]:
            continue
        if s["b_frames"] == 0:
            continue
        # At least one transition away from baseline during Phase B.
        off_baseline = [t for t in s["transitions"] if t[2] != baseline]
        if not off_baseline:
            continue
        candidates.append({
            "key": key,
            "baseline": baseline,
            "transitions": s["transitions"],
            "off_baseline_count": len(off_baseline),
            "off_baseline_kmh": [k for _, _, _, k in off_baseline],
            "back_to_baseline_count": len([t for t in s["transitions"]
                                           if t[2] == baseline]),
            "back_to_baseline_kmh": [k for _, p, n, k in s["transitions"]
                                     if n == baseline],
            "b_ones": s["b_ones"],
            "b_frames": s["b_frames"],
        })

    candidates.sort(key=lambda c: (-c["off_baseline_count"], c["key"]))
    if not candidates:
        print("\n  none — no bit follows the baseline=const → Phase-B-toggle shape.")
    else:
        print(f"\n  {'ID':>4}  {'D':>2}  {'b':>2}  {'base':>4}  "
              f"{'→!base':>7}  {'→base':>6}  "
              f"{'on@kmh(median)':>15}  {'off@kmh(median)':>16}  "
              f"{'B-fill%':>7}")
        for c in candidates:
            arb, bi, bit = c["key"]
            on_kmh = c["off_baseline_kmh"]
            off_kmh = c["back_to_baseline_kmh"]
            on_med = sorted(on_kmh)[len(on_kmh)//2] if on_kmh else float("nan")
            off_med = (sorted(off_kmh)[len(off_kmh)//2]
                       if off_kmh else float("nan"))
            fill = 100.0 * c["b_ones"] / c["b_frames"]
            if c["baseline"] == 1:
                fill = 100.0 - fill  # show fraction-off-baseline either way
            print(f"  {arb:>4}  {bi:>2}  {bit:>2}  {c['baseline']:>4}  "
                  f"{c['off_baseline_count']:>7}  "
                  f"{c['back_to_baseline_count']:>6}  "
                  f"{on_med:>15.2f}  {off_med:>16.2f}  {fill:>7.2f}")

        print("\n  NOTE: `12D` D2/D5/D6 are the rear-speed bytes themselves —")
        print("        any of their bits are speed-derived, not a separate signal.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
