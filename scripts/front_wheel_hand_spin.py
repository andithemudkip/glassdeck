#!/usr/bin/env python3
"""front_wheel_hand_spin.py — analyse the 2026-06-24 front-wheel hand-spin capture.

Free-form session (no event marks). The `12D` D0..D1 bytes self-delimit
motion windows. For each contiguous push window:

  - peak D0, peak D1, peak raw uint16 (BE)
  - duration, frame count
  - sanity-check that D2/D5/D6 stay at 0 (front-only motion)

Then runs the encoding mirror-test (uint16 vs uint8) on Phase A pushes
and fits an LSB calibration against the rider-reported dash peaks.

Usage:
  python scripts/front_wheel_hand_spin.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSION = REPO_ROOT / "logs" / "2026-06-24-front-wheel-hand-spin"
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

# Rider-reported dash peaks per push, in order (km/h). Phase C is sustained,
# so its "peak" is the held value, not a transient.
RIDER_NOTES = [
    ("A1", 4, "Phase A gentle"),
    ("A2", 3, "Phase A gentle"),
    ("A3", 3, "Phase A gentle"),
    ("A4", 3, "Phase A gentle"),
    ("B1", 10, "Phase B harder"),
    ("B2", 7,  "Phase B harder"),
    ("B3", 9,  "Phase B harder"),
    ("B4", 11, "Phase B harder"),
    ("C",  5,  "Phase C sustained ~4-5"),
]

# A push is a contiguous run of 12D frames where any of D0,D1,D2,D5,D6
# is non-zero. We split windows on a gap of >= GAP_S where everything's
# back to zero (the wheel has stopped between pushes).
GAP_S = 0.5


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


def segment_pushes(frames_12d, gap_s=GAP_S):
    """Return list of (start_ts, end_ts, [(ts, data), ...]) for each push."""
    motion = []
    for ts, arb, d in frames_12d:
        # Front bytes (D0,D1) or rear bytes (D2,D5,D6) non-zero -> motion frame
        if d[0] or d[1] or d[2] or d[5] or d[6]:
            motion.append((ts, d))
    if not motion:
        return []
    pushes = []
    cur = [motion[0]]
    for ts, d in motion[1:]:
        if ts - cur[-1][0] > gap_s:
            pushes.append(cur)
            cur = []
        cur.append((ts, d))
    pushes.append(cur)
    # Keep only windows with at least a handful of frames
    return [p for p in pushes if len(p) >= 3]


def summarise(push):
    """Per-push stats."""
    start = push[0][0]
    end = push[-1][0]
    peak_d0 = max(d[0] for _, d in push)
    peak_d1 = max(d[1] for _, d in push)
    peak_uint16 = max((d[0] << 8) | d[1] for _, d in push)
    # Rear-byte sanity check
    peak_d2 = max(d[2] for _, d in push)
    peak_d5 = max(d[5] for _, d in push)
    peak_d6 = max(d[6] for _, d in push)
    # Co-occurrence: when D0..D1 are non-zero, what's D0 vs D1 distribution?
    front_active = [(d[0], d[1]) for _, d in push if d[0] or d[1]]
    if front_active:
        d0_nonzero_frames = sum(1 for a, _ in front_active if a)
        d1_nonzero_frames = sum(1 for _, b in front_active if b)
    else:
        d0_nonzero_frames = d1_nonzero_frames = 0
    return {
        "start": start,
        "end": end,
        "duration": end - start,
        "n_frames": len(push),
        "n_front_active": len(front_active),
        "peak_d0": peak_d0,
        "peak_d1": peak_d1,
        "peak_uint16": peak_uint16,
        "peak_d2": peak_d2,
        "peak_d5": peak_d5,
        "peak_d6": peak_d6,
        "d0_nonzero_frames": d0_nonzero_frames,
        "d1_nonzero_frames": d1_nonzero_frames,
    }


def main():
    frames = parse_log(SESSION / "capture.log")
    frames_12d = [(ts, arb, d) for ts, arb, d in frames if arb == "12D"]
    print(f"# Loaded {len(frames)} frames, {len(frames_12d)} on 12D")

    t0 = frames[0][0]
    pushes = segment_pushes(frames_12d)
    print(f"# Detected {len(pushes)} push windows (gap-split at {GAP_S}s)\n")

    summaries = [summarise(p) for p in pushes]

    # ---------- per-push table
    print("# Per-push summary (12D)")
    print(f"  {'#':>2}  {'t+':>7}  {'dur':>5}  {'frames':>6}  "
          f"{'pk D0':>5}  {'pk D1':>5}  {'pk u16':>7}  "
          f"{'D0nz':>5}  {'D1nz':>5}  "
          f"{'pk D2':>5}  {'pk D5':>5}  {'pk D6':>5}")
    for i, s in enumerate(summaries):
        t_off = s["start"] - t0
        print(f"  {i+1:>2}  {t_off:>7.2f}  {s['duration']:>5.2f}  "
              f"{s['n_frames']:>6}  "
              f"{s['peak_d0']:>5}  {s['peak_d1']:>5}  {s['peak_uint16']:>7}  "
              f"{s['d0_nonzero_frames']:>5}  {s['d1_nonzero_frames']:>5}  "
              f"{s['peak_d2']:>5}  {s['peak_d5']:>5}  {s['peak_d6']:>5}")

    # ---------- rear-bytes sanity
    print("\n# Rear-byte sanity (D2/D5/D6 should stay at 0 — front-only motion)")
    rear_nonzero = sum(1 for s in summaries if s["peak_d2"] or s["peak_d5"] or s["peak_d6"])
    if rear_nonzero == 0:
        print("  All push windows: D2/D5/D6 stayed at 0x00. Rear sensor stationary. OK.")
    else:
        print(f"  WARNING: {rear_nonzero} push window(s) had non-zero rear bytes.")

    # ---------- encoding mirror-test (Phase A — low speed regime)
    print("\n# Encoding mirror-test on Phase A (low speed)")
    print("  If uint16 BE (D0=hi, D1=lo): D1 active, D0 stays at 0 for raw < 256.")
    print("  If uint8 (D0 only):          D0 active, D1 stays at 0.")
    print("  If uint8 (D1 only):          D1 active, D0 stays at 0.\n")
    for i, s in enumerate(summaries[:4]):
        verdict = "?"
        if s["peak_d0"] == 0 and s["peak_d1"] > 0:
            verdict = "D1-only (uint16 lo-byte, or single-byte at D1)"
        elif s["peak_d1"] == 0 and s["peak_d0"] > 0:
            verdict = "D0-only (single-byte at D0)"
        elif s["peak_d0"] and s["peak_d1"]:
            verdict = "BOTH active — uint16 with raw>=256 or different encoding"
        else:
            verdict = "no front-byte motion"
        print(f"  push #{i+1}: peak D0={s['peak_d0']:>3}  peak D1={s['peak_d1']:>3}  -> {verdict}")

    # ---------- LSB calibration against rider's dash notes
    print("\n# LSB calibration (raw uint16 BE on D0:D1 vs dash km/h)")
    if len(summaries) != len(RIDER_NOTES):
        print(f"  WARNING: {len(summaries)} detected pushes vs {len(RIDER_NOTES)} rider notes")
        print(f"  Detected counts must match for the calibration to align.")
    n = min(len(summaries), len(RIDER_NOTES))
    print(f"  {'tag':>4}  {'phase':<22}  {'dash km/h':>9}  {'raw u16':>7}  "
          f"{'km/h per LSB':>13}  {'1/LSB':>7}")
    pairs = []  # (raw, dash)
    for (tag, dash_kmh, phase), s in zip(RIDER_NOTES[:n], summaries[:n]):
        raw = s["peak_uint16"]
        if raw == 0:
            print(f"  {tag:>4}  {phase:<22}  {dash_kmh:>9}  {raw:>7}  {'—':>13}  {'—':>7}")
            continue
        lsb = dash_kmh / raw
        inv = 1 / lsb if lsb else 0
        pairs.append((raw, dash_kmh))
        print(f"  {tag:>4}  {phase:<22}  {dash_kmh:>9}  {raw:>7}  "
              f"{lsb:>13.5f}  {inv:>7.2f}")

    if len(pairs) >= 2:
        # Simple least-squares through origin: km/h = LSB * raw
        sx2 = sum(r * r for r, _ in pairs)
        sxy = sum(r * k for r, k in pairs)
        lsb_fit = sxy / sx2
        # Residuals
        residuals = [k - lsb_fit * r for r, k in pairs]
        ss_res = sum(e * e for e in residuals)
        rms = (ss_res / len(pairs)) ** 0.5
        print(f"\n  Through-origin fit: km/h = {lsb_fit:.5f} * raw_u16")
        print(f"    1 / LSB = {1/lsb_fit:.3f}   (predicted: 16 for ~1/16 km/h, matching rear)")
        print(f"    RMS residual: {rms:.3f} km/h  (dash quantises to integer km/h)")

    # ---------- D5:D6 reference: rear LSB transfer
    print("\n# Reminder: rear D5:D6 LSB was 0.05633 km/h (best-fit), ~10% under 1/16 = 0.0625.")
    print("  If front fit lands on 0.0625, it transfers to rear by shared encoding family")
    print("  and closes the [[signal-wheel-speed-rear]] § Open 'Exact LSB' question.")


if __name__ == "__main__":
    main()
