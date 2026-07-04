#!/usr/bin/env python3
"""injector_flow_scan.py — hunt for a fuel-rate / injector-flow channel.

Background: `engine_load_scan.py` ranks bytes by |r vs RPM·throttle| using only
the 5 rear-spin setpoints (B1..B5). On that drag curve RPM and throttle are
nearly linearly related, so RPM, throttle, and RPM·throttle are collinear and
no clean fuel candidate emerged. The strongest non-fuel hit was the [[byte-121-twin-int16]]
advance/trim channels.

This scan adds three things `engine_load_scan.py` doesn't do:

1. **Off-the-drag-curve operating points** to break (RPM, throttle) collinearity:
   - Neutral idle from each of the 3 engine-idle baselines (~1700 RPM, throttle=0).
   - Neutral idle from inside the rear-spin session (same RPM as Phase A, no load).
   - **Phase A: idle in 1st gear** (same RPM, drivetrain drag → measurable throttle).
   - B1..B5 setpoints (rising RPM, rising throttle, in 1st gear).

   Phase A vs neutral idle in the same session is the cleanest "constant RPM,
   varying load" pair we have. A fuel-rate byte must respond to it; an
   RPM-only byte must not.

2. **uint16 BE pair scan** alongside uint8. Fuel rate at 5500 RPM × WOT easily
   exceeds 8-bit dynamic range; a true injector-pulse-time channel is likely
   16 bits.

3. **Post-kill decay shape.** The rear-spin capture ends with a `kill` mark
   while engine is running at idle. Fuel cuts off instantly; RPM decays from
   inertia. A fuel byte should drop to its floor *faster* than RPM does.
   Computed as: byte half-life vs RPM half-life in the first 1.5 s after kill.

Output ranks candidates by a composite score combining:
  - R² of `byte ≈ a + b·RPM + c·throttle + d·RPM·throttle` across all operating points.
  - |coefficient d| (the RPM·throttle interaction — the injector-flow shape).
  - Phase-A-vs-neutral-idle Δ relative to within-window noise.
  - Decay ratio: byte_drops_faster_than_rpm.

D7 and already-attributed bytes are skipped. Read-only against logs/.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

ALWAYS_ON_IDS = ["120", "121", "129", "12A", "12D", "12E", "450", "540", "541", "5A0", "5B0"]
RPM_ID = "120"

# Bytes already attributed elsewhere (kept in sync with signal-*.md findings).
# We still scan them to sanity-check the ranking but they're tagged in output.
KNOWN_BYTE = {
    ("120", 0): "rpm-hi", ("120", 1): "rpm-lo", ("120", 2): "throttle",
    ("120", 7): "d7-hash",
    ("121", 0): "int16-A-hi", ("121", 1): "int16-A-lo",
    ("121", 2): "int16-B-hi", ("121", 3): "int16-B-lo",
    ("121", 5): "kill-mirror+engine-bit",
    ("121", 7): "d7-hash",
    ("129", 0): "gear+clutch+shift",
    ("129", 7): "d7-hash",
    ("12A", 7): "d7-hash",
    ("12D", 0): "front-speed-hi", ("12D", 1): "front-speed-lo+bit0",
    ("12D", 2): "rear-coarse",
    ("12D", 5): "rear-hi", ("12D", 6): "rear-lo",
    ("12D", 7): "d7-hash",
    ("12E", 7): "d7-hash",
    ("450", 7): "d7-hash",
    ("540", 1): "warmup/throttle-idle",
    ("540", 3): "side-stand+gear-mirror",
    ("540", 5): "coolant-hi", ("540", 6): "coolant-lo",
    ("540", 7): "d7-hash",
    ("541", 2): "kill-bits", ("541", 4): "engine-on-counter",
    ("541", 5): "ramp-counter-hi", ("541", 6): "ramp-counter-lo",
    ("541", 7): "d7-hash",
    ("5A0", 7): "d7-hash",
    ("5B0", 0): "kill-mirror",
    ("5B0", 7): "d7-hash",
}
KNOWN_PAIR = {
    ("120", 0): "rpm-uint16",
    ("121", 0): "int16-A", ("121", 2): "int16-B",
    ("12D", 0): "front-speed-12bit",
    ("12D", 5): "rear-speed-uint16",
    ("540", 5): "coolant-uint16",
}


@dataclass
class OpPoint:
    """One steady-state operating point."""
    label: str
    session: str
    t0: float
    t1: float
    rpm: float = 0.0
    throttle: float = 0.0
    bytes: dict = field(default_factory=dict)  # (id, byte_i) -> mean
    pairs: dict = field(default_factory=dict)  # (id, byte_i) -> mean of BE u16


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
            hex_data = m.group(3)
            if len(hex_data) != 16:
                continue
            out[arb].append((float(m.group(1)), bytes.fromhex(hex_data)))
    return out


def window(frames, t0, t1):
    return [(ts, d) for ts, d in frames if t0 <= ts <= t1]


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def compute_op(frames_by_id: dict[str, list], op: OpPoint) -> bool:
    win_120 = window(frames_by_id.get(RPM_ID, []), op.t0, op.t1)
    if len(win_120) < 5:
        return False
    op.rpm = mean([(d[0] << 8) | d[1] for _, d in win_120])
    op.throttle = mean([d[2] for _, d in win_120])
    for arb, frames in frames_by_id.items():
        win = window(frames, op.t0, op.t1)
        if len(win) < 5:
            continue
        for bi in range(8):
            op.bytes[(arb, bi)] = mean([d[bi] for _, d in win])
        for bi in range(7):  # u16 BE pair starting at bi
            op.pairs[(arb, bi)] = mean([(d[bi] << 8) | d[bi + 1] for _, d in win])
    return True


def session_iso(session_dir: Path) -> float:
    ev = session_dir / "events.csv"
    if ev.exists():
        with ev.open() as f:
            for row in csv.DictReader(f):
                try:
                    return dt.datetime.fromisoformat(row["timestamp_iso"]).timestamp()
                except (KeyError, TypeError):
                    break
    return 0.0


def collect_idle_baselines(logs_root: Path) -> list[OpPoint]:
    """30-s steady idle window from each engine-idle baseline session.

    Take a window starting 60 s after the `start` (starter button) event,
    of 30 s length — well past cranking transients, well inside the run.
    """
    out: list[OpPoint] = []
    for name in (
        "2026-06-17-engine-idle-run-1",
        "2026-06-17-engine-idle-run-2",
        "2026-06-17-engine-idle-run-3",
    ):
        d = logs_root / name
        ev = d / "events.csv"
        if not ev.exists() or not (d / "capture.log").exists():
            continue
        start = None
        with ev.open() as f:
            for r in csv.DictReader(f):
                if r["key"] == "start":
                    start = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
                    break
        if start is None:
            continue
        out.append(OpPoint(label=f"{name[-5:]} neutral-idle",
                           session=name, t0=start + 60.0, t1=start + 90.0))
    return out


def collect_rear_spin_ops(logs_root: Path) -> tuple[list[OpPoint], OpPoint | None, OpPoint | None]:
    """Operating points from the rear-spin session.

    Returns (op_points, neutral_idle_op, decay_anchor_op).
    decay_anchor_op carries the kill timestamp as t0 (no window itself).
    """
    name = "2026-06-23-engine-driven-rear-spin"
    d = logs_root / name
    ev = d / "events.csv"
    if not ev.exists():
        return [], None, None
    marks = {}
    with ev.open() as f:
        for r in csv.DictReader(f):
            marks[(r["key"], r["label"])] = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()

    def find(key_prefix: str, label_substr: str) -> float | None:
        for (k, lbl), t in marks.items():
            if k == key_prefix and label_substr in lbl:
                return t
        return None

    ops: list[OpPoint] = []

    # Neutral idle pre-Phase-A: from idle_settled to Phase A start.
    t_settle = find("idle_settled", "")
    t_phase_a = find("setpoint", "Phase A")
    neutral = None
    if t_settle is not None and t_phase_a is not None and t_phase_a - t_settle > 15:
        # Skip the first 5 s after settle for stability; take up to 5 s before Phase A.
        neutral = OpPoint(label="rear-spin neutral-idle",
                          session=name, t0=t_settle + 5.0, t1=t_phase_a - 5.0)
        ops.append(neutral)

    # Phase A: idle in 1st (drivetrain drag holds at ~1700 RPM).
    if t_phase_a is not None:
        ops.append(OpPoint(label="rear-spin Phase-A idle-in-1st",
                           session=name, t0=t_phase_a + 3.0, t1=t_phase_a + 18.0))

    # B1..B5 setpoints.
    for tag in ("B1", "B2", "B3", "B4", "B5"):
        t = find("setpoint", tag)
        if t is not None:
            ops.append(OpPoint(label=f"rear-spin {tag}",
                               session=name, t0=t + 3.0, t1=t + 11.0))

    # Phase C: idle in 1st post-sweep.
    t_phase_c = find("setpoint", "Phase C")
    if t_phase_c is not None:
        ops.append(OpPoint(label="rear-spin Phase-C idle-in-1st-post",
                           session=name, t0=t_phase_c + 3.0, t1=t_phase_c + 14.0))

    # Decay anchor = kill mark timestamp.
    t_kill = find("kill", "")
    decay_anchor = None
    if t_kill is not None:
        decay_anchor = OpPoint(label="rear-spin kill", session=name, t0=t_kill, t1=t_kill)

    return ops, neutral, decay_anchor


def fit_model(xs_rpm, xs_thr, ys) -> tuple[float, tuple[float, float, float, float]]:
    """Least-squares fit of y = a + b*RPM + c*thr + d*RPM*thr. Returns (R^2, (a,b,c,d)).

    Implemented without numpy via normal equations on a 4x4 system.
    """
    n = len(ys)
    if n < 5:
        return 0.0, (0.0, 0.0, 0.0, 0.0)
    feats = [(1.0, r, t, r * t) for r, t in zip(xs_rpm, xs_thr)]
    # Build normal equations XtX (4x4) and Xty (4).
    xtx = [[0.0] * 4 for _ in range(4)]
    xty = [0.0] * 4
    for f, y in zip(feats, ys):
        for i in range(4):
            xty[i] += f[i] * y
            for j in range(4):
                xtx[i][j] += f[i] * f[j]
    # Solve by Gauss-Jordan with partial pivoting.
    a = [row[:] + [xty[i]] for i, row in enumerate(xtx)]
    for i in range(4):
        piv = i
        for k in range(i + 1, 4):
            if abs(a[k][i]) > abs(a[piv][i]):
                piv = k
        a[i], a[piv] = a[piv], a[i]
        if abs(a[i][i]) < 1e-12:
            return 0.0, (0.0, 0.0, 0.0, 0.0)
        inv = 1.0 / a[i][i]
        for j in range(5):
            a[i][j] *= inv
        for k in range(4):
            if k == i:
                continue
            f = a[k][i]
            for j in range(5):
                a[k][j] -= f * a[i][j]
    coeffs = (a[0][4], a[1][4], a[2][4], a[3][4])
    yhat = [sum(c * fc for c, fc in zip(coeffs, f)) for f in feats]
    ybar = mean(ys)
    ss_tot = sum((y - ybar) ** 2 for y in ys)
    ss_res = sum((y - yh) ** 2 for y, yh in zip(ys, yhat))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    return r2, coeffs


def half_life(times: list[float], values: list[float], baseline: float, floor: float) -> float:
    """Time at which values cross the midpoint between baseline and floor.

    Returns the first crossing time, or +inf if never reached. Assumes
    `times` is sorted and `values` aligned.
    """
    if baseline <= floor or not values:
        return float("inf")
    midpoint = (baseline + floor) / 2.0
    for t, v in zip(times, values):
        if v <= midpoint:
            return t
    return float("inf")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--logs-dir", default="logs")
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--csv", help="write per-byte fit rows here")
    args = p.parse_args()

    logs_root = REPO_ROOT / args.logs_dir
    if not logs_root.is_dir():
        print(f"no logs dir at {logs_root}")
        return 1

    # 1) Build op-point list.
    idle_ops = collect_idle_baselines(logs_root)
    rear_ops, rear_neutral, decay_anchor = collect_rear_spin_ops(logs_root)
    if not rear_ops:
        print("rear-spin session missing or unreadable")
        return 1

    all_ops = idle_ops + rear_ops

    # 2) Load frames + compute per-op means.
    by_session: dict[str, dict[str, list]] = {}
    for op in all_ops:
        if op.session not in by_session:
            by_session[op.session] = parse_log(
                logs_root / op.session / "capture.log", set(ALWAYS_ON_IDS)
            )
    used_ops: list[OpPoint] = []
    for op in all_ops:
        if compute_op(by_session[op.session], op):
            used_ops.append(op)

    print(f"# injector-flow scan — {len(used_ops)} operating points\n")
    print(f"  {'label':<42} {'RPM':>6}  {'thr':>5}  {'RPM·thr':>10}")
    for op in used_ops:
        print(f"  {op.label:<42} {op.rpm:6.0f}  {op.throttle:5.1f}  {op.rpm * op.throttle:10.0f}")
    print()

    # 3) Phase-A vs neutral-idle diff (same session, same RPM, different throttle).
    rear_phase_a = next((o for o in used_ops if "Phase-A idle-in-1st" in o.label), None)
    phase_a_delta = {}  # (kind, id, byte) -> abs delta
    if rear_neutral is not None and rear_phase_a is not None:
        for key, va in rear_phase_a.bytes.items():
            vn = rear_neutral.bytes.get(key)
            if vn is not None:
                phase_a_delta[("byte",) + key] = abs(va - vn)
        for key, va in rear_phase_a.pairs.items():
            vn = rear_neutral.pairs.get(key)
            if vn is not None:
                phase_a_delta[("pair",) + key] = abs(va - vn)
        d_rpm = rear_phase_a.rpm - rear_neutral.rpm
        d_thr = rear_phase_a.throttle - rear_neutral.throttle
        print(f"# Phase-A vs rear-spin neutral idle: Δrpm={d_rpm:+.0f}, Δthrottle={d_thr:+.1f}")
        print(f"  → ΔRPM small (good), Δthrottle nonzero → bytes that move here are load-keyed at constant RPM.\n")

    # 4) Fit y ≈ a + b·RPM + c·thr + d·RPM·thr for each candidate.
    xs_rpm = [op.rpm for op in used_ops]
    xs_thr = [op.throttle for op in used_ops]

    @dataclass
    class Cand:
        kind: str  # "byte" or "pair"
        id: str
        byte: int
        rng: float
        r2: float
        coeffs: tuple
        phase_a_delta: float
        known: str

    candidates: list[Cand] = []

    def score_bytes_or_pairs(kind: str, getter):
        for arb in ALWAYS_ON_IDS:
            max_i = 8 if kind == "byte" else 7
            for bi in range(max_i):
                ys = []
                ok = True
                for op in used_ops:
                    v = getter(op).get((arb, bi))
                    if v is None:
                        ok = False
                        break
                    ys.append(v)
                if not ok:
                    continue
                rng = max(ys) - min(ys)
                if rng < 1.0:
                    continue
                r2, coeffs = fit_model(xs_rpm, xs_thr, ys)
                if kind == "byte" and bi == 7:
                    continue  # always D7 hash
                if kind == "byte":
                    known = KNOWN_BYTE.get((arb, bi), "")
                else:
                    known = KNOWN_PAIR.get((arb, bi), "")
                pa_delta = phase_a_delta.get((kind, arb, bi), 0.0)
                candidates.append(Cand(kind, arb, bi, rng, r2, coeffs, pa_delta, known))

    score_bytes_or_pairs("byte", lambda op: op.bytes)
    score_bytes_or_pairs("pair", lambda op: op.pairs)

    # 5) Composite ranking: R² × normalized d-coefficient × Phase-A Δ.
    # Normalize d coefficient by its term scale across the op points.
    def composite(c: Cand) -> float:
        a, b, cc, d = c.coeffs
        # Magnitude of the RPM·thr contribution at the max op point.
        max_rt = max(r * t for r, t in zip(xs_rpm, xs_thr))
        d_contrib = abs(d * max_rt)
        # Want big R², big d contribution relative to range, big Phase-A Δ.
        d_share = d_contrib / max(c.rng, 1.0)
        pa_share = c.phase_a_delta / max(c.rng, 1.0)
        return c.r2 * (d_share + pa_share)

    # 6) Decay test: per-byte half-life vs RPM half-life in 1.5 s after kill.
    decay_results: dict[tuple, tuple[float, float, float]] = {}  # (kind,id,bi) -> (hl, baseline, floor)
    rpm_hl = float("inf")
    if decay_anchor is not None:
        rear_frames = by_session[decay_anchor.session]
        t_kill = decay_anchor.t0
        # RPM half-life: baseline = mean over [t-1, t-0], floor = mean over [t+3, t+5].
        rpm_win_pre = [(ts, (d[0] << 8) | d[1]) for ts, d in rear_frames[RPM_ID]
                       if t_kill - 1.0 <= ts <= t_kill]
        rpm_win_post = [(ts, (d[0] << 8) | d[1]) for ts, d in rear_frames[RPM_ID]
                        if t_kill + 3.0 <= ts <= t_kill + 5.0]
        rpm_decay = [(ts - t_kill, (d[0] << 8) | d[1]) for ts, d in rear_frames[RPM_ID]
                     if t_kill <= ts <= t_kill + 2.0]
        if rpm_win_pre and rpm_win_post and rpm_decay:
            rpm_base = mean([v for _, v in rpm_win_pre])
            rpm_floor = mean([v for _, v in rpm_win_post])
            rpm_hl = half_life(
                [t for t, _ in rpm_decay], [v for _, v in rpm_decay], rpm_base, rpm_floor
            )

        for arb in ALWAYS_ON_IDS:
            frames = rear_frames[arb]
            pre = [d for ts, d in frames if t_kill - 1.0 <= ts <= t_kill]
            post = [d for ts, d in frames if t_kill + 3.0 <= ts <= t_kill + 5.0]
            decay = [(ts - t_kill, d) for ts, d in frames if t_kill <= ts <= t_kill + 2.0]
            if not pre or not post or not decay:
                continue
            for bi in range(8):
                if bi == 7:
                    continue
                base = mean([d[bi] for d in pre])
                floor = mean([d[bi] for d in post])
                hl = half_life([t for t, _ in decay], [d[bi] for _, d in decay], base, floor)
                decay_results[("byte", arb, bi)] = (hl, base, floor)
            for bi in range(7):
                base = mean([(d[bi] << 8) | d[bi + 1] for d in pre])
                floor = mean([(d[bi] << 8) | d[bi + 1] for d in post])
                hl = half_life(
                    [t for t, _ in decay],
                    [(d[bi] << 8) | d[bi + 1] for _, d in decay],
                    base,
                    floor,
                )
                decay_results[("pair", arb, bi)] = (hl, base, floor)

    candidates.sort(key=composite, reverse=True)

    # Output table.
    def fmt_decay(key):
        r = decay_results.get(key)
        if r is None:
            return "-"
        hl, base, floor = r
        if not math.isfinite(hl):
            return "(no cross)"
        if base <= floor:
            return "(rising)"
        ratio = (rpm_hl / hl) if math.isfinite(rpm_hl) and hl > 0 else float("inf")
        if math.isfinite(ratio):
            return f"{hl:.2f}s ({ratio:.1f}× RPM)"
        return f"{hl:.2f}s"

    print(f"## Top candidates by composite score (R² · (d-contrib + Phase-A Δ) / range)")
    print(f"   RPM half-life after kill = {rpm_hl:.2f}s  (decay shape baseline)\n")
    hdr = (f"  {'kind':<4} {'id':>3} {'B':>3}  {'min..max':>14}  {'R²':>5}  "
           f"{'d·max_rt':>9}  {'ΦA-Δ':>6}  {'decay':<18}  {'known':<24}")
    print(hdr)
    for c in candidates[: args.top]:
        rng_s = f"{c.coeffs[0]:5.1f}"  # placeholder, replace below
        # min..max from refit (we don't keep series, so recompute lazily)
        ys = []
        for op in used_ops:
            v = (op.bytes if c.kind == "byte" else op.pairs).get((c.id, c.byte))
            if v is not None:
                ys.append(v)
        rng_s = f"{min(ys):5.1f}..{max(ys):5.1f}"
        a, b, cc, d = c.coeffs
        max_rt = max(r * t for r, t in zip(xs_rpm, xs_thr))
        d_contrib = abs(d * max_rt)
        decay_s = fmt_decay((c.kind, c.id, c.byte))
        print(f"  {c.kind:<4} {c.id:>3} {('D'+str(c.byte)):>3}  {rng_s:>14}  "
              f"{c.r2:5.2f}  {d_contrib:9.1f}  {c.phase_a_delta:6.1f}  "
              f"{decay_s:<18}  {c.known:<24}")

    # Unknowns-only view.
    print(f"\n## Top UNKNOWN candidates (no existing attribution)\n")
    print(hdr)
    for c in [c for c in candidates if not c.known][: args.top]:
        ys = []
        for op in used_ops:
            v = (op.bytes if c.kind == "byte" else op.pairs).get((c.id, c.byte))
            if v is not None:
                ys.append(v)
        rng_s = f"{min(ys):5.1f}..{max(ys):5.1f}"
        a, b, cc, d = c.coeffs
        max_rt = max(r * t for r, t in zip(xs_rpm, xs_thr))
        d_contrib = abs(d * max_rt)
        decay_s = fmt_decay((c.kind, c.id, c.byte))
        print(f"  {c.kind:<4} {c.id:>3} {('D'+str(c.byte)):>3}  {rng_s:>14}  "
              f"{c.r2:5.2f}  {d_contrib:9.1f}  {c.phase_a_delta:6.1f}  "
              f"{decay_s:<18}  ")

    # Per-op trace for top-5 unknowns.
    top_unk = [c for c in candidates if not c.known][:5]
    if top_unk:
        print(f"\n## Per-op trace for top-5 unknowns\n")
        labels = [op.label.split(" ", 1)[-1][:14] for op in used_ops]
        print(f"  {'cand':<11}  " + "  ".join(f"{l:>14}" for l in labels))
        print(f"  {'(RPM)':<11}  " + "  ".join(f"{op.rpm:>14.0f}" for op in used_ops))
        print(f"  {'(thr)':<11}  " + "  ".join(f"{op.throttle:>14.1f}" for op in used_ops))
        for c in top_unk:
            tag = f"{c.kind[0]}{c.id}.{c.byte}"
            cells = []
            for op in used_ops:
                v = (op.bytes if c.kind == "byte" else op.pairs).get((c.id, c.byte))
                cells.append(f"{v:>14.2f}" if v is not None else f"{'-':>14}")
            print(f"  {tag:<11}  " + "  ".join(cells))

    if args.csv:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["kind", "id", "byte", "min", "max", "R2", "a", "b_rpm", "c_thr", "d_rpm_thr",
                        "phase_a_delta", "decay_halflife_s", "rpm_halflife_s", "known"])
            for c in candidates:
                ys = []
                for op in used_ops:
                    v = (op.bytes if c.kind == "byte" else op.pairs).get((c.id, c.byte))
                    if v is not None:
                        ys.append(v)
                hl = decay_results.get((c.kind, c.id, c.byte), (float("nan"),))[0]
                w.writerow([c.kind, c.id, c.byte, f"{min(ys):.2f}", f"{max(ys):.2f}",
                            f"{c.r2:.4f}", *(f"{v:.6g}" for v in c.coeffs),
                            f"{c.phase_a_delta:.2f}",
                            (f"{hl:.3f}" if math.isfinite(hl) else "inf"),
                            (f"{rpm_hl:.3f}" if math.isfinite(rpm_hl) else "inf"),
                            c.known])
        print(f"\nwrote {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
