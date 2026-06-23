#!/usr/bin/env python3
"""d7_payload_hash_search.py — search for f(D0..D6) producing the 5-bit
D7 cycle offset, using the ~1500-pair constraint corpus extracted from
all captures.

Method
------

  1. Reconstruct (payload, f(payload)) constraints by replaying the
     per-payload extraction in `d7_offset_per_payload.py` internally:
     for every (ID, payload) with a run of >= MIN_RUN consecutive
     same-payload frames, fit the cycle to derive f(payload).
     Cross-ID consistency: same payload on different IDs must yield
     the same f — if any conflict, that itself disproves the
     "no per-ID component" model, and we halt and report.

  2. For each output bit b (0..4) of f, solve the GF(2) affine system

        XOR_{i in mask_b}(payload_bit_i)  XOR  const_b  =  f_bit_b(payload)

     over 56 input bits + 1 constant bit. ~1500 equations,
     57 unknowns; Gaussian elimination over GF(2) using bit-packed
     row integers. All 5 output bits solved simultaneously by carrying
     their RHS values in extra bits of each row.

  3. If GF(2)-affine fits all 5 bits: f is fully linear in the input
     bits, which subsumes every CRC-8 variant (CRC over fixed-length
     input is GF(2)-affine in the input bits). We print the masks.
     If any bit fails: report which, and try simple non-linear forms
     (byte-sum mod 32, byte-XOR fold) as a fallback.

Runtime: well under a second.
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
MIN_RUN = 6
TARGET_IDS = ["120", "121", "129", "12A", "12D", "12E", "541", "5A0", "5B0"]

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


# --- capture parsing and cycle-fitting (lifted from d7_offset_per_payload.py)

def parse_log(path: Path):
    out = []
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            arb = m.group(2).upper()
            hex_data = m.group(3)
            if len(hex_data) != 16:
                continue
            out.append((arb, bytes.fromhex(hex_data)))
    return out


def fit_cycle(d7_seq):
    """Return c such that d7_seq[i] = REFERENCE_CYCLE[(r+i) % 6] XOR c,
    if a unique (r, c) fits MIN_RUN samples."""
    cands = []
    for r in range(CYCLE_LEN):
        c = d7_seq[0] ^ REFERENCE_CYCLE[r]
        if all(d7_seq[i] == REFERENCE_CYCLE[(r + i) % CYCLE_LEN] ^ c
               for i in range(len(d7_seq))):
            cands.append(c)
    return cands[0] if len(cands) == 1 else None


def collect_runs(frames, target_id):
    runs = []
    current_payload = None
    current_d7s = []
    for arb, data in frames:
        if arb != target_id:
            continue
        payload = bytes(data[:7])
        d7 = data[7]
        if payload != current_payload:
            if current_payload is not None:
                runs.append((current_payload, current_d7s))
            current_payload = payload
            current_d7s = [d7]
        else:
            current_d7s.append(d7)
    if current_payload is not None:
        runs.append((current_payload, current_d7s))
    return runs


# --- constraint collection

def collect_constraints():
    """Return dict[payload_bytes] -> f_value. Halt with an explanation
    if the same payload yields different f-values across IDs or windows
    (would falsify the no-per-ID-component model)."""
    constraints = {}  # payload -> f
    witnesses = defaultdict(list)  # payload -> [(capture_dir, ID, f)]
    conflicts = []  # (payload, prev_f, new_f, prev_witness, new_witness)
    captures = {}
    for d in CAPTURE_DIRS:
        log = REPO_ROOT / d / "capture.log"
        if log.exists():
            captures[d] = parse_log(log)
    for cap_dir, frames in captures.items():
        for tid in TARGET_IDS:
            for payload, d7s in collect_runs(frames, tid):
                if len(d7s) < MIN_RUN:
                    continue
                for start in range(0, len(d7s) - MIN_RUN + 1, MIN_RUN):
                    c = fit_cycle(d7s[start:start + MIN_RUN])
                    if c is None:
                        continue
                    if payload in constraints and constraints[payload] != c:
                        conflicts.append((payload, constraints[payload], c,
                                          witnesses[payload][0], (cap_dir, tid)))
                    else:
                        constraints[payload] = c
                        witnesses[payload].append((cap_dir, tid))
    return constraints, witnesses, conflicts


# --- GF(2) bit-packed Gaussian elimination over multiple RHS columns

def gf2_solve_multi(rows, n_input_cols, n_rhs):
    """
    rows: iterable of Python ints encoded as:
      bits [0 .. n_input_cols-1]: input columns (incl. constant col last)
      bits [n_input_cols .. n_input_cols+n_rhs-1]: RHS columns
    Returns list of length n_rhs: each entry is (input_col_mask, None)
    when the corresponding system is solvable (free vars set to 0),
    or None when inconsistent.
    """
    rows = list(rows)
    n = len(rows)
    pivot_row_for_col = [-1] * n_input_cols
    next_row = 0
    for col in range(n_input_cols):
        col_bit = 1 << col
        pivot = -1
        for r in range(next_row, n):
            if rows[r] & col_bit:
                pivot = r
                break
        if pivot < 0:
            continue
        rows[next_row], rows[pivot] = rows[pivot], rows[next_row]
        pivot_row_for_col[col] = next_row
        pivot_row = rows[next_row]
        for r in range(n):
            if r != next_row and rows[r] & col_bit:
                rows[r] ^= pivot_row
        next_row += 1

    col_mask = (1 << n_input_cols) - 1
    results = []
    for b in range(n_rhs):
        rhs_bit = 1 << (n_input_cols + b)
        # consistency: any row with all-zero input cols but RHS bit set?
        consistent = True
        for r in range(next_row, n):
            if rows[r] & rhs_bit and (rows[r] & col_mask) == 0:
                consistent = False
                break
        if not consistent:
            results.append(None)
            continue
        sol = 0
        for col in range(n_input_cols):
            pr = pivot_row_for_col[col]
            if pr < 0:
                continue
            if rows[pr] & rhs_bit:
                sol |= 1 << col
        results.append(sol)
    return results


def encode_row(payload: bytes, f_val: int, n_input_bits: int, n_rhs: int) -> int:
    """Pack a constraint row: 56 payload bits, then constant (=1) bit,
    then 5 RHS bits (one per output bit)."""
    row = 0
    for byte_i, byte_v in enumerate(payload):
        for bit_i in range(8):
            if byte_v & (1 << bit_i):
                row |= 1 << (byte_i * 8 + bit_i)
    # constant column at index n_input_bits-1... wait, we put it as the LAST input col
    row |= 1 << (n_input_bits - 1)  # constant column always set
    for b in range(n_rhs):
        if (f_val >> b) & 1:
            row |= 1 << (n_input_bits + b)
    return row


def describe_mask(mask: int, n_payload_bits: int, const_col: int):
    """Render a mask over payload bits + constant bit as a human-readable string."""
    parts = []
    for i in range(n_payload_bits):
        if mask & (1 << i):
            byte_i = i // 8
            bit_i = i % 8
            parts.append(f"D{byte_i}.{bit_i}")
    if mask & (1 << const_col):
        parts.append("1")
    return " ⊕ ".join(parts) if parts else "0"


# --- non-linear fallbacks

def try_simple_nonlinear(constraints):
    print("\n  Non-linear sanity probes:", flush=True)
    samples = list(constraints.items())

    def fit_ratio(predictor):
        hits = sum(1 for p, f in samples if predictor(p) == f)
        return hits / len(samples)

    probes = [
        ("sum(D0..D6) & 0x1F", lambda p: sum(p) & 0x1F),
        ("XOR(D0..D6) & 0x1F", lambda p: (p[0] ^ p[1] ^ p[2] ^ p[3] ^ p[4] ^ p[5] ^ p[6]) & 0x1F),
        ("(sum + XOR) & 0x1F", lambda p: (sum(p) ^ (p[0] ^ p[1] ^ p[2] ^ p[3] ^ p[4] ^ p[5] ^ p[6])) & 0x1F),
        ("(D0+D1+...+D6) % 32 (decimal)", lambda p: sum(p) % 32),
        ("nibble-XOR of all bytes & 0x1F",
            lambda p: ((p[0] ^ p[1] ^ p[2] ^ p[3] ^ p[4] ^ p[5] ^ p[6]) ^
                       ((p[0] ^ p[1] ^ p[2] ^ p[3] ^ p[4] ^ p[5] ^ p[6]) >> 4)) & 0x1F),
    ]
    for name, fn in probes:
        r = fit_ratio(fn)
        marker = " <-- FIT" if r == 1.0 else ""
        print(f"    {name:48s}: {r*100:5.1f}% match{marker}", flush=True)


# --- main

def main():
    print("Collecting constraints from all captures…", flush=True)
    constraints, witnesses, conflicts = collect_constraints()
    print(f"  {len(constraints)} unique payloads with consistent f.", flush=True)
    if conflicts:
        print(f"\n  !! {len(conflicts)} cross-witness conflicts detected:", flush=True)
        for payload, prev_f, new_f, prev_w, new_w in conflicts[:5]:
            print(f"    payload {payload.hex().upper()}  "
                  f"prev f=0x{prev_f:02X} (witness {prev_w})  "
                  f"new f=0x{new_f:02X} (witness {new_w})", flush=True)
        print("    -> This falsifies the 'no per-ID component' model — investigate before trusting the affine search.",
              flush=True)
    print()

    # Encode constraints. 56 payload bits + 1 constant col + 5 RHS = 62 bits/row.
    N_PAYLOAD_BITS = 56
    N_INPUT_COLS = N_PAYLOAD_BITS + 1   # +1 for constant col
    CONST_COL = N_PAYLOAD_BITS          # constant column index
    N_RHS = 5

    rows = [encode_row(p, f, N_INPUT_COLS, N_RHS) for p, f in constraints.items()]

    print(f"Solving GF(2)-affine system: {len(rows)} equations × "
          f"{N_INPUT_COLS} unknowns × {N_RHS} output bits…", flush=True)
    sols = gf2_solve_multi(rows, N_INPUT_COLS, N_RHS)

    all_fit = all(s is not None for s in sols)
    for b, s in enumerate(sols):
        if s is None:
            print(f"  bit {b}: INCONSISTENT — no affine fit.", flush=True)
        else:
            input_mask = s & ((1 << N_PAYLOAD_BITS) - 1)
            const_bit = (s >> CONST_COL) & 1
            popcount = bin(input_mask).count("1")
            print(f"  bit {b}: FIT. popcount={popcount}  const={const_bit}",
                  flush=True)
            print(f"    = {describe_mask(s, N_PAYLOAD_BITS, CONST_COL)}",
                  flush=True)

    if all_fit:
        print("\n  --> f is GF(2)-affine in D0..D6. Verifying on all constraints…",
              flush=True)
        ok = 0
        bad = 0
        for p, f in constraints.items():
            row = encode_row(p, 0, N_INPUT_COLS, N_RHS)
            recon = 0
            for b in range(N_RHS):
                sol = sols[b]
                # apply mask: parity of (row & sol_input_cols)
                v = row & sol & ((1 << N_INPUT_COLS) - 1)
                par = bin(v).count("1") & 1
                recon |= par << b
            if recon == f:
                ok += 1
            else:
                bad += 1
        print(f"    verification: {ok} OK / {bad} mismatch (of {ok + bad}).",
              flush=True)
    else:
        print("\n  --> f is NOT GF(2)-affine in D0..D6. Standard CRC-8 ruled out.",
              flush=True)
        try_simple_nonlinear(constraints)


if __name__ == "__main__":
    main()
