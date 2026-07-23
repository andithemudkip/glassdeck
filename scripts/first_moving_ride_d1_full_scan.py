#!/usr/bin/env python3
"""first_moving_ride_d1_full_scan.py — hunt the physical quantity behind `540 D1`.

Follow-up to `first_moving_ride_load_scan.py` and `first_moving_ride_warmup_index_check.py`.
The current [[signal-fuel-injection-setpoint]] finding retracted "warm-up index" but left
the physical quantity open. Candidates surviving:

  H1. Rider-grip-derived + coolant-keyed idle offset (throttle-derived).
  H2. Ride-by-wire butterfly position (M60), 0-100 scale — a "commanded"
      not "requested" quantity. Would be elevated during overrun (ECU keeps
      butterfly slightly open for catalyst/smoothness) and at cold idle
      (fast-idle bypass), matching the observed shape.
  H3. Calculated engine-load percent (OBD PID 04 analogue) — air-mass-based.
  H4. Ignition-timing degrees BTDC.
  H5. Absolute magnitude of a signed torque/load channel related to `121_A`.

Discriminators run here on the 2026-07-22 moving corpus:

  D1. Distribution + quantization (Task 1)
  D2. Univariate correlations vs {grip, RPM, coolant, 121_A, 121_B, rear_kmh,
      dRPM/dt, dthrottle/dt} (Task 2)
  D3. Multivariate residual: fit D1 = a + b·grip + c·RPM + d·coolant_idle_bias,
      look at residual across candidates (Task 3)
  D4. Overrun deep-dive: for each overrun episode, extract synchronized
      trajectory; test whether D1 tracks RPM decay, grip-close time, or 121_A
      magnitude (Task 4)
  D5. Fan cycle (moving-5): find fan-related transitions in coolant crossings,
      correlate D1 (Task 5)
  D6. Time-lag D1 vs grip: does D1 lead or lag? (Task 6)
  D7. Same-RPM across gears: is D1 gear-invariant at fixed RPM+grip? (Task 7)
"""

from __future__ import annotations

import math
import re
import statistics
import sys
from pathlib import Path
from collections import defaultdict, Counter

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSION = REPO_ROOT / "logs" / "2026-07-22-first-moving-ride"
LINE_RE = re.compile(r"\(([\d.]+)\)\s+t([0-9A-Fa-f]{3})([0-9A-Fa-f])([0-9A-Fa-f]*)")


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
    ch = {"rpm": [], "grip": [], "d540_d1": [], "d540_d0": [], "d540_d2": [], "d540_d3": [],
          "d540_d4": [], "d121_a": [], "d121_b": [], "coolant": [], "rear_kmh": [], "gear": []}
    for ts, arb, d in parse_frames(path):
        if arb == "120" and len(d) >= 3:
            ch["rpm"].append((ts, (d[0] << 8) | d[1]))
            ch["grip"].append((ts, d[2]))
        elif arb == "540" and len(d) >= 7:
            ch["d540_d0"].append((ts, d[0]))
            ch["d540_d1"].append((ts, d[1]))
            ch["d540_d2"].append((ts, d[2]))
            ch["d540_d3"].append((ts, d[3]))
            ch["d540_d4"].append((ts, d[4]))
            ch["coolant"].append((ts, ((d[5] << 8) | d[6]) * 0.1))
        elif arb == "121" and len(d) >= 4:
            a = int.from_bytes(d[0:2], "big", signed=True)
            b = int.from_bytes(d[2:4], "big", signed=True)
            ch["d121_a"].append((ts, a))
            ch["d121_b"].append((ts, b))
        elif arb == "12D" and len(d) >= 7:
            ch["rear_kmh"].append((ts, ((d[5] << 8) | d[6]) * 0.0565))
        elif arb == "129" and len(d) >= 1:
            ch["gear"].append((ts, (d[0] >> 4) & 0x0F))
    return ch


def resample_grid(channels, dt=0.1):
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


def merge_all_files():
    all_points = []
    file_bounds = []
    offset = 0.0
    for path in sorted(SESSION.glob("moving-*.log")):
        ch = extract_channels(path)
        if not ch["rpm"]:
            continue
        t0 = ch["rpm"][0][0]
        norm = {k: [(ts - t0 + offset, v) for ts, v in ser] for k, ser in ch.items()}
        grid = resample_grid(norm, dt=0.1)
        for pt in grid:
            pt["file"] = path.name
        all_points.extend(grid)
        file_end = max(ser[-1][0] for ser in norm.values() if ser)
        file_bounds.append((path.name, offset, file_end))
        offset = file_end + 10
    return all_points, file_bounds


def stddev(xs):
    return statistics.pstdev(xs) if len(xs) > 1 else 0.0


def pearson(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def linreg(xs, ys):
    if len(xs) < 3:
        return None, None, None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0:
        return None, None, None
    slope = sxy / sxx
    intercept = my - slope * mx
    resid = [y - (slope * x + intercept) for x, y in zip(xs, ys)]
    return slope, intercept, stddev(resid)


def multi_linreg_2(xs1, xs2, ys):
    """OLS for y = a + b*x1 + c*x2. Returns (a,b,c,resid_stddev,resid_series)."""
    n = len(ys)
    if n < 5:
        return None
    m1 = sum(xs1) / n
    m2 = sum(xs2) / n
    my = sum(ys) / n
    d1 = [x - m1 for x in xs1]
    d2 = [x - m2 for x in xs2]
    dy = [y - my for y in ys]
    s11 = sum(a * a for a in d1)
    s22 = sum(a * a for a in d2)
    s12 = sum(a * b for a, b in zip(d1, d2))
    s1y = sum(a * b for a, b in zip(d1, dy))
    s2y = sum(a * b for a, b in zip(d2, dy))
    det = s11 * s22 - s12 * s12
    if det == 0:
        return None
    b = (s1y * s22 - s2y * s12) / det
    c = (s2y * s11 - s1y * s12) / det
    a = my - b * m1 - c * m2
    resid = [y - (a + b * x1 + c * x2) for x1, x2, y in zip(xs1, xs2, ys)]
    return a, b, c, stddev(resid), resid


def multi_linreg_3(xs1, xs2, xs3, ys):
    """OLS y = a + b*x1 + c*x2 + d*x3 via normal equations."""
    n = len(ys)
    if n < 6:
        return None
    def dot(a, b): return sum(x * y for x, y in zip(a, b))
    ones = [1.0] * n
    X = [ones, list(xs1), list(xs2), list(xs3)]
    XtX = [[dot(X[i], X[j]) for j in range(4)] for i in range(4)]
    Xty = [dot(X[i], ys) for i in range(4)]
    # 4x4 gauss-jordan
    A = [row[:] + [b] for row, b in zip(XtX, Xty)]
    for i in range(4):
        pivot = A[i][i]
        if abs(pivot) < 1e-12:
            for k in range(i + 1, 4):
                if abs(A[k][i]) > 1e-12:
                    A[i], A[k] = A[k], A[i]
                    pivot = A[i][i]
                    break
            else:
                return None
        for j in range(i, 5):
            A[i][j] /= pivot
        for k in range(4):
            if k == i:
                continue
            factor = A[k][i]
            for j in range(i, 5):
                A[k][j] -= factor * A[i][j]
    a, b, c, d = A[0][4], A[1][4], A[2][4], A[3][4]
    resid = [y - (a + b * x1 + c * x2 + d * x3) for x1, x2, x3, y in zip(xs1, xs2, xs3, ys)]
    return a, b, c, d, stddev(resid), resid


def section(title):
    print("\n" + "=" * 76)
    print(title)
    print("=" * 76)


def main():
    points, bounds = merge_all_files()
    print(f"# `540 D1` full discriminator scan on 2026-07-22 moving corpus\n")
    print(f"{len(points)} resampled points (100 ms grid) across {len(bounds)} files")

    usable = [p for p in points
              if p["rpm"] is not None and p["grip"] is not None
              and p["d540_d1"] is not None and p["d121_a"] is not None
              and p["d121_b"] is not None and p["coolant"] is not None
              and p["rear_kmh"] is not None and p["gear"] is not None
              and p["rpm"] > 500]
    print(f"{len(usable)} points with all channels + engine running (RPM>500)\n")

    D1 = [p["d540_d1"] for p in usable]
    GRIP = [p["grip"] for p in usable]
    RPM = [p["rpm"] for p in usable]
    COOL = [p["coolant"] for p in usable]
    A121 = [p["d121_a"] for p in usable]
    B121 = [p["d121_b"] for p in usable]
    SPD = [p["rear_kmh"] for p in usable]
    GEAR = [p["gear"] for p in usable]

    # ------------------------------------------------------------------
    section("D1. Distribution / quantization")
    counts = Counter(D1)
    total = sum(counts.values())
    print(f"unique D1 values: {len(counts)}  (min {min(D1)}  max {max(D1)}  "
          f"mean {statistics.mean(D1):.2f}  σ {stddev(D1):.2f})")
    print(f"top 20 by frequency (value: %):")
    for v, n in counts.most_common(20):
        print(f"  {v:4d}: {100*n/total:5.2f}%  ({n} frames)")
    # dwell distribution: at each dt step is it same as previous?
    print(f"\nvalue-cluster shape (histogram, bin width 5):")
    bins = defaultdict(int)
    for v in D1:
        bins[v // 5 * 5] += 1
    for lo in sorted(bins):
        pct = 100 * bins[lo] / total
        bar = "▇" * int(pct)
        print(f"  {lo:3d}-{lo+4:3d}: {pct:5.1f}%  {bar}")
    # value increment/decrement between consecutive samples
    steps = [D1[i+1] - D1[i] for i in range(len(D1)-1)]
    step_hist = Counter(steps)
    print(f"\nstep-to-step Δ (unchanged rows dominate; interesting are the nonzero):")
    for delta, n in sorted(step_hist.items())[:20]:
        if abs(delta) > 20:
            continue
        print(f"  Δ={delta:+3d}: {100*n/len(steps):5.2f}%")

    # ------------------------------------------------------------------
    section("D2. Univariate correlations (D1 vs each candidate)")
    # derivatives
    dRPM = [(RPM[i+1] - RPM[i]) / 0.1 for i in range(len(RPM)-1)]  # RPM/s
    dGRIP = [(GRIP[i+1] - GRIP[i]) / 0.1 for i in range(len(GRIP)-1)]
    dSPD = [(SPD[i+1] - SPD[i]) / 0.1 for i in range(len(SPD)-1)]
    D1_short = D1[:-1]

    for name, series in [("grip (0-254)", GRIP), ("RPM", RPM),
                          ("coolant °C", COOL), ("121_A", A121),
                          ("121_B", B121), ("rear km/h", SPD),
                          ("|121_A|", [abs(a) for a in A121]),
                          ("max(0,121_A)", [max(0, a) for a in A121]),
                          ("grip · RPM", [g*r for g, r in zip(GRIP, RPM)]),
                          ("max(0,121_A) · RPM", [max(0,a)*r for a, r in zip(A121, RPM)])]:
        r = pearson(series, D1)
        s, i, resid = linreg(series, D1)
        print(f"  D1 vs {name:24s}  r={r:+.3f}  slope={s:+.5f}  D1_hat_resid_σ={resid:.2f}")
    for name, series in [("dRPM/dt", dRPM), ("dgrip/dt", dGRIP), ("dspeed/dt", dSPD)]:
        r = pearson(series, D1_short)
        s, i, resid = linreg(series, D1_short)
        print(f"  D1 vs {name:24s}  r={r:+.3f}  slope={s:+.5f}  D1_hat_resid_σ={resid:.2f}")

    # ------------------------------------------------------------------
    section("D3. Multivariate residual")
    # Fit D1 vs grip alone, then residual vs everything else
    print("(a) Fit  D1 ~ a + b·grip")
    s, i, r0 = linreg(GRIP, D1)
    print(f"    a={i:.2f}  b={s:.4f}  resid_σ={r0:.2f}")
    resid_after_grip = [d - (s * g + i) for d, g in zip(D1, GRIP)]

    for name, series in [("RPM", RPM), ("coolant", COOL), ("121_A", A121),
                          ("max(0,121_A)", [max(0, a) for a in A121]),
                          ("|121_A|", [abs(a) for a in A121]),
                          ("rear_kmh", SPD), ("gear", GEAR),
                          ("grip·RPM", [g*r for g, r in zip(GRIP, RPM)])]:
        r = pearson(series, resid_after_grip)
        print(f"    resid[D1|grip] vs {name:16s}  r={r:+.3f}")

    print("\n(b) Fit  D1 ~ a + b·grip + c·RPM")
    res = multi_linreg_2(GRIP, RPM, D1)
    if res:
        a, b, c, r1, resid1 = res
        print(f"    a={a:.2f}  b_grip={b:.4f}  c_rpm={c:.5f}  resid_σ={r1:.2f}")
        for name, series in [("coolant", COOL), ("121_A", A121),
                              ("max(0,121_A)", [max(0, x) for x in A121]),
                              ("|121_A|", [abs(x) for x in A121]),
                              ("gear", GEAR), ("dgrip/dt", dGRIP+[0]),
                              ("dRPM/dt", dRPM+[0])]:
            r = pearson(series, resid1)
            print(f"    resid[D1|grip,RPM] vs {name:16s}  r={r:+.3f}")

    print("\n(c) Fit  D1 ~ a + b·grip + c·RPM + d·coolant")
    res = multi_linreg_3(GRIP, RPM, COOL, D1)
    if res:
        a, b, c, d, r2, resid2 = res
        print(f"    a={a:.2f}  b_grip={b:.4f}  c_rpm={c:.5f}  d_coolant={d:.4f}  resid_σ={r2:.2f}")
        for name, series in [("121_A", A121), ("max(0,121_A)", [max(0, x) for x in A121]),
                              ("|121_A|", [abs(x) for x in A121]), ("121_B", B121),
                              ("rear_kmh", SPD), ("gear", GEAR),
                              ("grip·RPM", [g*r for g, r in zip(GRIP, RPM)]),
                              ("max(0,121_A)·RPM", [max(0,x)*r for x, r in zip(A121, RPM)])]:
            r = pearson(series, resid2)
            print(f"    resid[D1|grip,RPM,cool] vs {name:20s}  r={r:+.3f}")

    # ------------------------------------------------------------------
    section("D4. Overrun episodes (grip<8 raw = <3.1%, RPM>2500, held ≥1s)")
    # enumerate contiguous overrun windows on the merged grid
    OV_GRIP = 8
    OV_RPM = 2500
    MIN_DUR = 1.0  # seconds
    events = []
    i = 0
    while i < len(usable):
        if usable[i]["grip"] < OV_GRIP and usable[i]["rpm"] > OV_RPM:
            j = i
            while j < len(usable) and usable[j]["grip"] < OV_GRIP and usable[j]["rpm"] > OV_RPM:
                j += 1
            if (j - i) * 0.1 >= MIN_DUR:
                events.append((i, j))
            i = j
        else:
            i += 1
    print(f"{len(events)} overrun episodes ≥ {MIN_DUR:.1f}s\n")

    # aggregate stats across all overrun frames
    ov_pts = [usable[k] for a, b in events for k in range(a, b)]
    if ov_pts:
        print(f"aggregate {len(ov_pts)} overrun frames  ({len(ov_pts)*0.1:.1f}s):")
        d1_ov = [p["d540_d1"] for p in ov_pts]
        a_ov = [p["d121_a"] for p in ov_pts]
        rpm_ov = [p["rpm"] for p in ov_pts]
        grip_ov = [p["grip"] for p in ov_pts]
        cool_ov = [p["coolant"] for p in ov_pts]
        print(f"  D1     μ={statistics.mean(d1_ov):6.2f}  σ={stddev(d1_ov):5.2f}  min={min(d1_ov)}  max={max(d1_ov)}")
        print(f"  121_A  μ={statistics.mean(a_ov):+6.2f}  σ={stddev(a_ov):5.2f}  min={min(a_ov)}  max={max(a_ov)}")
        print(f"  RPM    μ={statistics.mean(rpm_ov):6.0f}  σ={stddev(rpm_ov):5.0f}  min={min(rpm_ov)}  max={max(rpm_ov)}")
        print(f"  grip   μ={statistics.mean(grip_ov):6.2f}  σ={stddev(grip_ov):5.2f}  min={min(grip_ov)}  max={max(grip_ov)}")
        print(f"  cool   μ={statistics.mean(cool_ov):6.1f}")
        # bin D1 by RPM to see if D1 tracks RPM during overrun
        rpm_bins = defaultdict(list)
        for p in ov_pts:
            rpm_bins[int(p["rpm"] // 500) * 500].append(p["d540_d1"])
        print(f"\n  D1 by RPM bin (overrun only):")
        for rb in sorted(rpm_bins):
            xs = rpm_bins[rb]
            if len(xs) >= 10:
                print(f"    RPM {rb:5d}-{rb+500:5d}  n={len(xs):5d}  D1 μ={statistics.mean(xs):6.2f}  σ={stddev(xs):5.2f}")
        # bin D1 by 121_A bin
        a_bins = defaultdict(list)
        for p in ov_pts:
            a_bins[int(p["d121_a"] // 10) * 10].append(p["d540_d1"])
        print(f"\n  D1 by 121_A bin (overrun only):")
        for ab in sorted(a_bins):
            xs = a_bins[ab]
            if len(xs) >= 10:
                print(f"    121_A {ab:+5d}..{ab+10:+5d}  n={len(xs):5d}  D1 μ={statistics.mean(xs):6.2f}  σ={stddev(xs):5.2f}")

    # ------------------------------------------------------------------
    section("D5. Fan cycle in moving-5")
    # points in the moving-5 window
    m5_lo = m5_hi = None
    for name, lo, hi in bounds:
        if name == "moving-5.log":
            m5_lo, m5_hi = lo, hi
            break
    m5 = [p for p in usable if m5_lo <= p["ts"] <= m5_hi]
    print(f"moving-5 span: {len(m5)} points, coolant range {min(p['coolant'] for p in m5):.1f}..{max(p['coolant'] for p in m5):.1f} °C")
    # find first 95°C hit (fan should go on) and 90°C after (fan should go off)
    hits = []
    up_cross = False
    for p in m5:
        if p["coolant"] >= 95 and not up_cross:
            up_cross = True
            hits.append(("→95", p["ts"], p["d540_d1"], p["coolant"], p["grip"], p["rpm"]))
        if p["coolant"] <= 90 and up_cross:
            up_cross = False
            hits.append(("→90", p["ts"], p["d540_d1"], p["coolant"], p["grip"], p["rpm"]))
    print(f"coolant threshold crossings: {len(hits)}")
    for tag, ts, d1, c, g, r in hits[:20]:
        print(f"  {tag}  t={ts:6.1f}  D1={d1:4d}  coolant={c:5.1f}  grip={g:3d}  RPM={r:5d}")
    # coolant-hot idle-band D1 stats
    hot_idle = [p for p in m5 if p["rpm"] < 2200 and p["grip"] < 8 and p["coolant"] >= 85]
    if hot_idle:
        d1s = [p["d540_d1"] for p in hot_idle]
        print(f"\n  hot idle band (RPM<2200, grip<8, coolant≥85°C): n={len(d1s)}  "
              f"D1 μ={statistics.mean(d1s):.2f}  σ={stddev(d1s):.2f}  range {min(d1s)}..{max(d1s)}")

    # Look for a candidate fan bit in 540 D0/D2/D3/D4 by regressing bit-value against coolant≥95
    section("D5b. Search 540 D0/D2/D3/D4 bits for coolant-fan-cycle correlate")
    D0 = [p["d540_d0"] for p in usable]
    D2 = [p["d540_d2"] for p in usable]
    D3 = [p["d540_d3"] for p in usable]
    D4 = [p["d540_d4"] for p in usable]
    hot = [1 if p["coolant"] >= 95 else 0 for p in usable]
    for byte_name, series in [("D0", D0), ("D2", D2), ("D3", D3), ("D4", D4)]:
        for bit in range(8):
            bits = [(v >> bit) & 1 for v in series]
            if sum(bits) < 30 or sum(bits) > len(bits) - 30:
                continue  # bit constant
            r = pearson(bits, hot)
            if r is not None and abs(r) > 0.15:
                print(f"  540 {byte_name} bit{bit}  active-fraction {sum(bits)/len(bits)*100:5.1f}%  "
                      f"r(coolant≥95°C)={r:+.3f}")

    # ------------------------------------------------------------------
    section("D6. Time-lag: D1 vs grip cross-correlation")
    # sample only high-grip-activity windows (where meaningful transitions happen)
    print("Pearson r(D1(t), grip(t+lag)) at lag {-500..+500} ms in 100 ms steps")
    max_lag = 5
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            xs = GRIP[:len(GRIP) - lag] if lag > 0 else GRIP[:]
            ys = D1[lag:] if lag > 0 else D1[:]
        else:
            xs = GRIP[-lag:]
            ys = D1[:len(D1) + lag]
        r = pearson(xs, ys)
        marker = "  ← best?" if lag == 0 else ""
        print(f"  lag = {lag*100:+4d} ms   r={r:+.4f}{marker}")

    # Similarly D1 vs 121_A
    print("\nPearson r(D1(t), max(0,121_A)(t+lag)) at lag {-500..+500} ms")
    A_pos = [max(0, x) for x in A121]
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            xs = A_pos[:len(A_pos) - lag] if lag > 0 else A_pos[:]
            ys = D1[lag:] if lag > 0 else D1[:]
        else:
            xs = A_pos[-lag:]
            ys = D1[:len(D1) + lag]
        r = pearson(xs, ys)
        print(f"  lag = {lag*100:+4d} ms   r={r:+.4f}")

    # ------------------------------------------------------------------
    section("D7. Same-RPM across gears — is D1 a load or a demand?")
    # For each RPM bin, look at points with LOW grip (<20 raw) in different gears
    # Different gears at same RPM means very different vehicle speed — so wind load
    # differs. If D1 is load-derived it should track gear; if demand-derived it shouldn't.
    print("Low-grip (0-20 raw = 0-8%) frames at fixed RPM, broken by gear:")
    print(f"  {'RPM bin':>10}  {'gear':>4}  {'n':>5}  {'D1 μ±σ':>10}  {'grip μ':>7}  {'speed μ':>8}")
    rpm_gear_bins = defaultdict(list)
    for p in usable:
        if p["grip"] > 20 or p["rpm"] < 1500:
            continue
        rpm_gear_bins[(int(p["rpm"] // 500) * 500, p["gear"])].append(p)
    for (rb, g), pts in sorted(rpm_gear_bins.items()):
        if len(pts) < 20:
            continue
        d1s = [p["d540_d1"] for p in pts]
        grip = [p["grip"] for p in pts]
        spd = [p["rear_kmh"] for p in pts]
        print(f"  {rb:>4}-{rb+500:<4}   {g:>4}  {len(pts):>5}  "
              f"{statistics.mean(d1s):5.2f}±{stddev(d1s):4.2f}  "
              f"{statistics.mean(grip):7.2f}  {statistics.mean(spd):8.1f}")

    # Same but medium grip (20-60 raw = ~8-24%)
    print("\nMedium-grip (20-60 raw = 8-24%) frames at fixed RPM, broken by gear:")
    print(f"  {'RPM bin':>10}  {'gear':>4}  {'n':>5}  {'D1 μ±σ':>10}  {'grip μ':>7}  {'speed μ':>8}")
    rpm_gear_bins2 = defaultdict(list)
    for p in usable:
        if p["grip"] < 20 or p["grip"] > 60:
            continue
        rpm_gear_bins2[(int(p["rpm"] // 500) * 500, p["gear"])].append(p)
    for (rb, g), pts in sorted(rpm_gear_bins2.items()):
        if len(pts) < 20:
            continue
        d1s = [p["d540_d1"] for p in pts]
        grip = [p["grip"] for p in pts]
        spd = [p["rear_kmh"] for p in pts]
        print(f"  {rb:>4}-{rb+500:<4}   {g:>4}  {len(pts):>5}  "
              f"{statistics.mean(d1s):5.2f}±{stddev(d1s):4.2f}  "
              f"{statistics.mean(grip):7.2f}  {statistics.mean(spd):8.1f}")


if __name__ == "__main__":
    sys.exit(main())
