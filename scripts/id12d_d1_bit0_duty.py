#!/usr/bin/env python3
"""id12d_d1_bit0_duty.py — characterise the 12D D1 bit-0 engine-on duty cycle.

[[signal-12d-d1-bit0]] notes ~3.5% engine-on duty cycle, 0 % engine-off,
without saying what governs the on/off pattern. Three live hypotheses:

  (a) periodic heartbeat — runs and gaps cluster around fixed durations
  (b) RPM/throttle-correlated   — distribution of carried-forward 120 D0:D1
      (RPM) and D2 (throttle) at frames where bit=1 differs from bit=0
  (c) state-machine / one-shot — bursts of contiguous 1s separated by long
      irregular gaps, no obvious correlate

Pulls the `12D` bit-0 stream out of every engine-on capture on disk
(2026-06-23-engine-driven-rear-spin + 3× 2026-06-17-engine-idle-run-N),
runs:

  - run-length / gap-length histograms (in frames AND in seconds)
  - period estimate via mean / median / std of gap durations
  - regression slope of "bit=1 fraction per RPM bin"
  - throttle-bin counterpart
  - co-occurrence with the 541 D4 ~1 Hz engine-on counter ticking

and reports it all to stdout.

Usage:
    python scripts/id12d_d1_bit0_duty.py
"""

from __future__ import annotations

import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from cross_session_diff import parse_log  # type: ignore  # noqa: E402

ENGINE_ON_SESSIONS = [
    "logs/2026-06-17-engine-idle-run-1",
    "logs/2026-06-17-engine-idle-run-2",
    "logs/2026-06-17-engine-idle-run-3",
    "logs/2026-06-23-engine-driven-rear-spin",
]


def runs_and_gaps(stream):
    """Walk a list of (ts, bit) pairs in order. Return:
       runs   = list of (start_ts, end_ts, length_frames) where bit==1
       gaps   = same shape, where bit==0
    """
    runs, gaps = [], []
    cur_bit, cur_start, cur_n = None, None, 0
    last_ts = None
    for ts, b in stream:
        if cur_bit is None:
            cur_bit, cur_start, cur_n = b, ts, 1
        elif b == cur_bit:
            cur_n += 1
        else:
            (runs if cur_bit == 1 else gaps).append(
                (cur_start, last_ts, cur_n))
            cur_bit, cur_start, cur_n = b, ts, 1
        last_ts = ts
    if cur_bit is not None:
        (runs if cur_bit == 1 else gaps).append(
            (cur_start, last_ts, cur_n))
    return runs, gaps


def hist_summary(values, label):
    if not values:
        print(f"  {label}: (empty)")
        return
    print(f"  {label}: n={len(values)}  "
          f"min={min(values):.3f}  median={statistics.median(values):.3f}  "
          f"mean={statistics.mean(values):.3f}  "
          f"max={max(values):.3f}  "
          f"stdev={(statistics.stdev(values) if len(values) > 1 else 0):.3f}")


def analyse(session_path: Path):
    print(f"\n## {session_path.name}")
    frames = parse_log(session_path / "capture.log")
    if not frames:
        print("  (no frames)")
        return

    # ------ pull every signal we want, indexed by timestamp.
    bit_stream = []     # (ts, bit) on every 12D frame
    rpm_carry = None
    throttle_carry = None
    counter541_carry = None
    coolant_carry = None

    # Carry-forward stream of features at every 12D frame.
    feats = []   # (ts, bit, rpm, throttle, counter541, coolant)
    for ts, arb, data in frames:
        if arb == "120":
            rpm_carry = (data[0] << 8) | data[1]
            throttle_carry = data[2]
        elif arb == "540":
            coolant_carry = (data[5] << 8) | data[6]   # raw, ×10 °C
        elif arb == "541":
            counter541_carry = data[4] & 0x7F
        elif arb == "12D":
            bit = (data[1] >> 0) & 1
            rear_kmh = ((data[5] << 8) | data[6]) / 16.0
            bit_stream.append((ts, bit))
            feats.append((ts, bit, rpm_carry, throttle_carry,
                          counter541_carry, coolant_carry, rear_kmh))

    n_total = len(bit_stream)
    n_ones = sum(b for _, b in bit_stream)
    print(f"  12D frames: {n_total}, bit=1 frames: {n_ones} ({100*n_ones/n_total:.3f}%)")
    if n_ones == 0:
        print("  no bit=1 frames — nothing else to report.")
        return

    # ------ run-length and gap-length histograms
    runs, gaps = runs_and_gaps(bit_stream)
    run_frames = [r[2] for r in runs]
    gap_frames = [g[2] for g in gaps]
    run_dur = [r[1] - r[0] for r in runs if r[2] > 1]
    gap_dur = [g[1] - g[0] for g in gaps if g[2] > 1]
    # gap "wall time" between consecutive bit=1 events (use start of one run to
    # the start of the next) — robust to single-frame runs of zero duration.
    inter_run_dt = [runs[i+1][0] - runs[i][0] for i in range(len(runs)-1)]

    print(f"  runs (bit=1 stretches): {len(runs)},  gaps (bit=0): {len(gaps)}")
    hist_summary(run_frames, "run length (frames)")
    hist_summary(run_dur,    "run duration  (s)  [runs with >1 frame]")
    hist_summary(gap_frames, "gap length (frames)")
    hist_summary(gap_dur,    "gap duration  (s)  [gaps with >1 frame]")
    hist_summary(inter_run_dt, "inter-run interval (s)  [run_start[i+1]-run_start[i]]")

    # Counter of run-frame counts for quick eyeball — heartbeat would be tightly
    # peaked (e.g. all length 1 or all length 2).
    rc = Counter(run_frames)
    print(f"  run-length distribution: {dict(sorted(rc.items()))}")

    # Counter of inter-run intervals bucketed to 0.05 s.
    if inter_run_dt:
        ic = Counter(round(x, 2) for x in inter_run_dt)
        top = sorted(ic.items(), key=lambda kv: -kv[1])[:6]
        print(f"  inter-run interval top-6 buckets (s): {top}")

    # ------ correlation with RPM / throttle / coolant
    def bin_fraction(values_when_1, values_when_0, label, bin_size, fmt):
        if not values_when_1:
            return
        all_vals = values_when_1 + values_when_0
        lo = (min(all_vals) // bin_size) * bin_size
        hi = ((max(all_vals) // bin_size) + 1) * bin_size
        rows = []
        for b in range(int(lo), int(hi), int(bin_size)):
            n1 = sum(1 for v in values_when_1 if b <= v < b + bin_size)
            n0 = sum(1 for v in values_when_0 if b <= v < b + bin_size)
            n = n1 + n0
            if n < 50:
                continue
            rows.append((b, n1, n, 100.0*n1/n))
        if not rows:
            return
        print(f"\n  {label} bins (size {bin_size}): "
              f"showing bins with >=50 12D frames")
        print(f"    {'bin':>8}  {'#1':>7}  {'#total':>7}  {'%1':>6}")
        for b, n1, n, pct in rows:
            print(f"    {fmt(b):>8}  {n1:>7}  {n:>7}  {pct:>6.3f}")

    # filter feats with the relevant signal carried forward
    rpm_feats = [(f[1], f[2]) for f in feats if f[2] is not None]
    thr_feats = [(f[1], f[3]) for f in feats if f[3] is not None]
    rear_feats = [(f[1], f[6]) for f in feats]
    bin_fraction([rpm for b, rpm in rpm_feats if b == 1],
                 [rpm for b, rpm in rpm_feats if b == 0],
                 "RPM", 500, lambda b: f"{b}-{b+499}")
    bin_fraction([th for b, th in thr_feats if b == 1],
                 [th for b, th in thr_feats if b == 0],
                 "Throttle (raw)", 20, lambda b: f"{b}-{b+19}")
    bin_fraction([k for b, k in rear_feats if b == 1],
                 [k for b, k in rear_feats if b == 0],
                 "Rear km/h", 1, lambda b: f"{b:.1f}-{b+0.99:.1f}")

    # ------ joint check: at frames where RPM is BELOW its 4500-ish threshold
    # but the bit is set anyway, what's the rear km/h? If high, the actual key
    # is rear speed (RPM transient dipped but wheel kept moving). If similarly
    # low, that's a real RPM-keyed firing.
    sub_rpm_bit1 = [(f[2], f[6]) for f in feats
                    if f[1] == 1 and f[2] is not None and f[2] < 4500]
    if sub_rpm_bit1:
        print(f"\n  Joint RPM-vs-rear-km/h check (frames where RPM<4500 AND bit=1):")
        print(f"    n={len(sub_rpm_bit1)}")
        rpms = [r for r, _ in sub_rpm_bit1]
        kmhs = [k for _, k in sub_rpm_bit1]
        print(f"    RPM       min={min(rpms)}  median={int(statistics.median(rpms))}  max={max(rpms)}")
        print(f"    Rear km/h min={min(kmhs):.2f}  median={statistics.median(kmhs):.2f}  max={max(kmhs):.2f}")
    # Inverse: frames where rear < 27 km/h AND bit=1 (should be ~empty if
    # speed-keyed at 27 km/h).
    sub_kmh_bit1 = [(f[2], f[6]) for f in feats
                    if f[1] == 1 and f[6] < 27.0]
    if sub_kmh_bit1:
        print(f"\n  Joint check (frames where rear_kmh<27 AND bit=1):")
        print(f"    n={len(sub_kmh_bit1)}")
        rpms = [r for r, _ in sub_kmh_bit1 if r is not None]
        kmhs = [k for _, k in sub_kmh_bit1]
        if rpms:
            print(f"    RPM       min={min(rpms)}  median={int(statistics.median(rpms))}  max={max(rpms)}")
        print(f"    Rear km/h min={min(kmhs):.2f}  median={statistics.median(kmhs):.2f}  max={max(kmhs):.2f}")
    else:
        print(f"\n  Joint check: 0 frames with rear_kmh<27 AND bit=1 — clean speed threshold.")

    # ------ tick co-incidence with 541 D4 counter
    # Does bit=1 onset (run start) coincide with a 541 D4 tick? Compare the
    # carried-forward 541 D4 value at run start vs at run start - prev run end.
    if feats and any(f[4] is not None for f in feats):
        tick_at_run_start = []
        for r in runs:
            start_ts = r[0]
            ctr = next((f[4] for f in feats if f[0] == start_ts and f[4] is not None), None)
            if ctr is not None:
                tick_at_run_start.append(ctr)
        if tick_at_run_start:
            # If runs fire once per tick, each tick value should appear at most
            # a small number of times in this list.
            tc = Counter(tick_at_run_start)
            dup = sum(1 for c in tc.values() if c > 1)
            print(f"\n  541 D4 counter at run start: {len(tc)} distinct "
                  f"values across {len(tick_at_run_start)} runs, "
                  f"{dup} values appear more than once")

    # ------ regime check: are runs concentrated in any time interval?
    # Compute fraction-of-bit=1 over 10 s windows; flag windows >5× mean.
    if bit_stream:
        t0 = bit_stream[0][0]
        bucket = defaultdict(lambda: [0, 0])  # bucket -> [ones, total]
        for ts, b in bit_stream:
            k = int((ts - t0) // 10)
            bucket[k][0] += b
            bucket[k][1] += 1
        baseline = n_ones / n_total
        spikes = []
        for k, (ones, total) in sorted(bucket.items()):
            if total < 10:
                continue
            pct = ones / total
            if pct > 5 * baseline and ones >= 5:
                spikes.append((k*10, ones, total, 100*pct))
        if spikes:
            print(f"\n  10-s windows with >5× baseline ({100*baseline:.2f}%) bit=1 density:")
            for off, ones, total, pct in spikes[:8]:
                print(f"    t+{off:5d}-{off+10:5d}s : {ones}/{total} ({pct:.2f}%)")
        else:
            print(f"\n  bit=1 events distributed evenly across capture "
                  f"(no 10-s window above 5× baseline {100*baseline:.2f}%).")


def main() -> int:
    for s in ENGINE_ON_SESSIONS:
        analyse(REPO_ROOT / s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
