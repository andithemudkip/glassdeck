#!/usr/bin/env python3
"""unknown_byte_sweep.py — desk-only reconnaissance over undecoded payload bytes.

Profiles every '?' byte on the 11 always-on broadcast IDs across the full
captured corpus and ranks them by what we don't yet explain. The output is
the prioritised target list for the next bike-side capture and for
correlation work.

Buckets per (ID, byte):
  GLOBAL-STATIC        single value across every frame of every session
  EXPLAINED-BY:<sig>   bucket-mean Pearson |r| >= 0.9 vs a known channel
  STATE-BIT-SHAPED     at least one bit flips at engine-on / engine-off only
  UNEXPLAINED-ACTIVE   moves across the corpus, not explained by any known
  INSUFFICIENT-DATA    moves in only one session; can't discriminate

The coverage mask (which bytes are already explained) is derived from
docs/signals/signals.yaml plus a small additions table for non-signal
explanations (D7 cycle hash on 9 IDs, engine-state bits, kill mirrors,
known coarse mirrors). Persisted to scripts/coverage_mask.yaml.

Reference signals for correlation: rpm, throttle_position, coolant_temp,
wheel_speed_front, wheel_speed_rear, engine_on_counter, RPM*throttle,
time-since-engine-on.

Three sub-checks tacked on:
  - 121 channel A/B (D0:D1, D2:D3) int16 vs rpm / throttle / load
  - 541 D6 vs throttle (revisit the weak r ~ +0.26 from signal-throttle-position)
  - 540 D7 / 450 D7 "always 0x00" reconfirmation across all sessions

Outputs:
  scripts/coverage_mask.yaml                       derived explanation map
  scripts/out/unknown_byte_sweep_per_byte.csv      per (ID, byte) bucket
  scripts/out/unknown_byte_sweep_per_bit.csv       per (ID, byte, bit) bit-level
  scripts/out/unknown_byte_sweep_corr.csv          per (ID, byte, ref) Pearson r
  stdout: human-readable summary + shortlist

See docs/experiments/2026-06-30-unknown-byte-corpus-sweep.md for the design.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import re
import statistics as stats
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from signals import byte_coords, load_signals  # noqa: E402

LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

ALWAYS_ON_IDS = ["120", "121", "129", "12A", "12D", "12E", "450", "540", "541", "5A0", "5B0"]

# Sessions in scope. "engine" = "on" if a starter+kill window exists, else "off".
SESSIONS = [
    ("idle-1",      "logs/2026-06-17-engine-idle-run-1",                "on"),
    ("idle-2",      "logs/2026-06-17-engine-idle-run-2",                "on"),
    ("idle-3",      "logs/2026-06-17-engine-idle-run-3",                "on"),
    ("cold-boot",   "logs/2026-06-17-key-on-cold-boot",                 "off"),
    ("clutch-A",    "logs/2026-06-19-gear-cycle-clutch-A-clutch-only",  "off"),
    ("gear-B",      "logs/2026-06-19-gear-cycle-clutch-B-gear-cycle",   "off"),
    ("kill",        "logs/2026-06-19-kill-switch-toggle",               "off"),
    ("stand",       "logs/2026-06-19-side-stand-toggle",                "off"),
    ("throttle",    "logs/2026-06-19-throttle-sweep-engine-off",        "off"),
    ("paddock",     "logs/2026-06-22-wheel-spin-paddock-stand",         "off"),
    ("rear-spin",   "logs/2026-06-23-engine-driven-rear-spin",          "on"),
    ("shift-lever", "logs/2026-06-23-shift-lever-vs-clutch",            "off"),
    ("decay-mark",  "logs/2026-06-24-front-wheel-decay-mark",           "off"),
    ("hand-spin",   "logs/2026-06-24-front-wheel-hand-spin",            "off"),
]

# Additions to the coverage mask beyond signals.yaml. Format:
#   (arb_str, byte, kind, label)
# kind ∈ {"hash", "engine-state-bit:<bit>", "kill-mirror", "coarse-mirror",
#         "reserved-bit:<bit>", "static-zero"}
MASK_ADDITIONS: list[tuple[str, int, str, str]] = [
    # D7 cycle hash on 9 IDs (byte-d7-cycle-hash)
    ("120", 7, "hash", "D7 cycle hash"),
    ("121", 7, "hash", "D7 cycle hash"),
    ("129", 7, "hash", "D7 cycle hash"),
    ("12A", 7, "hash", "D7 cycle hash"),
    ("12D", 7, "hash", "D7 cycle hash"),
    ("12E", 7, "hash", "D7 cycle hash"),
    ("541", 7, "hash", "D7 cycle hash"),
    ("5A0", 7, "hash", "D7 cycle hash"),
    ("5B0", 7, "hash", "D7 cycle hash"),
    # Static-zero D7 on the two IDs where the cycle hash doesn't apply
    ("540", 7, "static-zero", "D7 always 0x00 (byte-d7-cycle-hash exception)"),
    ("450", 7, "static-zero", "D7 always 0x00 (byte-d7-cycle-hash exception)"),
    # Engine-state bits (engine-state-bits-decay-shape)
    ("121", 1, "engine-state-bit:5", "engine-state bit"),
    ("121", 1, "engine-state-bit:7", "engine-state bit"),
    ("121", 5, "engine-state-bit:3", "engine-state bit"),
    ("540", 2, "engine-state-bit:6", "engine-state bit"),
    ("540", 3, "engine-state-bit:4", "engine-state bit"),
    # Kill-switch redundant mirrors (signal-kill-switch)
    ("121", 5, "kill-mirror:2", "kill switch mirror at bit 2"),
    ("5B0", 0, "kill-mirror:4", "kill switch mirror at bit 4"),
    # Known coarse mirror
    ("12D", 2, "coarse-mirror", "rear wheel speed coarse mirror (~1/10 km/h, wraps)"),
    # Observed-zero bytes called out in coverage.md (downgraded to provisional)
    ("120", 3, "static-zero", "stays 0x00 across all observed conditions"),
    # 12D D3:D4 — 16-bit BE front-wheel-speed mirror at 3/64 km/h LSB
    # (byte-12d-d3-d4-front-mirror, provisional — D3 high byte observed 0x00
    # because front wheel never exceeded ~12.7 km/h in any captured session).
    ("12D", 3, "provisional-finding", "front-speed mirror hi byte (observed 0)"),
    ("12D", 4, "provisional-finding", "front-speed mirror lo byte (3/64 km/h LSB)"),
    # 541 D4 reserved high bit
    ("541", 4, "reserved-bit:7", "bit 7 reserved (never toggled), low 7 = engine-on counter"),
    # 12D D1 reserved bits 1-3 (low nibble of front-wheel slot)
    ("12D", 1, "reserved-bit:1", "always-zero per byte-encoding-12-in-16"),
    ("12D", 1, "reserved-bit:2", "always-zero per byte-encoding-12-in-16"),
    ("12D", 1, "reserved-bit:3", "always-zero per byte-encoding-12-in-16"),
    # 12D D1 bit 0: rear-speed 27 km/h threshold flag, in findings but not yet
    # promoted to signals.yaml (signal-12d-d1-bit0, provisional)
    ("12D", 1, "provisional-bit:0", "rear-speed 27 km/h flag (provisional finding)"),
]

# Reference signals for correlation. Each (name, decoder) returns float
# given an arb_str and raw payload, or None if the frame isn't this signal.
def _u16be(d: bytes, hi: int, lo: int) -> int:
    return (d[hi] << 8) | d[lo]


def _signed16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def _front_wheel_kmh(d: bytes) -> float:
    raw = (_u16be(d, 0, 1) & 0xFFF0) >> 4
    return raw / 12.0


def _rear_wheel_kmh(d: bytes) -> float:
    return _u16be(d, 5, 6) / 16.0


def _coolant_c(d: bytes) -> float:
    return _u16be(d, 5, 6) / 10.0


def _rpm(d: bytes) -> int:
    return _u16be(d, 0, 1)


def _throttle(d: bytes) -> int:
    return d[2]


def _engine_on_counter(d: bytes) -> int:
    return d[4] & 0x7F


# (arb_str, name, extractor) — extractor takes raw bytes.
REFERENCE_DECODERS = {
    "rpm":              ("120", _rpm),
    "throttle":         ("120", _throttle),
    "coolant":          ("540", _coolant_c),
    "wheel_front":      ("12D", _front_wheel_kmh),
    "wheel_rear":       ("12D", _rear_wheel_kmh),
    "engine_on_count":  ("541", _engine_on_counter),
}

# Correlation bucket width (seconds)
BUCKET_S = 0.1
# r threshold for EXPLAINED-BY
R_EXPLAIN = 0.9
# Minimum bucket count for a correlation to be reported
MIN_BUCKETS = 30
# Minimum reference-signal std within a window — guards against spurious
# correlations against near-constant references (e.g. engine-off coolant
# is effectively 0; correlating a non-flat candidate against it produces
# noise-level r values).
MIN_REF_STD = 0.5


# -------------------- parsing helpers --------------------

def parse_log(path: Path) -> list[tuple[float, str, bytes]]:
    out = []
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            ts = float(m.group(1))
            arb = m.group(2).upper()
            if arb not in set(ALWAYS_ON_IDS):
                continue
            hexd = m.group(3)
            if len(hexd) != 16:
                continue
            out.append((ts, arb, bytes.fromhex(hexd)))
    return out


def parse_events(path: Path) -> dict:
    if not path.exists():
        return {"start": None, "kill": None, "all": []}
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            rows.append({"t": t, "key": r["key"], "label": r["label"]})
    start = next((r["t"] for r in rows if r["key"] == "start"), None)
    kill = next((r["t"] for r in rows if r["key"] == "kill"), None)
    return {"start": start, "kill": kill, "all": rows}


# -------------------- coverage mask --------------------

def build_coverage_mask(signals) -> dict:
    """Return a dict describing every byte/bit explanation we already have.

    Shape:
      {
        "fully_explained_bytes": set[(arb_str, byte)],
        "bit_explanations":       {(arb_str, byte): {bit: "label"}},
        "byte_label":             {(arb_str, byte): "label"},
      }
    A byte is "fully explained" if either every bit is attributed by a signal
    or it carries a structural marker (hash, coarse-mirror, static-zero).
    """
    byte_label: dict[tuple[str, int], list[str]] = defaultdict(list)
    bit_expl: dict[tuple[str, int], dict[int, str]] = defaultdict(dict)
    fully: set[tuple[str, int]] = set()

    # Pull every signal coordinate from signals.yaml
    for sig in signals:
        arb = f"{sig.arbitration_id:03X}"
        if sig.bytes_ is not None:
            # Multi-byte signal. Resolve bit_offset/bit_length against the
            # combined value to figure out which (byte, bit) coordinates the
            # signal actually occupies. Mirrors Signal._extract_raw().
            order = list(sig.bytes_ if sig.byte_order == "big"
                         else reversed(sig.bytes_))
            covered_bytes: set[int] = set()
            for value_bit in range(sig.bit_offset, sig.bit_offset + sig.bit_length):
                byte_pos_from_lsb = value_bit // 8
                actual_byte = order[-1 - byte_pos_from_lsb]
                bit_in_byte = value_bit % 8
                bit_expl[(arb, actual_byte)][bit_in_byte] = sig.name
                covered_bytes.add(actual_byte)
            for b in covered_bytes:
                if sig.name not in byte_label[(arb, b)]:
                    byte_label[(arb, b)].append(sig.name)
        else:
            arb_b = (arb, sig.byte)
            byte_label[arb_b].append(sig.name)
            for bit in range(sig.bit_offset, sig.bit_offset + sig.bit_length):
                bit_expl[arb_b][bit] = sig.name

    # Apply additions
    for arb, byte_idx, kind, label in MASK_ADDITIONS:
        key = (arb, byte_idx)
        byte_label[key].append(f"{kind}: {label}")
        if kind in ("hash", "coarse-mirror", "static-zero", "provisional-finding"):
            for bit in range(8):
                bit_expl[key].setdefault(bit, kind)
        elif kind.startswith("engine-state-bit:"):
            bit = int(kind.split(":", 1)[1])
            bit_expl[key][bit] = "engine-state-bit"
        elif kind.startswith("kill-mirror:"):
            bit = int(kind.split(":", 1)[1])
            bit_expl[key][bit] = "kill-mirror"
        elif kind.startswith("reserved-bit:"):
            bit = int(kind.split(":", 1)[1])
            bit_expl[key][bit] = "reserved-zero"
        elif kind.startswith("provisional-bit:"):
            bit = int(kind.split(":", 1)[1])
            bit_expl[key][bit] = "provisional-finding"

    # A byte is fully explained if all 8 bits are attributed, OR it carries
    # a whole-byte structural marker.
    for arb in ALWAYS_ON_IDS:
        for b in range(8):
            key = (arb, b)
            if all(bit in bit_expl[key] for bit in range(8)):
                fully.add(key)

    return {
        "fully_explained_bytes": fully,
        "bit_explanations": dict(bit_expl),
        "byte_label": {k: "; ".join(v) for k, v in byte_label.items()},
    }


def write_coverage_mask_yaml(mask: dict, path: Path) -> None:
    lines = [
        "# Auto-generated by scripts/unknown_byte_sweep.py.",
        "# DO NOT hand-edit — source of truth is docs/signals/signals.yaml + the",
        "# MASK_ADDITIONS table at the top of the script.",
        "always_on_ids: [" + ", ".join(f"0x{arb}" for arb in ALWAYS_ON_IDS) + "]",
        "",
        "# fully-explained bytes (every bit attributed or whole-byte structural)",
        "fully_explained_bytes:",
    ]
    for (arb, b) in sorted(mask["fully_explained_bytes"]):
        label = mask["byte_label"].get((arb, b), "")
        lines.append(f"  - {{ id: 0x{arb}, byte: {b}, label: {label!r} }}")
    lines.append("")
    lines.append("# per-byte bit explanations (partial cells)")
    lines.append("bit_explanations:")
    for (arb, b) in sorted(mask["bit_explanations"].keys()):
        bits = mask["bit_explanations"][(arb, b)]
        if (arb, b) in mask["fully_explained_bytes"]:
            continue  # already in fully_explained_bytes
        if not bits:
            continue
        lines.append(f"  - id: 0x{arb}")
        lines.append(f"    byte: {b}")
        lines.append(f"    bits:")
        for bit in sorted(bits):
            lines.append(f"      {bit}: {bits[bit]!r}")
    path.write_text("\n".join(lines) + "\n")


# -------------------- per-session aggregation --------------------

def session_engine_window(events: dict, frames: list[tuple[float, str, bytes]],
                          session_engine: str) -> tuple[float | None, float | None]:
    """Return (engine_on_t0, engine_on_t1) or (None, None) if no engine-on."""
    if session_engine == "off":
        return None, None
    start = events["start"]
    kill = events["kill"]
    if start is None or kill is None:
        return None, None
    # Skip first 5 s after starter (cranking transient) and last 2 s.
    return start + 5.0, kill - 2.0


def session_off_window(events: dict, frames: list[tuple[float, str, bytes]],
                       session_engine: str) -> tuple[float | None, float | None]:
    """Return the engine-off window for this session. For 'off' sessions:
    first 60 s after first frame (skip 2 s boot transient). For 'on' sessions:
    first frame → starter - 2 s, if long enough."""
    if not frames:
        return None, None
    t_first = frames[0][0]
    if session_engine == "off":
        return t_first + 2.0, t_first + 60.0
    start = events["start"]
    if start is None or start - t_first < 8.0:
        return None, None
    return t_first + 2.0, start - 2.0


def slice_frames(frames: list[tuple[float, str, bytes]], t0: float, t1: float):
    return [(ts, arb, d) for ts, arb, d in frames if t0 <= ts <= t1]


def byte_stats(frames, arb, byte_idx):
    vals = [d[byte_idx] for _, a, d in frames if a == arb]
    if not vals:
        return None
    c = Counter(vals)
    dom, dom_n = c.most_common(1)[0]
    return {
        "n": len(vals),
        "distinct": len(c),
        "dom": dom,
        "purity": dom_n / len(vals),
        "mean": stats.fmean(vals),
        "std": stats.pstdev(vals) if len(vals) > 1 else 0.0,
        "values": set(c.keys()),
    }


def bit_toggle_count(frames, arb, byte_idx, bit):
    last = None
    toggles = 0
    n = 0
    ones = 0
    mask = 1 << bit
    for _, a, d in frames:
        if a != arb:
            continue
        v = 1 if (d[byte_idx] & mask) else 0
        if last is not None and v != last:
            toggles += 1
        last = v
        n += 1
        ones += v
    if n == 0:
        return None
    return {"toggles": toggles, "n": n, "ones": ones, "dom": 1 if ones * 2 > n else 0,
            "purity": max(ones, n - ones) / n}


# -------------------- bucket aggregation for correlation --------------------

def bucket_series(frames, arb_filter, value_fn, t0, t1):
    """Aggregate frames into BUCKET_S-second bins. Returns {bucket_idx: mean}."""
    bins: dict[int, list[float]] = defaultdict(list)
    for ts, arb, d in frames:
        if arb != arb_filter:
            continue
        if not (t0 <= ts <= t1):
            continue
        v = value_fn(d)
        if v is None:
            continue
        b = int((ts - t0) / BUCKET_S)
        bins[b].append(float(v))
    return {b: stats.fmean(vs) for b, vs in bins.items()}


def pearson_r(xs, ys):
    n = len(xs)
    if n < MIN_BUCKETS:
        return None
    mx = stats.fmean(xs)
    my = stats.fmean(ys)
    sx2 = sum((x - mx) ** 2 for x in xs)
    sy2 = sum((y - my) ** 2 for y in ys)
    if sx2 <= 0 or sy2 <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sx2 * sy2)


# -------------------- main --------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--top", type=int, default=25, help="rows to show in shortlist")
    ap.add_argument("--write-csv", action="store_true",
                    help="write CSVs to scripts/out/ (default: print only)")
    args = ap.parse_args()

    out_dir = REPO_ROOT / "scripts" / "out"
    if args.write_csv:
        out_dir.mkdir(parents=True, exist_ok=True)

    print("# unknown-byte sweep — desk-only reconnaissance\n")

    # ---- 1. coverage mask ----
    signals = load_signals()
    mask = build_coverage_mask(signals)
    mask_path = REPO_ROOT / "scripts" / "coverage_mask.yaml"
    write_coverage_mask_yaml(mask, mask_path)
    print(f"## Coverage mask → {mask_path.relative_to(REPO_ROOT)}")
    print(f"  fully-explained bytes:    {len(mask['fully_explained_bytes']):3d} / 88")
    partially = sum(1 for k in mask["bit_explanations"]
                    if k not in mask["fully_explained_bytes"] and mask["bit_explanations"][k])
    print(f"  partially-explained bytes: {partially:3d}")
    unknown_bytes = [
        (arb, b) for arb in ALWAYS_ON_IDS for b in range(8)
        if (arb, b) not in mask["fully_explained_bytes"]
        and not mask["bit_explanations"].get((arb, b))
    ]
    print(f"  fully-unknown bytes:       {len(unknown_bytes):3d}")
    print()

    # ---- 2. load all sessions ----
    print("## Loading sessions\n")
    loaded = []
    for key, rel, engine in SESSIONS:
        sess_dir = REPO_ROOT / rel
        events = parse_events(sess_dir / "events.csv")
        frames = parse_log(sess_dir / "capture.log")
        off_w = session_off_window(events, frames, engine)
        on_w = session_engine_window(events, frames, engine)
        loaded.append({
            "key": key, "engine": engine, "frames": frames,
            "events": events, "off_w": off_w, "on_w": on_w,
        })
        off_len = (off_w[1] - off_w[0]) if off_w[0] is not None else 0
        on_len = (on_w[1] - on_w[0]) if on_w[0] is not None else 0
        print(f"  {key:<12}  frames={len(frames):>6}  "
              f"engine={engine}  off-window={off_len:5.1f}s  on-window={on_len:5.1f}s")
    print()

    # ---- 3. per (ID, byte) corpus stats ----
    print("## Cross-corpus per-byte stats\n")
    target_bytes = [(arb, b) for arb in ALWAYS_ON_IDS for b in range(8)
                    if (arb, b) not in mask["fully_explained_bytes"]]

    per_byte_corpus = {}
    for (arb, b) in target_bytes:
        # union of distinct values across all sessions, all windows
        all_vals: set[int] = set()
        per_session_dom: dict[str, int | None] = {}
        per_session_purity: dict[str, float] = {}
        per_session_distinct: dict[str, int] = {}
        per_session_mean_off: dict[str, float] = {}
        per_session_mean_on: dict[str, float] = {}
        moves_in_n_sessions = 0
        for L in loaded:
            f = L["frames"]
            s_off = byte_stats(slice_frames(f, *L["off_w"]), arb, b) if L["off_w"][0] is not None else None
            s_on = byte_stats(slice_frames(f, *L["on_w"]), arb, b) if L["on_w"][0] is not None else None
            s_all = byte_stats(f, arb, b)
            if s_all is None:
                continue
            all_vals |= s_all["values"]
            per_session_dom[L["key"]] = s_all["dom"]
            per_session_purity[L["key"]] = s_all["purity"]
            per_session_distinct[L["key"]] = s_all["distinct"]
            if s_off is not None:
                per_session_mean_off[L["key"]] = s_off["mean"]
            if s_on is not None:
                per_session_mean_on[L["key"]] = s_on["mean"]
            if s_all["distinct"] >= 2 and s_all["purity"] < 0.99:
                moves_in_n_sessions += 1

        per_byte_corpus[(arb, b)] = {
            "union": all_vals,
            "moves_in_n_sessions": moves_in_n_sessions,
            "per_session_dom": per_session_dom,
            "per_session_purity": per_session_purity,
            "per_session_distinct": per_session_distinct,
            "mean_off": per_session_mean_off,
            "mean_on": per_session_mean_on,
        }

    # ---- 4. per-bit toggle / engine-state shape ----
    per_bit_state_shaped: dict[tuple[str, int, int], dict] = {}
    for (arb, b) in target_bytes:
        for bit in range(8):
            # skip if this bit is already attributed
            if bit in mask["bit_explanations"].get((arb, b), {}):
                continue
            off_dom_set: set[int] = set()
            on_dom_set: set[int] = set()
            total_toggles = 0
            off_purity_min = 1.0
            on_purity_min = 1.0
            saw_off = saw_on = False
            for L in loaded:
                f = L["frames"]
                if L["off_w"][0] is not None:
                    s = bit_toggle_count(slice_frames(f, *L["off_w"]), arb, b, bit)
                    if s and s["n"] > 50:
                        off_dom_set.add(s["dom"])
                        off_purity_min = min(off_purity_min, s["purity"])
                        total_toggles += s["toggles"]
                        saw_off = True
                if L["on_w"][0] is not None:
                    s = bit_toggle_count(slice_frames(f, *L["on_w"]), arb, b, bit)
                    if s and s["n"] > 50:
                        on_dom_set.add(s["dom"])
                        on_purity_min = min(on_purity_min, s["purity"])
                        total_toggles += s["toggles"]
                        saw_on = True
            # State-bit-shaped: off-mode unique, on-mode unique, off != on,
            # both purities >= 0.95
            if saw_off and saw_on and len(off_dom_set) == 1 and len(on_dom_set) == 1:
                off_d = next(iter(off_dom_set))
                on_d = next(iter(on_dom_set))
                if off_d != on_d and off_purity_min >= 0.95 and on_purity_min >= 0.95:
                    per_bit_state_shaped[(arb, b, bit)] = {
                        "off_dom": off_d, "on_dom": on_d,
                        "off_purity": off_purity_min, "on_purity": on_purity_min,
                        "total_toggles": total_toggles,
                    }

    print(f"  state-bit-shaped bits found: {len(per_bit_state_shaped)}")
    for (arb, b, bit), s in sorted(per_bit_state_shaped.items()):
        print(f"    {arb} D{b} bit{bit}: off={s['off_dom']} on={s['on_dom']} "
              f"(off-purity≥{s['off_purity']:.2f}, on-purity≥{s['on_purity']:.2f})")
    print()

    # ---- 5. correlation pass on ACTIVE bytes ----
    print("## Correlation pass (bucket-mean Pearson r vs known signals)\n")
    print(f"  bucket width = {BUCKET_S*1000:.0f} ms, |r| ≥ {R_EXPLAIN} ⇒ EXPLAINED-BY\n")

    # Decide which bytes to correlate: those with union > 1 AND moves in >=2 sessions
    active_bytes = [(arb, b) for (arb, b) in target_bytes
                    if len(per_byte_corpus[(arb, b)]["union"]) > 1
                    and per_byte_corpus[(arb, b)]["moves_in_n_sessions"] >= 2]

    correlations: dict[tuple[str, int], dict[str, float]] = defaultdict(dict)

    for L in loaded:
        f = L["frames"]
        # build reference series per signal (only on engine-on windows for most)
        for win_label, win in [("off", L["off_w"]), ("on", L["on_w"])]:
            if win[0] is None:
                continue
            t0, t1 = win

            # reference series in this window
            refs: dict[str, dict[int, float]] = {}
            for name, (ref_arb, ref_fn) in REFERENCE_DECODERS.items():
                refs[name] = bucket_series(f, ref_arb, ref_fn, t0, t1)
            # RPM × throttle (load proxy)
            if win_label == "on":
                rpm_s = refs.get("rpm", {})
                thr_s = refs.get("throttle", {})
                refs["rpm_x_throttle"] = {
                    b_: rpm_s[b_] * thr_s[b_] for b_ in rpm_s.keys() & thr_s.keys()
                }
                # time-since-engine-on: linear ramp 0..1 across the window
                if t1 > t0:
                    refs["time_in_on"] = {
                        b_: (b_ * BUCKET_S) / (t1 - t0)
                        for b_ in rpm_s.keys()
                    }

            for (arb, b) in active_bytes:
                cand_series = bucket_series(f, arb, lambda d, i=b: d[i], t0, t1)
                if len(cand_series) < MIN_BUCKETS:
                    continue
                for ref_name, ref_series in refs.items():
                    # restrict reference signals to appropriate engine state
                    if ref_name in ("rpm", "engine_on_count", "rpm_x_throttle", "time_in_on"):
                        if win_label != "on":
                            continue
                    if ref_name == "coolant" and L["key"] not in ("idle-1", "idle-2", "idle-3"):
                        continue
                    if ref_name == "throttle" and win_label == "on" and L["key"] != "rear-spin":
                        # only rear-spin has meaningful engine-on throttle modulation
                        # (idle-x3 sit at zero) — but throttle-sweep engine-off is
                        # captured by win_label == "off"
                        continue
                    common = cand_series.keys() & ref_series.keys()
                    if len(common) < MIN_BUCKETS:
                        continue
                    xs = [cand_series[k] for k in common]
                    ys = [ref_series[k] for k in common]
                    # Skip if the reference signal is effectively constant in
                    # this window — a flat reference produces spurious r.
                    if stats.pstdev(ys) < MIN_REF_STD:
                        continue
                    if stats.pstdev(xs) < 0.1:
                        continue
                    r = pearson_r(xs, ys)
                    if r is None:
                        continue
                    key = f"{ref_name}@{L['key']}/{win_label}"
                    correlations[(arb, b)][key] = r

    # Aggregate per byte: keep the |r|-max across sessions for each ref family
    best_by_ref: dict[tuple[str, int], dict[str, tuple[float, str]]] = defaultdict(dict)
    for (arb, b), cors in correlations.items():
        for k, r in cors.items():
            ref = k.split("@", 1)[0]
            cur = best_by_ref[(arb, b)].get(ref)
            if cur is None or abs(r) > abs(cur[0]):
                best_by_ref[(arb, b)][ref] = (r, k)

    # ---- 6. bucket each unknown byte ----
    print("## Per-byte bucketing\n")
    buckets: dict[tuple[str, int], dict] = {}
    for (arb, b) in target_bytes:
        c = per_byte_corpus[(arb, b)]
        if len(c["union"]) <= 1:
            label = next(iter(c["union"])) if c["union"] else None
            buckets[(arb, b)] = {"bucket": "GLOBAL-STATIC", "detail": f"value={label}"}
            continue

        # State-bit shaped?
        state_bits = [(bit, s) for (a, bb, bit), s in per_bit_state_shaped.items()
                      if a == arb and bb == b]
        if state_bits:
            bits_desc = ", ".join(f"bit{bit}:{s['off_dom']}→{s['on_dom']}"
                                  for bit, s in state_bits)
            buckets[(arb, b)] = {
                "bucket": "STATE-BIT-SHAPED",
                "detail": bits_desc,
            }
            continue

        if c["moves_in_n_sessions"] < 2:
            # Find which session moved it
            mover = next(
                (k for k, d in c["per_session_distinct"].items()
                 if d >= 2 and c["per_session_purity"][k] < 0.99),
                None,
            )
            buckets[(arb, b)] = {
                "bucket": "INSUFFICIENT-DATA",
                "detail": f"moved only in: {mover}",
            }
            continue

        # Check correlations
        best = best_by_ref.get((arb, b), {})
        explained = [(ref, r, where) for ref, (r, where) in best.items()
                     if abs(r) >= R_EXPLAIN]
        if explained:
            explained.sort(key=lambda x: -abs(x[1]))
            ref, r, where = explained[0]
            buckets[(arb, b)] = {
                "bucket": f"EXPLAINED-BY:{ref}",
                "detail": f"r={r:+.3f} ({where})",
            }
            continue

        # UNEXPLAINED-ACTIVE — record top suggestive correlation
        if best:
            top = max(best.items(), key=lambda kv: abs(kv[1][0]))
            ref, (r, where) = top
            detail = f"moves in {c['moves_in_n_sessions']}/{len(loaded)} sessions; best r={r:+.3f} ({ref})"
        else:
            detail = f"moves in {c['moves_in_n_sessions']}/{len(loaded)} sessions; no ref correlation"
        buckets[(arb, b)] = {"bucket": "UNEXPLAINED-ACTIVE", "detail": detail}

    # Tallies
    tally = Counter(v["bucket"].split(":", 1)[0] for v in buckets.values())
    print("  Bucket tally:")
    for k in ["GLOBAL-STATIC", "EXPLAINED-BY", "STATE-BIT-SHAPED",
              "UNEXPLAINED-ACTIVE", "INSUFFICIENT-DATA"]:
        print(f"    {k:<22} {tally.get(k, 0)}")
    print()

    # ---- 7. per-ID coverage table ----
    print("## Per-ID byte status (this run)\n")
    glyph = {
        "GLOBAL-STATIC": "0",
        "EXPLAINED-BY": "E",
        "STATE-BIT-SHAPED": "s",
        "UNEXPLAINED-ACTIVE": "?",
        "INSUFFICIENT-DATA": ".",
    }
    print(f"  legend: 0=GLOBAL-STATIC  E=EXPLAINED-BY  s=STATE-BIT-SHAPED  "
          f"?=UNEXPLAINED-ACTIVE  .=INSUFFICIENT-DATA  X=already-in-mask")
    print(f"  {'ID':<5} {'D0':>3} {'D1':>3} {'D2':>3} {'D3':>3} "
          f"{'D4':>3} {'D5':>3} {'D6':>3} {'D7':>3}")
    for arb in ALWAYS_ON_IDS:
        cells = []
        for b in range(8):
            if (arb, b) in mask["fully_explained_bytes"]:
                cells.append("X")
            elif (arb, b) in buckets:
                cells.append(glyph[buckets[(arb, b)]["bucket"].split(":", 1)[0]])
            else:
                cells.append("?")
        print(f"  {arb:<5} " + "  ".join(f"{c:>2}" for c in cells))
    print()

    # ---- 7b. detail for every non-static cell ----
    print("## Per-byte detail (non-static, non-mask bytes only)\n")
    detail_rows = [(k, v) for k, v in buckets.items()
                   if v["bucket"] != "GLOBAL-STATIC"]
    detail_rows.sort(key=lambda kv: (kv[0][0], kv[0][1]))
    print(f"  {'ID':<5} {'byte':>4}  {'bucket':<22}  detail")
    for (arb, b), v in detail_rows:
        print(f"  {arb:<5}  D{b}    {v['bucket']:<22}  {v['detail']}")
    print()

    # ---- 8. shortlist of UNEXPLAINED-ACTIVE bytes ----
    print("## Shortlist — UNEXPLAINED-ACTIVE bytes (highest-value targets)\n")
    shortlist = [(k, v) for k, v in buckets.items()
                 if v["bucket"] == "UNEXPLAINED-ACTIVE"]
    shortlist.sort(key=lambda kv: (
        -per_byte_corpus[kv[0]]["moves_in_n_sessions"],
        -len(per_byte_corpus[kv[0]]["union"]),
    ))
    print(f"  {'ID':<5} {'byte':>4}  {'moves':>5}  {'union':>5}  detail")
    for (arb, b), v in shortlist[:args.top]:
        c = per_byte_corpus[(arb, b)]
        print(f"  {arb:<5}  D{b}    {c['moves_in_n_sessions']:>4}  {len(c['union']):>4}   "
              f"{v['detail']}")
    print()

    # ---- 9. sub-check: 121 channel A/B int16 ----
    print("## Sub-check — 121 D0:D1 / D2:D3 int16 channels vs known signals\n")
    int16_summary = []
    for L in loaded:
        f = L["frames"]
        for win_label, win in [("off", L["off_w"]), ("on", L["on_w"])]:
            if win[0] is None:
                continue
            t0, t1 = win
            chA = bucket_series(f, "121", lambda d: _signed16(_u16be(d, 0, 1)), t0, t1)
            chB = bucket_series(f, "121", lambda d: _signed16(_u16be(d, 2, 3)), t0, t1)
            if len(chA) < MIN_BUCKETS:
                continue
            rpm = bucket_series(f, "120", _rpm, t0, t1)
            thr = bucket_series(f, "120", _throttle, t0, t1)
            r_a_rpm = pearson_r(*zip(*[(chA[k], rpm[k]) for k in chA.keys() & rpm.keys()])) \
                if chA.keys() & rpm.keys() else None
            r_b_rpm = pearson_r(*zip(*[(chB[k], rpm[k]) for k in chB.keys() & rpm.keys()])) \
                if chB.keys() & rpm.keys() else None
            r_a_thr = pearson_r(*zip(*[(chA[k], thr[k]) for k in chA.keys() & thr.keys()])) \
                if chA.keys() & thr.keys() else None
            r_b_thr = pearson_r(*zip(*[(chB[k], thr[k]) for k in chB.keys() & thr.keys()])) \
                if chB.keys() & thr.keys() else None
            mean_a = stats.fmean(chA.values())
            mean_b = stats.fmean(chB.values())
            int16_summary.append({
                "session": L["key"], "win": win_label,
                "mean_A": mean_a, "mean_B": mean_b,
                "r_A_rpm": r_a_rpm, "r_B_rpm": r_b_rpm,
                "r_A_thr": r_a_thr, "r_B_thr": r_b_thr,
            })
    print(f"  {'session':<14} {'win':>3}  {'μA':>7}  {'μB':>7}  "
          f"{'rA·RPM':>7}  {'rB·RPM':>7}  {'rA·thr':>7}  {'rB·thr':>7}")
    for s in int16_summary:
        def fr(x):
            return f"{x:+.2f}" if x is not None else "  -  "
        print(f"  {s['session']:<14} {s['win']:>3}  {s['mean_A']:7.2f}  {s['mean_B']:7.2f}  "
              f"{fr(s['r_A_rpm']):>7}  {fr(s['r_B_rpm']):>7}  "
              f"{fr(s['r_A_thr']):>7}  {fr(s['r_B_thr']):>7}")
    print()

    # ---- 10. sub-check: 541 D6 vs throttle ----
    print("## Sub-check — 541 D6 vs throttle (revisit of weak r≈+0.26)\n")
    d6_rows = []
    for L in loaded:
        f = L["frames"]
        for win_label, win in [("off", L["off_w"]), ("on", L["on_w"])]:
            if win[0] is None:
                continue
            t0, t1 = win
            d6 = bucket_series(f, "541", lambda d: d[6], t0, t1)
            thr = bucket_series(f, "120", _throttle, t0, t1)
            common = d6.keys() & thr.keys()
            if len(common) < MIN_BUCKETS:
                continue
            xs = [d6[k] for k in common]
            ys = [thr[k] for k in common]
            r = pearson_r(xs, ys)
            d6_rows.append((L["key"], win_label, r, len(common),
                            stats.fmean(xs), stats.pstdev(xs) if len(xs) > 1 else 0.0,
                            stats.fmean(ys)))
    print(f"  {'session':<14} {'win':>3}  {'r':>7}  {'n_buckets':>9}  "
          f"{'μD6':>7}  {'σD6':>6}  {'μthr':>6}")
    for sess, w, r, n, mu, sd, my in d6_rows:
        rs = f"{r:+.3f}" if r is not None else "  -  "
        print(f"  {sess:<14} {w:>3}  {rs:>7}  {n:>9}  {mu:7.2f}  {sd:6.2f}  {my:6.2f}")
    print()

    # ---- 11. sub-check: 540 D7 / 450 D7 ----
    print("## Sub-check — 540 D7 and 450 D7 (always-0x00 reconfirm)\n")
    for arb in ("540", "450"):
        vals: Counter = Counter()
        total = 0
        per_session_max = {}
        for L in loaded:
            sess_vals = [d[7] for ts, a, d in L["frames"] if a == arb]
            if sess_vals:
                vals.update(sess_vals)
                total += len(sess_vals)
                per_session_max[L["key"]] = max(sess_vals)
        if not total:
            print(f"  {arb} D7: no frames")
            continue
        non_zero = total - vals.get(0, 0)
        print(f"  {arb} D7: {total} frames, {non_zero} non-zero "
              f"({'CONFIRMED 0x00' if non_zero == 0 else 'BROKEN'})")
        if non_zero:
            for sess, mx in per_session_max.items():
                if mx > 0:
                    print(f"    {sess}: max D7 = 0x{mx:02X}")
    print()

    # ---- 12. CSV outputs ----
    if args.write_csv:
        per_byte_csv = out_dir / "unknown_byte_sweep_per_byte.csv"
        with per_byte_csv.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "byte", "bucket", "detail",
                        "union_size", "moves_in_n_sessions"])
            for (arb, b), v in sorted(buckets.items()):
                c = per_byte_corpus[(arb, b)]
                w.writerow([arb, b, v["bucket"], v["detail"],
                            len(c["union"]), c["moves_in_n_sessions"]])

        corr_csv = out_dir / "unknown_byte_sweep_corr.csv"
        with corr_csv.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "byte", "ref_signal", "session_window", "r"])
            for (arb, b), cors in sorted(correlations.items()):
                for key, r in sorted(cors.items()):
                    ref, where = key.split("@", 1)
                    w.writerow([arb, b, ref, where, f"{r:.4f}"])

        per_bit_csv = out_dir / "unknown_byte_sweep_per_bit.csv"
        with per_bit_csv.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "byte", "bit", "off_dom", "on_dom",
                        "off_purity_min", "on_purity_min", "total_toggles"])
            for (arb, b, bit), s in sorted(per_bit_state_shaped.items()):
                w.writerow([arb, b, bit, s["off_dom"], s["on_dom"],
                            f"{s['off_purity']:.4f}", f"{s['on_purity']:.4f}",
                            s["total_toggles"]])
        print(f"## CSVs written to {out_dir.relative_to(REPO_ROOT)}/\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
