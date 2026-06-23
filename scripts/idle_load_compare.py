#!/usr/bin/env python3
"""idle_load_compare.py — neutral idle vs in-gear-clutch-slip idle, same session.

Within the 2026-06-23-engine-driven-rear-spin capture, the timeline gives a
free MAP/engine-load test for `540` D1 — no extra capture needed:

  - engine-off (key on, pre-start) ............ baseline 0 reference
  - idle-neutral pre-Phase-A ................... engine warm, no load
  - Phase A — idle in 1st (clutch out, ~idle) .. engine warm, drivetrain load
  - B1..B5 .................................... (analyzed elsewhere)
  - Phase C — idle in 1st (post-sweep) ........ engine warm, drivetrain load
  - idle-neutral post-Phase-C ................. engine warm, no load
  - post-kill ................................. decay

If `540` D1 is a load proxy (MAP / injection pulse-width / engine-load %), then
at matched RPM and matched coolant temp:

  D1(idle in 1st, clutch out) > D1(idle in neutral)

because the drivetrain demands more torque to keep the rear wheel spinning,
which the ECU meets by adding fuel/air — manifold pressure rises, computed
load rises, pulse-width rises.

If D1 is coolant-only, the in-gear and neutral idle reads will match within
noise (coolant is identical, the idle controller just nudges air/fuel up and
those nudges aren't reflected in D1).

If D1 is throttle-derived, it should track `120` D2 (throttle position byte)
in lockstep across the two conditions.

Reports per-window mean ± std for RPM, throttle, D1, coolant, plus a delta
table aligned to the neutral-idle reference.
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

SKIP_S = 3.0   # let each window settle before sampling


def parse_events(path):
    out = {}
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            out.setdefault(r["label"], t)
    return out


def parse_log(path, ids):
    out = {arb: [] for arb in ids}
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            arb = m.group(2).upper()
            if arb not in out:
                continue
            hex_data = m.group(3)
            if len(hex_data) != 16:
                continue
            out[arb].append((float(m.group(1)), bytes.fromhex(hex_data)))
    return out


def window(frames, t0, t1):
    return [(ts, d) for ts, d in frames if t0 <= ts <= t1]


def stat(values):
    if not values:
        return None
    vals = list(values)
    mn, mx = min(vals), max(vals)
    mean = sum(vals) / len(vals)
    std = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    return {"mean": mean, "min": mn, "max": mx, "std": std, "n": len(vals)}


def fmt(s):
    if s is None:
        return "    —    "
    return f"{s['mean']:6.2f} ±{s['std']:4.2f}"


def summarize(frames, t0, t1):
    win_120 = window(frames["120"], t0, t1)
    win_540 = window(frames["540"], t0, t1)
    rpm = stat([(d[0] << 8) | d[1] for _, d in win_120])
    thr = stat([d[2] for _, d in win_120])
    d1 = stat([d[1] for _, d in win_540])
    coolant = stat([((d[5] << 8) | d[6]) / 10.0 for _, d in win_540])
    return {"rpm": rpm, "throttle": thr, "d1": d1, "coolant": coolant,
            "duration": t1 - t0, "n_120": len(win_120), "n_540": len(win_540)}


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--session", default="logs/2026-06-23-engine-driven-rear-spin")
    args = p.parse_args()

    session = REPO_ROOT / args.session
    events = parse_events(session / "events.csv")
    frames = parse_log(session / "capture.log", {"120", "540"})

    # Anchor timestamps for each window.
    key_on   = events["key on"]
    starter  = events["starter pressed"]
    idle_set = events["idle settled (neutral)"]
    phase_a  = events["Phase A — idle in 1st"]
    b1       = events["B1 — ~2000 RPM in 1st"]
    phase_c  = events["Phase C — idle in 1st (post-sweep)"]
    to_n     = events["back to neutral"]
    kill     = events["kill switch"]

    # Define windows. SKIP_S in from each leading edge to let the engine settle
    # into the new state; trail edge is the start of the next mark.
    windows = [
        ("engine-off (pre-start)",        key_on + 1.0,        starter - 1.0),
        ("neutral idle (engine on)",      idle_set + SKIP_S,   phase_a - 1.0),
        ("Phase A — idle in 1st",         phase_a + SKIP_S,    b1 - 1.0),
        ("Phase C — idle in 1st (post)",  phase_c + SKIP_S,    to_n - 1.0),
        ("neutral idle (return)",         to_n + SKIP_S,       kill - 1.0),
    ]

    print(f"# Idle-load comparison — {args.session}")
    print(f"# Hypothesis: if `540` D1 is engine-load, D1(in-gear) > D1(neutral) at matched RPM and coolant.\n")

    print(f"  {'window':<32}  {'dur':>5}  {'RPM':>14}  {'throttle':>14}  {'540 D1':>14}  {'coolant °C':>14}")
    results = []
    for name, t0, t1 in windows:
        if t1 - t0 < 1.0:
            print(f"  {name:<32}  {'—':>5}   window too short")
            continue
        s = summarize(frames, t0, t1)
        print(f"  {name:<32}  {s['duration']:5.1f}  "
              f"{fmt(s['rpm'])}  {fmt(s['throttle'])}  {fmt(s['d1'])}  {fmt(s['coolant'])}")
        results.append((name, s))

    # ---- Pairwise comparison: neutral-idle reference vs in-gear conditions ---
    print("\n## Δ vs neutral-idle (engine on) reference\n")
    ref = next((s for n, s in results if n == "neutral idle (engine on)"), None)
    if ref is None or ref["d1"] is None:
        print("  no neutral-idle reference available")
        return 1
    ref_d1 = ref["d1"]["mean"]
    ref_rpm = ref["rpm"]["mean"]
    ref_thr = ref["throttle"]["mean"]
    ref_coolant = ref["coolant"]["mean"]
    print(f"  reference: RPM={ref_rpm:.1f}, throttle={ref_thr:.2f}, D1={ref_d1:.2f}, coolant={ref_coolant:.2f} °C\n")
    print(f"  {'window':<32}  {'ΔRPM':>8}  {'Δthrottle':>10}  {'ΔD1':>8}  {'Δcoolant':>10}")
    for name, s in results:
        if name == "neutral idle (engine on)" or s["d1"] is None:
            continue
        d_rpm = s["rpm"]["mean"] - ref_rpm
        d_thr = s["throttle"]["mean"] - ref_thr
        d_d1 = s["d1"]["mean"] - ref_d1
        d_coolant = s["coolant"]["mean"] - ref_coolant
        print(f"  {name:<32}  {d_rpm:+8.1f}  {d_thr:+10.2f}  {d_d1:+8.2f}  {d_coolant:+10.2f}")

    # ---- Verdict ------------------------------------------------------------
    print("\n## Verdict\n")
    in_gear = [(n, s) for n, s in results if "in 1st" in n]
    if not in_gear:
        print("  no in-gear windows found")
        return 0
    in_gear_d1 = [s["d1"]["mean"] for _, s in in_gear if s["d1"]]
    in_gear_rpm = [s["rpm"]["mean"] for _, s in in_gear if s["rpm"]]
    in_gear_thr = [s["throttle"]["mean"] for _, s in in_gear if s["throttle"]]
    mean_in_gear_d1 = sum(in_gear_d1) / len(in_gear_d1)
    mean_in_gear_rpm = sum(in_gear_rpm) / len(in_gear_rpm)
    mean_in_gear_thr = sum(in_gear_thr) / len(in_gear_thr)
    delta_d1 = mean_in_gear_d1 - ref_d1
    delta_rpm = mean_in_gear_rpm - ref_rpm
    delta_thr = mean_in_gear_thr - ref_thr
    ref_d1_std = ref["d1"]["std"]
    threshold = max(0.5, 2 * ref_d1_std)

    print(f"  mean in-gear D1 = {mean_in_gear_d1:.2f}, neutral-idle D1 = {ref_d1:.2f}, Δ = {delta_d1:+.2f}")
    print(f"  (neutral-idle D1 std = {ref_d1_std:.2f}; calling Δ significant if |Δ| > {threshold:.2f})\n")
    print(f"  RPM Δ in-gear vs neutral:      {delta_rpm:+.1f}  ({'≈ matched' if abs(delta_rpm) < 100 else 'CONFOUND — idle controller did not match RPM'})")
    print(f"  throttle Δ in-gear vs neutral: {delta_thr:+.2f}  ({'≈ matched' if abs(delta_thr) < 1.0 else 'throttle differs — D1 could be throttle-derived'})")
    print()

    if abs(delta_d1) < threshold:
        print(f"  → D1 indistinguishable between in-gear and neutral idle at matched RPM/coolant.")
        print(f"    Consistent with coolant-only / RPM-only / throttle-only encoding;")
        print(f"    AGAINST the engine-load / MAP hypothesis from the in-gear sweep.")
    elif delta_d1 > 0:
        print(f"  → D1(in-gear) > D1(neutral) by {delta_d1:.2f}.")
        print(f"    Consistent with engine-load / MAP / injection-pulse-width encoding;")
        print(f"    SUPPORTS the load hypothesis. Cross-check vs Δthrottle above — if throttle")
        print(f"    also rose to keep idle in gear, D1 could be tracking throttle rather than")
        print(f"    load directly. Phase E (neutral RPM setpoints) is still the cleanest test")
        print(f"    because it decouples throttle from RPM/load.")
    else:
        print(f"  → D1(in-gear) < D1(neutral) by {-delta_d1:.2f}.")
        print(f"    UNEXPECTED — load hypothesis predicts the opposite direction.")
        print(f"    Possible explanations: idle controller cut throttle in gear (check Δthrottle),")
        print(f"    or D1 is a quantity that drops under load (AFR-shaped) rather than rising.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
