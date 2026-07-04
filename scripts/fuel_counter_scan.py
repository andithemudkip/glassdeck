#!/usr/bin/env python3
"""fuel_counter_scan.py — hunt for a fuel-integrator byte in the always-on set.

Background: `injector_flow_scan.py` ruled out rate-shaped uint8 / uint16-BE
fuel signals in the 11 always-on broadcast IDs. UDS path is also closed
(no diagnostic traffic on the bus, [[project-fuel-on-can]] 2026-06-26).

That leaves one broadcast-hypothesis the prior scans don't test:
a **monotonically-rising counter** whose *tick rate* (not value) tracks fuel
flow. Same shape as `541 D4` (engine-on seconds counter at 1 Hz) but with a
RPM·throttle-proportional rate — every injection event, every N injection
events, or every mg of fuel.

Signature we hunt:
  1. WITHIN each B1..B5 setpoint window the byte (or pair) walks monotonically
     up (modulo wraparound), with a near-constant tick rate during the window.
  2. The per-window tick rate scales with RPM·throttle across B1..B5.
  3. At engine-off the byte holds constant (no ticks).

Method:
  - For each candidate (id, byte) and (id, uint16 BE pair):
    - Compute tick rate during each rear-spin setpoint window (B1..B5 + idle).
      Tick rate = total absolute delta (handling u8/u16 wraparound) ÷ window
      seconds. Skip bytes/pairs that bit-bounce noisily (we require monotone
      direction within the window — at least 90% of step deltas same-sign).
    - Compute tick rate during the engine-off baseline (any pre-start window).
    - Score = corr(tick_rates, RPM·throttle) across the 6 windows, weighted by
      tick-rate range (so a byte that ticks at 0.1/s across all setpoints scores
      below one that ticks 1/s → 50/s).
  - Skip already-attributed bytes (gear, speed, coolant, etc.) and D7.

Read-only against logs/. Reuses the rear-spin session as the workhorse.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")
ALWAYS_ON_IDS = ["120", "121", "129", "12A", "12D", "12E", "450", "540", "541", "5A0", "5B0"]
RPM_ID = "120"

KNOWN_BYTE = {
    ("120", 0): "rpm-hi", ("120", 1): "rpm-lo", ("120", 2): "throttle", ("120", 7): "d7",
    ("121", 0): "int16-A-hi", ("121", 1): "int16-A-lo",
    ("121", 2): "int16-B-hi", ("121", 3): "int16-B-lo",
    ("121", 5): "kill-mirror", ("121", 7): "d7",
    ("129", 0): "gear+clutch", ("129", 7): "d7",
    ("12A", 7): "d7",
    ("12D", 0): "front-speed-hi", ("12D", 1): "front-speed-lo",
    ("12D", 2): "rear-coarse", ("12D", 5): "rear-hi", ("12D", 6): "rear-lo", ("12D", 7): "d7",
    ("12E", 7): "d7",
    ("450", 7): "d7",
    ("540", 1): "warmup/throttle", ("540", 3): "side-stand",
    ("540", 5): "coolant-hi", ("540", 6): "coolant-lo", ("540", 7): "d7",
    ("541", 2): "kill", ("541", 4): "engine-on-counter",
    ("541", 5): "ramp-hi", ("541", 6): "ramp-lo", ("541", 7): "d7",
    ("5A0", 7): "d7",
    ("5B0", 0): "kill-mirror", ("5B0", 7): "d7",
}
KNOWN_PAIR = {
    ("120", 0): "rpm-uint16",
    ("121", 0): "int16-A", ("121", 2): "int16-B",
    ("12D", 0): "front-speed-12bit", ("12D", 5): "rear-speed",
    ("540", 5): "coolant-uint16",
    ("541", 4): "engine-on-counter-pair",  # D4:D5 — likely just secs + ramp adjacency
    ("541", 5): "ramp-counter",
}

WINDOW_SKIP_S = 3.0
WINDOW_LEN_S = 8.0


def parse_log(path: Path, ids: set[str]):
    out = {arb: [] for arb in ids}
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            arb = m.group(2).upper()
            if arb not in out:
                continue
            h = m.group(3)
            if len(h) != 16:
                continue
            out[arb].append((float(m.group(1)), bytes.fromhex(h)))
    return out


def signed_delta_mod(curr: int, prev: int, mod: int) -> int:
    """Shortest-arc delta on a modular counter (uint8: mod=256, uint16: mod=65536).

    Returns the wraparound-adjusted step. A counter walking up by 3 with one
    wrap from 254 → 1 returns +3, not -253.
    """
    raw = curr - prev
    if raw > mod // 2:
        raw -= mod
    elif raw < -mod // 2:
        raw += mod
    return raw


def window_tick_stats(frames: list[tuple[float, bytes]], t0: float, t1: float,
                      pos: int, mod: int, pair: bool):
    """Compute tick stats for one byte / pair within a window.

    Returns dict with: n_frames, total_signed_delta, total_abs_delta,
    monotone_fraction (fraction of steps with same sign as the dominant
    direction), value_range, seconds.
    """
    vals = []
    times = []
    for ts, d in frames:
        if not (t0 <= ts <= t1):
            continue
        if pair:
            v = (d[pos] << 8) | d[pos + 1]
        else:
            v = d[pos]
        vals.append(v)
        times.append(ts)
    n = len(vals)
    if n < 5:
        return None
    deltas = [signed_delta_mod(vals[i], vals[i - 1], mod) for i in range(1, n)]
    nonzero = [d for d in deltas if d != 0]
    if not nonzero:
        return {"n": n, "total_signed": 0, "total_abs": 0, "mono": 1.0,
                "rng": max(vals) - min(vals), "secs": times[-1] - times[0],
                "v0": vals[0], "v1": vals[-1]}
    pos_steps = sum(1 for d in nonzero if d > 0)
    neg_steps = len(nonzero) - pos_steps
    dominant = max(pos_steps, neg_steps) / len(nonzero)
    total_signed = sum(deltas)
    total_abs = sum(abs(d) for d in deltas)
    return {
        "n": n,
        "total_signed": total_signed,
        "total_abs": total_abs,
        "mono": dominant,
        "rng": max(vals) - min(vals),
        "secs": times[-1] - times[0],
        "v0": vals[0],
        "v1": vals[-1],
    }


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denom = math.sqrt(sxx * syy)
    return sxy / denom if denom else 0.0


@dataclass
class Cand:
    kind: str
    id: str
    pos: int
    known: str
    rates: list  # tick rate (signed total / sec) per setpoint
    mono: list   # monotone fraction per setpoint
    ranges: list  # absolute range per setpoint
    eng_off_rate: float
    score: float = 0.0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--session", default="logs/2026-06-23-engine-driven-rear-spin")
    p.add_argument("--engine-off-sessions", nargs="+",
                   default=["logs/2026-06-17-key-on-cold-boot",
                            "logs/2026-06-19-throttle-sweep-engine-off"],
                   help="sessions used to estimate engine-off tick rate (must hold counter at 0)")
    p.add_argument("--mono-threshold", type=float, default=0.85,
                   help="min dominant-direction fraction within a setpoint window (default 0.85)")
    p.add_argument("--top", type=int, default=20)
    args = p.parse_args()

    session = REPO_ROOT / args.session

    # Parse events.csv for setpoint marks. Use timestamp_iso → unix epoch.
    marks = []
    with (session / "events.csv").open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            marks.append((r["key"], r["label"], t))

    # Idle baseline + B1..B5 windows.
    setpoints: list[tuple[str, float]] = []
    for key, label, t in marks:
        if key == "idle_settled":
            # 30s window of pre-Phase-A neutral idle.
            setpoints.append(("idle-neutral", t + 5.0))
        elif key == "setpoint" and any(b in label for b in ("B1", "B2", "B3", "B4", "B5")):
            setpoints.append((label.split("—")[0].strip(), t))
    if not setpoints:
        print("no setpoints recognized in events.csv")
        return 1

    frames = parse_log(session / "capture.log", set(ALWAYS_ON_IDS))

    # Get RPM/throttle per window for the regressor.
    win_meta = []  # (label, t0, t1, rpm, thr)
    for label, mark in setpoints:
        t0, t1 = mark + WINDOW_SKIP_S, mark + WINDOW_SKIP_S + WINDOW_LEN_S
        win_120 = [(ts, d) for ts, d in frames[RPM_ID] if t0 <= ts <= t1]
        if len(win_120) < 10:
            continue
        rpm = mean([(d[0] << 8) | d[1] for _, d in win_120])
        thr = mean([d[2] for _, d in win_120])
        win_meta.append((label, t0, t1, rpm, thr))
    if len(win_meta) < 4:
        print(f"only {len(win_meta)} usable setpoint windows")
        return 1

    print(f"# Fuel-counter scan — {args.session}")
    print(f"# {len(win_meta)} engine-on setpoints (idle + B1..B5)\n")
    print(f"  {'label':<14} {'RPM':>6} {'thr':>5} {'RPM·thr':>10}")
    for lbl, _, _, r, t in win_meta:
        print(f"  {lbl:<14} {r:6.0f} {t:5.1f} {r * t:10.0f}")
    print()

    # Engine-off rate estimate. Take a 30s window from each off-session.
    eng_off_rates: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    for sess_path in args.engine_off_sessions:
        d = REPO_ROOT / sess_path
        if not (d / "capture.log").exists():
            continue
        off_frames = parse_log(d / "capture.log", set(ALWAYS_ON_IDS))
        # Find a 30s window from the middle of the capture.
        any_id_frames = next((v for v in off_frames.values() if v), [])
        if not any_id_frames:
            continue
        t_start = any_id_frames[0][0] + 30.0
        t_end = t_start + 30.0
        for arb in ALWAYS_ON_IDS:
            f_list = off_frames[arb]
            for bi in range(8):
                if bi == 7:
                    continue
                s = window_tick_stats(f_list, t_start, t_end, bi, 256, pair=False)
                if s and s["secs"] > 5:
                    eng_off_rates[("byte", arb, bi)].append(s["total_abs"] / s["secs"])
            for bi in range(7):
                s = window_tick_stats(f_list, t_start, t_end, bi, 65536, pair=True)
                if s and s["secs"] > 5:
                    eng_off_rates[("pair", arb, bi)].append(s["total_abs"] / s["secs"])

    def eng_off(key):
        rs = eng_off_rates.get(key, [])
        return max(rs) if rs else 0.0  # conservative: worst-case off-rate

    # Per-window stats per candidate.
    cands: list[Cand] = []

    def scan(kind: str, mod: int, pair: bool, max_i: int):
        for arb in ALWAYS_ON_IDS:
            for bi in range(max_i):
                if kind == "byte" and bi == 7:
                    continue
                rates: list[float] = []
                monos: list[float] = []
                ranges: list[int] = []
                ok = True
                for _, t0, t1, _, _ in win_meta:
                    s = window_tick_stats(frames[arb], t0, t1, bi, mod, pair=pair)
                    if s is None or s["secs"] < 1.0:
                        ok = False
                        break
                    # Signed tick rate (per second) — sign captured by total_signed.
                    rates.append(s["total_signed"] / s["secs"])
                    monos.append(s["mono"])
                    ranges.append(s["rng"])
                if not ok:
                    continue
                known = (KNOWN_BYTE if kind == "byte" else KNOWN_PAIR).get((arb, bi), "")
                cands.append(Cand(kind, arb, bi, known, rates, monos, ranges,
                                  eng_off((kind, arb, bi))))

    scan("byte", 256, pair=False, max_i=8)
    scan("pair", 65536, pair=True, max_i=7)

    # Filter for counter shape:
    #  - every setpoint window must be ≥mono_threshold monotone
    #  - rate magnitude must rise across at least 3 setpoints (not flat noise)
    #  - engine-off rate must be small relative to engine-on rate range
    rpm_thr = [r * t for _, _, _, r, t in win_meta]

    def score(c: Cand) -> float:
        if min(c.mono) < args.mono_threshold:
            return 0.0
        sign = 1 if sum(c.rates) >= 0 else -1
        rates = [sign * r for r in c.rates]
        rate_range = max(rates) - min(rates)
        if rate_range < 0.05:
            return 0.0
        if c.eng_off_rate > 2.0 * max(abs(r) for r in rates):
            return 0.0
        corr = pearson(rpm_thr, rates)
        return corr * math.log1p(rate_range)

    for c in cands:
        c.score = score(c)

    cands.sort(key=lambda c: c.score, reverse=True)

    # Output.
    hdr = (f"  {'kind':<4} {'id':>3} {'pos':>3}  {'score':>6}  "
           + " ".join(f"{lbl[:8]:>10}" for lbl, *_ in win_meta)
           + f"  {'min_mono':>8}  {'off-rate':>9}  {'known':<22}")
    print("## Top counter candidates (rates per second, signed)\n")
    print(hdr)
    for c in cands[: args.top]:
        if c.score == 0.0:
            break
        rates_s = " ".join(f"{r:>10.2f}" for r in c.rates)
        print(f"  {c.kind:<4} {c.id:>3} D{c.pos:<2}  {c.score:>6.2f}  {rates_s}  "
              f"{min(c.mono):>8.2f}  {c.eng_off_rate:>9.3f}  {c.known:<22}")

    # Unknown-only view.
    unk = [c for c in cands if not c.known and c.score > 0]
    print(f"\n## UNKNOWN counter candidates (no existing attribution)\n")
    print(hdr)
    for c in unk[: args.top]:
        rates_s = " ".join(f"{r:>10.2f}" for r in c.rates)
        print(f"  {c.kind:<4} {c.id:>3} D{c.pos:<2}  {c.score:>6.2f}  {rates_s}  "
              f"{min(c.mono):>8.2f}  {c.eng_off_rate:>9.3f}  ")

    # Sanity check — `541 D4` (known 1 Hz engine-on counter) should rank.
    print("\n## Sanity check — known counters\n")
    for c in cands:
        if (c.id, c.pos) in (("541", 4), ("541", 5)) and c.kind == "byte":
            rates_s = " ".join(f"{r:>10.2f}" for r in c.rates)
            print(f"  byte {c.id} D{c.pos}  rates={rates_s}  min_mono={min(c.mono):.2f}  "
                  f"off_rate={c.eng_off_rate:.3f}  known={c.known}")

    print("\nInterpretation:")
    print("  A real fuel integrator should show:")
    print("   - rates rising monotonically with RPM·thr (idle ~near 0, B5 fastest)")
    print("   - high min_mono (>0.9) — counters don't bit-bounce")
    print("   - engine-off rate ~0 — fuel doesn't accumulate when injectors are off")
    print("   - rate range >> 1 LSB/s — a useful fuel signal needs dynamic range")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
