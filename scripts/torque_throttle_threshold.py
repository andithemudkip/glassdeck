#!/usr/bin/env python3
"""torque_throttle_threshold.py — verify the engine-off `121` D0:D1 flip.

Investigates the throttle-conditional discontinuity on `121` D0:D1 observed
in the 2026-07-24 live view: with ignition on and engine off, D0:D1 sits at
+166 but jumps to a negative value at `120` D2 = 234 (~92 % grip).

Analysis mirrors the plan in
docs/experiments/2026-07-24-torque-throttle-threshold-engine-off.md:

  1. Threshold + hysteresis. Every up-crossing and down-crossing of D0:D1
     through 0 in the slow-sweep phase, tagged with the concurrent `120`
     D2 value. Consistent value across sweeps → hard threshold; band
     between up-cross and down-cross values → hysteresis.
  2. `121` D2:D3 twin channel. Does the twin channel also flip at the
     same threshold, or is D0:D1 alone?
  3. `121` D4:D6 mode-bit hunt. Any byte / bit that co-transitions on the
     same frame as the D0:D1 flip.
  4. Bus-wide diff. Last-pre-flip vs first-post-flip byte across every ID.
  5. Latency. Time from `120` D2 reaching the threshold to `121` D0:D1
     crossing 0.
  6. Latch. Behaviour of `121` D0:D1 in the phase-2 hold-at-0-after-WOT
     window — does it return to +166 (mode disarms on throttle release)
     or stay at −36 (latches until key-cycle)?
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")


def parse_events(path: Path) -> list[tuple[float, str, str]]:
    out: list[tuple[float, str, str]] = []
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            out.append((t, r["key"], r["label"]))
    return sorted(out)


def parse_log(path: Path, ids: set[str]) -> dict[str, list[tuple[float, bytes]]]:
    ids_upper = {i.upper() for i in ids}
    out: dict[str, list[tuple[float, bytes]]] = {i: [] for i in ids_upper}
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


def parse_all_ids(path: Path) -> dict[str, list[tuple[float, bytes]]]:
    out: dict[str, list[tuple[float, bytes]]] = defaultdict(list)
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            arb = m.group(2).upper()
            hex_data = m.group(3)
            if len(hex_data) != 16:
                continue
            out[arb].append((float(m.group(1)), bytes.fromhex(hex_data)))
    return out


def s16_be(hi: int, lo: int) -> int:
    v = (hi << 8) | lo
    return v - 65536 if v >= 32768 else v


def window(frames, t0, t1):
    return [(ts, d) for ts, d in frames if t0 <= ts <= t1]


def nearest_before(times_values, t):
    """Given a sorted list of (ts, val), return the val at the last ts ≤ t (or None)."""
    lo, hi = 0, len(times_values) - 1
    if hi < 0 or times_values[0][0] > t:
        return None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if times_values[mid][0] <= t:
            lo = mid
        else:
            hi = mid - 1
    return times_values[lo][1]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--session",
        default="logs/2026-07-24-torque-throttle-engine-off-3",
        help="Session dir (relative to repo root).",
    )
    args = p.parse_args()

    session = REPO_ROOT / args.session
    events = parse_events(session / "events.csv")
    frames121 = parse_log(session / "capture.log", {"121", "120"})
    id121 = frames121["121"]
    id120 = frames121["120"]

    print(f"# `121` throttle-conditional flip — {args.session}\n")
    print(f"`121` frames: {len(id121):,}   `120` frames: {len(id120):,}")

    marks = [(t, l or k) for t, k, l in events]
    if len(marks) < 3:
        sys.exit(f"expected ≥3 marks (t presses), got {len(marks)}")
    m1, m2, m3 = marks[0][0], marks[1][0], marks[2][0]

    # Capture ends shortly after mark 3; use the last 121 frame as an upper bound.
    capture_end = id121[-1][0]

    print(f"\n## Phases (from event marks)\n")
    print(f"* phase 1 (slow-sweep pair ×3): {m1:.3f} → {m2:.3f}  ({m2-m1:.1f} s)")
    print(f"* phase 2 (latch probe):        {m2:.3f} → {m3:.3f}  ({m3-m2:.1f} s)")
    print(f"* phase 3 (step response):      {m3:.3f} → {capture_end:.3f}  ({capture_end-m3:.1f} s)")

    # Throttle timeseries (D2) for the whole capture — used to look up
    # concurrent throttle at each flip.
    throttle_ts = [(ts, d[2]) for ts, d in id120]

    # 121 signed int16 channels.
    def torque_pair(d: bytes) -> tuple[int, int]:
        return s16_be(d[0], d[1]), s16_be(d[2], d[3])

    # ---- 1. Threshold + hysteresis (phase 1 sweep) -----------------------------
    sweep_121 = window(id121, m1, m2)
    print(f"\n## 1. Threshold + hysteresis (phase 1)\n")
    print(f"`121` frames in phase 1: {len(sweep_121):,}")

    # Zero-crossings of D0:D1. A crossing is a frame N where sign(prev) != sign(this),
    # counting 0 as its own thing to avoid spurious flips on wobble at 0.
    def crossings(frames):
        ups, downs = [], []
        prev_sign = None
        for ts, d in frames:
            a, _ = torque_pair(d)
            sign = 1 if a > 0 else (-1 if a < 0 else 0)
            if prev_sign is not None and sign != 0 and prev_sign != 0 and sign != prev_sign:
                thr = nearest_before(throttle_ts, ts)
                if sign > prev_sign:
                    ups.append((ts, thr, a))
                else:
                    downs.append((ts, thr, a))
            if sign != 0:
                prev_sign = sign
        return ups, downs

    ups, downs = crossings(sweep_121)
    print(f"up-crossings (+ → −): {len(ups)}   down-crossings (− → +): {len(downs)}")

    if ups:
        print(f"\n| # | t (s) | throttle raw at flip | 121_A post-flip |")
        print(f"|---|------:|---------------------:|----------------:|")
        for i, (ts, thr, a) in enumerate(ups, 1):
            print(f"| up-{i} | {ts:.3f} | {thr} | {a} |")
    if downs:
        print()
        for i, (ts, thr, a) in enumerate(downs, 1):
            print(f"| dn-{i} | {ts:.3f} | {thr} | {a} |")

    up_thrs = [t for _, t, _ in ups if t is not None]
    dn_thrs = [t for _, t, _ in downs if t is not None]
    if up_thrs:
        print(f"\nup-threshold values: {sorted(set(up_thrs))}   "
              f"(mean {statistics.mean(up_thrs):.2f}, "
              f"stdev {statistics.stdev(up_thrs) if len(up_thrs)>1 else 0:.2f})")
    if dn_thrs:
        print(f"down-threshold values: {sorted(set(dn_thrs))}   "
              f"(mean {statistics.mean(dn_thrs):.2f}, "
              f"stdev {statistics.stdev(dn_thrs) if len(dn_thrs)>1 else 0:.2f})")
    if up_thrs and dn_thrs:
        band = statistics.mean(up_thrs) - statistics.mean(dn_thrs)
        print(f"hysteresis band (up − down): {band:+.2f}")

    # ---- 2. D2:D3 twin-channel response ---------------------------------------
    print(f"\n## 2. `121` D2:D3 twin-channel response\n")
    # For each up-crossing on D0:D1, check whether D2:D3 also crossed 0 within
    # the same 121 broadcast frame (± 1 frame slack).
    if ups:
        print(f"| flip | D0:D1 post | D2:D3 same frame | D2:D3 also flipped? |")
        print(f"|------|-----------:|-----------------:|--------------------:|")
        for i, (ts, thr, a) in enumerate(ups, 1):
            # Find the frame at ts
            match = next(((tt, dd) for tt, dd in id121 if abs(tt - ts) < 0.001), None)
            if not match:
                continue
            _, d_post = match
            a_post, b_post = torque_pair(d_post)
            # Frame immediately before
            idx_post = next(j for j, (tt, _) in enumerate(id121) if abs(tt - ts) < 0.001)
            b_pre = None
            if idx_post > 0:
                _, d_pre = id121[idx_post - 1]
                _, b_pre = torque_pair(d_pre)
            flipped = (b_pre is not None and (b_pre > 0) != (b_post > 0))
            print(f"| up-{i} | {a_post} | {b_post} | {'yes' if flipped else 'no'} |")

    # Aggregate D0:D1 vs D2:D3 in the phase-2 flipped state (after WOT hold).
    # Take a 2-s window in the middle of phase 2 while throttle likely still
    # held / released — inspect the plateau values.
    print(f"\nphase-2 aggregate (D0:D1 and D2:D3 by throttle side):")
    p2 = window(id121, m2, m3)
    p2_low_a, p2_low_b, p2_high_a, p2_high_b = [], [], [], []
    for ts, d in p2:
        thr = nearest_before(throttle_ts, ts)
        if thr is None:
            continue
        a, b = torque_pair(d)
        if thr < 100:
            p2_low_a.append(a); p2_low_b.append(b)
        elif thr >= 240:
            p2_high_a.append(a); p2_high_b.append(b)
    if p2_low_a:
        print(f"  throttle < 100 (n={len(p2_low_a):,}):  D0:D1 μ={statistics.mean(p2_low_a):+.1f}   D2:D3 μ={statistics.mean(p2_low_b):+.1f}")
    if p2_high_a:
        print(f"  throttle ≥ 240 (n={len(p2_high_a):,}):  D0:D1 μ={statistics.mean(p2_high_a):+.1f}   D2:D3 μ={statistics.mean(p2_high_b):+.1f}")

    # ---- 3. `121` D4:D6 mode-bit hunt -----------------------------------------
    print(f"\n## 3. `121` D4:D6 mode-bit hunt\n")
    if ups:
        print(f"| flip | pre D4 D5 D6 | post D4 D5 D6 | XOR |")
        print(f"|------|-------------:|--------------:|----:|")
        for i, (ts, thr, a) in enumerate(ups, 1):
            idx = next((j for j, (tt, _) in enumerate(id121) if abs(tt - ts) < 0.001), None)
            if idx is None or idx == 0:
                continue
            _, d_pre = id121[idx - 1]
            _, d_post = id121[idx]
            pre_hex = f"{d_pre[4]:02X} {d_pre[5]:02X} {d_pre[6]:02X}"
            post_hex = f"{d_post[4]:02X} {d_post[5]:02X} {d_post[6]:02X}"
            xor_hex = f"{d_pre[4]^d_post[4]:02X} {d_pre[5]^d_post[5]:02X} {d_pre[6]^d_post[6]:02X}"
            print(f"| up-{i} | {pre_hex} | {post_hex} | {xor_hex} |")

    # ---- 4. Bus-wide diff at the transition ----------------------------------
    print(f"\n## 4. Bus-wide diff — last-pre vs first-post per ID (up-crossing 1)\n")
    if ups:
        all_frames = parse_all_ids(session / "capture.log")
        ts_flip = ups[0][0]
        # For each ID, find last frame before ts_flip and first at/after ts_flip.
        rows = []
        for arb in sorted(all_frames.keys()):
            fr = all_frames[arb]
            pre = None
            post = None
            for tt, dd in fr:
                if tt < ts_flip:
                    pre = (tt, dd)
                else:
                    post = (tt, dd)
                    break
            if pre is None or post is None:
                continue
            xor = bytes(a ^ b for a, b in zip(pre[1], post[1]))
            if any(xor):
                # Byte positions with any change.
                changed = [i for i, x in enumerate(xor) if x]
                rows.append((arb, pre[1].hex().upper(), post[1].hex().upper(),
                             " ".join(f"D{i}" for i in changed), xor.hex().upper()))
        print(f"| ID  | pre payload      | post payload     | changed bytes | XOR              |")
        print(f"|-----|------------------|------------------|---------------|------------------|")
        for arb, pre_h, post_h, ch, x in rows:
            print(f"| {arb} | {pre_h} | {post_h} | {ch} | {x} |")
        if not rows:
            print("(no ID changed across the flip frame — flip is confined to `121` alone)")

    # ---- 5. Latency ----------------------------------------------------------
    print(f"\n## 5. Latency (`120` D2 first ≥ 234  →  `121` D0:D1 first < 0)\n")
    if ups:
        for i, (ts_flip, thr_at_flip, _) in enumerate(ups, 1):
            # Find the `120` frame(s) that first crossed 234 near this flip.
            # Look back ~250 ms from the flip.
            recent_120 = [(tt, v) for tt, v in throttle_ts if ts_flip - 0.5 <= tt <= ts_flip]
            first_over = next((tt for tt, v in recent_120 if v >= 234), None)
            if first_over is None:
                print(f"* up-{i}: no `120` D2 ≥ 234 in the 500 ms before the flip")
                continue
            print(f"* up-{i}: `120` D2 ≥ 234 at {first_over:.3f}  →  `121` flip at {ts_flip:.3f}   Δ = {(ts_flip - first_over)*1000:.1f} ms")

    # ---- 6. Latch (phase 2 hold-at-0-after-WOT) ------------------------------
    print(f"\n## 6. Latch — phase 2 (WOT snap → hold, then close → hold 10 s)\n")
    # Divide phase 2 into segments: before WOT, at WOT, after WOT close.
    # Simplify: bin by throttle band.
    if p2:
        # Slice phase 2 into 1-s bins and report mean throttle + mean D0:D1.
        bins = {}
        for ts, d in p2:
            k = int(ts - m2)
            thr = nearest_before(throttle_ts, ts)
            a, _ = torque_pair(d)
            bins.setdefault(k, []).append((thr, a))
        print(f"| t-since-mark2 (s) | n | mean throttle | mean D0:D1 |")
        print(f"|------------------:|--:|--------------:|-----------:|")
        for k in sorted(bins):
            vals = bins[k]
            n = len(vals)
            thrs = [t for t, _ in vals if t is not None]
            aas = [a for _, a in vals]
            mt = statistics.mean(thrs) if thrs else float("nan")
            ma = statistics.mean(aas)
            print(f"| {k} | {n} | {mt:6.1f} | {ma:+7.1f} |")

    # ---- 7. Phase 3 step response --------------------------------------------
    print(f"\n## 7. Phase 3 step-response snapshot (entry / exit latency)\n")
    p3 = window(id121, m3, capture_end)
    if p3:
        bins = {}
        for ts, d in p3:
            k = round((ts - m3) * 10) / 10  # 0.1 s bins
            thr = nearest_before(throttle_ts, ts)
            a, _ = torque_pair(d)
            bins.setdefault(k, []).append((thr, a))
        print(f"| t-since-mark3 (s) | n | throttle | D0:D1 |")
        print(f"|------------------:|--:|---------:|------:|")
        for k in sorted(bins):
            vals = bins[k]
            n = len(vals)
            thrs = [t for t, _ in vals if t is not None]
            aas = [a for _, a in vals]
            mt = statistics.mean(thrs) if thrs else float("nan")
            ma = statistics.mean(aas)
            print(f"| {k:+.1f} | {n} | {mt:5.1f} | {ma:+6.1f} |")

    return 0


if __name__ == "__main__":
    sys.exit(main())
