#!/usr/bin/env python3
"""cross_session_diff.py — payload-byte classification across all sessions on disk.

Extends payload_diff.py from 3 engine-idle baselines to the full 9-session
corpus (cold-boot, 3 idle runs, throttle, kill, side-stand, clutch-only,
gear-cycle). For each (arbitration_id, byte_index) pair across the 11
always-on broadcast IDs, computes a per-session movement profile and
classifies:

  GLOBAL-STATIC  same dominant value in every session at >=99% purity
  ENGINE-STATE   engine-on (idle-run-1/2/3) differs from engine-off
                 (cold-boot + all per-input sessions); engine-off uniform
  SINGLE-CAUSE   exactly one session "moves" (>=2 distinct values, purity
                 <99%); the other 8 are static at the same value
  MULTI-CAUSE    2+ sessions move (D7 bytes flagged separately per the
                 byte-d7-cycle-hash finding)
  CROSS-DRIFT    no session moves internally, but dominant value differs
                 between sessions
  D7-EXCLUDED    byte index 7 — printed in its own table since D7 churns
                 deterministically per byte-d7-cycle-hash

See docs/experiments/2026-06-21-cross-session-payload-diff.md for the
experiment design.

Usage:
    python scripts/cross_session_diff.py            # full table
    python scripts/cross_session_diff.py --csv      # also write classification.csv
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
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from signals import byte_coords, load_signals  # type: ignore  # noqa: E402

LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

ALWAYS_ON_IDS = ["120", "121", "129", "12A", "12D", "12E", "450", "540", "541", "5A0", "5B0"]

# Engine-idle runs use idle_settled → kill window (matches payload_diff.py).
# Per-input + cold-boot sessions use first generic mark + 2 s → end of capture.
SESSIONS = [
    # (key, path, window_type, engine)
    ("cold-boot", "logs/2026-06-17-key-on-cold-boot", "from_key_on", "off"),
    ("idle-1", "logs/2026-06-17-engine-idle-run-1", "idle_to_kill", "on"),
    ("idle-2", "logs/2026-06-17-engine-idle-run-2", "idle_to_kill", "on"),
    ("idle-3", "logs/2026-06-17-engine-idle-run-3", "idle_to_kill", "on"),
    ("throttle", "logs/2026-06-19-throttle-sweep-engine-off", "from_key_on", "off"),
    ("kill", "logs/2026-06-19-kill-switch-toggle", "from_key_on", "off"),
    ("stand", "logs/2026-06-19-side-stand-toggle", "from_key_on", "off"),
    ("clutch", "logs/2026-06-19-gear-cycle-clutch-A-clutch-only", "from_key_on", "off"),
    ("gear", "logs/2026-06-19-gear-cycle-clutch-B-gear-cycle", "from_key_on", "off"),
]

ENGINE_ON = {"idle-1", "idle-2", "idle-3"}
ENGINE_OFF = {s[0] for s in SESSIONS} - ENGINE_ON

BOOT_TRIM_S = 2.0
END_TRIM_S = 2.0


def parse_events(path: Path) -> dict:
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            rows.append((t, r["key"], r["label"]))
    gm = [t for t, _, l in rows if l == "generic mark"]
    starter = next((t for t, _, l in rows if l == "starter button"), None)
    kill = next((t for t, _, l in rows if l == "kill switch"), None)
    return {
        "key_on": gm[0] if gm else None,
        "starter": starter,
        "idle_settled": gm[1] if len(gm) >= 2 else (starter + 1.0 if starter else None),
        "kill": kill,
        "all_events": rows,
    }


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
            if len(hex_data) % 2 or len(hex_data) != 16:
                continue
            data = bytes.fromhex(hex_data)
            frames.append((ts, arb, data))
    return frames


def session_window(key: str, path: Path, window_type: str):
    """Return (frames, (t0, t1)) for the chosen window."""
    events = parse_events(path / "events.csv")
    frames = parse_log(path / "capture.log")
    if not frames:
        return [], (None, None)
    capture_end = frames[-1][0]
    if window_type == "idle_to_kill":
        t0 = events["idle_settled"]
        t1 = events["kill"]
        if t0 is None or t1 is None:
            return [], (None, None)
    elif window_type == "from_key_on":
        t0 = (events["key_on"] or frames[0][0]) + BOOT_TRIM_S
        t1 = capture_end - END_TRIM_S
    else:
        raise ValueError(window_type)
    selected = [f for f in frames if t0 <= f[0] < t1]
    return selected, (t0, t1)


def session_state(values: list[int]):
    """Return (dominant, distinct, purity, moves) or None."""
    if not values:
        return None
    c = Counter(values)
    dom, dom_n = c.most_common(1)[0]
    distinct = len(c)
    purity = dom_n / len(values)
    moves = distinct >= 2 and purity < 0.99
    return dom, distinct, purity, moves


def classify(per_session, engine_on_keys, engine_off_keys):
    """per_session: {key: (dom, distinct, purity, moves) or None}"""
    valid = {k: v for k, v in per_session.items() if v is not None}
    if not valid:
        return "NODATA", {}

    movers = sorted(k for k, v in valid.items() if v[3])
    static_keys = [k for k in valid if k not in movers]
    dom_of = {k: v[0] for k, v in valid.items()}
    distinct_dom = set(dom_of.values())

    on_present = [k for k in valid if k in engine_on_keys]
    off_present = [k for k in valid if k in engine_off_keys]

    if not movers and len(distinct_dom) == 1:
        v = next(iter(distinct_dom))
        return "GLOBAL-STATIC", {"value": f"0x{v:02X}"}

    if off_present and on_present:
        off_doms = {dom_of[k] for k in off_present}
        off_movers = [k for k in off_present if k in movers]
        on_movers = [k for k in on_present if k in movers]
        on_doms = {dom_of[k] for k in on_present}
        if (not off_movers
                and len(off_doms) == 1
                and (on_movers == on_present or on_doms != off_doms)):
            off_v = next(iter(off_doms))
            on_dom_list = sorted({f"0x{v:02X}" for v in on_doms})
            return "ENGINE-STATE", {
                "off_value": f"0x{off_v:02X}",
                "on_doms": "/".join(on_dom_list),
                "on_moves": ",".join(sorted(on_movers)) if on_movers else "no",
            }

    if len(movers) == 1:
        static_doms = {dom_of[k] for k in static_keys}
        mover = movers[0]
        active = valid[mover]
        if len(static_doms) == 1:
            sv = next(iter(static_doms))
            return f"SINGLE-CAUSE({mover})", {
                "static_value": f"0x{sv:02X}",
                "active_distinct": active[1],
                "active_purity": round(active[2], 2),
            }
        return f"SINGLE-CAUSE({mover})+DRIFT", {
            "static_doms": "/".join(sorted(f"{k}=0x{dom_of[k]:02X}" for k in static_keys)),
            "active_distinct": active[1],
        }

    if len(movers) >= 2:
        return "MULTI-CAUSE", {
            "movers": ",".join(movers),
            "n_movers": len(movers),
            "n_static_doms": len(distinct_dom),
        }

    if not movers and len(distinct_dom) > 1:
        return "CROSS-DRIFT", {"dominants": "/".join(sorted(f"{k}=0x{dom_of[k]:02X}" for k in dom_of))}

    return "UNKNOWN", {}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--csv", action="store_true")
    args = p.parse_args()

    session_data: dict = {}
    print("# Per-session window summary")
    print(f"  {'session':>10}  {'engine':>6}  {'frames':>7}  {'window':>30}")
    for key, path, wtype, engine in SESSIONS:
        full = REPO_ROOT / path
        frames, (t0, t1) = session_window(key, full, wtype)
        win_desc = f"{wtype}" if t0 is None else f"{wtype} ({t1 - t0:.1f}s)"
        print(f"  {key:>10}  {engine:>6}  {len(frames):>7}  {win_desc:>30}")
        per_id_byte = defaultdict(lambda: defaultdict(list))
        for _ts, arb, data in frames:
            if arb not in ALWAYS_ON_IDS:
                continue
            for i in range(8):
                per_id_byte[arb][i].append(data[i])
        session_data[key] = per_id_byte
    print()

    rows = []
    print("# Per-byte cross-session classification (D7 excluded — see separate table below)")
    print(f"  {'ID':>4}  {'B':>1}  {'classification':<32}  detail")
    for arb in ALWAYS_ON_IDS:
        for bidx in range(8):
            if bidx == 7:
                continue
            per_session = {
                k: session_state(session_data[k][arb][bidx]) for k in session_data
            }
            tag, detail = classify(per_session, ENGINE_ON, ENGINE_OFF)
            detail_s = "  ".join(f"{k}={v}" for k, v in detail.items())
            print(f"  {arb:>4}  {bidx:>1}  {tag:<32}  {detail_s}")
            rows.append({
                "id": arb, "byte": bidx, "classification": tag, "detail": detail_s,
                "per_session": "; ".join(
                    f"{k}:{'-' if v is None else f'd{v[1]}/p{v[2]:.2f}/dom0x{v[0]:02X}'}"
                    for k, v in per_session.items()
                ),
            })
        print()

    print("# D7 byte distribution per ID (per byte-d7-cycle-hash — expected MULTI-CAUSE)")
    print(f"  {'ID':>4}  per-session distinct counts")
    for arb in ALWAYS_ON_IDS:
        per_session_d7 = {
            k: session_state(session_data[k][arb][7]) for k in session_data
        }
        cells = []
        for k in [s[0] for s in SESSIONS]:
            v = per_session_d7[k]
            cells.append(f"{k}={'-' if v is None else v[1]}")
        print(f"  {arb:>4}  {'  '.join(cells)}")
    print()

    # Aggregate counts per classification
    bucket = Counter(r["classification"].split("(")[0] for r in rows)
    print("# Classification summary (D7 excluded; 77 non-D7 byte slots, minus IDs not present in sessions)")
    for tag, n in bucket.most_common():
        print(f"  {tag:<20}  {n}")
    print()

    # Reproduce known signals as a procedural sanity check.
    # Coordinates derived from docs/signals/signals.yaml (ADR 0005) — adding a
    # confirmed signal there auto-extends this check.
    schema_signals = load_signals()
    schema_coords = byte_coords(schema_signals)
    print("# Known-signal reproduction check (sourced from docs/signals/signals.yaml)")
    by_key = {(r["id"], int(r["byte"])): r for r in rows}
    failures = 0
    for arb, bidx, name in schema_coords:
        r = by_key.get((arb, bidx))
        if not r:
            print(f"  {arb} D{bidx}  MISSING                              ({name})")
            failures += 1
            continue
        cls = r["classification"]
        # A confirmed signal sitting on a GLOBAL-STATIC byte means either the
        # schema drifted or the corpus changed shape — surface it loudly.
        flag = "  ← FAIL" if cls.startswith("GLOBAL-STATIC") else ""
        if flag:
            failures += 1
        print(f"  {arb} D{bidx}  {cls:<35}  ({name}){flag}")
    if failures:
        print(f"  → {failures} signal byte(s) drifted from schema")
    print()

    # Candidate short list: anything that is not GLOBAL-STATIC and not on the known-signal list
    print("# Candidate short list (non-GLOBAL-STATIC, non-known-signal)")
    known_set = {(arb, bidx) for arb, bidx, _ in schema_coords}
    candidates = [r for r in rows
                  if not r["classification"].startswith("GLOBAL-STATIC")
                  and (r["id"], r["byte"]) not in known_set]
    print(f"  {'ID':>4}  {'B':>1}  {'classification':<32}  detail")
    for r in candidates:
        print(f"  {r['id']:>4}  {r['byte']:>1}  {r['classification']:<32}  {r['detail']}")
    print()

    if args.csv:
        out = REPO_ROOT / "cross_session_classification.csv"
        with out.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["id", "byte", "classification", "detail", "per_session"])
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print(f"wrote {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
