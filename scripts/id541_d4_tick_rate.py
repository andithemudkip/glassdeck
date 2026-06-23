#!/usr/bin/env python3
"""id541_d4_tick_rate.py — does 541 D4 (low 7 bits) tick at engine-time or wall-clock?

The bit-transition scan flagged 541 D4 bits 0..6 as a monotonic 7-bit counter
that only ticks engine-on at roughly 1 Hz at idle (see
docs/experiments/2026-06-21-bit-transition-scan.md). Three live hypotheses:

  (a) wall-clock seconds counter           → tick_rate constant ≈ 1 Hz
  (b) engine-cycle / fuel-injection events → tick_rate scales ∝ RPM
  (c) integrated fuel mass / consumption   → tick_rate scales ∝ RPM × throttle

The 2026-06-23 engine-driven-rear-spin capture holds steady RPM setpoints at
~2000, 2500, 3500, 4500, 5500. Bin frames by RPM, measure mean tick rate per
bin. Outcome decides the next step on the fuel-consumption hunt.

Usage:
    python scripts/id541_d4_tick_rate.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from cross_session_diff import parse_log  # type: ignore  # noqa: E402

COUNTER_MASK = 0x7F           # bits 0..6
COUNTER_MOD = 128


def decode_120(data: bytes) -> tuple[int, int]:
    """(rpm, throttle_raw 0..254) from a 120 frame."""
    rpm = (data[0] << 8) | data[1]
    return rpm, data[2]


def accumulate_ticks(frames):
    """Walk 541 frames in time order, return list of (ts, cumulative_ticks)."""
    out = []
    prev = None
    cum = 0
    for ts, _arb, data in frames:
        v = data[4] & COUNTER_MASK
        if prev is None:
            out.append((ts, 0))
        else:
            delta = (v - prev) % COUNTER_MOD
            # Sanity: legit ticks are small per 20 ms frame. A delta > 64 most
            # likely means we missed something or bit 7 leaked — clamp/print.
            if delta > 64:
                # treat as backward (counter behaviour means an apparent
                # wrap-equivalent of >64 forward is more parsimoniously a
                # small reverse — ignore).
                delta = 0
            cum += delta
            out.append((ts, cum))
        prev = v
    return out


def rpm_throttle_series(frames):
    """Return list of (ts, rpm, throttle_raw) from 120 frames in order."""
    out = []
    for ts, _arb, data in frames:
        rpm, thr = decode_120(data)
        out.append((ts, rpm, thr))
    return out


def interp(series, ts):
    """Linear interpolate (ts, value) series at given timestamp. Series sorted."""
    import bisect
    times = [s[0] for s in series]
    i = bisect.bisect_left(times, ts)
    if i <= 0:
        return series[0][1:]
    if i >= len(series):
        return series[-1][1:]
    t0, *v0 = series[i - 1]
    t1, *v1 = series[i]
    if t1 == t0:
        return v0
    f = (ts - t0) / (t1 - t0)
    return tuple(a + (b - a) * f for a, b in zip(v0, v1))


def analyze(session_path: Path) -> None:
    print(f"\n## {session_path.name}")
    frames = parse_log(session_path / "capture.log")
    if not frames:
        print("  (no frames)")
        return

    frames_541 = [f for f in frames if f[1] == "541"]
    frames_120 = [f for f in frames if f[1] == "120"]
    if not frames_541 or not frames_120:
        print(f"  (missing data — 541={len(frames_541)} 120={len(frames_120)})")
        return

    ticks = accumulate_ticks(frames_541)
    t0, t_end = ticks[0][0], ticks[-1][0]
    total_ticks = ticks[-1][1]
    dur = t_end - t0
    print(f"  duration {dur:.1f} s, 541 frames {len(frames_541)}, "
          f"total ticks {total_ticks}, mean {total_ticks/dur:.2f}/s")

    # Build (rpm, throttle) series from 120
    rpm_thr = rpm_throttle_series(frames_120)

    # For each 541 frame, get co-temporal (rpm, throttle) by interpolation.
    samples = []
    for i, (ts, cum) in enumerate(ticks):
        rpm, thr = interp(rpm_thr, ts)
        samples.append((ts, cum, rpm, thr))

    # Engine-on filter — RPM > 500
    on = [s for s in samples if s[2] > 500]
    if not on:
        print("  (no engine-on frames — RPM stayed at 0)")
        return

    # Recompute tick rate per RPM bin. To avoid edge artifacts, only count
    # pairs of consecutive samples where both are inside the same bin.
    bins = [(500, 1900, "idle"),
            (1900, 2300, "~2000"),
            (2300, 2800, "~2500"),
            (2800, 3200, "~3000"),
            (3200, 3900, "~3500"),
            (3900, 4300, "~4000"),
            (4300, 4900, "~4500"),
            (4900, 5800, "~5500"),
            (5800, 9999, ">5800")]

    print(f"  {'bin':>8}  {'frames':>6}  {'dur_s':>7}  {'ticks':>6}  {'rate_hz':>8}  "
          f"{'mean_rpm':>8}  {'mean_thr':>8}  {'ticks/rev':>10}")
    for lo, hi, name in bins:
        # consecutive in-bin pairs
        n = 0
        dt_total = 0.0
        dticks_total = 0
        rpm_sum = 0.0
        thr_sum = 0.0
        for a, b in zip(on, on[1:]):
            ra, rb = a[2], b[2]
            if not (lo <= ra < hi and lo <= rb < hi):
                continue
            dt = b[0] - a[0]
            if dt <= 0 or dt > 1.0:    # gap → skip
                continue
            n += 1
            dt_total += dt
            dticks_total += b[1] - a[1]
            rpm_sum += (ra + rb) / 2
            thr_sum += (a[3] + b[3]) / 2
        if not n or dt_total < 0.5:
            continue
        rate = dticks_total / dt_total
        mean_rpm = rpm_sum / n
        mean_thr = thr_sum / n
        # If rate is engine-cycle linked: 4-stroke fires once per 2 revs, so
        # an "events per rev" metric of 0.5 would mean "per cylinder firing".
        ticks_per_rev = rate / (mean_rpm / 60) if mean_rpm else 0
        print(f"  {name:>8}  {n:>6}  {dt_total:>7.1f}  {dticks_total:>6}  "
              f"{rate:>8.3f}  {mean_rpm:>8.0f}  {mean_thr:>8.1f}  "
              f"{ticks_per_rev:>10.4f}")


def main() -> int:
    # Sessions with engine-on time. The rear-spin capture is the decisive
    # one (RPM setpoints); the three idle runs are calibration anchors at
    # constant ~1700 RPM.
    sessions = [
        "logs/2026-06-17-engine-idle-run-1",
        "logs/2026-06-17-engine-idle-run-2",
        "logs/2026-06-17-engine-idle-run-3",
        "logs/2026-06-23-engine-driven-rear-spin",
    ]
    print("# 541 D4 (low 7 bits) tick-rate vs RPM")
    print("# wall-clock hypothesis → rate ≈ 1/s everywhere")
    print("# engine-cycle hypothesis → rate ∝ RPM (ticks/rev ≈ const)")
    print("# fuel-mass hypothesis → rate ∝ RPM × throttle (ticks/rev climbs with thr)")
    for s in sessions:
        analyze(REPO_ROOT / s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
