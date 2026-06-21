#!/usr/bin/env python3
"""cold_boot_emergence.py — module boot order, one-shot IDs, cadence ramp.

Three passes against the 4 captures that contain a key-off → key-on transition
(the cold-boot capture plus the three engine-idle baselines' key-on preludes):

  1. First-seen offsets per ID in the 1000 ms after key_on. Cross-capture
     stability check — if any ID's first-seen spread exceeds one of its steady-
     state broadcast periods, the ordering is non-deterministic there.
  2. One-shot ID inventory — any ID broadcast in the boot window but absent
     from [[always-on-broadcast-ids]]'s steady-state set of 11.
  3. Cadence ramp — for each always-on ID, the deltas between its first 10
     frames, compared to its steady-state period.
  4. Cross-correlate boot ordering with the Fast/Slow decay grouping.

Reads:
  logs/2026-06-17-key-on-cold-boot/{capture.log,events.csv}
  logs/2026-06-17-engine-idle-run-{1,2,3}/{capture.log,events.csv}

Output: stdout, four sections.
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

CAPTURES = [
    ("cold-boot", "logs/2026-06-17-key-on-cold-boot"),
    ("run1",      "logs/2026-06-17-engine-idle-run-1"),
    ("run2",      "logs/2026-06-17-engine-idle-run-2"),
    ("run3",      "logs/2026-06-17-engine-idle-run-3"),
]

ALWAYS_ON_11 = ["120", "121", "129", "12A", "12D", "12E", "450", "540", "541", "5A0", "5B0"]
FAST_GROUP = {"120", "121", "129", "540", "5B0"}
SLOW_GROUP = {"12A", "12D", "12E", "450", "541", "5A0"}

# Per-ID steady-state periods in ms, sourced from inventory_ids and findings.
STEADY_PERIOD_MS = {
    "120": 10, "12D": 10,            # 10 ms cohort
    "121": 20, "129": 20, "12A": 20, "12E": 20, "541": 20,  # 20 ms cohort
    "540": 100,  # 100 ms cohort
    "450": 50, "5A0": 100, "5B0": 100,  # 50/100 ms cohort
}

BOOT_WINDOW_S = 1.000


def parse_events(path: Path):
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            rows.append((t, r["key"], r["label"]))
    gm = [t for t, _, l in rows if l == "generic mark"]
    return {"key_on": gm[0] if gm else None}


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


def load(name, rel):
    path = REPO_ROOT / rel
    events = parse_events(path / "events.csv")
    frames = parse_log(path / "capture.log")
    return events, frames


# ---------- Analysis 1: first-seen offsets ----------

def analysis_first_seen():
    print("=" * 78)
    print("# Analysis 1 — first-seen offsets in the 1000 ms after key_on")
    print("=" * 78)
    print()

    # caps[capture_name][arb] = first-seen offset in ms (or None if not seen)
    caps = {}
    for name, rel in CAPTURES:
        events, frames = load(name, rel)
        t0 = events["key_on"]
        if t0 is None:
            continue
        firsts = {}
        for ts, arb, _ in frames:
            if ts < t0:
                continue
            if ts > t0 + BOOT_WINDOW_S:
                continue
            if arb not in firsts:
                firsts[arb] = (ts - t0) * 1000.0
        caps[name] = firsts

    # All IDs seen in any boot window
    all_ids = sorted({arb for f in caps.values() for arb in f})
    print(f"IDs seen in any 1000 ms boot window across the 4 captures: {all_ids}")
    print()

    # Per-ID first-seen offset per capture
    print(f"{'ID':>4}  " + "  ".join(f"{name:>10}" for name, _ in CAPTURES) +
          "  " + f"{'median (ms)':>12}  {'spread':>8}  {'steady T':>9}  stability")
    summary_rows = []
    for arb in all_ids:
        cells = []
        offsets = []
        for name, _ in CAPTURES:
            v = caps.get(name, {}).get(arb)
            if v is None:
                cells.append("—")
            else:
                cells.append(f"{v:>8.1f}")
                offsets.append(v)
        median = statistics.median(offsets) if offsets else None
        spread = (max(offsets) - min(offsets)) if len(offsets) > 1 else 0.0
        T = STEADY_PERIOD_MS.get(arb)
        if median is None:
            stability = "—"
        elif T is None:
            stability = "no steady T known"
        elif spread <= T:
            stability = f"stable (≤ steady T {T}ms)"
        else:
            stability = f"NOISY (spread {spread:.0f}ms > steady T {T}ms)"
        cells_s = "  ".join(f"{c:>10}" for c in cells)
        med_s = f"{median:.1f}" if median is not None else "—"
        T_s = f"{T} ms" if T is not None else "—"
        print(f"  {arb:>4}  {cells_s}  {med_s:>12}  {spread:>6.1f}ms  {T_s:>9}  {stability}")
        if median is not None:
            summary_rows.append((arb, median))
    print()

    # Boot order sorted by median first-seen
    print("## Boot order (sorted by median first-seen offset)")
    print()
    summary_rows.sort(key=lambda r: r[1])
    for i, (arb, med) in enumerate(summary_rows):
        group = "Fast" if arb in FAST_GROUP else ("Slow" if arb in SLOW_GROUP else "?")
        T = STEADY_PERIOD_MS.get(arb, "?")
        print(f"  {i+1:>2}.  {arb}  median {med:>6.1f} ms after key_on   group={group:<4}  steady T={T} ms")
    print()


# ---------- Analysis 2: one-shot IDs ----------

def analysis_one_shots():
    print("=" * 78)
    print("# Analysis 2 — one-shot IDs (boot window only, not in the always-on 11)")
    print("=" * 78)
    print()

    # An ID is "one-shot" if it appears in any boot window but NOT in the always-on-11 set,
    # OR if it appears in the boot window but does not appear in steady state of that capture.
    novel_ids_per_capture = {}
    for name, rel in CAPTURES:
        events, frames = load(name, rel)
        t0 = events["key_on"]
        if t0 is None:
            continue
        boot_ids = set()
        steady_ids = set()
        for ts, arb, _ in frames:
            if t0 <= ts < t0 + BOOT_WINDOW_S:
                boot_ids.add(arb)
            elif ts >= t0 + 5.0:  # steady-state surrogate: anything from +5s onward
                steady_ids.add(arb)
        novel = boot_ids - set(ALWAYS_ON_11)
        boot_only = boot_ids - steady_ids
        novel_ids_per_capture[name] = (boot_ids, novel, boot_only)

    print("Per-capture inventory:")
    for name, (boot_ids, novel, boot_only) in novel_ids_per_capture.items():
        print(f"  {name}:")
        print(f"    IDs in boot window      : {sorted(boot_ids)}")
        print(f"    Not in always-on 11     : {sorted(novel)}")
        print(f"    In boot but not steady  : {sorted(boot_only)}")
    print()

    # Union across captures
    all_novel = set().union(*(n for _, (_, n, _) in novel_ids_per_capture.items()))
    all_boot_only = set().union(*(b for _, (_, _, b) in novel_ids_per_capture.items()))
    print(f"Union novel (in boot, not in always-on 11): {sorted(all_novel)}")
    print(f"Union boot-only (in boot, not steady):      {sorted(all_boot_only)}")
    print()
    if not all_novel and not all_boot_only:
        print("VERDICT: No one-shot IDs. The 11 always-on broadcast IDs are the complete bus inventory.")
    print()


# ---------- Analysis 3: cadence ramp ----------

def analysis_cadence_ramp():
    print("=" * 78)
    print("# Analysis 3 — cadence ramp on first 10 frames per always-on ID")
    print("=" * 78)
    print()
    print("Deltas between successive first 10 frames of each always-on ID, per capture,")
    print("compared to steady-state period.")
    print()

    for arb in ALWAYS_ON_11:
        T = STEADY_PERIOD_MS.get(arb)
        print(f"## {arb}  (steady T = {T} ms)")
        for name, rel in CAPTURES:
            events, frames = load(name, rel)
            t0 = events["key_on"]
            if t0 is None:
                continue
            id_frames = [ts for ts, a, _ in frames if a == arb and ts >= t0][:10]
            if len(id_frames) < 2:
                print(f"  {name:<10}  fewer than 2 frames in capture window")
                continue
            first_offset_ms = (id_frames[0] - t0) * 1000.0
            deltas = [(id_frames[i+1] - id_frames[i]) * 1000.0 for i in range(len(id_frames) - 1)]
            deltas_s = " ".join(f"{d:>6.1f}" for d in deltas)
            avg = statistics.mean(deltas)
            ramp = "—"
            if T is not None:
                if avg < T * 0.7:
                    ramp = "FAST (backlog flush?)"
                elif avg > T * 1.3:
                    ramp = "SLOW (startup lag)"
                else:
                    ramp = "steady"
            print(f"  {name:<10}  first@{first_offset_ms:>6.1f}ms  Δ(ms)={deltas_s}   avg={avg:>5.1f}  {ramp}")
        print()


# ---------- Analysis 4: Fast/Slow group correlation with boot order ----------

def analysis_group_correlation():
    print("=" * 78)
    print("# Analysis 4 — boot-order vs Fast/Slow decay-group correlation")
    print("=" * 78)
    print()
    # Take medians from analysis 1's data
    cap_firsts = {}
    for name, rel in CAPTURES:
        events, frames = load(name, rel)
        t0 = events["key_on"]
        if t0 is None:
            continue
        firsts = {}
        for ts, arb, _ in frames:
            if t0 <= ts < t0 + BOOT_WINDOW_S and arb not in firsts:
                firsts[arb] = (ts - t0) * 1000.0
        cap_firsts[name] = firsts

    medians = {}
    for arb in ALWAYS_ON_11:
        offs = [cap_firsts[name][arb] for name in cap_firsts if arb in cap_firsts[name]]
        if offs:
            medians[arb] = statistics.median(offs)

    fast_median = statistics.median([medians[a] for a in FAST_GROUP if a in medians])
    slow_median = statistics.median([medians[a] for a in SLOW_GROUP if a in medians])
    print(f"Fast-group median first-seen: {fast_median:.1f} ms")
    print(f"Slow-group median first-seen: {slow_median:.1f} ms")
    print()

    # Per-group breakdown
    print(f"{'group':<6} {'ID':>4} {'median first-seen':>20}")
    for grp, members in (("Fast", FAST_GROUP), ("Slow", SLOW_GROUP)):
        for arb in sorted(members):
            m = medians.get(arb)
            m_s = f"{m:.1f} ms" if m is not None else "—"
            print(f"{grp:<6} {arb:>4} {m_s:>20}")
    print()

    if abs(fast_median - slow_median) < 50:
        print(f"VERDICT: Fast and Slow groups boot within ~50 ms of each other ({abs(fast_median-slow_median):.0f} ms apart).")
        print("         The decay grouping does not correspond to a power-up sequence delay.")
    else:
        print(f"VERDICT: {'Fast' if fast_median < slow_median else 'Slow'} group leads by "
              f"{abs(fast_median - slow_median):.0f} ms — consistent with that group's module booting first.")
    print()


def main() -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    analysis_first_seen()
    analysis_one_shots()
    analysis_cadence_ramp()
    analysis_group_correlation()
    return 0


if __name__ == "__main__":
    sys.exit(main())
