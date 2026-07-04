#!/usr/bin/env python3
"""battery_voltage_scan.py — desk-only hunt for the battery-voltage byte.

Strategy: battery voltage has three signatures no other CAN value shares well:

  S1. Steps up engine-off → engine-on
      Resting battery is ~12.4–12.8 V; alternator charging is ~13.8–14.4 V.
      That's a clean +1 to +2 V step that holds for the entire engine-on
      window.  Almost every encoding lands this as +10..+30 LSB.

  S2. Stable within each engine state
      Resting and alternator regulation are both quiet; within-session std
      should be tiny.  Coolant temp, throttle, RPM, etc. all wobble more.

  S3. Cross-session-consistent within each state
      Resting voltage is similar across sessions (±0.2 V); alternator-regulated
      voltage even tighter.  Coolant-keyed bytes vary widely across the 3 idle
      runs (cold / partial-warm / hot).  Use this to drop coolant-correlated
      candidates.

We also pull two bonus discriminators from existing captures:

  D1. RPM-sweep stability
      Alternator regulation holds voltage flat through the B1..B5 RPM setpoint
      sweep in 2026-06-23-engine-driven-rear-spin.  RPM-keyed bytes drift hard
      through the sweep; voltage shouldn't.

  D2. High-beam load test
      2026-06-24-front-wheel-decay-mark has 6 high-beam toggles, engine off.
      Headlight is ~50 W → ~4 A draw on a healthy battery → ~0.1-0.3 V dip.
      We compare pre-toggle vs post-toggle byte means for the top candidates.

D7 excluded (cycle hash, [[byte-d7-cycle-hash]]).  Known signals are tagged
but not filtered, so the scan acts as its own sanity check (coolant + RPM +
throttle should rank below true voltage candidates on the combined score).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import re
import statistics as stats
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

ALWAYS_ON_IDS = ["120", "121", "129", "12A", "12D", "12E", "450", "540", "541", "5A0", "5B0"]

KNOWN = {
    ("120", 0): "rpm-hi",       ("120", 1): "rpm-lo",
    ("120", 2): "throttle",
    ("121", 0): "121-int16-A-hi", ("121", 1): "121-int16-A-lo",
    ("121", 2): "121-int16-B-hi", ("121", 3): "121-int16-B-lo",
    ("12D", 0): "front-wheel-hi", ("12D", 1): "front-wheel-lo",
    ("12D", 2): "rear-wheel-coarse",
    ("12D", 5): "rear-wheel-hi", ("12D", 6): "rear-wheel-lo",
    ("540", 1): "warmup-index",
    ("540", 2): "ignition-armed-bit",
    ("540", 3): "side-stand+gear-mirror+ignition-armed-bit",
    ("540", 5): "coolant-hi",   ("540", 6): "coolant-lo",
    ("541", 2): "kill-bits",    ("541", 4): "engine-on-counter",
    ("541", 6): "key-on-ramp-counter",  # side-finding from 2026-06-18-gear-cycle-clutch
    ("129", 0): "gear+clutch+shift",
    ("121", 5): "kill-mirror",
    ("5B0", 0): "kill-mirror",
}

# Sessions and the absolute timestamp windows (monotonic, derived from events.csv)
# where the bike is in a known steady state.  Offsets are added in main() — we
# only store (session_dir, event_index, t_offset_start_s, t_offset_end_s) so the
# script is robust to absolute clock skew.

# Engine OFF windows (key on, kill RUN, engine never started or fully decayed
# before the window).  Pulled from session.md classifications.
ENGINE_OFF = [
    # (session, anchor_kind, anchor_idx_in_events, t0_offset_s, t1_offset_s, label)
    # idle-runs have the pre-start key-on window before the starter press
    ("2026-06-17-engine-idle-run-1", "between", "mark", "start", +2.0, -2.0, "idle-1 pre-start"),
    ("2026-06-17-engine-idle-run-2", "between", "mark", "start", +2.0, -2.0, "idle-2 pre-start"),
    ("2026-06-17-engine-idle-run-3", "between", "mark", "start", +2.0, -2.0, "idle-3 pre-start"),
    # full-session engine-off captures: take a tail window after dash settle (~30 s)
    ("2026-06-17-key-on-cold-boot", "from-first-frame", None, +35.0, +95.0, "key-on cold-boot tail"),
    ("2026-06-19-side-stand-toggle", "from-first-frame", None, +1.0, +30.0, "side-stand head"),
    ("2026-06-19-gear-cycle-clutch-A-clutch-only", "from-first-frame", None, +1.0, +30.0, "clutch-only head"),
    ("2026-06-19-throttle-sweep-engine-off", "from-first-frame", None, +1.0, +12.0, "throttle-sweep head"),
    ("2026-06-22-wheel-spin-paddock-stand", "from-first-frame", None, +1.0, +25.0, "wheel-spin head"),
    ("2026-06-24-front-wheel-hand-spin", "from-first-frame", None, +1.0, +25.0, "hand-spin head"),
    ("2026-06-24-front-wheel-decay-mark", "from-first-frame", None, +1.0, +12.0, "decay-mark head"),
]

# Engine ON IDLE windows: skip the first ~20 s after starter (start transient,
# fast-idle drop), end ~5 s before kill.
ENGINE_ON_IDLE = [
    ("2026-06-17-engine-idle-run-1", "starter-to-kill", +22.0, -5.0, "idle-1"),
    ("2026-06-17-engine-idle-run-2", "starter-to-kill", +22.0, -5.0, "idle-2"),
    ("2026-06-17-engine-idle-run-3", "starter-to-kill", +22.0, -5.0, "idle-3"),
    # rear-spin pre-sweep idle (Phase A is at +45 s after starter — use the gap
    # between starter+25 and the Phase A mark)
    ("2026-06-23-engine-driven-rear-spin", "starter-to-phaseA", +25.0, -2.0, "rear-spin pre-sweep idle"),
]

# Engine ON RPM-SWEPT windows: setpoint mark + skip + len.
RPM_SWEEP_SETPOINTS = ["B1", "B2", "B3", "B4", "B5"]
SETPOINT_SKIP = 3.0
SETPOINT_LEN = 8.0


def parse_log(path, ids_of_interest):
    out = {arb: [] for arb in ids_of_interest}
    t_first = None
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
            ts = float(m.group(1))
            if t_first is None:
                t_first = ts
            out[arb].append((ts, bytes.fromhex(hex_data)))
    return out, t_first


def parse_events(path):
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            rows.append({"t": t, "key": r["key"], "label": r["label"]})
    return rows


def first_event(rows, key):
    for r in rows:
        if r["key"] == key:
            return r
    return None


def window(frames, t0, t1):
    return [(ts, d) for ts, d in frames if t0 <= ts <= t1]


def resolve_window(session_dir, spec, events):
    """Return (t0, t1) absolute seconds for the window spec."""
    kind = spec[0]
    if kind == "between":
        _, k_start, k_end, off_start, off_end, _label = spec
        a = first_event(events, k_start)
        b = first_event(events, k_end)
        if not a or not b:
            return None
        return a["t"] + off_start, b["t"] + off_end
    if kind == "from-first-frame":
        _, _none, off_start, off_end, _label = spec
        # Caller patches in t_first since we don't know it here yet.
        return ("REL_TO_FIRST", off_start, off_end)
    if kind == "starter-to-kill":
        _, off_start, off_end, _label = spec
        a = first_event(events, "start")
        b = first_event(events, "kill")
        if not a or not b:
            return None
        return a["t"] + off_start, b["t"] + off_end
    if kind == "starter-to-phaseA":
        _, off_start, off_end, _label = spec
        a = first_event(events, "start")
        # Phase A mark is the first setpoint
        b = next((r for r in events if r["key"] == "setpoint" and "Phase A" in r["label"]), None)
        if not a or not b:
            return None
        return a["t"] + off_start, b["t"] + off_end
    raise ValueError(f"unknown spec kind {kind}")


def aggregate_window(frames_per_id, t0, t1):
    """Return {(id, byte_idx): (mean, std, n)} for every always-on ID byte."""
    out = {}
    for arb, frames in frames_per_id.items():
        win = window(frames, t0, t1)
        if len(win) < 5:
            continue
        for bi in range(8):
            vals = [d[bi] for _, d in win]
            mu = stats.fmean(vals)
            sd = stats.pstdev(vals) if len(vals) > 1 else 0.0
            out[(arb, bi)] = (mu, sd, len(vals))
    return out


def fmt_bytes(b, idx):
    return f"{b:>3} D{idx}"


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--show-known", action="store_true",
                   help="leave known signals in the ranked table (sanity check)")
    args = p.parse_args()

    # -------------------------- ENGINE-OFF aggregation ------------------------
    print("# Battery-voltage scan (desk-only)\n")
    print("## Step 1 — engine-OFF windows\n")
    off_session_stats = []  # list of (label, {(id, bi): (mean, std, n)})
    for spec in ENGINE_OFF:
        session = spec[0]
        label = spec[-1]
        events = parse_events(REPO_ROOT / "logs" / session / "events.csv")
        frames_per_id, t_first = parse_log(REPO_ROOT / "logs" / session / "capture.log",
                                            set(ALWAYS_ON_IDS))
        if spec[1] == "from-first-frame":
            t0 = t_first + spec[3]
            t1 = t_first + spec[4]
        else:
            tw = resolve_window(session, spec[1:], events)
            if tw is None:
                print(f"  ! {label}: window unresolved", file=sys.stderr)
                continue
            t0, t1 = tw
        agg = aggregate_window(frames_per_id, t0, t1)
        if not agg:
            print(f"  ! {label}: empty window", file=sys.stderr)
            continue
        off_session_stats.append((label, agg))
        print(f"  {label:<32}  window {t1-t0:5.1f} s,  IDs seen: {len({k[0] for k in agg})}")
    print()

    # -------------------------- ENGINE-ON IDLE aggregation --------------------
    print("## Step 2 — engine-ON idle windows\n")
    on_session_stats = []
    for spec in ENGINE_ON_IDLE:
        session = spec[0]
        label = spec[-1]
        events = parse_events(REPO_ROOT / "logs" / session / "events.csv")
        frames_per_id, _ = parse_log(REPO_ROOT / "logs" / session / "capture.log",
                                     set(ALWAYS_ON_IDS))
        tw = resolve_window(session, spec[1:], events)
        if tw is None:
            print(f"  ! {label}: window unresolved", file=sys.stderr)
            continue
        t0, t1 = tw
        agg = aggregate_window(frames_per_id, t0, t1)
        if not agg:
            print(f"  ! {label}: empty window", file=sys.stderr)
            continue
        on_session_stats.append((label, agg))
        print(f"  {label:<32}  window {t1-t0:5.1f} s,  IDs seen: {len({k[0] for k in agg})}")
    print()

    # -------------------------- RPM SWEEP aggregation -------------------------
    print("## Step 3 — engine-ON RPM-swept windows (B1..B5)\n")
    rear_spin = "2026-06-23-engine-driven-rear-spin"
    events = parse_events(REPO_ROOT / "logs" / rear_spin / "events.csv")
    frames_per_id, _ = parse_log(REPO_ROOT / "logs" / rear_spin / "capture.log",
                                  set(ALWAYS_ON_IDS))
    sweep_stats = []  # list of (label, agg, rpm_mean)
    for sp_label in RPM_SWEEP_SETPOINTS:
        ev = next((r for r in events if r["key"] == "setpoint" and r["label"].startswith(sp_label)), None)
        if not ev:
            continue
        t0 = ev["t"] + SETPOINT_SKIP
        t1 = t0 + SETPOINT_LEN
        agg = aggregate_window(frames_per_id, t0, t1)
        if not agg:
            continue
        rpm_lo = agg.get(("120", 1), (0, 0, 0))[0]
        rpm_hi = agg.get(("120", 0), (0, 0, 0))[0]
        rpm = rpm_hi * 256 + rpm_lo
        sweep_stats.append((sp_label, agg, rpm))
        print(f"  {sp_label}  ~{rpm:5.0f} RPM,  window {SETPOINT_LEN:.0f} s")
    print()

    # -------------------------- Scoring ---------------------------------------
    # Per (id, bi):
    #   - off_means = list of per-session means
    #   - on_means  = list of per-session means
    #   - delta = mean(on_means) - mean(off_means)
    #   - cross_spread_off = stdev of off_means
    #   - cross_spread_on  = stdev of on_means
    #   - within_std = max within-session std across all sessions
    #   - sweep_drift = max-min across B1..B5 means (alternator-regulated should be small)
    print("## Step 4 — ranked candidates\n")
    keys = set()
    for _, a in off_session_stats + on_session_stats:
        keys |= set(a.keys())
    # exclude D7 (cycle hash)
    keys = {k for k in keys if k[1] != 7}

    rows = []
    for k in keys:
        off_means = [a[k][0] for _, a in off_session_stats if k in a]
        on_means = [a[k][0] for _, a in on_session_stats if k in a]
        within = [a[k][1] for _, a in off_session_stats + on_session_stats if k in a]
        if not off_means or not on_means:
            continue
        m_off = stats.fmean(off_means)
        m_on = stats.fmean(on_means)
        delta = m_on - m_off
        cs_off = stats.pstdev(off_means) if len(off_means) > 1 else 0.0
        cs_on = stats.pstdev(on_means) if len(on_means) > 1 else 0.0
        within_max = max(within) if within else 0.0
        sweep_means = [a[k][0] for _, a, _ in sweep_stats if k in a]
        sweep_drift = (max(sweep_means) - min(sweep_means)) if sweep_means else 0.0
        sweep_mean = stats.fmean(sweep_means) if sweep_means else float("nan")
        rows.append({
            "id": k[0], "byte": k[1],
            "m_off": m_off, "m_on": m_on, "delta": delta,
            "cs_off": cs_off, "cs_on": cs_on,
            "within": within_max,
            "sweep_drift": sweep_drift, "sweep_mean": sweep_mean,
            "known": KNOWN.get(k, ""),
        })

    # Drop static-across-EVERYTHING bytes (truly invariant across every window).
    rows = [r for r in rows if abs(r["delta"]) > 0.05 or r["cs_off"] > 0.05 or r["cs_on"] > 0.05
            or r["sweep_drift"] > 0.1]

    # Don't gate on byte range here — a uint16-high byte might rest at 0, and a
    # voltage byte at 0.05 V/LSB+6 V offset would rest at ~130.  Let the score
    # handle it.

    # Battery-voltage-likeness score:
    #   - reward |delta|  (must be > a few LSB)
    #   - penalise cross-session spread (voltage stable across sessions)
    #   - penalise sweep drift (alternator-regulated)
    #   - penalise within-session std (resting voltage is quiet)
    # Use a simple S/N: |delta| / (1 + cs_off + cs_on + 0.5*within + 0.5*sweep_drift)
    for r in rows:
        noise = 1.0 + r["cs_off"] + r["cs_on"] + 0.5 * r["within"] + 0.5 * r["sweep_drift"]
        r["score"] = abs(r["delta"]) / noise

    rows.sort(key=lambda r: r["score"], reverse=True)

    visible = rows if args.show_known else [r for r in rows if not r["known"]]

    print("  Ranked by battery-voltage-likeness score.")
    print("  Score ↑ = clean engine-on step that DOESN'T drift across sessions or RPM.")
    print()
    print(f"  {'id':>4} {'b':>3}  {'off μ':>7}  {'on μ':>7}  {'Δ':>6}  "
          f"{'cs_off':>6}  {'cs_on':>6}  {'within':>6}  {'sweep':>6}  {'score':>6}  {'known':<28}")
    for r in visible[: args.top]:
        print(f"  {r['id']:>4} D{r['byte']:<2}  "
              f"{r['m_off']:7.2f}  {r['m_on']:7.2f}  {r['delta']:+6.2f}  "
              f"{r['cs_off']:6.2f}  {r['cs_on']:6.2f}  {r['within']:6.2f}  "
              f"{r['sweep_drift']:6.2f}  {r['score']:6.2f}  {r['known']:<28}")

    # -------------------------- Top-candidate per-session detail --------------
    print("\n## Step 5 — per-session means for top-5 unknown candidates\n")
    top5 = [r for r in rows if not r["known"]][:5]
    if not top5:
        print("  (none)")
    for r in top5:
        k = (r["id"], r["byte"])
        print(f"\n### {r['id']} D{r['byte']}  (score {r['score']:.2f}, Δ {r['delta']:+.2f})\n")
        print("  Engine OFF:")
        for label, a in off_session_stats:
            if k in a:
                mu, sd, n = a[k]
                print(f"    {label:<32}  μ={mu:6.2f}  σ={sd:5.2f}  n={n:5d}")
        print("  Engine ON idle:")
        for label, a in on_session_stats:
            if k in a:
                mu, sd, n = a[k]
                print(f"    {label:<32}  μ={mu:6.2f}  σ={sd:5.2f}  n={n:5d}")
        if sweep_stats:
            print("  RPM sweep (engine ON):")
            for sp_label, a, rpm in sweep_stats:
                if k in a:
                    mu, sd, n = a[k]
                    print(f"    {sp_label} ~{rpm:5.0f} RPM        μ={mu:6.2f}  σ={sd:5.2f}  n={n:5d}")

        # Voltage-encoding interpretations for the engine-off vs engine-on means
        for label, scale, offset in [
            ("0.1 V/LSB",       0.1,    0.0),
            ("0.1 V/LSB +6V",   0.1,    6.0),
            ("0.0625 V/LSB",    0.0625, 0.0),
            ("0.05 V/LSB +5V",  0.05,   5.0),
        ]:
            v_off = r["m_off"] * scale + offset
            v_on = r["m_on"] * scale + offset
            tag = ""
            if 11.8 <= v_off <= 13.0 and 13.4 <= v_on <= 14.8:
                tag = "  ← matches expected resting+alternator"
            print(f"    → if {label}: off={v_off:5.2f} V, on={v_on:5.2f} V{tag}")

    # -------------------------- Exhaustive Δ table ----------------------------
    # Sorted by |delta|, all bytes including KNOWN.  Useful as a sanity check
    # that we aren't missing a subtle voltage step somewhere — if voltage is
    # broadcast as a uint8, it MUST appear here with delta ≈ +10..+30.
    print("\n## Step 7 — exhaustive Δ(engine-on - engine-off) sorted, all uint8 bytes\n")
    all_rows = []
    for k in sorted(keys):
        off_means = [a[k][0] for _, a in off_session_stats if k in a]
        on_means = [a[k][0] for _, a in on_session_stats if k in a]
        if not off_means or not on_means:
            continue
        m_off = stats.fmean(off_means)
        m_on = stats.fmean(on_means)
        all_rows.append({
            "id": k[0], "byte": k[1],
            "m_off": m_off, "m_on": m_on, "delta": m_on - m_off,
            "cs_off": stats.pstdev(off_means) if len(off_means) > 1 else 0.0,
            "cs_on": stats.pstdev(on_means) if len(on_means) > 1 else 0.0,
            "known": KNOWN.get(k, ""),
        })
    all_rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    print(f"  {'id':>4} {'b':>3}  {'off μ':>7}  {'on μ':>7}  {'Δ':>7}  "
          f"{'cs_off':>6}  {'cs_on':>6}  {'known':<32}")
    for r in all_rows[:30]:
        print(f"  {r['id']:>4} D{r['byte']:<2}  "
              f"{r['m_off']:7.2f}  {r['m_on']:7.2f}  {r['delta']:+7.2f}  "
              f"{r['cs_off']:6.2f}  {r['cs_on']:6.2f}  {r['known']:<32}")

    # -------------------------- uint16 BE pair scan ---------------------------
    # If voltage is encoded as a 16-bit field at e.g. 0.001 V/LSB it would be
    # split across two adjacent bytes.  Recompute engine-off / engine-on means
    # for every adjacent pair (D0:D1, D1:D2, ..., D5:D6) and rank.  D6:D7 is
    # excluded since D7 is the cycle hash.
    print("\n## Step 8 — uint16 BE pair scan (D0:D1 .. D5:D6 per ID)\n")
    print("  Battery voltage at 0.001 V/LSB BE uint16 would rest at ~12500 (off) /")
    print("  ~14000 (on) — delta ≈ +1500.  At 0.01 V/LSB: rest ~1250 / 1400, Δ ≈ +150.\n")

    def pair_stats(session_stats, arb, hi, lo):
        means = []
        for _, a in session_stats:
            if (arb, hi) in a and (arb, lo) in a:
                mu_hi = a[(arb, hi)][0]
                mu_lo = a[(arb, lo)][0]
                # Use the byte means as a proxy for the pair mean.  This is
                # exact iff hi never wraps within the window — true for a
                # voltage value that varies <2.5 V.
                means.append(mu_hi * 256 + mu_lo)
        return means

    pair_rows = []
    for arb in ALWAYS_ON_IDS:
        for hi in range(6):  # D0..D5; pairs D0:D1..D5:D6
            lo = hi + 1
            off_pair = pair_stats(off_session_stats, arb, hi, lo)
            on_pair = pair_stats(on_session_stats, arb, hi, lo)
            if not off_pair or not on_pair:
                continue
            m_off = stats.fmean(off_pair)
            m_on = stats.fmean(on_pair)
            delta = m_on - m_off
            cs_off = stats.pstdev(off_pair) if len(off_pair) > 1 else 0.0
            cs_on = stats.pstdev(on_pair) if len(on_pair) > 1 else 0.0
            known_hi = KNOWN.get((arb, hi), "")
            known_lo = KNOWN.get((arb, lo), "")
            known = known_hi or known_lo
            pair_rows.append({
                "id": arb, "hi": hi, "lo": lo,
                "m_off": m_off, "m_on": m_on, "delta": delta,
                "cs_off": cs_off, "cs_on": cs_on, "known": known,
            })
    pair_rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    print(f"  {'id':>4} {'pair':>6}  {'off μ':>9}  {'on μ':>9}  {'Δ':>9}  "
          f"{'cs_off':>7}  {'cs_on':>7}  {'V@0.001':>9}  {'V@0.01':>9}  {'known':<32}")
    for r in pair_rows[:20]:
        v001_off = r["m_off"] * 0.001
        v001_on = r["m_on"] * 0.001
        v01_off = r["m_off"] * 0.01
        v01_on = r["m_on"] * 0.01
        v001 = f"{v001_off:4.1f}/{v001_on:4.1f}"
        v01 = f"{v01_off:4.0f}/{v01_on:4.0f}"
        tag = ""
        if 11.5 <= v001_off <= 13.0 and 13.4 <= v001_on <= 14.8:
            tag = " ← V@0.001 fits!"
        elif 11.5 <= v01_off <= 13.0 and 13.4 <= v01_on <= 14.8:
            tag = " ← V@0.01 fits!"
        print(f"  {r['id']:>4} D{r['hi']}:D{r['lo']:<2}  {r['m_off']:9.1f}  {r['m_on']:9.1f}  "
              f"{r['delta']:+9.1f}  {r['cs_off']:7.1f}  {r['cs_on']:7.1f}  "
              f"{v001:>9}  {v01:>9}  {r['known']:<24}{tag}")

    # -------------------------- High-beam load test ---------------------------
    print("\n## Step 6 — high-beam toggle load test (engine OFF)\n")
    print("  Session: 2026-06-24-front-wheel-decay-mark.  6 toggles, ~10 s spacing.")
    print("  For each top candidate: mean over [-2, -0.5] s pre-toggle vs [+0.5, +2.5] s post-toggle.\n")
    beam_session = "2026-06-24-front-wheel-decay-mark"
    beam_events = parse_events(REPO_ROOT / "logs" / beam_session / "events.csv")
    beam_frames, _ = parse_log(REPO_ROOT / "logs" / beam_session / "capture.log",
                                set(ALWAYS_ON_IDS))
    beam_marks = [r["t"] for r in beam_events if r["key"] == "beam"]
    if not beam_marks:
        print("  (no beam marks found)")
    else:
        print(f"  {'id':>4} {'b':>3}  " +
              "  ".join(f"toggle{i+1:>2}" for i in range(len(beam_marks))) +
              f"  {'mean Δ':>7}  {'known':<28}")
        for r in (top5 if top5 else rows[:5]):
            k = (r["id"], r["byte"])
            deltas = []
            cells = []
            for t_beam in beam_marks:
                pre = window(beam_frames[k[0]], t_beam - 2.0, t_beam - 0.5)
                post = window(beam_frames[k[0]], t_beam + 0.5, t_beam + 2.5)
                if not pre or not post:
                    cells.append("    -")
                    continue
                mu_pre = stats.fmean([d[k[1]] for _, d in pre])
                mu_post = stats.fmean([d[k[1]] for _, d in post])
                d = mu_post - mu_pre
                deltas.append(d)
                cells.append(f"{d:+7.2f}")
            mean_d = stats.fmean(deltas) if deltas else float("nan")
            print(f"  {r['id']:>4} D{r['byte']:<2}  " + "  ".join(cells) +
                  f"  {mean_d:+7.2f}  {r['known']:<28}")
        print()
        print("  Reading: a true battery-voltage byte should show a CONSISTENT NEGATIVE Δ on")
        print("  the 'beam on' toggles and a positive Δ on 'beam off' toggles (high-beam load")
        print("  ≈ 50 W = ~4 A → ~0.1-0.3 V dip → 1-3 LSB at 0.1 V/LSB).  We don't know toggle")
        print("  polarity from the marks, so look for any consistent ±2 LSB pattern.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
