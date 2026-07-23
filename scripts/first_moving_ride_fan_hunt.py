#!/usr/bin/env python3
"""first_moving_ride_fan_hunt.py — hunt for a cooling-fan status bit in moving-5.

Rider observation on moving-5 (coolant trace confirms):
  - Capture starts at 95.0 °C with fan ON (bike had been ridden hot).
  - t+27.2 s: coolant falls through 90 °C — fan turns OFF.
  - t+75.5 s: coolant rises back through 95 °C — fan turns ON.
  - t+116.3 s: coolant falls through 90 °C again — fan turns OFF.

Coolant is 540 D5:D6 BE at 0.1 °C/LSB ([[signal-coolant-temp]]).

Strategy: fan status should be a bit that either doesn't change at all across
these 3 events (fan status absent from broadcasts) or has EXACTLY 3 transitions
in the whole capture landing within a small tolerance of the events, with
matching polarity. First hunt was too loose (>40 noise transitions in top
candidates). This version filters to bits with total-transitions in [1, 6] to
kill fast-changing counters and heartbeat bits.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG = REPO_ROOT / "logs" / "2026-07-22-first-moving-ride" / "moving-5.log"

LINE_RE = re.compile(r"\(([\d.]+)\)\s+t([0-9A-Fa-f]{3})([0-9A-Fa-f])([0-9A-Fa-f]*)")
COOLANT_LSB = 0.1
TOL_S = 5.0
MAX_TRANSITIONS = 6  # bit must be quiet — reject counters / heartbeats


def parse_frames(path):
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            arb = m.group(2).upper()
            length = int(m.group(3), 16)
            hex_data = m.group(4)
            if len(hex_data) < length * 2:
                continue
            data = bytes.fromhex(hex_data[: length * 2])
            yield float(m.group(1)), arb, data


def decode_coolant_series(path):
    return [(ts, ((d[5] << 8) | d[6]) * COOLANT_LSB)
            for ts, arb, d in parse_frames(path)
            if arb == "540" and len(d) >= 7]


def find_threshold_crossings(coolant, thresh_c, direction):
    out = []
    prev_t, prev_c = coolant[0]
    for t, c in coolant[1:]:
        crossed = (direction == "falling" and prev_c > thresh_c and c <= thresh_c) \
               or (direction == "rising"  and prev_c < thresh_c and c >= thresh_c)
        if crossed:
            denom = abs(prev_c - c) if direction == "falling" else (c - prev_c)
            frac = ((prev_c - thresh_c) if direction == "falling" else (thresh_c - prev_c)) / max(denom, 1e-6)
            out.append(prev_t + frac * (t - prev_t))
        prev_t, prev_c = t, c
    return out


def bit_series_and_transitions(log_path):
    """Return {(id, byte, bit): (first_value, [(ts, new_value), ...])}."""
    latest = defaultdict(list)  # (id, byte, bit) → list[(ts, val)]
    for ts, arb, data in parse_frames(log_path):
        for b_idx, byte in enumerate(data):
            for bit in range(8):
                latest[(arb, b_idx, bit)].append((ts, (byte >> bit) & 1))

    out = {}
    for key, ser in latest.items():
        if not ser:
            continue
        first_val = ser[0][1]
        transitions = []
        prev = first_val
        for t, v in ser[1:]:
            if v != prev:
                transitions.append((t, v))
                prev = v
        out[key] = (first_val, transitions)
    return out


def main():
    print(f"# Fan-status hunt (tightened) — {LOG.name}\n")

    coolant = decode_coolant_series(LOG)
    ts0 = coolant[0][0]

    print(f"Coolant span: start {coolant[0][1]:.1f} °C  peak {max(c for _, c in coolant):.1f} °C  end {coolant[-1][1]:.1f} °C")
    print(f"Duration: {coolant[-1][0] - ts0:.1f} s over {len(coolant)} frames")

    fall90 = find_threshold_crossings(coolant, 90.0, "falling")
    rise95 = find_threshold_crossings(coolant, 95.0, "rising")

    print(f"\n90 °C falling crossings: {[f'{t-ts0:.2f} s' for t in fall90]}")
    print(f"95 °C rising crossings:  {[f'{t-ts0:.2f} s' for t in rise95]}")

    if len(fall90) < 2 or len(rise95) < 1:
        print("Cannot align to expected 3-event sequence.")
        return 0

    event_times = [fall90[0], rise95[0], fall90[1]]
    event_labels = ["fan OFF #1 (90°C fall)", "fan ON (95°C rise)", "fan OFF #2 (90°C fall)"]
    print(f"\nAligned fan events (t+s from capture start):")
    for lbl, ts in zip(event_labels, event_times):
        print(f"  {lbl}: {ts - ts0:.2f}")

    # ----- collect bit transitions and filter to quiet bits
    bits = bit_series_and_transitions(LOG)

    # Report the quiet-bit population
    n_by_transitions = defaultdict(int)
    for (arb, b, bit), (fv, tx) in bits.items():
        n_by_transitions[len(tx)] += 1
    print(f"\nTransition-count distribution across {len(bits)} bits:")
    for n in sorted(n_by_transitions):
        if n <= 10 or n_by_transitions[n] >= 5:
            print(f"  {n:>4} transitions: {n_by_transitions[n]} bits")

    quiet = [(k, fv, tx) for k, (fv, tx) in bits.items() if 1 <= len(tx) <= MAX_TRANSITIONS]
    print(f"\n{len(quiet)} bits have 1..{MAX_TRANSITIONS} transitions in the whole capture — the fan-cycle candidates.\n")

    # Print the whole quiet-bit population so we can see everything the ECU
    # broadcasts quietly during moving-5, matched or not.
    print("All quiet bits (regardless of match):")
    print(f"  {'ID':>4} {'byte':>4} {'bit':>3}  {'first':>5}  transitions (t+s → new_value)")
    for (arb, b, bit), fv, tx in sorted(quiet):
        tx_str = "  ".join(f"t+{t-ts0:6.2f}→{v}" for t, v in tx)
        print(f"  {arb:>4} {b:>4} {bit:>3}  {fv:>5}  {tx_str}")

    if not quiet:
        print("No quiet bits with 1..6 transitions found.")
        return 0

    # ---- score every quiet bit against the expected polarity+timing
    # Two polarities: fan ON = bit HIGH (start=1, then 0,1,0) or fan ON = bit LOW (start=0, then 1,0,1)
    for polarity_desc, expected in [
        ("bit HIGH = fan ON (start=1 → 0 → 1 → 0)", [1, 0, 1, 0]),
        ("bit LOW  = fan ON (start=0 → 1 → 0 → 1)", [0, 1, 0, 1]),
    ]:
        print(f"\n## Polarity: {polarity_desc}")
        first_expected = expected[0]
        target_seq = expected[1:]  # after start
        matches = []
        for (arb, b, bit), fv, tx in quiet:
            if fv != first_expected:
                continue
            if len(tx) < len(target_seq):
                continue
            # try to align the first N transitions to the N events greedily
            # (bit may have extra transitions beyond the sequence — but we
            #  filtered on total ≤ 6, so noise is bounded)
            ok = True
            offsets = []
            tx_pos = 0
            for exp_val, exp_ts in zip(target_seq, event_times):
                # find next transition ≥ tx_pos matching exp_val
                found = None
                for i in range(tx_pos, len(tx)):
                    t, v = tx[i]
                    if v == exp_val and abs(t - exp_ts) <= TOL_S:
                        found = (i, t - exp_ts)
                        break
                if found is None:
                    ok = False
                    break
                tx_pos = found[0] + 1
                offsets.append(found[1])
            if ok:
                rms = (sum(o * o for o in offsets) / len(offsets)) ** 0.5
                matches.append((rms, (arb, b, bit), tx, offsets))

        matches.sort()
        if not matches:
            print("  No matches.")
            continue
        print(f"  {'ID':>4} {'byte':>4} {'bit':>3}  {'rms(s)':>6}  {'transitions in file':<40}  offsets(s)")
        for rms, (arb, b, bit), tx, offs in matches[:20]:
            tx_str = " ".join(f"t+{t-ts0:.1f}→{v}" for t, v in tx)
            offs_str = " ".join(f"{o:+.2f}" for o in offs)
            print(f"  {arb:>4} {b:>4} {bit:>3}  {rms:6.2f}  {tx_str:<40}  {offs_str}")


if __name__ == "__main__":
    sys.exit(main())
