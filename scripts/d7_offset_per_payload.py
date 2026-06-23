#!/usr/bin/env python3
"""d7_offset_per_payload.py — derive the D7 cycle offset for every
distinct (ID, D0..D6) payload observed in the captures, to distinguish
the two open hypotheses for what the "per-ID offset" really is:

  H1 (per-ID secret):  offset depends only on ID. Same ID, any payload
                       => same offset.
  H2 (payload hash):   offset is f(D0..D6). Same ID, different payload
                       => different offset.

The model in `docs/findings/can/byte-d7-cycle-hash.md` says:

    D7  =  cycle[counter mod 6]  XOR  offset  XOR  f(D0..D6)

For a *static-payload* window, `f(D0..D6)` is a constant and absorbs into
`offset`, so what we extract per window is really `offset XOR f(payload)`.
Under H1 this equals `offset_ID` for all payloads of an ID.
Under H2 this equals `f(payload)` and varies with payload.

Reference cycle (time-ordered, position 0..5) from the finding:

    [0x35, 0x5F, 0x6A, 0x8B, 0xBE, 0xD4]

Method: for each (ID, payload), find runs of >= MIN_RUN consecutive
frames sharing that exact payload. For each run, extract the first
MIN_RUN D7 values and fit (rotation r, xor c) such that
D7[i] == cycle[(r+i) % 6] XOR c. The resulting c is the per-window
"effective offset". Per ID, list the distinct values.

Output focus: ID 121, but reports for all 9 D7-cycle-candidate IDs.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]+)")

REFERENCE_CYCLE = [0x35, 0x5F, 0x6A, 0x8B, 0xBE, 0xD4]
CYCLE_LEN = 6
MIN_RUN = 6  # frames of identical payload required to fit (r, c) uniquely

TARGET_IDS = {"120", "121", "129", "12A", "12D", "12E", "541", "5A0", "5B0"}
FOCUS_ID = "121"

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


def parse_log(path: Path):
    """Yield (ts, arb_id_upper, data_bytes) in capture order."""
    out = []
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            ts = float(m.group(1))
            arb = m.group(2).upper()
            hex_data = m.group(3)
            if len(hex_data) != 16:  # 8 bytes
                continue
            data = bytes.fromhex(hex_data)
            out.append((ts, arb, data))
    return out


def fit_cycle(d7_seq):
    """Given >=MIN_RUN consecutive D7 bytes, find (r, c) such that
    d7_seq[i] == REFERENCE_CYCLE[(r+i) % 6] XOR c. Return c if unique,
    else None."""
    candidates = []
    for r in range(CYCLE_LEN):
        c = d7_seq[0] ^ REFERENCE_CYCLE[r]
        if all(d7_seq[i] == REFERENCE_CYCLE[(r + i) % CYCLE_LEN] ^ c
               for i in range(len(d7_seq))):
            candidates.append((r, c))
    if len(candidates) == 1:
        return candidates[0][1]
    return None


def collect_runs(frames, target_id):
    """For an ID, group its frames into runs of consecutive identical
    payloads (D0..D6). Returns list of (payload_bytes, [d7 values...]).

    "Consecutive" here means consecutive in this ID's broadcast stream,
    not in wall-clock — we drop frames of other IDs between."""
    runs = []
    current_payload = None
    current_d7s = []
    for _, arb, data in frames:
        if arb != target_id:
            continue
        payload = bytes(data[:7])
        d7 = data[7]
        if payload != current_payload:
            if current_payload is not None and current_d7s:
                runs.append((current_payload, current_d7s))
            current_payload = payload
            current_d7s = [d7]
        else:
            current_d7s.append(d7)
    if current_payload is not None and current_d7s:
        runs.append((current_payload, current_d7s))
    return runs


def analyze_id(frames_per_capture, target_id):
    """For one ID, scan every capture for fixed-payload runs >= MIN_RUN
    and fit an offset per run. Returns: dict[payload] -> set of offsets."""
    payload_offsets = defaultdict(set)
    payload_witnesses = defaultdict(list)  # (capture_name, offset, n_frames)
    for capture_name, frames in frames_per_capture.items():
        for payload, d7s in collect_runs(frames, target_id):
            if len(d7s) < MIN_RUN:
                continue
            # Try multiple non-overlapping windows in this run
            for start in range(0, len(d7s) - MIN_RUN + 1, MIN_RUN):
                window = d7s[start:start + MIN_RUN]
                c = fit_cycle(window)
                if c is None:
                    continue
                payload_offsets[payload].add(c)
                payload_witnesses[payload].append((capture_name, c, MIN_RUN))
    return payload_offsets, payload_witnesses


def main():
    captures = {}
    for d in CAPTURE_DIRS:
        log = REPO_ROOT / d / "capture.log"
        if not log.exists():
            continue
        captures[d] = parse_log(log)
    print(f"Loaded {len(captures)} captures, "
          f"{sum(len(v) for v in captures.values())} total frames.\n", flush=True)

    print(f"=== Focus: ID {FOCUS_ID} — does offset vary by payload? ===\n", flush=True)
    payload_offsets, witnesses = analyze_id(captures, FOCUS_ID)
    if not payload_offsets:
        print(f"  No fixed-payload runs of >={MIN_RUN} frames for {FOCUS_ID}.",
              flush=True)
    else:
        print(f"  {len(payload_offsets)} distinct payloads with fittable runs:\n",
              flush=True)
        for payload in sorted(payload_offsets.keys()):
            offsets = payload_offsets[payload]
            ws = witnesses[payload]
            ofs_str = ", ".join(f"0x{c:02X}" for c in sorted(offsets))
            n_windows = len(ws)
            print(f"    payload {payload.hex().upper()}  -> offset(s) {{{ofs_str}}}  "
                  f"({n_windows} windows)", flush=True)
        all_offsets = set()
        for s in payload_offsets.values():
            all_offsets |= s
        print(f"\n  Distinct offsets seen on {FOCUS_ID} across all payloads: "
              f"{sorted(f'0x{c:02X}' for c in all_offsets)}", flush=True)
        if len(all_offsets) == 1:
            print(f"  -> H1 SUPPORTED: offset stays constant across all payloads.",
                  flush=True)
        else:
            print(f"  -> H2 SUPPORTED: offset varies with payload "
                  f"({len(all_offsets)} distinct values).", flush=True)

    print(f"\n=== All {len(TARGET_IDS)} D7-cycle IDs — payload-offset map ===\n",
          flush=True)
    for tid in sorted(TARGET_IDS):
        po, _ = analyze_id(captures, tid)
        if not po:
            print(f"  {tid}: no fittable runs", flush=True)
            continue
        all_offsets = set()
        for s in po.values():
            all_offsets |= s
        ofs_str = ", ".join(f"0x{c:02X}" for c in sorted(all_offsets))
        verdict = "constant (H1)" if len(all_offsets) == 1 else f"varies ({len(all_offsets)} values, H2)"
        print(f"  {tid}: {len(po)} payloads, {len(all_offsets)} distinct offset(s) "
              f"{{{ofs_str}}}  -> {verdict}", flush=True)


if __name__ == "__main__":
    main()
