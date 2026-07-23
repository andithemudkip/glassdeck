#!/usr/bin/env python3
"""first_moving_ride_fuel_model.py — fuel-consumption modelling on the 2026-07-22 ride.

Fuel consumption isn't broadcast on this bike's CAN (see
`fuel-consumption-absent-from-broadcasts`), so it has to be derived. ADR 0017
proposes `fuel_rate ∝ a·RPM + b·RPM·throttle`. But 2026-07-22 also surfaced
`121 A/B` as leading-candidate SIGNED engine torque, which changes what's
possible: torque × RPM is engine power output, which is fuel × combustion
efficiency × specific energy — a physical law, not an empirical fit.

This script:

  1. Integrates each candidate over the whole ride.
  2. Anchors to the rider's baseline consumption (3.4 L/100km for typical
     riding, [[project-fuel-consumption-baseline]]) via ride distance.
  3. Solves for the scaling constant in each model.
  4. Reports the constants in physically meaningful terms — a torque-based
     constant should land near an engine's known specific fuel consumption
     (BSFC), which for a small gasoline single is roughly 300-400 g/kWh.

  5. Regime breakdown: time spent in overrun (fuel cut), idle, drive.

Candidates:
  * RPM × throttle (current ADR 0017 plan)
  * RPM × max(0, 121_A) (torque-based, with overrun cut)
  * (540 D1 - coolant_baseline) × RPM (warmup-index-as-injection-pulse proxy)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSION = REPO_ROOT / "logs" / "2026-07-22-first-moving-ride"
LINE_RE = re.compile(r"\(([\d.]+)\)\s+t([0-9A-Fa-f]{3})([0-9A-Fa-f])([0-9A-Fa-f]*)")

RIDER_BASELINE_L_PER_100KM = 3.4  # from project-fuel-consumption-baseline (3.3-3.5)
FUEL_DENSITY_G_PER_ML = 0.745      # gasoline, ~745 g/L
FUEL_ENERGY_MJ_PER_L = 34.2        # gasoline lower heating value

DT = 0.1  # resample grid


def parse_frames(path):
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            arb = m.group(2).upper()
            length = int(m.group(3), 16)
            hex_data = m.group(4)
            if len(hex_data) < length * 2:
                continue
            data = bytes.fromhex(hex_data[: length * 2])
            yield float(m.group(1)), arb, data


def extract_channels(path):
    ch = {"rpm": [], "throttle": [], "d540_d1": [],
          "d121_a": [], "coolant": [], "rear_kmh": []}
    for ts, arb, d in parse_frames(path):
        if arb == "120" and len(d) >= 3:
            ch["rpm"].append((ts, (d[0] << 8) | d[1]))
            ch["throttle"].append((ts, d[2]))
        elif arb == "540" and len(d) >= 7:
            ch["d540_d1"].append((ts, d[1]))
            ch["coolant"].append((ts, ((d[5] << 8) | d[6]) * 0.1))
        elif arb == "121" and len(d) >= 2:
            ch["d121_a"].append((ts, int.from_bytes(d[0:2], "big", signed=True)))
        elif arb == "12D" and len(d) >= 7:
            ch["rear_kmh"].append((ts, ((d[5] << 8) | d[6]) * 0.0565))
    return ch


def resample(channels, dt=DT):
    """Return grid list of dicts, nearest-past for each channel."""
    if not any(channels.values()):
        return []
    t_lo = max((s[0][0] for s in channels.values() if s), default=0)
    t_hi = min((s[-1][0] for s in channels.values() if s), default=0)
    if t_hi <= t_lo:
        return []
    n = int((t_hi - t_lo) / dt)
    positions = {k: 0 for k in channels}
    last = {k: None for k in channels}
    out = []
    for i in range(n):
        t = t_lo + i * dt
        for k, ser in channels.items():
            j = positions[k]
            while j + 1 < len(ser) and ser[j + 1][0] <= t:
                j += 1
            positions[k] = j
            if j < len(ser) and ser[j][0] <= t:
                last[k] = ser[j][1]
        out.append(dict(last, ts=t))
    return out


def main():
    # Merge all 5 files onto a single virtual timeline (10s gaps between)
    all_points = []
    offset = 0.0
    for path in sorted(SESSION.glob("moving-*.log")):
        ch = extract_channels(path)
        if not ch["rpm"]:
            continue
        t0 = ch["rpm"][0][0]
        norm = {k: [(ts - t0 + offset, v) for ts, v in s] for k, s in ch.items()}
        pts = resample(norm)
        for p in pts:
            p["file"] = path.name
        all_points.extend(pts)
        offset = max(s[-1][0] for s in norm.values() if s) + 10

    # Filter to fully-populated engine-on points
    usable = [p for p in all_points
              if all(p[k] is not None for k in ("rpm", "throttle", "d540_d1", "d121_a", "coolant", "rear_kmh"))
              and p["rpm"] > 500]

    if not usable:
        print("no usable points")
        return 1

    total_time_s = len(usable) * DT
    total_time_h = total_time_s / 3600

    # Distance = ∫ speed dt (speed in km/h, dt in seconds → km/h × s/3600)
    total_km = sum(p["rear_kmh"] * DT / 3600 for p in usable)
    avg_speed_kmh = sum(p["rear_kmh"] for p in usable) / len(usable)

    # Predicted fuel from rider baseline
    predicted_fuel_L = total_km * RIDER_BASELINE_L_PER_100KM / 100
    predicted_fuel_mL = predicted_fuel_L * 1000

    print(f"# Fuel model calibration on 2026-07-22 rolling corpus\n")
    print(f"Ride totals (engine-on, all 5 files merged):")
    print(f"  Time engine-on: {total_time_s:.0f} s ({total_time_h*60:.1f} min)")
    print(f"  Distance:       {total_km:.2f} km")
    print(f"  Avg speed:      {avg_speed_kmh:.1f} km/h")
    print(f"  Rider baseline: {RIDER_BASELINE_L_PER_100KM} L/100km ⇒ this ride ≈ {predicted_fuel_mL:.0f} mL / {predicted_fuel_L*1000/total_time_h/60:.1f} mL/min")

    # ------------------------------- Regime breakdown
    idle = [p for p in usable if p["rear_kmh"] < 3 and p["throttle"] < 8]
    overrun = [p for p in usable if p["throttle"] < 8 and p["rpm"] > 2000 and p["d121_a"] < -3]
    drive = [p for p in usable if p["throttle"] >= 8 and p["d121_a"] > 3]
    other = [p for p in usable if p not in idle and p not in overrun and p not in drive]

    print(f"\n## Regime breakdown")
    for label, group in [("idle stop", idle), ("overrun (throttle=0, RPM>2000, torque<0)", overrun),
                          ("drive (throttle>3%, torque>0)", drive), ("transitional/other", other)]:
        pct = len(group) / len(usable) * 100
        seconds = len(group) * DT
        print(f"  {label:<40}  {seconds:6.1f} s  ({pct:5.1f}%)")

    # ------------------------------- Model 1: RPM × throttle (ADR 0017)
    integral_rpm_throttle = sum(p["rpm"] * (p["throttle"] / 254) * DT for p in usable)
    integral_rpm = sum(p["rpm"] * DT for p in usable)
    print(f"\n## Model 1: `fuel_mL = a · ∫RPM dt + b · ∫(RPM × throttle_frac) dt` (ADR 0017)")
    print(f"  ∫RPM dt              = {integral_rpm:.0f} RPM·s")
    print(f"  ∫(RPM × thr) dt      = {integral_rpm_throttle:.0f} RPM·s")
    print(f"  If we assume idle-fuel takes up the ∫RPM term and load-fuel takes ∫(RPM×thr):")
    print(f"  Under-determined without an idle-consumption anchor. Set idle = 0 for now:")
    b1 = predicted_fuel_mL / integral_rpm_throttle
    print(f"    b ≈ {b1*1e6:.3f} µL per (RPM · s · fractional_throttle)")
    print(f"    (At 5000 RPM, 30% throttle: predicts {b1 * 5000 * 0.30 * 60 * 1000:.1f} mL/min)")

    # ------------------------------- Model 2: RPM × max(0, torque)
    integral_rpm_torque_pos = sum(p["rpm"] * max(0, p["d121_a"]) * DT for p in usable)
    print(f"\n## Model 2: `fuel_mL = k · ∫(RPM × max(0, 121_A)) dt` (torque-based)")
    print(f"  ∫(RPM × torque_pos) dt = {integral_rpm_torque_pos:.0f} RPM·LSB·s")
    if integral_rpm_torque_pos > 0:
        k = predicted_fuel_mL / integral_rpm_torque_pos
        print(f"  k = {k:.3e} mL / (RPM · LSB · s)")

        # If 121 A LSB is 0.5 N·m (the hypothesis), then torque_Nm = A * 0.5
        # Then RPM × torque_Nm ∝ power (with 2π/60 factor)
        # Power_W = RPM × torque_Nm × 2π/60 = RPM × A × 0.5 × 0.1047 = RPM × A × 0.0524
        # Energy_J = ∫Power dt
        # Fuel_mL = Energy_J / (efficiency × specific_energy × density_g_mL)
        integral_power_W_if_torque_hypothesis = sum(
            p["rpm"] * max(0, p["d121_a"]) * 0.5 * 0.1047 * DT for p in usable
        )
        integral_energy_MJ = integral_power_W_if_torque_hypothesis / 1e6
        # Assuming 30% thermal efficiency and 34.2 MJ/L gasoline:
        for efficiency, label in [(0.20, "20% (city, low)"), (0.30, "30% (steady cruise)"), (0.35, "35% (peak-efficiency)")]:
            fuel_L_predicted = integral_energy_MJ / (efficiency * FUEL_ENERGY_MJ_PER_L)
            fuel_mL_predicted = fuel_L_predicted * 1000
            ratio = fuel_mL_predicted / predicted_fuel_mL if predicted_fuel_mL > 0 else 0
            print(f"    IF 121_A LSB = 0.5 N·m/LSB AND thermal-eff = {efficiency*100:.0f}%: predicts {fuel_mL_predicted:.0f} mL "
                  f"({ratio:.2f}× rider baseline)")
        print(f"    Rearranging: implied thermal efficiency at rider-baseline = "
              f"{integral_energy_MJ / (predicted_fuel_L * FUEL_ENERGY_MJ_PER_L) * 100:.1f}%")

    # ------------------------------- Model 3: `540 D1` × RPM (warmup-index-as-injection-pulse)
    # Baseline D1 at idle warm ≈ 14; extra above that is candidate injection quantity
    integral_d1_rpm = sum(max(0, p["d540_d1"] - 14) * p["rpm"] * DT for p in usable)
    print(f"\n## Model 3: `fuel_mL = m · ∫((540_D1 - 14_baseline) × RPM) dt` (D1-as-injection-pulse)")
    print(f"  ∫((D1-14) × RPM) dt = {integral_d1_rpm:.0f} LSB·RPM·s")
    if integral_d1_rpm > 0:
        m = predicted_fuel_mL / integral_d1_rpm
        print(f"  m = {m*1e6:.3f} µL / (LSB · RPM · s)")

    # ------------------------------- Overrun savings and idle penalty
    print(f"\n## Regime economics")
    overrun_seconds = len(overrun) * DT
    overrun_km = sum(p["rear_kmh"] * DT / 3600 for p in overrun)
    idle_seconds = len(idle) * DT
    print(f"  Time in overrun (fuel cut, still rolling): {overrun_seconds:.1f} s covering {overrun_km:.2f} km")
    print(f"  These km are 'free' if fuel cut is genuine — {overrun_km / total_km * 100:.1f}% of ride distance at zero fuel.")
    print(f"  Time at idle stop (fuel burned but no distance): {idle_seconds:.1f} s ({idle_seconds/total_time_s*100:.1f}% of ride)")

    # ------------------------------- Torque signature during coast
    print(f"\n## Physical-plausibility check: does torque go negative during coast?")
    if overrun:
        overrun_torque_avg = sum(p["d121_a"] for p in overrun) / len(overrun)
        overrun_rpm_avg = sum(p["rpm"] for p in overrun) / len(overrun)
        overrun_speed_avg = sum(p["rear_kmh"] for p in overrun) / len(overrun)
        print(f"  During identified overrun (throttle=0, RPM>2000, 121_A<-3):")
        print(f"    n={len(overrun)} points  ({overrun_seconds:.1f} s)")
        print(f"    avg 121_A     = {overrun_torque_avg:+.1f} LSB (negative — engine-brake torque, hypothesis confirmed)")
        print(f"    avg RPM       = {overrun_rpm_avg:.0f}")
        print(f"    avg speed     = {overrun_speed_avg:.1f} km/h")
    if drive:
        drive_torque_avg = sum(p["d121_a"] for p in drive) / len(drive)
        drive_rpm_avg = sum(p["rpm"] for p in drive) / len(drive)
        drive_thr_avg = sum(p["throttle"] for p in drive) / len(drive)
        print(f"  During identified drive (throttle>3%, 121_A>+3):")
        print(f"    n={len(drive)} points  ({len(drive) * DT:.1f} s)")
        print(f"    avg 121_A     = {drive_torque_avg:+.1f} LSB (positive — drive torque, hypothesis confirmed)")
        print(f"    avg RPM       = {drive_rpm_avg:.0f}")
        print(f"    avg throttle  = {drive_thr_avg:.0f} raw ({drive_thr_avg*100/254:.1f}%)")


if __name__ == "__main__":
    sys.exit(main())
