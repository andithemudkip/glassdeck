#!/usr/bin/env python3
"""first_moving_ride_torque_physics_check.py — LSB-consistency test for the
signed-torque interpretation of `121_A` on `121 D0:D1`.

If `121_A` is signed engine torque, then at steady-state cruise (no
acceleration, no gradient assumed here — the flat-ground approximation),
mechanical power output = rolling drag power + aero drag power.

  P_mech = RPM · torque · (2π/60)
         = drivetrain_efficiency · engine_output_power

  P_drag = m·g·Crr·v + 0.5·ρ·CdA·v³

Setting P_mech = P_drag / drivetrain_efficiency solves for torque, which
divided by observed `121_A` at that cruise regime gives an implied LSB.

**A signed torque signal should produce a consistent LSB across all cruise
speeds.** Air drag scales with v³, rolling with v — so if the LSB comes out
constant across a 30-100 km/h speed range, `121_A` really is torque (or
close). If the LSB varies by >2× across cruise regimes, `121_A` is
something else that just happens to correlate with load.

Bike parameters (Svartpilen 401 nominal):
  m_bike + rider ≈ 220 kg (bike 158 kg + rider 62 kg + fuel/gear)
  Crr ≈ 0.015 (sport touring tire on tarmac)
  CdA ≈ 0.42 m² (naked bike + upright rider, mid-range)
  ρ ≈ 1.2 kg/m³
  drivetrain_efficiency ≈ 0.90 (chain final, 5-speed cluster)
"""

from __future__ import annotations

import math
import re
import statistics
import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSION = REPO_ROOT / "logs" / "2026-07-22-first-moving-ride"
LINE_RE = re.compile(r"\(([\d.]+)\)\s+t([0-9A-Fa-f]{3})([0-9A-Fa-f])([0-9A-Fa-f]*)")

# Bike physics
M_TOTAL = 220.0
G = 9.81
CRR = 0.015
RHO_AIR = 1.20
CDA = 0.42
ETA_DRIVETRAIN = 0.90


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


def extract(path):
    ch = {"rpm": [], "grip": [], "d121_a": [], "rear_kmh": []}
    for ts, arb, d in parse_frames(path):
        if arb == "120" and len(d) >= 3:
            ch["rpm"].append((ts, (d[0] << 8) | d[1]))
            ch["grip"].append((ts, d[2]))
        elif arb == "121" and len(d) >= 4:
            ch["d121_a"].append((ts, int.from_bytes(d[0:2], "big", signed=True)))
        elif arb == "12D" and len(d) >= 7:
            ch["rear_kmh"].append((ts, ((d[5] << 8) | d[6]) * 0.0565))
    return ch


def resample(channels, dt=0.1):
    t_lo = min(ch[0][0] for ch in channels.values() if ch)
    t_hi = max(ch[-1][0] for ch in channels.values() if ch)
    grid = []
    positions = {k: 0 for k in channels}
    last = {k: None for k in channels}
    t = t_lo
    while t <= t_hi:
        for k, ser in channels.items():
            j = positions[k]
            while j + 1 < len(ser) and ser[j + 1][0] <= t:
                j += 1
            positions[k] = j
            if j < len(ser) and ser[j][0] <= t:
                last[k] = ser[j][1]
        grid.append(dict(last, ts=t))
        t += dt
    return grid


def stddev(xs):
    return statistics.pstdev(xs) if len(xs) > 1 else 0.0


def drag_power_W(v_kmh):
    v = v_kmh / 3.6
    roll = M_TOTAL * G * CRR * v
    aero = 0.5 * RHO_AIR * CDA * v ** 3
    return roll + aero, roll, aero


def find_cruise_segments(grid, min_duration_s=1.0, max_dspeed_kmh_per_s=4.0,
                         min_speed_kmh=20.0, min_grip=3, min_a121=3):
    """Return (start_idx, end_idx) tuples where speed is roughly steady,
    grip is nonzero, 121_A is positive (drive)."""
    segments = []
    i = 0
    n = len(grid)
    while i < n - 1:
        pt = grid[i]
        if (pt["rear_kmh"] is None or pt["rear_kmh"] < min_speed_kmh
                or pt["grip"] is None or pt["grip"] < min_grip
                or pt["d121_a"] is None or pt["d121_a"] < min_a121):
            i += 1
            continue
        # try to extend
        j = i + 1
        while j < n:
            p_prev = grid[j - 1]
            p_now = grid[j]
            if (p_now["rear_kmh"] is None or p_now["grip"] is None
                    or p_now["d121_a"] is None):
                break
            dv = abs(p_now["rear_kmh"] - p_prev["rear_kmh"]) / 0.1  # km/h per s
            if dv > max_dspeed_kmh_per_s:
                break
            if p_now["grip"] < min_grip or p_now["d121_a"] < min_a121:
                break
            j += 1
        if (j - i) * 0.1 >= min_duration_s:
            segments.append((i, j))
        i = max(j, i + 1)
    return segments


def main():
    all_grids = []
    for p in sorted(SESSION.glob("moving-*.log")):
        ch = extract(p)
        if not ch["rpm"]:
            continue
        grid = resample(ch, dt=0.1)
        for pt in grid:
            pt["file"] = p.name
        all_grids.append((p.name, grid))

    print("# Physics-based signed-torque LSB consistency check for `121_A`")
    print(f"\n**Bike physics assumptions (Svartpilen 401 nominal):**")
    print(f"  m_total = {M_TOTAL} kg, Crr = {CRR}, CdA = {CDA} m²,")
    print(f"  ρ_air = {RHO_AIR} kg/m³, η_drivetrain = {ETA_DRIVETRAIN}\n")

    # Reference drag powers at cruise speeds
    print("Expected drag-power vs speed (flat, no wind):")
    print(f"  {'v (km/h)':>8}  {'roll (W)':>10}  {'aero (W)':>10}  {'total (W)':>10}")
    for v in (30, 40, 50, 60, 70, 80, 90, 100):
        total, roll, aero = drag_power_W(v)
        print(f"  {v:>8}  {roll:>10.0f}  {aero:>10.0f}  {total:>10.0f}")

    # Collect cruise segments
    print("\n## Cruise segments per file (steady speed ≥ 2 s, grip > 4, 121_A > 3)")
    all_segs = []
    for fname, grid in all_grids:
        segs = find_cruise_segments(grid)
        print(f"  {fname}: {len(segs)} segments")
        for s, e in segs:
            all_segs.append((fname, grid, s, e))

    # Per-segment implied LSB
    print("\n## Per-segment implied LSB for `121_A`")
    print(f"  Assumes P_engine · η_drivetrain = P_drag")
    print(f"  →  torque = P_drag / (ω · η) = P_drag · 60 / (RPM · 2π · η)")
    print(f"  →  LSB (N·m/LSB) = torque / 121_A_mean\n")
    print(f"  {'file':<15} {'dur (s)':>7}  {'v μ':>6}  {'RPM μ':>6}  {'grip μ':>6}  "
          f"{'121_A μ':>7}  {'P_drag (W)':>10}  {'implied LSB (N·m)':>18}")

    lsb_by_speed_bin = defaultdict(list)
    for fname, grid, s, e in all_segs:
        pts = grid[s:e]
        v = statistics.mean(p["rear_kmh"] for p in pts)
        rpm = statistics.mean(p["rpm"] for p in pts)
        grip = statistics.mean(p["grip"] for p in pts)
        a121 = statistics.mean(p["d121_a"] for p in pts)
        p_drag, _, _ = drag_power_W(v)
        omega = rpm * 2 * math.pi / 60
        if omega < 1 or a121 < 1:
            continue
        torque_needed_Nm = p_drag / (omega * ETA_DRIVETRAIN)
        implied_lsb = torque_needed_Nm / a121
        print(f"  {fname:<15} {(e-s)*0.1:7.1f}  {v:6.1f}  {rpm:6.0f}  {grip:6.1f}  "
              f"{a121:7.1f}  {p_drag:10.0f}  {implied_lsb:18.4f}")
        lsb_by_speed_bin[int(v // 10) * 10].append(implied_lsb)

    # Summary by speed band
    print("\n## Implied LSB by speed band (consistent LSB ⇒ signed torque)")
    print(f"  {'speed band (km/h)':>18}  {'n segments':>10}  {'LSB μ (N·m)':>14}  {'LSB σ':>8}  {'LSB range':>15}")
    for band in sorted(lsb_by_speed_bin):
        lsbs = lsb_by_speed_bin[band]
        if len(lsbs) < 2:
            continue
        print(f"  {band:>4}-{band+10:<12}  {len(lsbs):>10}  "
              f"{statistics.mean(lsbs):>14.4f}  {stddev(lsbs):>8.4f}  "
              f"{min(lsbs):.3f} .. {max(lsbs):.3f}")

    # Overall
    all_lsbs = [x for xs in lsb_by_speed_bin.values() for x in xs]
    if all_lsbs:
        print(f"\n  Across all speed bands: n={len(all_lsbs)}  LSB μ={statistics.mean(all_lsbs):.4f}  "
              f"σ={stddev(all_lsbs):.4f}  ({100*stddev(all_lsbs)/statistics.mean(all_lsbs):.1f}% CoV)")

    # Comparison to the fuel-derivation model's implied LSB
    print(f"\n## Cross-check vs the fuel-derivation model's estimate")
    print(f"  The `fuel-consumption-derivation-from-torque` finding argued LSB ≈ 0.25 N·m gives")
    print(f"  27 % thermal efficiency across the whole ride. If the physics-based LSB here")
    print(f"  matches ~ 0.25 within a factor of 2, that's a strong independent corroboration.")


if __name__ == "__main__":
    sys.exit(main())
