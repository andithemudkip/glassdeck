#!/usr/bin/env python3
"""d7_offset_search.py — search for g(canID) → per-ID D7 offset.

The 9 D7-cycle IDs in docs/findings/can/byte-d7-cycle-hash.md have
per-ID XOR offsets that cluster in 0x00..0x1B — far below the entropy of a
random per-ID seed. This script searches for a small function `g(canID)`
that reproduces all 9 (ID, offset) pairs, which would replace the
"per-ID secret" story with a deterministic ID-keyed function.

Searches:

  1. GF(2)-linear: each output bit is XOR of a subset of ID bits.
     Per output bit, enumerate all 2^11 masks and check 9-way fit.

  2. Affine: GF(2)-linear plus a constant XOR.

  3. CRC-8 over ID bytes: every poly x init x refin/refout x xorout,
     low 5 bits of the result must match offset.

  4. Simple modular forms: (a * ID + b) mod K, K small.

Prints any fitting function. No arguments.
"""

from __future__ import annotations

from itertools import product

# (CAN ID, observed offset) from docs/findings/can/byte-d7-cycle-hash.md
PAIRS = [
    (0x120, 0x00),
    (0x121, 0x08),
    (0x129, 0x04),
    (0x12A, 0x08),
    (0x12D, 0x00),
    (0x12E, 0x1B),
    (0x541, 0x15),
    (0x5A0, 0x0E),
    (0x5B0, 0x01),
]

ID_BITS = 11  # 11-bit standard CAN identifiers
OUT_BITS = 5  # offsets fit in 5 bits (max 0x1B)


def popcount_parity(x: int) -> int:
    """Parity of the set bits of x (XOR of all bits)."""
    p = 0
    while x:
        p ^= x & 1
        x >>= 1
    return p


def search_linear():
    """For each output bit, find ID-bit-mask m such that
    parity(ID & m) == bit_b(offset) for every (ID, offset) pair."""
    print("\n=== 1. GF(2)-linear: offset_bit_b = XOR_{i in mask_b}(ID_bit_i) ===\n")
    per_bit_solutions = []
    for b in range(OUT_BITS):
        targets = [(ofs >> b) & 1 for _, ofs in PAIRS]
        fits = []
        for mask in range(1 << ID_BITS):
            ok = True
            for (cid, _), tgt in zip(PAIRS, targets):
                if popcount_parity(cid & mask) != tgt:
                    ok = False
                    break
            if ok:
                fits.append(mask)
        per_bit_solutions.append(fits)
        if not fits:
            print(f"  bit {b}: NO linear mask fits (targets across IDs = {targets})")
        else:
            short = sorted(fits, key=lambda m: bin(m).count("1"))[:5]
            print(f"  bit {b}: {len(fits)} masks fit. smallest-weight: "
                  + ", ".join(f"0x{m:03X} (popcount {bin(m).count('1')})" for m in short))
    if all(per_bit_solutions):
        print("\n  -> linear g(ID) EXISTS. Smallest-weight masks per bit:")
        chosen = [min(s, key=lambda m: bin(m).count("1")) for s in per_bit_solutions]
        for b, m in enumerate(chosen):
            print(f"      bit {b} <- popcount(ID & 0x{m:03X})  (popcount {bin(m).count('1')})")
        # Verify by applying it
        print("  verify:")
        for cid, ofs in PAIRS:
            recon = 0
            for b, m in enumerate(chosen):
                recon |= (popcount_parity(cid & m) << b)
            mark = "OK" if recon == ofs else "MISMATCH"
            print(f"      0x{cid:03X}: predicted 0x{recon:02X}, observed 0x{ofs:02X}  {mark}")
    else:
        print("\n  -> NO purely linear g(ID) fits (at least one bit has no mask).")
    return per_bit_solutions


def search_affine(linear_failures):
    """Same as search_linear but with an additional constant XOR.
    Only relevant if some bit had no linear solution: try flipping its
    target and search again — equivalent to XOR with 1 on that bit."""
    print("\n=== 2. Affine: offset = (linear(ID)) ^ const ===\n")
    chosen = []
    any_fail = False
    for b in range(OUT_BITS):
        bit_solutions = []
        for const_bit in (0, 1):
            targets = [((ofs >> b) & 1) ^ const_bit for _, ofs in PAIRS]
            for mask in range(1 << ID_BITS):
                ok = all(popcount_parity(cid & mask) == tgt
                         for (cid, _), tgt in zip(PAIRS, targets))
                if ok:
                    bit_solutions.append((mask, const_bit))
        if not bit_solutions:
            any_fail = True
            chosen.append(None)
            print(f"  bit {b}: NO affine solution.")
        else:
            best = min(bit_solutions, key=lambda x: bin(x[0]).count("1"))
            chosen.append(best)
            print(f"  bit {b}: mask 0x{best[0]:03X} (popcount {bin(best[0]).count('1')}), const_bit={best[1]}")
    if not any_fail:
        const = sum((c << b) for b, (_, c) in enumerate(chosen))
        print(f"\n  -> affine fit. constant XOR = 0x{const:02X}")


def crc8(data: bytes, poly: int, init: int, refin: bool, refout: bool, xorout: int) -> int:
    def reflect(x, n):
        r = 0
        for _ in range(n):
            r = (r << 1) | (x & 1)
            x >>= 1
        return r
    crc = init
    for b in data:
        if refin:
            b = reflect(b, 8)
        crc ^= b
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    if refout:
        crc = reflect(crc, 8)
    return crc ^ xorout


def search_crc():
    """Try every CRC-8 variant over 2-byte ID (big-endian and little-endian),
    masked to low 5 bits, looking for full 9/9 fit. Collapse xorout to a
    consistency check: for fixed (poly, init, refin, refout, endian), all 9
    `(crc ^ ofs) & 0x1F` values must agree — that constant IS the xorout."""
    print("\n=== 3. CRC-8 over ID bytes, low 5 bits ===\n", flush=True)
    hits = []
    endians = ("big", "little")
    payloads = {
        "big":    [bytes([(cid >> 8) & 0xFF, cid & 0xFF]) for cid, _ in PAIRS],
        "little": [bytes([cid & 0xFF, (cid >> 8) & 0xFF]) for cid, _ in PAIRS],
    }
    offsets = [ofs for _, ofs in PAIRS]
    for poly in range(1, 256):
        for init in range(256):
            for refin, refout in product([False, True], [False, True]):
                for endian in endians:
                    crcs = [crc8(d, poly, init, refin, refout, 0) for d in payloads[endian]]
                    diffs = [(c ^ o) & 0x1F for c, o in zip(crcs, offsets)]
                    if len(set(diffs)) == 1:
                        xorout_low5 = diffs[0]
                        hits.append((poly, init, refin, refout, xorout_low5, endian))
                        if len(hits) <= 5:
                            print(f"  HIT: poly=0x{poly:02X} init=0x{init:02X} refin={refin} refout={refout} xorout(low5)=0x{xorout_low5:02X} endian={endian}", flush=True)
    if not hits:
        print("  -> NO CRC-8 variant fits 9/9 on low 5 bits.", flush=True)
    else:
        print(f"  -> total CRC-8 hits: {len(hits)}", flush=True)


def search_modular():
    """offset = (a * ID + b) mod K for small a, K."""
    print("\n=== 4. Modular: (a*ID + b) mod K ===\n")
    hits = []
    for K in range(2, 64):
        for a in range(K):
            for b in range(K):
                if all(((a * cid + b) % K) == ofs for cid, ofs in PAIRS):
                    hits.append((a, b, K))
    if not hits:
        print("  -> NO (a*ID+b) mod K fits 9/9 for K<64.")
    else:
        for a, b, K in hits[:10]:
            print(f"  HIT: ({a}*ID + {b}) mod {K}")


if __name__ == "__main__":
    print("D7 per-ID offset search")
    print("9 (ID, offset) pairs:")
    for cid, ofs in PAIRS:
        print(f"  0x{cid:03X} -> 0x{ofs:02X}")
    fails = search_linear()
    search_affine(fails)
    search_modular()
    search_crc()
