#!/usr/bin/env python3
"""d7_algorithm.py — reproduce the D7 checksum algorithm, or refute the hypothesis.

Three passes against every capture on disk:

  A. Polynomial-fit search for the 9 D7-checksum-candidate IDs (120, 121, 129,
     12A, 12D, 12E, 541, 5A0, 5B0). Tries a list of standard automotive CRC-8
     variants, simple XOR fold, and J1939-style additive checksum, with global
     seeds first, then per-ID seeds, then with the CAN ID byte prepended.

  B. `12D` D7 time-series — counter (mod N) vs checksum. Uses the long, steady
     idle-run-1 capture for a clean delta sequence over ~10 s of `12D` frames.

  C. Same winning algorithm applied to `540` and `450` D7 (excluded from the
     original hypothesis because of payload sparsity; now retestable with the
     wider corpus).

Reads every capture in logs/ that contains frames. No arguments; prints to
stdout in three blocks.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

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
]

CHECKSUM_HYPOTHESIS_IDS = ["120", "121", "129", "12A", "12D", "12E", "541", "5A0", "5B0"]
PART_C_IDS = ["540", "450"]


# Standard automotive CRC-8 variants: (name, poly, init, refin, refout, xorout)
CRC8_VARIANTS = [
    ("CRC-8/SMBUS",     0x07, 0x00, False, False, 0x00),
    ("CRC-8/ITU",       0x07, 0x00, False, False, 0x55),
    ("CRC-8/ROHC",      0x07, 0xFF, True,  True,  0x00),
    ("CRC-8/SAE-J1850", 0x1D, 0xFF, False, False, 0xFF),
    ("CRC-8/SAE-J1850-ZERO", 0x1D, 0x00, False, False, 0x00),
    ("CRC-8/I-CODE",    0x1D, 0xFD, False, False, 0x00),
    ("CRC-8/AUTOSAR",   0x2F, 0xFF, False, False, 0xFF),
    ("CRC-8/MAXIM",     0x31, 0x00, True,  True,  0x00),
    ("CRC-8/DARC",      0x39, 0x00, True,  True,  0x00),
    ("CRC-8/WCDMA",     0x9B, 0x00, True,  True,  0x00),
    ("CRC-8/CDMA2000",  0x9B, 0xFF, False, False, 0x00),
    ("CRC-8/NRSC-5",    0x31, 0xFF, False, False, 0x00),
    ("CRC-8/MIFARE",    0x1D, 0xC7, False, False, 0x00),
    ("CRC-8/BLUETOOTH", 0xA7, 0x00, True,  True,  0x00),
    ("CRC-8/HITAG",     0x1D, 0xFF, False, False, 0x00),
]


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


def reflect8(b: int) -> int:
    r = 0
    for _ in range(8):
        r = (r << 1) | (b & 1)
        b >>= 1
    return r


def crc8_table(poly: int, refin: bool):
    """Build a 256-entry CRC-8 lookup table."""
    table = [0] * 256
    if refin:
        rpoly = reflect8(poly)
        for b in range(256):
            crc = b
            for _ in range(8):
                crc = (crc >> 1) ^ rpoly if crc & 1 else crc >> 1
            table[b] = crc
    else:
        for b in range(256):
            crc = b
            for _ in range(8):
                crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
            table[b] = crc
    return tuple(table)


def crc8_compute(data: bytes, table, init: int, refin: bool, refout: bool, xorout: int) -> int:
    crc = init
    if refin:
        for b in data:
            crc = table[crc ^ b]
        # When refin matches refout (both True), the LSB-first computation is correct.
        # When they differ, reflect the output.
        if not refout:
            crc = reflect8(crc)
    else:
        for b in data:
            crc = table[crc ^ b]
        if refout:
            crc = reflect8(crc)
    return crc ^ xorout


def xor_fold(data: bytes, init: int = 0) -> int:
    r = init
    for b in data:
        r ^= b
    return r


def j1939_sum(data: bytes, init: int = 0) -> int:
    return (sum(data) + init) & 0xFF


def j1939_sum_complement(data: bytes, init: int = 0) -> int:
    return ((sum(data) + init) ^ 0xFF) & 0xFF


# ---------- Frame corpus assembly ----------

def build_corpus():
    """corpus[arb] = set of (D0..D6 tuple, D7) pairs across all captures."""
    corpus: dict[str, set] = defaultdict(set)
    for d in CAPTURE_DIRS:
        path = REPO_ROOT / d / "capture.log"
        if not path.exists():
            continue
        for _ts, arb, data in parse_log(path):
            corpus[arb].add((bytes(data[:7]), data[7]))
    return corpus


# ---------- Part A: polynomial-fit search ----------

def test_crc8_global(corpus, ids, name, poly, init, refin, refout, xorout):
    """Return (per-ID match counts, total_matches, total_frames) for this variant."""
    table = crc8_table(poly, refin)
    per_id = {}
    tot_match = 0
    tot_n = 0
    for arb in ids:
        frames = corpus.get(arb, ())
        match = 0
        for d, expected in frames:
            if crc8_compute(d, table, init, refin, refout, xorout) == expected:
                match += 1
        per_id[arb] = (match, len(frames))
        tot_match += match
        tot_n += len(frames)
    return per_id, tot_match, tot_n


def test_crc8_with_id_byte(corpus, ids, name, poly, init, refin, refout, xorout, prepend=True):
    """Like test_crc8_global but with the low byte of the arbitration ID included."""
    table = crc8_table(poly, refin)
    per_id = {}
    tot_match = 0
    tot_n = 0
    for arb in ids:
        id_byte = int(arb, 16) & 0xFF
        frames = corpus.get(arb, ())
        match = 0
        for d, expected in frames:
            payload = bytes([id_byte]) + d if prepend else d + bytes([id_byte])
            if crc8_compute(payload, table, init, refin, refout, xorout) == expected:
                match += 1
        per_id[arb] = (match, len(frames))
        tot_match += match
        tot_n += len(frames)
    return per_id, tot_match, tot_n


def test_xor_fold(corpus, ids, init=0):
    per_id = {}
    tot_match = 0
    tot_n = 0
    for arb in ids:
        frames = corpus.get(arb, ())
        match = sum(1 for d, exp in frames if xor_fold(d, init) == exp)
        per_id[arb] = (match, len(frames))
        tot_match += match
        tot_n += len(frames)
    return per_id, tot_match, tot_n


def test_j1939_sum(corpus, ids, init=0, complement=False):
    fn = j1939_sum_complement if complement else j1939_sum
    per_id = {}
    tot_match = 0
    tot_n = 0
    for arb in ids:
        frames = corpus.get(arb, ())
        match = sum(1 for d, exp in frames if fn(d, init) == exp)
        per_id[arb] = (match, len(frames))
        tot_match += match
        tot_n += len(frames)
    return per_id, tot_match, tot_n


def test_per_id_seed_search(corpus, arb, poly, refin, refout, xorout):
    """For one ID, search init in 0..255 for best fit. Returns (best_init, match, n)."""
    table = crc8_table(poly, refin)
    frames = corpus.get(arb, ())
    if not frames:
        return None, 0, 0
    best = (None, -1)
    for init in range(256):
        m = sum(1 for d, exp in frames if crc8_compute(d, table, init, refin, refout, xorout) == exp)
        if m > best[1]:
            best = (init, m)
    return best[0], best[1], len(frames)


def analysis_a_polynomial_fit(corpus):
    print("=" * 78)
    print("# Part A — single-polynomial fit on the 9 D7-checksum-candidate IDs")
    print("=" * 78)
    print()
    ids = CHECKSUM_HYPOTHESIS_IDS

    print("## A.1 — Global parameterisation (same seed/poly/refl across all 9 IDs)")
    print()
    print(f"{'algorithm':<30} {'aggregate':>15}  {'per-ID hit rate':<60}")

    # CRC-8 variants, no ID byte
    results = []
    for name, poly, init, refin, refout, xorout in CRC8_VARIANTS:
        per_id, tot_match, tot_n = test_crc8_global(corpus, ids, name, poly, init, refin, refout, xorout)
        results.append((name, per_id, tot_match, tot_n, ("plain", poly, init, refin, refout, xorout)))

    # XOR folds
    for init in (0x00, 0xFF):
        per_id, tm, tn = test_xor_fold(corpus, ids, init)
        results.append((f"XOR fold init=0x{init:02X}", per_id, tm, tn, ("xor", init)))

    # J1939 sums
    for init in (0x00, 0xFF):
        for compl in (False, True):
            per_id, tm, tn = test_j1939_sum(corpus, ids, init, compl)
            name = f"J1939 sum init=0x{init:02X}{' (complement)' if compl else ''}"
            results.append((name, per_id, tm, tn, ("j1939", init, compl)))

    # Sort by total hit rate, descending
    results.sort(key=lambda r: -r[2] / max(r[3], 1))
    for name, per_id, tm, tn, _ in results:
        pct = tm / tn * 100 if tn else 0
        per_id_s = " ".join(f"{arb}:{m}/{n}" for arb, (m, n) in per_id.items())
        print(f"{name:<30} {tm:>8}/{tn:<6} ({pct:5.1f}%)  {per_id_s}")
    print()

    best_global = results[0]
    best_pct = best_global[2] / max(best_global[3], 1) * 100
    print(f"Best global: **{best_global[0]}** at {best_pct:.1f}% aggregate.")
    if best_pct >= 99.0:
        print("VERDICT: Single-algorithm global fit ≥99%. Hypothesis confirmed with algorithm.")
        return best_global
    print(f"Best global is below 99% — proceeding to per-ID seed search and ID-byte inclusion.")
    print()

    # A.2: Per-ID seed search for the top few polynomials
    print("## A.2 — Per-ID seed search over the top CRC-8 polynomials")
    print()
    print("For each (poly, refin, refout, xorout), search init in 0..255 per-ID and report best fit.")
    print()
    top_polys = []
    seen = set()
    for name, _per, tm, tn, params in results:
        if params[0] != "plain":
            continue
        key = params[1:]  # (poly, init, refin, refout, xorout) — but we want to ignore init here
        sig = (params[1], params[3], params[4], params[5])  # (poly, refin, refout, xorout)
        if sig in seen:
            continue
        seen.add(sig)
        top_polys.append((name, params[1], params[3], params[4], params[5]))
        if len(top_polys) >= 6:
            break

    perid_best = []
    for name, poly, refin, refout, xorout in top_polys:
        print(f"### {name}  (poly=0x{poly:02X}, refin={refin}, refout={refout}, xorout=0x{xorout:02X})")
        total_match = 0
        total_n = 0
        for arb in ids:
            best_init, match, n = test_per_id_seed_search(corpus, arb, poly, refin, refout, xorout)
            pct = match / n * 100 if n else 0
            seed_s = f"0x{best_init:02X}" if best_init is not None else "—"
            print(f"  {arb}  best_init={seed_s}  {match}/{n} ({pct:5.1f}%)")
            total_match += match
            total_n += n
        print(f"  TOTAL with per-ID seeds: {total_match}/{total_n} ({total_match/max(total_n,1)*100:.1f}%)")
        print()
        perid_best.append((name, poly, refin, refout, xorout, total_match, total_n))

    perid_best.sort(key=lambda r: -r[5] / max(r[6], 1))
    best_perid = perid_best[0]
    best_perid_pct = best_perid[5] / max(best_perid[6], 1) * 100
    print(f"Best per-ID-seed: **{best_perid[0]}** at {best_perid_pct:.1f}% aggregate.")
    print()

    # A.3: ID-byte included
    print("## A.3 — With CAN ID low byte prepended/appended (AUTOSAR E2E-style)")
    print()
    id_byte_results = []
    for name, poly, init, refin, refout, xorout in CRC8_VARIANTS:
        for prepend in (True, False):
            per_id, tm, tn = test_crc8_with_id_byte(corpus, ids, name, poly, init, refin, refout, xorout, prepend=prepend)
            tag = "prepend" if prepend else "append"
            id_byte_results.append((f"{name} (id-{tag})", per_id, tm, tn))
    id_byte_results.sort(key=lambda r: -r[2] / max(r[3], 1))
    print(f"{'algorithm':<40} {'aggregate':>15}")
    for name, _per, tm, tn in id_byte_results[:6]:
        pct = tm / tn * 100 if tn else 0
        print(f"{name:<40} {tm:>8}/{tn:<6} ({pct:5.1f}%)")
    print()
    best_id = id_byte_results[0]
    best_id_pct = best_id[2] / max(best_id[3], 1) * 100
    print(f"Best with ID byte: **{best_id[0]}** at {best_id_pct:.1f}% aggregate.")
    print()

    return None


# ---------- Part B: 12D D7 character ----------

def analysis_b_12d_character():
    print("=" * 78)
    print("# Part B — `12D` D7 character (counter vs checksum)")
    print("=" * 78)
    print()
    # Pull a steady idle window from idle-run-1
    path = REPO_ROOT / "logs/2026-06-17-engine-idle-run-1/capture.log"
    frames = parse_log(path)
    # Take a 10-second slice from mid-capture for stable behaviour
    if not frames:
        print("No frames in idle-run-1; skipping.")
        return
    t0 = frames[0][0]
    window = [b for ts, arb, b in frames if arb == "12D" and t0 + 60 <= ts < t0 + 70]
    print(f"Window: 10 s mid-capture of idle-run-1, `12D` frames: {len(window)}")
    d7_seq = [b[7] for b in window]
    print(f"Distinct D7 values seen: {sorted(set(d7_seq))}  (count = {len(set(d7_seq))})")
    print()

    print("## Counter test: (D7[i+1] - D7[i]) mod N for N in {2,3,5,6,7,8,14,16}")
    diffs_raw = [(d7_seq[i+1] - d7_seq[i]) % 256 for i in range(len(d7_seq) - 1)]
    for N in (2, 3, 5, 6, 7, 8, 14, 16):
        mod_diffs = [(d7_seq[i+1] - d7_seq[i]) % N for i in range(len(d7_seq) - 1)]
        c = Counter(mod_diffs)
        most = c.most_common(1)[0]
        pct = most[1] / len(mod_diffs) * 100
        print(f"  N={N:<3}  most-common diff = {most[0]} ({pct:5.1f}%)  full dist = {dict(c.most_common(5))}")
    print()

    # Mod-256 raw distribution
    c = Counter(diffs_raw)
    print(f"Raw (mod 256) diff distribution (top 8): {dict(c.most_common(8))}")
    print()

    # Time-series scatter — first 100 frames
    print("Time-series of D7 over first 100 frames (compact):")
    for i in range(0, min(100, len(d7_seq)), 10):
        chunk = d7_seq[i:i+10]
        print(f"  [{i:>3}..]  " + " ".join(f"0x{v:02X}" for v in chunk))
    print()

    # D0..D6 inspection — is it really static?
    payloads = Counter(bytes(b[:7]) for b in window)
    print(f"Distinct D0..D6 payloads in window: {len(payloads)}")
    for payload, n in payloads.most_common(5):
        print(f"  {payload.hex(' ')} → {n} frames")
    print()


# ---------- Part C: 540 and 450 ----------

def analysis_c_540_450(corpus, best_params=None):
    print("=" * 78)
    print("# Part C — apply best algorithm to `540` and `450` D7")
    print("=" * 78)
    print()
    if best_params is None:
        print("(No single-polynomial fit was identified in Part A — skipping per-ID re-fit;")
        print(" instead show the same wide CRC-8 sweep against 540 and 450 for completeness.)")
        print()
        for arb in PART_C_IDS:
            frames = corpus.get(arb, ())
            print(f"## {arb}  (corpus size: {len(frames)} distinct (D0..D6,D7) tuples)")
            results = []
            for name, poly, init, refin, refout, xorout in CRC8_VARIANTS:
                table = crc8_table(poly, refin)
                m = sum(1 for d, exp in frames if crc8_compute(d, table, init, refin, refout, xorout) == exp)
                results.append((name, m, len(frames), (poly, init, refin, refout, xorout)))
            # Also per-ID seed search top 3 polys
            results.sort(key=lambda r: -r[1])
            print(f"  {'algorithm':<25} {'match':>10}")
            for name, m, n, _ in results[:5]:
                pct = m / n * 100 if n else 0
                print(f"  {name:<25} {m:>5}/{n:<5} ({pct:5.1f}%)")
            # Best per-ID seed for top poly
            top_poly, _, refin, refout, xorout = results[0][3]
            best_init, m, n = test_per_id_seed_search(corpus, arb, top_poly, refin, refout, xorout)
            print(f"  Per-ID seed search on top poly: init=0x{best_init:02X}, {m}/{n} ({m/max(n,1)*100:.1f}%)")
            print()


def analysis_d_cycle_check():
    """Per-ID D7 cycle verification — is the observed 6-value set a fixed cycle of length 6,
    cycle-locked across captures, on every static-payload ID? Also surfaces the cycles for
    active-payload IDs by restricting to frames where D0..D6 is constant."""
    print("=" * 78)
    print("# Part D — D7 cycle verification across IDs")
    print("=" * 78)
    print()
    print("For each ID, pull a steady 5-second window from idle-run-1 and tabulate:")
    print("  - the distinct D0..D6 payloads observed (for cycle-isolation)")
    print("  - the D7 sequence per payload")
    print("  - the cycle period (if any) of D7 within constant-payload runs")
    print()

    frames_all = parse_log(REPO_ROOT / "logs/2026-06-17-engine-idle-run-1/capture.log")
    t0 = frames_all[0][0]
    window = [(ts, arb, b) for ts, arb, b in frames_all if t0 + 60 <= ts < t0 + 65]

    all_ids = CHECKSUM_HYPOTHESIS_IDS + PART_C_IDS
    for arb in all_ids:
        sel = [(ts, b) for ts, a, b in window if a == arb]
        if not sel:
            print(f"## {arb}: no frames in window")
            continue
        payloads = Counter(bytes(b[:7]) for _, b in sel)
        most_payload, n = payloads.most_common(1)[0]
        # Restrict to frames with the most-common D0..D6 to isolate the cycle
        cycle_frames = [b[7] for _, b in sel if bytes(b[:7]) == most_payload]
        distinct_d7 = sorted(set(cycle_frames))
        # Find cycle period: smallest k where cycle_frames[i+k] == cycle_frames[i] for all i
        period = None
        for k in range(1, min(20, len(cycle_frames) // 2)):
            if all(cycle_frames[i] == cycle_frames[i + k] for i in range(len(cycle_frames) - k)):
                period = k
                break
        # Extract the first `period` D7 values as the cycle
        cycle = cycle_frames[:period] if period else cycle_frames[:6]
        print(f"## {arb}  frames={len(sel)}  distinct D0..D6={len(payloads)}  "
              f"dominant payload {most_payload.hex(' ')} ({n}x)")
        print(f"  D7 distinct values: {[f'0x{v:02X}' for v in distinct_d7]}  (n={len(distinct_d7)})")
        if period:
            print(f"  Cycle period: {period}  →  cycle = {[f'0x{v:02X}' for v in cycle]}")
        else:
            print(f"  No cycle period found in window")
        print()


def analysis_i_payload_function_search():
    """Revised hypothesis: D7 = cycle[counter mod 6] XOR f(D0..D6), no per-ID secret.
    Test by computing f(dominant_payload_per_ID) against the observed offsets."""
    print("=" * 78)
    print("# Part I — payload-function search: is f(D0..D6) the only modulation?")
    print("=" * 78)
    print()
    # Observed (dominant payload, offset) pairs from Parts F + H
    observations = [
        ("120", bytes.fromhex("00000000000000"), 0x00),
        ("121", bytes.fromhex("00000000048800"), 0x08),
        ("129", bytes.fromhex("00000001000000"), 0x04),
        ("12A", bytes.fromhex("100500000a00")    + b"\x00", 0x08),
        ("12D", bytes.fromhex("00000000000000"), 0x00),
        ("12E", bytes.fromhex("00000000000000")[:6] + b"\xC0", 0x1B),
        ("541", bytes.fromhex("0000100000")[:5]  + b"\x1B\x00", 0x15),
        ("5A0", bytes.fromhex("0000000004")     + b"\x00\x00", 0x0E),
        ("5B0", bytes.fromhex("10000000000000"), 0x01),
    ]
    # Sanity-fix the payload bytes (the hex.fromhex shortcuts above are error-prone).
    observations = [
        ("120", b"\x00\x00\x00\x00\x00\x00\x00", 0x00),
        ("121", b"\x00\x00\x00\x00\x04\x88\x00", 0x08),
        ("129", b"\x00\x00\x00\x01\x00\x00\x00", 0x04),
        ("12A", b"\x10\x05\x00\x00\x00\x0A\x00", 0x08),
        ("12D", b"\x00\x00\x00\x00\x00\x00\x00", 0x00),
        ("12E", b"\x00\x00\x00\x00\x00\x00\xC0", 0x1B),
        ("541", b"\x00\x00\x10\x00\x1B\x00\x00", 0x15),
        ("5A0", b"\x00\x00\x00\x00\x04\x00\x00", 0x0E),
        ("5B0", b"\x10\x00\x00\x00\x00\x00\x00", 0x01),
    ]
    print("Observation set (payload, observed offset):")
    for arb, p, o in observations:
        print(f"  {arb}: payload={p.hex(' ')}  offset=0x{o:02X}")
    print()

    # Try each standard CRC-8 variant on the payloads, looking for one where
    # crc(payload) == offset for ALL 9 observations.
    print(f"## I.1 — Standard CRC-8 variants on D0..D6 alone")
    print()
    print(f"{'algorithm':<30}  {'match count':>12}  {'per-ID':>5}")
    results = []
    for name, poly, init, refin, refout, xorout in CRC8_VARIANTS:
        table = crc8_table(poly, refin)
        per_id = []
        match = 0
        for arb, p, o in observations:
            crc = crc8_compute(p, table, init, refin, refout, xorout)
            ok = (crc == o)
            per_id.append(f"{arb}:{'✓' if ok else f'{crc:02X}'}")
            if ok:
                match += 1
        results.append((name, match, per_id, (poly, init, refin, refout, xorout)))
    results.sort(key=lambda r: -r[1])
    for name, m, per_id, _ in results[:6]:
        print(f"{name:<30}  {m:>5}/9      {' '.join(per_id)}")
    print()

    best = results[0]
    print(f"Best plain CRC-8: **{best[0]}** at {best[1]}/9.")
    if best[1] == 9:
        print(f"VERDICT: full algorithm identified. D7 = cycle[counter mod 6] XOR {best[0]}(D0..D6).")
        return best
    print()

    # I.2: brute-force every polynomial × init × reflection × xorout
    print(f"## I.2 — Exhaustive CRC-8 search for one variant that fits all 9 observations")
    print()
    found = []
    for poly in range(1, 256):
        for refin in (False, True):
            table = crc8_table(poly, refin)
            for refout in (False, True):
                for init in range(256):
                    for xorout in (0x00, 0xFF):
                        ok = True
                        for arb, p, o in observations:
                            if crc8_compute(p, table, init, refin, refout, xorout) != o:
                                ok = False
                                break
                        if ok:
                            found.append((poly, init, refin, refout, xorout))
                            if len(found) >= 20:
                                break
                    if len(found) >= 20:
                        break
                if len(found) >= 20:
                    break
            if len(found) >= 20:
                break
        if len(found) >= 20:
            break
    if not found:
        # Try a relaxed search: at least 8/9 matches
        print("No exact 9/9 fit. Searching for 8/9 (one tolerated mismatch) …")
        partial = []
        for poly in range(1, 256):
            for refin in (False, True):
                table = crc8_table(poly, refin)
                for refout in (False, True):
                    for init in range(256):
                        for xorout in (0x00, 0xFF):
                            match = 0
                            for arb, p, o in observations:
                                if crc8_compute(p, table, init, refin, refout, xorout) == o:
                                    match += 1
                            if match >= 8:
                                partial.append((match, poly, init, refin, refout, xorout))
        partial.sort(key=lambda r: -r[0])
        if partial:
            print(f"Found {len(partial)} parameterisation(s) matching ≥8/9:")
            for m, poly, init, refin, refout, xorout in partial[:10]:
                print(f"  match={m}/9  poly=0x{poly:02X} init=0x{init:02X} refin={refin} "
                      f"refout={refout} xorout=0x{xorout:02X}")
        else:
            print("No CRC-8 variant matches even 8/9. Algorithm is not a CRC-8 over D0..D6 alone.")
        return None
    print(f"Found {len(found)} exact 9/9 fit(s):")
    for poly, init, refin, refout, xorout in found:
        print(f"  poly=0x{poly:02X} init=0x{init:02X} refin={refin} refout={refout} xorout=0x{xorout:02X}")
    print()
    print(f"VERDICT: D7 algorithm reproduced. f(D0..D6) = CRC-8(poly=0x{found[0][0]:02X}, "
          f"init=0x{found[0][1]:02X}, refin={found[0][2]}, refout={found[0][3]}, "
          f"xorout=0x{found[0][4]:02X}).")
    print(f"         D7 = cycle[counter mod 6] XOR f(D0..D6), no per-ID secret.")
    return found[0]


def analysis_j_extended_payload_search():
    """Extended search: CRC-8 variants over D0..D6 with reverse byte order, plus
    Pearson-style searches and direct table-constraint solving."""
    print("=" * 78)
    print("# Part J — extended payload-function search (reverse order, Pearson, tables)")
    print("=" * 78)
    print()
    observations = [
        ("120", b"\x00\x00\x00\x00\x00\x00\x00", 0x00),
        ("121", b"\x00\x00\x00\x00\x04\x88\x00", 0x08),
        ("129", b"\x00\x00\x00\x01\x00\x00\x00", 0x04),
        ("12A", b"\x10\x05\x00\x00\x00\x0A\x00", 0x08),
        ("12D", b"\x00\x00\x00\x00\x00\x00\x00", 0x00),
        ("12E", b"\x00\x00\x00\x00\x00\x00\xC0", 0x1B),
        ("541", b"\x00\x00\x10\x00\x1B\x00\x00", 0x15),
        ("5A0", b"\x00\x00\x00\x00\x04\x00\x00", 0x0E),
        ("5B0", b"\x10\x00\x00\x00\x00\x00\x00", 0x01),
    ]

    # J.1: reverse byte order
    print("## J.1 — CRC-8 with reversed byte order")
    print()
    print(f"{'algorithm':<30}  {'match':>5}  per-ID")
    rev_results = []
    for name, poly, init, refin, refout, xorout in CRC8_VARIANTS:
        table = crc8_table(poly, refin)
        per_id = []
        match = 0
        for arb, p, o in observations:
            crc = crc8_compute(p[::-1], table, init, refin, refout, xorout)
            ok = (crc == o)
            per_id.append(f"{arb}:{'✓' if ok else f'{crc:02X}'}")
            if ok:
                match += 1
        rev_results.append((name, match, per_id))
    rev_results.sort(key=lambda r: -r[1])
    for name, m, per_id in rev_results[:5]:
        print(f"{name:<30}  {m:>3}/9   {' '.join(per_id)}")
    print()

    # J.2: exhaustive reverse-order search
    print("## J.2 — Exhaustive CRC-8 search with reversed byte order")
    print()
    found = []
    for poly in range(1, 256):
        for refin in (False, True):
            table = crc8_table(poly, refin)
            for refout in (False, True):
                for init in range(256):
                    for xorout in (0x00, 0xFF):
                        ok = True
                        for arb, p, o in observations:
                            if crc8_compute(p[::-1], table, init, refin, refout, xorout) != o:
                                ok = False
                                break
                        if ok:
                            found.append((poly, init, refin, refout, xorout))
                            if len(found) >= 10:
                                break
                    if len(found) >= 10:
                        break
                if len(found) >= 10:
                    break
            if len(found) >= 10:
                break
        if len(found) >= 10:
            break
    if found:
        print(f"Found {len(found)} 9/9 fit(s) with reverse byte order!")
        for poly, init, refin, refout, xorout in found:
            print(f"  poly=0x{poly:02X} init=0x{init:02X} refin={refin} refout={refout} xorout=0x{xorout:02X}")
        print()
        return found[0]
    print("No 9/9 reverse-order CRC-8 fit either.")
    print()

    # J.3: derive table constraints from single-non-zero-byte observations
    print("## J.3 — Direct table-constraint analysis from single-non-zero-byte payloads")
    print()
    print("Assuming standard byte order, init=0, refin=False, refout=False, xorout=0,")
    print("a CRC's table T must satisfy these constraints:")
    print()
    constraints = [
        ("12E", 0xC0, 6, 0x1B),
        ("5A0", 0x04, 4, 0x0E),
        ("129", 0x01, 3, 0x04),
        ("5B0", 0x10, 0, 0x01),
    ]
    for arb, byte, pos, target in constraints:
        n_apps = 7 - pos  # number of T applications after the first nonzero byte
        print(f"  {arb}: byte 0x{byte:02X} at position {pos} → T^{n_apps}[0x{byte:02X}] = 0x{target:02X}")
    print()
    # For each polynomial 1..255, build table and check constraints
    print("Searching all 255 polys (refin=False, init=0) for one that satisfies all 4 constraints:")
    matches = []
    for poly in range(1, 256):
        table = crc8_table(poly, False)
        ok_count = 0
        for arb, byte, pos, target in constraints:
            v = byte
            for _ in range(7 - pos):
                v = table[v]
            if v == target:
                ok_count += 1
        if ok_count >= 3:
            matches.append((poly, ok_count))
    matches.sort(key=lambda r: -r[1])
    if matches:
        print(f"  Top candidates (≥3 constraints satisfied):")
        for poly, m in matches[:5]:
            print(f"    poly=0x{poly:02X}: {m}/4 constraints")
    else:
        print(f"  No polynomial satisfies even 3/4 constraints.")
    print()

    # Same with refin=True
    print("Same with refin=True (LSB-first byte processing):")
    matches = []
    for poly in range(1, 256):
        table = crc8_table(poly, True)
        ok_count = 0
        for arb, byte, pos, target in constraints:
            v = byte
            for _ in range(7 - pos):
                v = table[v]
            if v == target:
                ok_count += 1
        if ok_count >= 3:
            matches.append((poly, ok_count))
    matches.sort(key=lambda r: -r[1])
    if matches:
        print(f"  Top candidates (≥3 constraints satisfied):")
        for poly, m in matches[:5]:
            print(f"    poly=0x{poly:02X}: {m}/4 constraints")
    else:
        print(f"  No polynomial satisfies even 3/4 constraints.")
    print()

    # Reverse-order interpretation:
    # If bytes are processed in reverse, then for byte at position p (in original order),
    # T applications BEFORE the byte = p (since we process the trailing zeros first).
    print("Reverse byte order (bytes processed right-to-left):")
    print("  For byte at position p, T applications BEFORE the nonzero byte = p (trailing zeros first).")
    print("  After the nonzero byte, no more nonzero bytes follow, so result = T^0[T(byte)] after T(byte).")
    print("  Actually: state evolves as state = table[state XOR byte], so after processing the")
    print("  nonzero byte at LSB-end (after p zeros from the right), state = table[byte] if init=0.")
    print()
    print("  In reverse order, position p (0=first nonzero from the left in original) means")
    print("  (6 - p) trailing zeros, then the byte. So state after byte = table[byte].")
    print("  Then process 0..p more zeros, giving state = table^(p+1)[byte].")
    print()
    constraints_rev = []
    for arb, byte, pos, target in constraints:
        # In original order, the nonzero byte is at index `pos` (0-indexed).
        # Reverse-order processing: first process positions 6, 5, ..., pos+1 (all zeros, total 6-pos),
        # then process position `pos` (the nonzero byte), then positions pos-1, ..., 0 (all zeros, total pos).
        # If init=0 and table[0]=0, then initial zeros don't change state.
        # After processing the nonzero byte: state = table[byte].
        # After remaining `pos` zeros: state = table^(pos+1)[byte] if pos>0, or table[byte] if pos==0.
        # Wait, table[0] = 0 only if init=0 AND poly's table[0] = 0 (which is true for any normal CRC).
        # So initial zeros leave state=0. Then byte → table[byte]. Then `pos` more zeros: each is
        # state = table[state XOR 0] = table[state], so state = table^(pos+1)[byte] after total processing.
        n_apps = pos + 1
        constraints_rev.append((arb, byte, n_apps, target))
        print(f"  {arb}: T^{n_apps}[0x{byte:02X}] = 0x{target:02X}")
    print()

    print("Searching all 255 polys (refin=False, init=0) for reverse-order constraints:")
    matches = []
    for poly in range(1, 256):
        table = crc8_table(poly, False)
        ok_count = 0
        for arb, byte, n_apps, target in constraints_rev:
            v = byte
            for _ in range(n_apps):
                v = table[v]
            if v == target:
                ok_count += 1
        if ok_count >= 3:
            matches.append((poly, ok_count))
    matches.sort(key=lambda r: -r[1])
    if matches:
        print(f"  Top candidates:")
        for poly, m in matches[:10]:
            print(f"    poly=0x{poly:02X}: {m}/4 constraints")
    else:
        print(f"  No polynomial satisfies even 3/4 constraints.")
    print()

    print("Searching all 255 polys (refin=True, init=0) for reverse-order constraints:")
    matches = []
    for poly in range(1, 256):
        table = crc8_table(poly, True)
        ok_count = 0
        for arb, byte, n_apps, target in constraints_rev:
            v = byte
            for _ in range(n_apps):
                v = table[v]
            if v == target:
                ok_count += 1
        if ok_count >= 3:
            matches.append((poly, ok_count))
    matches.sort(key=lambda r: -r[1])
    if matches:
        print(f"  Top candidates:")
        for poly, m in matches[:10]:
            print(f"    poly=0x{poly:02X}: {m}/4 constraints")
    else:
        print(f"  No polynomial satisfies even 3/4 constraints.")
    print()


def analysis_h_120_engine_off_cycle():
    """Pull `120` D7 from the cold-boot engine-off window where D0..D6 = 0,
    verify period-6 cycle, compute per-ID offset vs `12D`'s reference."""
    print("=" * 78)
    print("# Part H — `120` D7 cycle from engine-off cold-boot (constant-payload run)")
    print("=" * 78)
    print()
    frames = parse_log(REPO_ROOT / "logs/2026-06-17-key-on-cold-boot/capture.log")
    events_path = REPO_ROOT / "logs/2026-06-17-key-on-cold-boot/events.csv"
    import csv as _csv
    import datetime as _dt
    with events_path.open() as f:
        for row in _csv.DictReader(f):
            t0 = _dt.datetime.fromisoformat(row["timestamp_iso"]).timestamp()
            break
    # Skip the first 5 s after key_on to clear boot transients, take next 30 s
    window = [b for ts, a, b in frames if a == "120" and t0 + 5 <= ts < t0 + 35]
    if not window:
        print("No 120 frames in window")
        return
    payloads = Counter(bytes(b[:7]) for b in window)
    print(f"`120` frames in engine-off cold-boot (t0+5 → t0+35 s): {len(window)}")
    print(f"Distinct D0..D6 payloads: {len(payloads)}")
    most_payload, n = payloads.most_common(1)[0]
    print(f"Dominant payload: {most_payload.hex(' ')} ({n} frames = {n/len(window)*100:.1f}%)")
    print()

    cycle_frames = [b[7] for b in window if bytes(b[:7]) == most_payload]
    distinct = sorted(set(cycle_frames))
    print(f"D7 distinct values on dominant payload: {[f'0x{v:02X}' for v in distinct]}  (n={len(distinct)})")
    # Find cycle period
    period = None
    for k in range(1, min(20, len(cycle_frames) // 2)):
        if all(cycle_frames[i] == cycle_frames[i + k] for i in range(min(len(cycle_frames) - k, 200))):
            period = k
            break
    if period:
        cycle = cycle_frames[:period]
        print(f"Cycle period: {period}")
        print(f"Cycle (in order): {[f'0x{v:02X}' for v in cycle]}")
    else:
        print(f"No clean cycle period in first 200 frames")
    print()

    # XOR offset vs 12D reference cycle
    reference = sorted({0x35, 0x5F, 0x6A, 0x8B, 0xBE, 0xD4})
    if len(distinct) == 6:
        offsets = [a ^ b for a, b in zip(distinct, reference)]
        if len(set(offsets)) == 1:
            offset = offsets[0]
            print(f"Sorted cycle XOR `12D` sorted reference: 0x{offset:02X} (constant) — matches universal-base hypothesis.")
            print(f"→ `120` per-ID offset = 0x{offset:02X}")
        else:
            print(f"Pairwise offsets: {[f'0x{o:02X}' for o in offsets]} — does NOT match universal base.")
    else:
        print(f"Cycle length {len(distinct)} ≠ 6 — cannot extract single per-ID offset.")
    print()


def analysis_f_universal_cycle(corpus):
    """Test the hypothesis: every ID's 6-value cycle equals 12D's cycle XOR a per-ID constant.
    If true, the cycle base is universal and the per-ID secret is just an 8-bit XOR offset."""
    print("=" * 78)
    print("# Part F — universal cycle hypothesis: per-ID cycle = `12D` cycle XOR offset_ID")
    print("=" * 78)
    print()
    reference_cycle = {0x35, 0x5F, 0x6A, 0x8B, 0xBE, 0xD4}  # from 12D in idle-run-1
    print(f"Reference (`12D` static-payload cycle): {sorted(f'0x{v:02X}' for v in reference_cycle)}")
    print()

    # For each ID, pull a steady 5 s window from idle-run-1, isolate the dominant-payload D7 set,
    # then check whether (cycle_id XOR cycle_12D) is a single constant for ALL 6 values when sorted.
    frames_all = parse_log(REPO_ROOT / "logs/2026-06-17-engine-idle-run-1/capture.log")
    t0 = frames_all[0][0]
    window = [(ts, arb, b) for ts, arb, b in frames_all if t0 + 60 <= ts < t0 + 65]

    print(f"{'ID':>4}  {'offset':>8}  {'cycle (sorted)':<42}  matches universal base?")
    for arb in CHECKSUM_HYPOTHESIS_IDS + PART_C_IDS:
        sel = [b for _, a, b in window if a == arb]
        if not sel:
            print(f"  {arb:>4}  {'—':>8}  (no frames)")
            continue
        payloads = Counter(bytes(b[:7]) for b in sel)
        most_payload, _ = payloads.most_common(1)[0]
        cycle = sorted({b[7] for b in sel if bytes(b[:7]) == most_payload})
        if len(cycle) != 6:
            print(f"  {arb:>4}  {'—':>8}  {[f'0x{v:02X}' for v in cycle]!s:<42}  cycle len {len(cycle)} (skipped)")
            continue
        # Compute XOR offset by pairing sorted cycle values
        ref_sorted = sorted(reference_cycle)
        offsets = [a ^ b for a, b in zip(cycle, ref_sorted)]
        if len(set(offsets)) == 1:
            offset = offsets[0]
            verdict = f"YES — offset 0x{offset:02X}"
        else:
            verdict = f"NO — pairwise offsets: {[f'0x{o:02X}' for o in offsets]}"
        cycle_s = "[" + ", ".join(f"0x{v:02X}" for v in cycle) + "]"
        print(f"  {arb:>4}  0x{offsets[0]:02X}      {cycle_s:<42}  {verdict}")
    print()

    # Gray code structure of the reference cycle
    print("Reference cycle XOR structure (12D, payload=0):")
    base_vals = sorted(reference_cycle)
    print(f"  Sorted values: {[f'0x{v:02X}' for v in base_vals]}")
    # Find a 3-vector basis {a, b, c} such that the cycle = {a, b, c, a^b, a^c, b^c, a^b^c}\{empty}
    # The 6 values cover positions in a Gray-code subset of the {a,b,c} XOR-vector space.
    # Try each pair as candidates for a, b, c
    print(f"  Pairwise XOR sums between cycle values (canonical XOR-vector basis check):")
    pairwise_xors = sorted({a ^ b for i, a in enumerate(base_vals) for b in base_vals[i+1:]})
    print(f"    distinct pairwise XORs: {[f'0x{v:02X}' for v in pairwise_xors]}")
    # In a 3-element {a,b,c} subset cycle, pairwise XORs are at most 7 nonzero values (the {a,b,c} cosets)
    print()


def analysis_g_exhaustive_crc_search():
    """Exhaustive search: for every polynomial 0x01..0xFF, every init 0x00..0xFF, every reflection
    setting, every counter placement, does the resulting 6 CRCs over (counter ∈ {0..5}, D0..D6=0)
    match `12D`'s target set {0x35, 0x5F, 0x6A, 0x8B, 0xBE, 0xD4}?"""
    print("=" * 78)
    print("# Part G — exhaustive CRC-8 search over all 255 polynomials × per-position counter")
    print("=" * 78)
    print()
    target = {0x35, 0x5F, 0x6A, 0x8B, 0xBE, 0xD4}
    payload_zero = (0,) * 7
    matches = []
    for poly in range(1, 256):
        for refin in (False, True):
            table = crc8_table(poly, refin)
            for refout in (False, True):
                for xorout in (0x00, 0xFF):
                    for init in range(256):
                        for p in range(9):
                            d7s = set()
                            for ctr in range(6):
                                if p == 0:
                                    bs = (ctr,) + payload_zero
                                elif p == 8:
                                    bs = payload_zero + (ctr,)
                                else:
                                    bs = payload_zero[:p] + (ctr,) + payload_zero[p:]
                                crc = crc8_compute(bytes(bs), table, init, refin, refout, xorout)
                                d7s.add(crc)
                            if d7s == target:
                                matches.append((poly, init, refin, refout, xorout, p))
                                if len(matches) > 50:
                                    break
                        if len(matches) > 50:
                            break
                    if len(matches) > 50:
                        break
                if len(matches) > 50:
                    break
            if len(matches) > 50:
                break
        if len(matches) > 50:
            break
    if not matches:
        print("Exhaustive search across 255 polys × 256 inits × 2 refin × 2 refout × 2 xorout × 9 placements")
        print("found NO standard-form CRC-8 that produces `12D`'s 6-cycle from (counter ∈ 0..5, D0..D6=0).")
        print()
        print("Implication: either the algorithm has an additional input we don't see on the bus")
        print("(a DataID, a per-ID secret, a frame-count register beyond the 6-cycle), or the")
        print("transformation is not a standard CRC-8 over the input bytes.")
    else:
        print(f"Found {len(matches)} match(es):")
        for poly, init, refin, refout, xorout, p in matches[:20]:
            placement = "prepend" if p == 0 else ("append" if p == 8 else f"insert@{p}")
            print(f"  poly=0x{poly:02X} init=0x{init:02X} refin={refin} refout={refout} "
                  f"xorout=0x{xorout:02X} counter {placement}")
    print()


def analysis_e_counter_input_search(corpus):
    """For 12D specifically (D0..D6 is all-zero), brute-force search over (poly, init, refin,
    refout, xorout) and counter-byte position to find a CRC-8 that produces the observed
    6-value set {0x35, 0x5F, 0x6A, 0x8B, 0xBE, 0xD4} for counter ∈ {0,1,2,3,4,5}."""
    print("=" * 78)
    print("# Part E — counter-input CRC search against `12D`'s 6-value set")
    print("=" * 78)
    print()
    target = {0x35, 0x5F, 0x6A, 0x8B, 0xBE, 0xD4}
    print(f"Target D7 set on `12D`: {sorted(f'0x{v:02X}' for v in target)}")
    print(f"Test: for each CRC-8 variant and each counter-byte placement, compute CRC over the")
    print(f"      8-byte input with a counter in 0..5 substituted at that position, with D0..D6 = 0.")
    print(f"      Match if the 6 resulting CRCs equal the target set (as a set, order ignored).")
    print()

    payload_zero = (0,) * 7
    # Placements: counter byte goes in position p of the CRC input.
    # p=0 → counter, D0..D6
    # p=8 → D0..D6, counter (append)
    # p ∈ {1..7} → counter inserted at byte p of the input
    matches = []
    for name, poly, _orig_init, refin, refout, xorout in CRC8_VARIANTS:
        table = crc8_table(poly, refin)
        for init in range(256):
            for p in range(9):  # 0 = prepend, 8 = append, 1..7 = interleaved positions
                d7s = set()
                for ctr in range(6):
                    if p == 0:
                        bs = (ctr,) + payload_zero
                    elif p == 8:
                        bs = payload_zero + (ctr,)
                    else:
                        bs = payload_zero[:p] + (ctr,) + payload_zero[p:]
                    crc = crc8_compute(bytes(bs), table, init, refin, refout, xorout)
                    d7s.add(crc)
                if d7s == target:
                    matches.append((name, poly, init, refin, refout, xorout, p))
    if not matches:
        # Try with XOR fold + counter byte
        print("No standard CRC-8 variant with a sequence-counter byte in 0..5 produces the target set.")
        print()
        # Try also with the counter as the only varying byte (since payload is zero, this is just CRC8(counter alone))
        # ... already covered when p=0 with payload = 0,0,0,0,0,0,0
        return None
    print(f"Found {len(matches)} match candidate(s):")
    for name, poly, init, refin, refout, xorout, p in matches[:20]:
        placement = "prepend" if p == 0 else ("append" if p == 8 else f"insert@{p}")
        print(f"  {name}  poly=0x{poly:02X} init=0x{init:02X} refin={refin} refout={refout} xorout=0x{xorout:02X}  counter {placement}")
    print()
    return matches


def main() -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    print("Building corpus…", file=sys.stderr)
    corpus = build_corpus()
    sizes = {arb: len(corpus.get(arb, ())) for arb in CHECKSUM_HYPOTHESIS_IDS + PART_C_IDS}
    print("Corpus size per ID (distinct (D0..D6, D7) tuples):", file=sys.stderr)
    for arb, n in sizes.items():
        print(f"  {arb}: {n}", file=sys.stderr)
    print(file=sys.stderr)

    best = analysis_a_polynomial_fit(corpus)
    analysis_b_12d_character()
    analysis_c_540_450(corpus, best)
    analysis_d_cycle_check()
    analysis_f_universal_cycle(corpus)
    analysis_h_120_engine_off_cycle()
    analysis_i_payload_function_search()
    analysis_j_extended_payload_search()
    analysis_e_counter_input_search(corpus)
    analysis_g_exhaustive_crc_search()
    return 0


if __name__ == "__main__":
    sys.exit(main())
