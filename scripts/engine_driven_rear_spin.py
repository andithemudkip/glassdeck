#!/usr/bin/env python3
"""engine_driven_rear_spin.py — analyse the engine-driven rear-spin session.

For each RPM setpoint mark in events.csv, take a steady-state window
inside the hold and summarise:
  - RPM      (120 D0:D1 BE uint16)
  - 12D D2, D3, D5, D6 (mean / min / max)
  - D6/D2 ratio (constant across setpoints = same quantity, different scale)
  - Candidate uint16 decodes: D2:D3 LE/BE, D5:D6 LE/BE
  - Predicted wheel km/h from RPM × gearing × wheel circumference
  - Implied scale per candidate (km/h per raw LSB)

Procedure: see docs/experiments/2026-06-23-engine-driven-rear-spin.md
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

# KTM 390 / Svartpilen 401 drivetrain — see experiment .md
PRIMARY = 80 / 30
GEAR_1ST = 32 / 12
FINAL = 45 / 15
TOTAL_1ST = PRIMARY * GEAR_1ST * FINAL                       # 21.333…
REAR_CIRC_M = 1.922                                          # 150/60ZR17
RPM_TO_KMH_1ST = REAR_CIRC_M * 60 / 1000 / TOTAL_1ST         # km/h per RPM

# Steady-state window inside each hold. The setpoint marks fire at the
# rider's "begin holding now" cue; allow ~3 s for the throttle to reach
# the target and then sample the remainder.
WINDOW_SKIP_S = 3.0
WINDOW_LEN_S = 8.0


def parse_events(path: Path):
    """Return ordered list of (label, unix_ts) for the setpoint marks."""
    setpoints = []
    with path.open() as f:
        for r in csv.DictReader(f):
            if r["key"] != "setpoint":
                continue
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            setpoints.append((r["label"], t))
    return setpoints


def parse_log(path: Path, ids_of_interest):
    """Return {arb_id: [(ts, data_bytes), ...]} filtered to ids_of_interest."""
    out = {arb: [] for arb in ids_of_interest}
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            arb = m.group(2).upper()
            if arb not in out:
                continue
            hex_data = m.group(3)
            if len(hex_data) % 2:
                continue
            data = bytes.fromhex(hex_data)
            if len(data) != 8:
                continue
            out[arb].append((float(m.group(1)), data))
    return out


def window_frames(frames, t0, t1):
    return [(ts, d) for ts, d in frames if t0 <= ts <= t1]


def stats(values):
    if not values:
        return None
    vals = list(values)
    mn, mx = min(vals), max(vals)
    mean = sum(vals) / len(vals)
    std = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    return {"mean": mean, "min": mn, "max": mx, "std": std, "n": len(vals)}


def fmt_byte_stats(s):
    if s is None:
        return "        —          "
    if s["min"] == s["max"]:
        return f"0x{s['min']:02X}              "
    return f"0x{s['min']:02X}..0x{s['max']:02X} (μ={s['mean']:5.1f})"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--session",
                   default="logs/2026-06-23-engine-driven-rear-spin")
    args = p.parse_args()

    session = REPO_ROOT / args.session
    setpoints = parse_events(session / "events.csv")
    if not setpoints:
        print("no setpoint marks in events.csv", file=sys.stderr)
        return 1

    frames = parse_log(session / "capture.log", {"120", "12D"})

    print(f"# Engine-driven rear-spin analysis — {args.session}")
    print(f"# Steady-state window: t+{WINDOW_SKIP_S:.0f}..t+{WINDOW_SKIP_S+WINDOW_LEN_S:.0f} s after each mark")
    print(f"# Gearing: total 1st = {TOTAL_1ST:.3f}, rear circ {REAR_CIRC_M} m → {RPM_TO_KMH_1ST*1000:.3f} km/h per 1000 RPM\n")

    print(f"  {'label':<36}  {'RPM (μ)':>8}  {'pred km/h':>9}  "
          f"{'D2':>22}  {'D3':>22}  {'D5':>22}  {'D6':>22}")

    rows = []  # for downstream regression
    for label, mark in setpoints:
        t0, t1 = mark + WINDOW_SKIP_S, mark + WINDOW_SKIP_S + WINDOW_LEN_S
        rpm_frames = window_frames(frames["120"], t0, t1)
        wheel_frames = window_frames(frames["12D"], t0, t1)
        rpm_vals = [(d[0] << 8) | d[1] for _, d in rpm_frames]
        d2 = [d[2] for _, d in wheel_frames]
        d3 = [d[3] for _, d in wheel_frames]
        d5 = [d[5] for _, d in wheel_frames]
        d6 = [d[6] for _, d in wheel_frames]
        rpm_s = stats(rpm_vals)
        if rpm_s is None:
            continue
        rpm_mean = rpm_s["mean"]
        pred_kmh = rpm_mean * RPM_TO_KMH_1ST
        print(f"  {label:<36}  {rpm_mean:8.0f}  {pred_kmh:9.2f}  "
              f"{fmt_byte_stats(stats(d2))}  "
              f"{fmt_byte_stats(stats(d3))}  "
              f"{fmt_byte_stats(stats(d5))}  "
              f"{fmt_byte_stats(stats(d6))}")
        rows.append({
            "label": label, "rpm": rpm_mean, "pred_kmh": pred_kmh,
            "d2": stats(d2), "d3": stats(d3), "d5": stats(d5), "d6": stats(d6),
        })

    # ---------------------------------------------- D6 / D2 ratio table
    print("\n## D6 / D2 ratio at each setpoint")
    print("  (filtered-vs-raw → ratio converges to a constant; different scaling → ratio constant always; different quantities → ratio drifts with speed)\n")
    print(f"  {'label':<36}  {'D2 μ':>6}  {'D6 μ':>6}  {'D6/D2':>7}")
    for r in rows:
        if r["d2"]["mean"] > 0.5:
            ratio = r["d6"]["mean"] / r["d2"]["mean"]
            print(f"  {r['label']:<36}  {r['d2']['mean']:6.1f}  {r['d6']['mean']:6.1f}  {ratio:7.3f}")
        else:
            print(f"  {r['label']:<36}  {r['d2']['mean']:6.1f}  {r['d6']['mean']:6.1f}  {'—':>7}")

    # ---------------------------------------------- Endianness check
    print("\n## Endianness check — implied km/h per raw LSB for each candidate decode")
    print("  (raw built from per-frame bytes; here we just use μ-of-byte for the table.")
    print("   A clean scale appears as a constant column. 0.1 km/h / LSB matches a decimal-friendly OEM choice;")
    print("   1/16 km/h / LSB = 0.0625 matches a binary-friendly OEM choice.)\n")
    candidates = [
        ("D2:D3 LE",     lambda r: r["d2"]["mean"] + 256 * r["d3"]["mean"]),
        ("D2:D3 BE",     lambda r: 256 * r["d2"]["mean"] + r["d3"]["mean"]),
        ("D2 alone",     lambda r: r["d2"]["mean"]),
        ("D5:D6 LE",     lambda r: r["d5"]["mean"] + 256 * r["d6"]["mean"]),
        ("D5:D6 BE",     lambda r: 256 * r["d5"]["mean"] + r["d6"]["mean"]),
        ("D6 alone",     lambda r: r["d6"]["mean"]),
    ]
    header = "  " + f"{'label':<36}  " + "  ".join(f"{name:>14}" for name, _ in candidates)
    print(header)
    print("  " + " " * 36 + "    (km/h per LSB if this decode is right)")
    for r in rows:
        kmh = r["pred_kmh"]
        cells = []
        for _, fn in candidates:
            raw = fn(r)
            if raw < 0.5:
                cells.append(f"{'—':>14}")
            else:
                cells.append(f"{kmh / raw:14.5f}")
        print(f"  {r['label']:<36}  " + "  ".join(cells))

    # ---------------------------------------------- Linear regression
    print("\n## Best linear fit km/h = a·raw + b per candidate (across all setpoints)")
    print("  (intercept ~0 + slope matching a known OEM unit ⇒ that decode is right)\n")
    for name, fn in candidates:
        xs = [fn(r) for r in rows]
        ys = [r["pred_kmh"] for r in rows]
        # Drop any point where raw < 0.5 (saturation / unused)
        pairs = [(x, y) for x, y in zip(xs, ys) if x > 0.5]
        if len(pairs) < 2:
            print(f"  {name:<12} insufficient non-zero points ({len(pairs)})")
            continue
        n = len(pairs)
        sx = sum(x for x, _ in pairs)
        sy = sum(y for _, y in pairs)
        sxx = sum(x*x for x, _ in pairs)
        sxy = sum(x*y for x, y in pairs)
        denom = n * sxx - sx * sx
        if denom == 0:
            print(f"  {name:<12} constant x — can't fit")
            continue
        slope = (n * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / n
        resid = [y - (slope * x + intercept) for x, y in pairs]
        rms = (sum(r*r for r in resid) / n) ** 0.5
        print(f"  {name:<12}  slope = {slope:9.5f} km/h/LSB    intercept = {intercept:+6.3f}    "
              f"rms = {rms:.3f}    n = {n}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
