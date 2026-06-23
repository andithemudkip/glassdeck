#!/usr/bin/env python3
"""d7_540_450_check.py — test whether IDs 540 and 450 follow the cycle
scheme established for the 9 catalog IDs.

Closed-form prediction: D7 = cycle[counter mod 6] XOR f(D0..D6), where
cycle values are {0x35, 0x5F, 0x6A, 0x8B, 0xBE, 0xD4} (all have at least
one of the high 3 bits set) and f outputs 5 bits (touches only the low
5). So under the cycle model:

    D7's high 3 bits == cycle[c]'s high 3 bits
    -> D7's high 3 bits cannot be 000.

If 540/450 show D7=0x00 universally, the cycle model is falsified for
them. The test:

  1. Tabulate observed (payload, D7) on 540 and 450 across all captures.
  2. For each (payload, D7), compute f(payload) from the closed form
     and check whether D7 XOR f(payload) lands in the cycle set.
  3. Report: fraction of frames consistent with the cycle model.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]+)")
CYCLE_SET = {0x35, 0x5F, 0x6A, 0x8B, 0xBE, 0xD4}

CAPTURE_DIRS = [
    "logs/2026-06-17-key-on-cold-boot",
    "logs/2026-06-17-engine-idle-run-1",
    "logs/2026-06-17-engine-idle-run-2",
    "logs/2026-06-17-engine-idle-run-3",
    "logs/2026-06-19-throttle-sweep-engine-off",
    "logs/2026-06-19-kill-switch-toggle",
    "logs/2026-06-19-side-stand-toggle",
    "logs/2026-06-19-gear-cycle-clutch-A-clutch-only",
    "logs/2026-06-19-gear-cycle-clutch-B-gear-cycle",
    "logs/2026-06-22-wheel-spin-paddock-stand",
]

# Closed-form f masks from scripts/d7_payload_hash_search.py.
# Each entry is the 56-bit mask over (D0.0, D0.1, ..., D6.7) for one
# output bit. Bit ordering: bit i of the payload-byte-stream is
# byte_i*8 + bit_i.
F_MASKS = [
    # bit 0
    {(0,0),(0,4),(1,2),(1,3),(1,7),(2,0),(2,3),(2,5),
     (4,0),(4,1),(4,4),(4,6),(5,4),(6,1),(6,2),(6,5),(6,7)},
    # bit 1
    {(0,0),(0,3),(1,3),(1,5),(1,7),(2,0),(2,1),(2,4),(2,6),
     (3,3),(4,1),(4,2),(4,5),(4,7),(5,0),(5,7),(6,0),(6,2),(6,3),(6,6)},
    # bit 2
    {(0,0),(0,1),(0,2),(0,5),(1,2),(1,3),(1,5),(1,7),
     (2,0),(2,1),(2,2),(2,3),(2,7),(3,0),(3,5),
     (4,1),(4,2),(4,3),(4,4),(5,1),(5,4),(5,7),
     (6,0),(6,2),(6,3),(6,4),(6,5)},
    # bit 3
    {(0,1),(0,3),(0,5),(1,0),(1,3),(2,1),(2,2),(2,3),(2,4),
     (3,1),(3,3),(4,0),(4,2),(4,3),(4,4),(4,5),(5,2),
     (6,1),(6,3),(6,4),(6,5),(6,6)},
    # bit 4
    {(0,0),(0,1),(0,3),(0,5),(1,1),(1,2),(1,3),
     (2,2),(2,4),(3,2),(4,0),(4,3),(4,5),
     (5,3),(5,4),(5,7),(6,0),(6,1),(6,4),(6,6)},
]


def f(payload: bytes) -> int:
    """5-bit GF(2)-linear hash of D0..D6 per the closed form."""
    out = 0
    for b in range(5):
        par = 0
        for (byte_i, bit_i) in F_MASKS[b]:
            par ^= (payload[byte_i] >> bit_i) & 1
        out |= par << b
    return out


def parse_log(path: Path):
    out = []
    with path.open() as f_:
        for line in f_:
            m = LINE_RE.match(line)
            if not m:
                continue
            arb = m.group(2).upper()
            hex_data = m.group(3)
            if len(hex_data) != 16:
                continue
            out.append((arb, bytes.fromhex(hex_data)))
    return out


def analyze_id(target_id):
    d7_counts = Counter()
    payload_d7s = {}  # payload -> set of D7 values
    n_frames = 0
    for d in CAPTURE_DIRS:
        log = REPO_ROOT / d / "capture.log"
        if not log.exists():
            continue
        for arb, data in parse_log(log):
            if arb != target_id:
                continue
            payload = bytes(data[:7])
            d7 = data[7]
            d7_counts[d7] += 1
            payload_d7s.setdefault(payload, set()).add(d7)
            n_frames += 1
    return n_frames, d7_counts, payload_d7s


def main():
    for tid in ("540", "450"):
        print(f"\n=== ID {tid} ===\n")
        n, d7s, p_d7s = analyze_id(tid)
        if n == 0:
            print(f"  no frames observed.")
            continue
        print(f"  {n} frames across {len(p_d7s)} distinct payloads.")
        print(f"  D7 value distribution (top 10):")
        for v, c in d7s.most_common(10):
            print(f"    0x{v:02X}: {c} ({100*c/n:.1f}%)")
        n_distinct_d7 = len(d7s)
        n_zero_d7 = d7s.get(0, 0)
        print(f"  distinct D7 values: {n_distinct_d7}")
        print(f"  fraction with D7==0x00: {100*n_zero_d7/n:.1f}%")

        # Cycle-model consistency check
        # For each frame, compute f(payload) and check if (D7 XOR f(payload))
        # ∈ CYCLE_SET. If yes, frame is consistent with the cycle model.
        consistent = 0
        for payload, d7_set in p_d7s.items():
            f_val = f(payload)
            for d7 in d7_set:
                # Count this payload→D7 combination as one observation
                # (we lose the count of how many frames had this pair, but
                # the model-consistency answer is about pairs, not counts)
                if (d7 ^ f_val) in CYCLE_SET:
                    consistent += 1
        total_pairs = sum(len(s) for s in p_d7s.values())
        print(f"  cycle-model consistency: {consistent}/{total_pairs} "
              f"distinct (payload, D7) pairs consistent "
              f"(D7 XOR f(payload) lands in cycle set)")
        if consistent == 0:
            print(f"  -> NOT cycle-family. D7 high-3 bits never match the cycle.")
        elif consistent == total_pairs:
            print(f"  -> consistent with cycle model.")
        else:
            print(f"  -> partial. Worth a closer look.")

        # Show a few example payload, D7, f(payload), D7 XOR f(payload)
        print(f"\n  Sample of payload → (D7, f(payload), D7 XOR f):")
        for i, (payload, d7_set) in enumerate(sorted(p_d7s.items())[:6]):
            f_val = f(payload)
            d7_list = sorted(d7_set)
            for d7 in d7_list[:2]:
                xor = d7 ^ f_val
                mark = " ∈ cycle" if xor in CYCLE_SET else ""
                print(f"    {payload.hex().upper()}  D7=0x{d7:02X}  "
                      f"f=0x{f_val:02X}  D7⊕f=0x{xor:02X}{mark}")


if __name__ == "__main__":
    main()
