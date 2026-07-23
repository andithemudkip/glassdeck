#!/usr/bin/env python3
"""first_moving_ride.py — wheel-speed calibration probe on the 2026-07-22 ride.

Extracts time-series of raw and decoded front/rear wheel speed from each of the
five moving-* captures and reports:

  1. Peak decoded rear vs peak decoded front per file (compare against dash max
     of 101 km/h in moving-3).
  2. Front / rear ratio across the speed range (should be ~1 if both LSBs are
     right; deviation tells us which channel is scaled wrong).
  3. Steady-state windows where decoded rear sits near 66 km/h (rider reported
     dash 60 at that time) — extract concurrent front value.
  4. Raw-value structural checks:
     - front raw_u16 modulo 16 (probes the 12-bit-in-16-bit finding under real
       motion, not just the engine-off hand-spin corpus)
     - rear raw_u16 modulo 16 (open question from signal-wheel-speed-rear).
"""

from __future__ import annotations

import re
import statistics
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSION = REPO_ROOT / "logs" / "2026-07-22-first-moving-ride"

# wifi-bridge SLCAN-style: "(sec.us) t<3-hex-id><1-hex-len><data>"
LINE_RE = re.compile(r"\(([\d.]+)\)\s+t([0-9A-Fa-f]{3})([0-9A-Fa-f])([0-9A-Fa-f]*)")


def parse_frames(path):
    """Yield (ts, arb_id_upper, data_bytes) for every valid frame in path."""
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


def extract_wheel_series(path):
    """Return list of (t, raw_front_u16, raw_rear_u16) for every 12D frame."""
    out = []
    for ts, arb, data in parse_frames(path):
        if arb != "12D" or len(data) < 8:
            continue
        raw_front = (data[0] << 8) | data[1]
        raw_rear = (data[5] << 8) | data[6]
        out.append((ts, raw_front, raw_rear))
    return out


def describe_file(name, series, *, lsb_front, lsb_rear):
    print(f"\n## {name}  ({len(series)} frames on ID 12D)")

    front_kmh = [rf * lsb_front for _, rf, _ in series]
    rear_kmh = [rr * lsb_rear for _, _, rr in series]

    print(f"  front decoded (LSB={lsb_front:.5g} km/h/LSB):"
          f"  peak {max(front_kmh):6.2f}  mean {statistics.mean(front_kmh):6.2f}")
    print(f"  rear  decoded (LSB={lsb_rear:.5g} km/h/LSB):"
          f"  peak {max(rear_kmh):6.2f}  mean {statistics.mean(rear_kmh):6.2f}")

    # Structural check: how often is the low 4 bits of the raw u16 non-zero?
    front_low4_hits = sum(1 for _, rf, _ in series if rf & 0xF)
    rear_low4_hits = sum(1 for _, _, rr in series if rr & 0xF)
    moving_front = sum(1 for _, rf, _ in series if rf > 0)
    moving_rear = sum(1 for _, _, rr in series if rr > 0)
    print(f"  raw front u16 low-nibble non-zero: {front_low4_hits} / {moving_front} moving frames"
          f"  ({100 * front_low4_hits / max(moving_front, 1):.1f}%)")
    print(f"  raw rear  u16 low-nibble non-zero: {rear_low4_hits} / {moving_rear} moving frames"
          f"  ({100 * rear_low4_hits / max(moving_rear, 1):.1f}%)")

    return front_kmh, rear_kmh


def front_rear_ratio_table(series, *, lsb_front, lsb_rear, bin_kmh=5):
    """Bin by decoded rear and report mean front/rear per bin."""
    bins = {}
    for _, rf, rr in series:
        rear_k = rr * lsb_rear
        front_k = rf * lsb_front
        if rear_k < 1:  # bike essentially stopped; ratio noise
            continue
        b = int(rear_k // bin_kmh) * bin_kmh
        bins.setdefault(b, []).append((front_k, rear_k))
    return bins


def imply_lsbs(series, *, lsb_front_current, lsb_rear_current, dash_kmh, decoded_rear_at_dash):
    """Given rider observation dash=X while our decoded rear=Y, infer both LSBs
    assuming (a) both wheels turn at the same true speed (no slip), and
    (b) the true speed at that moment was `dash_kmh` (i.e., dash reads truth)."""
    # scale factor to bring decoded rear onto the dash reading
    rear_scale = dash_kmh / decoded_rear_at_dash
    implied_lsb_rear = lsb_rear_current * rear_scale
    # for the front, we need the concurrent front decoded value — but if we
    # don't have a synchronized point, the caller passes a scalar decoded_front
    # separately. Handled outside.
    return implied_lsb_rear


def main():
    # Current codified LSBs (per findings)
    LSB_FRONT = 1 / 192  # 12-bit-in-16-bit u16 → 1/192 km/h per raw u16 LSB
    LSB_REAR = 1 / 16    # uint16 BE

    files = sorted(SESSION.glob("moving-*.log"))
    all_series = []
    per_file_peaks = []
    for f in files:
        series = extract_wheel_series(f)
        all_series.append((f.name, series))
        front, rear = describe_file(f.name, series, lsb_front=LSB_FRONT, lsb_rear=LSB_REAR)
        per_file_peaks.append((f.name, max(front), max(rear)))

    print("\n" + "=" * 78)
    print("## Per-file peak summary (current LSBs)")
    print(f"  {'file':<14}  {'front peak':>10}  {'rear peak':>10}  {'ratio F/R':>10}")
    for name, fp, rp in per_file_peaks:
        print(f"  {name:<14}  {fp:10.2f}  {rp:10.2f}  {fp/rp:10.3f}")

    # ------------------------------------------------------------------ ratio table
    print("\n" + "=" * 78)
    print("## Front/rear ratio binned by decoded rear speed (all files combined)")
    print("  (if both LSBs are correct and no slip, front/rear ≈ 1 across all bins)\n")
    combined = [tpl for _, ser in all_series for tpl in ser]
    bins = front_rear_ratio_table(combined, lsb_front=LSB_FRONT, lsb_rear=LSB_REAR, bin_kmh=10)
    print(f"  {'rear bin':>10}  {'n':>7}  {'front μ':>8}  {'rear μ':>8}  {'front/rear':>11}")
    for b in sorted(bins):
        pairs = bins[b]
        fm = statistics.mean(f for f, _ in pairs)
        rm = statistics.mean(r for _, r in pairs)
        print(f"  {b:>3}-{b+10:>3}     {len(pairs):>7}  {fm:8.2f}  {rm:8.2f}  {fm/rm:11.3f}")

    # ------------------------------------------------------------------ LSB implications
    print("\n" + "=" * 78)
    print("## LSB implications from the rider's calibration points")
    print()
    print("  Rider observation A: OEM dash steady ~60 km/h → decoded rear ~66, decoded front ~45")
    print("  Rider observation B: OEM dash peak in moving-3 = 101 km/h")
    print()

    # From observation A, if dash reads truth:
    rear_scale = 60 / 66
    front_scale = 60 / 45
    print(f"  Assuming dash = truth:")
    print(f"    rear LSB should be scaled by {rear_scale:.4f}  →  new LSB ≈ {LSB_REAR * rear_scale:.5f}"
          f" km/h/LSB  (was {LSB_REAR:.5f} = 1/16)")
    print(f"    front LSB should be scaled by {front_scale:.4f}  →  new LSB ≈ {LSB_FRONT * front_scale:.5f}"
          f" km/h/LSB  (was {LSB_FRONT:.5f} = 1/192)")
    print(f"    → rear ~ {1 / (LSB_REAR * rear_scale):.2f}⁻¹ (candidate: 1/17.6, best-fit engine-driven was 0.05633 = 1/17.75)")
    print(f"    → front ~ {1 / (LSB_FRONT * front_scale):.2f}⁻¹ (candidate: 1/144 or similar)")
    print()

    # Alternative: what if neither is right, but both channels agree with each other?
    combined_bin = front_rear_ratio_table(combined, lsb_front=LSB_FRONT, lsb_rear=LSB_REAR, bin_kmh=5)
    ratios = []
    for b in combined_bin:
        pairs = combined_bin[b]
        fm = statistics.mean(f for f, _ in pairs)
        rm = statistics.mean(r for _, r in pairs)
        if rm > 0:
            ratios.append(fm / rm)
    if ratios:
        avg_ratio = statistics.mean(ratios)
        print(f"  Empirical mean front/rear ratio (bike moving > 1 km/h): {avg_ratio:.3f}")
        print(f"  If BOTH channels are meant to report the same physical km/h, the ratio should be 1.")
        print(f"  Observed ratio → one channel is scaled ~{100*abs(1-avg_ratio):.0f}% off relative to the other.")

    # ------------------------------------------------------------------ moving-3 peak vs dash 101
    print()
    for name, ser in all_series:
        if "moving-3" not in name:
            continue
        front_kmh = [rf * LSB_FRONT for _, rf, _ in ser]
        rear_kmh = [rr * LSB_REAR for _, _, rr in ser]
        peak_front = max(front_kmh)
        peak_rear = max(rear_kmh)
        print(f"  moving-3 peak (dash reported 101 km/h at some point):")
        print(f"    decoded front peak = {peak_front:.2f}")
        print(f"    decoded rear  peak = {peak_rear:.2f}")
        print(f"    if dash 101 = truth,")
        print(f"      implied rear LSB ~ {LSB_REAR * 101 / peak_rear:.5f} km/h/LSB")
        print(f"      implied front LSB ~ {LSB_FRONT * 101 / peak_front:.5f} km/h/LSB")


if __name__ == "__main__":
    sys.exit(main())
