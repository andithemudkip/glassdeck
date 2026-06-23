#!/usr/bin/env python3
"""bit_transition_scan.py — per-bit toggle-rate classifier across all sessions.

For every (arbitration_id, byte, bit) across the 11 always-on broadcast IDs
and the 9-session capture corpus, computes per-session toggle rate and
dominant-value purity, then classifies each bit as:

  GLOBAL-CONSTANT  toggle_rate == 0 in every session
  CHECKSUM-LIKE    toggle_rate >= 0.25 in every session (D7 bits, RPM bits)
  SESSION-CONTRAST high in some sessions (>=0.05), low in others (<=0.005)
  ENGINE-CONTRAST  special case: high in all 3 engine-on, low in all 6 off
  NEAR-CONSTANT    low but non-zero everywhere (<=0.005)
  MIXED            doesn't fit the cleaner classes

D7 bits are filtered out of the SESSION-CONTRAST hunt by default (per
byte-d7-cycle-hash they cycle deterministically and would swamp
any ranking) but are computed and printed separately as a sanity check.

See docs/experiments/2026-06-21-bit-transition-scan.md for the design.

Usage:
    python scripts/bit_transition_scan.py
    python scripts/bit_transition_scan.py --include-d7
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from cross_session_diff import (  # type: ignore
    ALWAYS_ON_IDS,
    ENGINE_OFF,
    ENGINE_ON,
    SESSIONS,
    session_window,
)
from signals import bit_coords, load_signals  # type: ignore  # noqa: E402

ACTIVE_TOGGLE_COUNT = 2  # treat a session as "active" if the bit toggled at least N times
FAST_RATE = 0.05         # rate above which we consider the bit toggling fast (RPM-like)
CHECKSUM_RATE = 0.25     # rate above which the bit is essentially saturated


def per_session_bit_stats(values: list[int], bit: int) -> dict:
    if len(values) < 2:
        return {"n": len(values), "toggles": 0, "toggle_rate": 0.0, "dom": 0, "dom_purity": 1.0}
    bits = [(v >> bit) & 1 for v in values]
    toggles = sum(1 for i in range(len(bits) - 1) if bits[i] != bits[i + 1])
    rate = toggles / (len(bits) - 1)
    n1 = sum(bits)
    dom = 1 if n1 > len(bits) / 2 else 0
    dom_purity = max(n1, len(bits) - n1) / len(bits)
    return {"n": len(values), "toggles": toggles, "toggle_rate": rate, "dom": dom, "dom_purity": dom_purity}


def classify_bit(per_session: dict, engine_on: set, engine_off: set):
    valid = {k: v for k, v in per_session.items() if v["n"] > 0}
    if not valid:
        return "NODATA", {}

    toggles = {k: v["toggles"] for k, v in valid.items()}
    rates = {k: v["toggle_rate"] for k, v in valid.items()}

    if all(t == 0 for t in toggles.values()):
        return "GLOBAL-CONSTANT", {"dom": valid[next(iter(valid))]["dom"]}

    if all(r >= CHECKSUM_RATE for r in rates.values()):
        return "CHECKSUM-LIKE", {"min_rate": round(min(rates.values()), 3),
                                  "max_rate": round(max(rates.values()), 3)}

    # Activity-based contrast: "active" = toggled >=N times (catches slow flag bits
    # that toggle only a handful of times when the corresponding input fires).
    active = {k for k, t in toggles.items() if t >= ACTIVE_TOGGLE_COUNT}
    inactive = {k for k, t in toggles.items() if t == 0}

    if active and inactive and active | inactive == set(valid):
        on_in_valid = engine_on & set(valid)
        off_in_valid = engine_off & set(valid)
        if active == on_in_valid and inactive == off_in_valid:
            min_rate_active = min(rates[k] for k in active)
            tag = "ENGINE-CONTRAST-FAST" if min_rate_active >= FAST_RATE else "ENGINE-CONTRAST-SLOW"
            return tag, {"high": ",".join(sorted(active)),
                         "rates": {k: round(rates[k], 3) for k in active},
                         "toggles": {k: toggles[k] for k in active}}
        return "SESSION-CONTRAST", {"high": ",".join(sorted(active)),
                                     "low": ",".join(sorted(inactive)),
                                     "rates": {k: round(rates[k], 3) for k in active},
                                     "toggles": {k: toggles[k] for k in active}}

    # Partial: some sessions active, some inactive, some have 1 toggle (noise)
    if max(toggles.values()) <= 1:
        return "NEAR-CONSTANT", {"max_toggles": max(toggles.values()),
                                  "any_active": ",".join(sorted(k for k, t in toggles.items() if t > 0))}

    return "MIXED", {"toggles": {k: t for k, t in toggles.items() if t > 0},
                     "rates": {k: round(r, 3) for k, r in rates.items() if r > 0}}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--include-d7", action="store_true",
                   help="Include D7 bits in the main classification table")
    args = p.parse_args()

    session_data: dict = {}
    for key, path, wtype, _engine in SESSIONS:
        full = REPO_ROOT / path
        frames, _ = session_window(key, full, wtype)
        per_id_byte: dict = defaultdict(lambda: defaultdict(list))
        for _ts, arb, data in frames:
            if arb not in ALWAYS_ON_IDS:
                continue
            for i in range(8):
                per_id_byte[arb][i].append(data[i])
        session_data[key] = per_id_byte

    # Compute classification for all 11 * 8 * 8 = 704 bits
    all_bits = []
    for arb in ALWAYS_ON_IDS:
        for byte_idx in range(8):
            for bit in range(8):
                per_session = {
                    k: per_session_bit_stats(session_data[k][arb][byte_idx], bit)
                    for k in session_data
                }
                tag, detail = classify_bit(per_session, ENGINE_ON, ENGINE_OFF)
                all_bits.append({
                    "id": arb, "byte": byte_idx, "bit": bit,
                    "tag": tag, "detail": detail, "per_session": per_session,
                })

    # Summary counts (excluding D7 unless flagged)
    main_bits = [b for b in all_bits if args.include_d7 or b["byte"] != 7]
    d7_bits = [b for b in all_bits if b["byte"] == 7]

    from collections import Counter
    tag_counts = Counter(b["tag"] for b in main_bits)
    print("# Bit-level classification summary (D7 {} — {} bits total)".format(
        "INCLUDED" if args.include_d7 else "EXCLUDED",
        len(main_bits)))
    for t, n in tag_counts.most_common():
        print(f"  {t:<18}  {n}")
    print()

    # Show SESSION-CONTRAST and both ENGINE-CONTRAST variants in full
    interesting = [b for b in main_bits if b["tag"] in (
        "SESSION-CONTRAST", "ENGINE-CONTRAST-FAST", "ENGINE-CONTRAST-SLOW")]
    print(f"# Interesting bits — {len(interesting)} hits")
    print(f"  {'ID':>4}  {'byte:bit':>8}  {'tag':<22}  match               toggles per active session")
    for b in interesting:
        tog = b["detail"].get("toggles", {})
        tog_str = "  ".join(f"{k}={v}" for k, v in tog.items())
        match = trigger_match(b["detail"].get("high", ""))
        print(f"  {b['id']:>4}  {b['byte']}:{b['bit']:<5}  {b['tag']:<22}  {match:<18}  {tog_str}")
    print()

    # CHECKSUM-LIKE — verify D7 bits land here when included
    print("# CHECKSUM-LIKE bits — D7 expected to dominate")
    cs = [b for b in main_bits if b["tag"] == "CHECKSUM-LIKE"]
    for b in cs:
        rmin = b["detail"]["min_rate"]
        rmax = b["detail"]["max_rate"]
        print(f"  {b['id']:>4}  {b['byte']}:{b['bit']}  rates [{rmin}-{rmax}]")
    print()

    # MIXED — interesting partial patterns
    mixed = [b for b in main_bits if b["tag"] == "MIXED"]
    print(f"# MIXED bits — partial patterns ({len(mixed)} hits)")
    print(f"  {'ID':>4}  {'byte:bit':>8}  per-session rates (top 6 by rate)")
    for b in mixed[:30]:
        rates = sorted(b["detail"]["rates"].items(), key=lambda x: -x[1])[:6]
        rates_str = "  ".join(f"{k}={r}" for k, r in rates)
        print(f"  {b['id']:>4}  {b['byte']}:{b['bit']:<5}  {rates_str}")
    if len(mixed) > 30:
        print(f"  ... and {len(mixed)-30} more")
    print()

    # Reproduce known signals — schema half is auto-derived from
    # docs/signals/signals.yaml (ADR 0005); the unattributed-bit study
    # targets stay as a script-local literal because they aren't promoted
    # signals (they're hypotheses this scan exists to refine).
    schema_bits = [
        (arb, byte, bit, name) for arb, byte, bit, name in bit_coords(load_signals())
    ]
    study_targets = [
        ("540", 2, 6, "ignition-permission → expect ENGINE-CONTRAST + kill in high"),
        ("540", 3, 4, "ignition-permission → expect ENGINE-CONTRAST + kill in high"),
        ("121", 5, 3, "engine-state → expect ENGINE-CONTRAST"),
    ]
    print("# Known-signal reproduction check — bit-level (schema-sourced)")
    lookup = {(b["id"], b["byte"], b["bit"]): b for b in all_bits}
    failures = 0
    for arb, byte, bit, name in schema_bits:
        b = lookup.get((arb, byte, bit))
        if not b:
            print(f"  {arb} {byte}:{bit}  MISSING                                  ({name})")
            failures += 1
            continue
        rates = {k: round(v['toggle_rate'], 3) for k, v in b['per_session'].items() if v['toggle_rate'] > 0}
        flag = "  ← FAIL" if b['tag'] == 'GLOBAL-CONSTANT' else ""
        if flag:
            failures += 1
        print(f"  {arb} {byte}:{bit}  {b['tag']:<17} rates>0: {rates}  ({name}){flag}")
    if failures:
        print(f"  → {failures} schema bit(s) drifted")
    print()
    print("# Unattributed bit study targets")
    for arb, byte, bit, note in study_targets:
        b = lookup.get((arb, byte, bit))
        if not b:
            print(f"  {arb} {byte}:{bit}  MISSING — ({note})")
            continue
        rates = {k: round(v['toggle_rate'], 3) for k, v in b['per_session'].items() if v['toggle_rate'] > 0}
        print(f"  {arb} {byte}:{bit}  {b['tag']:<17} rates>0: {rates}  ({note})")
    print()

    # D7 sanity check
    print("# D7 bit classification (separate — expected CHECKSUM-LIKE)")
    d7_tags = Counter(b["tag"] for b in d7_bits)
    for t, n in d7_tags.most_common():
        print(f"  {t:<18}  {n}")
    print()

    return 0


def trigger_match(high_str: str) -> str:
    s = set(high_str.split(","))
    if s == {"throttle"}: return "throttle"
    if s == {"kill"}: return "kill"
    if s == {"stand"}: return "side-stand"
    if s == {"gear"}: return "gear"
    if s == {"clutch"}: return "clutch"
    if s == {"idle-1", "idle-2", "idle-3"}: return "engine-on"
    if s.issubset({"idle-1", "idle-2", "idle-3"}): return "engine-on(partial)"
    if "kill" in s and len(s) <= 3: return f"kill+{s-{'kill'}}"
    return "/".join(sorted(s)) if len(s) <= 3 else f"{len(s)} sessions"


if __name__ == "__main__":
    sys.exit(main())
