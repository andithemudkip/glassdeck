#!/usr/bin/env python3
"""payload_diff.py — classify CAN payload bytes by behaviour across windows.

For each (arbitration_id, byte_index) pair across one or more capture
sessions, partitions frames into engine-off / steady-idle / post-kill
windows (using event marks from each session's events.csv), computes
per-window summary statistics, and emits classification tags:

  STATIC, LOW-CARD, COUNTER, CRC-LIKE, ENGINE-STATE, COOLANT-TEMP-CAND,
  IDLE-RPM-CAND, UNKNOWN

Also emits a bit-level engine-state map showing which individual bits
flip mode between engine-off and steady-idle windows.

Hard-coded for the three engine-idle baseline runs of 2026-06-17 — the
analysis is calibrated against having exactly three thermal points
across Run 1 (cold), Run 2 (partial warm), Run 3 (operating temp).

Usage:
    python scripts/payload_diff.py            # full analysis, all 3 runs
    python scripts/payload_diff.py --csv      # also emit machine-readable CSV
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

RUNS = [
    ("run1", "logs/2026-06-17-engine-idle-run-1", "cold"),
    ("run2", "logs/2026-06-17-engine-idle-run-2", "partial-warm"),
    ("run3", "logs/2026-06-17-engine-idle-run-3", "operating-temp"),
]


def parse_events(path: Path) -> dict:
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            t = dt.datetime.fromisoformat(r["timestamp_iso"]).timestamp()
            rows.append((t, r["key"], r["label"]))
    gm = [t for t, _, l in rows if l == "generic mark"]
    starter = next((t for t, _, l in rows if l == "starter button"), None)
    kill = next((t for t, _, l in rows if l == "kill switch"), None)
    return {
        "key_on": gm[0] if gm else None,
        "starter": starter,
        "idle_settled": gm[1] if len(gm) >= 2 else (starter + 1.0 if starter else None),
        "kill": kill,
    }


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


def in_window(frames, t0, t1):
    return [(ts, arb, b) for ts, arb, b in frames if t0 <= ts < t1]


def is_counter(seq: list[int]):
    """Detect a counter byte: ≥80% of diffs are a single small step."""
    if len(seq) < 20:
        return None
    for step in (1, 2, 4, 8, 16):
        diffs = [(seq[i + 1] - seq[i]) % 256 for i in range(len(seq) - 1)]
        hits = sum(1 for d in diffs if d == step)
        if hits / len(diffs) >= 0.80:
            return step
    return None


def safe_stdev(seq):
    return statistics.stdev(seq) if len(seq) > 1 else 0.0


def safe_median(seq):
    return statistics.median(seq) if seq else None


def safe_mean(seq):
    return statistics.mean(seq) if seq else None


def classify(idle_seqs, off_seqs, decay_seqs):
    """Return (tags_list, detail_dict)."""
    all_vals = sum(idle_seqs + off_seqs + decay_seqs, [])
    if not all_vals:
        return ["NODATA"], {}

    distinct_all = set(all_vals)
    tags = []
    detail = {}

    # STATIC
    if len(distinct_all) == 1:
        v = next(iter(distinct_all))
        detail["value"] = f"0x{v:02X}"
        return ["STATIC"], detail

    # COUNTER (need agreement across runs)
    counter_steps = []
    for seq in idle_seqs:
        step = is_counter(seq)
        if step:
            counter_steps.append(step)
    if len(counter_steps) >= 2 and len(set(counter_steps)) == 1:
        tags.append(f"COUNTER(step={counter_steps[0]})")

    # CRC-LIKE: high entropy in idle, no counter found
    max_distinct_idle = max((len(set(s)) for s in idle_seqs if s), default=0)
    if max_distinct_idle >= 128 and not any(t.startswith("COUNTER") for t in tags):
        tags.append("CRC-LIKE")

    # LOW-CARD (only if not COUNTER/CRC)
    if not tags and len(distinct_all) <= 16:
        tags.append(f"LOW-CARD({len(distinct_all)})")

    # ENGINE-STATE: in all three runs, off-set and idle-set are mostly disjoint
    state_flips = 0
    for off_s, idle_s in zip(off_seqs, idle_seqs):
        if not off_s or not idle_s:
            continue
        off_set = set(off_s)
        idle_set = set(idle_s)
        off_in_idle = sum(1 for v in off_s if v in idle_set) / len(off_s)
        idle_in_off = sum(1 for v in idle_s if v in off_set) / len(idle_s)
        if off_in_idle < 0.25 and idle_in_off < 0.25:
            state_flips += 1
    if state_flips == 3:
        tags.append("ENGINE-STATE")
        off_mode = Counter(sum(off_seqs, [])).most_common(1)[0]
        idle_mode = Counter(sum(idle_seqs, [])).most_common(1)[0]
        detail["off_mode"] = f"0x{off_mode[0]:02X} ({off_mode[1]}x)"
        detail["idle_mode"] = f"0x{idle_mode[0]:02X} ({idle_mode[1]}x)"

    # COOLANT-TEMP-CAND: idle-median monotonic non-strict, strict overall change
    if all(idle_seqs):
        medians = [safe_median(s) for s in idle_seqs]
        rising = all(medians[i] <= medians[i + 1] for i in range(len(medians) - 1))
        spread = max(medians) - min(medians)
        within_stdev = statistics.mean([safe_stdev(s) for s in idle_seqs])
        if rising and spread >= 1 and medians[0] < medians[-1] and spread >= max(1, within_stdev):
            tags.append("COOLANT-TEMP-CAND")
            detail["per_run_median"] = medians

    # IDLE-RPM-CAND: ENGINE-STATE + low engine-on stdev + nonzero idle mean
    if "ENGINE-STATE" in tags:
        idle_stdevs = [safe_stdev(s) for s in idle_seqs]
        idle_means = [safe_mean(s) for s in idle_seqs]
        if all(s <= 4.0 for s in idle_stdevs) and all((m or 0) > 0 for m in idle_means):
            tags.append("IDLE-RPM-CAND")
            detail["idle_means"] = [round(m, 1) for m in idle_means]

    if not tags:
        tags.append("UNKNOWN")
    return tags, detail


def bit_flip_map(idle_seqs, off_seqs):
    """For each of 8 bits in a byte, return list of (bit_idx, off_mode, idle_mode)
    where the dominant bit value flips between off and idle in all three runs."""
    flips = []
    for bit in range(8):
        flipped_runs = 0
        off_modes = []
        idle_modes = []
        for off_s, idle_s in zip(off_seqs, idle_seqs):
            if not off_s or not idle_s:
                continue
            off_bits = [(v >> bit) & 1 for v in off_s]
            idle_bits = [(v >> bit) & 1 for v in idle_s]
            off_mode = 1 if sum(off_bits) > len(off_bits) / 2 else 0
            idle_mode = 1 if sum(idle_bits) > len(idle_bits) / 2 else 0
            # Also require the modes to be near-pure (≥90% one way)
            off_pure = max(off_bits.count(0), off_bits.count(1)) / len(off_bits)
            idle_pure = max(idle_bits.count(0), idle_bits.count(1)) / len(idle_bits)
            if off_mode != idle_mode and off_pure > 0.90 and idle_pure > 0.90:
                flipped_runs += 1
                off_modes.append(off_mode)
                idle_modes.append(idle_mode)
        if flipped_runs == 3 and len(set(off_modes)) == 1 and len(set(idle_modes)) == 1:
            flips.append((bit, off_modes[0], idle_modes[0]))
    return flips


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--csv", action="store_true", help="Also emit a machine-readable CSV")
    args = p.parse_args()

    # data[run][arb][byte_idx] = {"off": [...], "idle": [...], "decay": [...]}
    data: dict = {}
    summaries = []
    for name, path, thermal in RUNS:
        events = parse_events(REPO_ROOT / path / "events.csv")
        frames = parse_log(REPO_ROOT / path / "capture.log")
        off = in_window(frames, events["key_on"], events["starter"])
        idle = in_window(frames, events["idle_settled"], events["kill"])
        decay = in_window(frames, events["kill"], float("inf"))
        summaries.append((name, thermal, len(off), len(idle), len(decay)))
        run_data: dict = defaultdict(lambda: defaultdict(lambda: {"off": [], "idle": [], "decay": []}))
        for win_label, wf in (("off", off), ("idle", idle), ("decay", decay)):
            for _ts, arb, b in wf:
                for i in range(8):
                    run_data[arb][i][win_label].append(b[i])
        data[name] = run_data

    print("# Window frame counts per run")
    print(f"{'run':>5}  {'thermal':>15}  {'off':>6}  {'idle':>6}  {'decay':>6}")
    for name, thermal, no, ni, nd in summaries:
        print(f"{name:>5}  {thermal:>15}  {no:>6}  {ni:>6}  {nd:>6}")
    print()

    all_ids = sorted(set().union(*[set(d.keys()) for d in data.values()]))
    run_names = [r[0] for r in RUNS]

    rows = []
    print("# Per-byte classification")
    print(f"{'ID':>4}  {'B':>1}  {'tags':<55}  detail")
    for arb in all_ids:
        for bidx in range(8):
            idle_seqs = [data[r][arb][bidx]["idle"] for r in run_names]
            off_seqs = [data[r][arb][bidx]["off"] for r in run_names]
            decay_seqs = [data[r][arb][bidx]["decay"] for r in run_names]
            tags, detail = classify(idle_seqs, off_seqs, decay_seqs)
            tags_s = ", ".join(tags)
            detail_s = "  ".join(f"{k}={v}" for k, v in detail.items())
            print(f"{arb:>4}  {bidx:>1}  {tags_s:<55}  {detail_s}")
            rows.append({"id": arb, "byte": bidx, "tags": tags_s, "detail": detail_s})
        print()

    # Bit-level engine-state map
    print("# Engine-state bit map (bits that flip mode engine-off vs idle in all 3 runs)")
    print(f"{'ID':>4}  {'B':>1}  bit  off→idle")
    for arb in all_ids:
        for bidx in range(8):
            idle_seqs = [data[r][arb][bidx]["idle"] for r in run_names]
            off_seqs = [data[r][arb][bidx]["off"] for r in run_names]
            flips = bit_flip_map(idle_seqs, off_seqs)
            for bit, om, im in flips:
                print(f"{arb:>4}  {bidx:>1}  {bit:>3}  {om}→{im}")
    print()

    # Detailed printouts for interesting bytes
    print("# Per-run idle median/stdev for COOLANT-TEMP-CAND bytes")
    for row in rows:
        if "COOLANT-TEMP-CAND" not in row["tags"]:
            continue
        arb, bidx = row["id"], row["byte"]
        meds = [safe_median(data[r][arb][bidx]["idle"]) for r in run_names]
        stds = [round(safe_stdev(data[r][arb][bidx]["idle"]), 2) for r in run_names]
        means = [round(safe_mean(data[r][arb][bidx]["idle"]) or 0, 2) for r in run_names]
        print(f"  {arb}[{bidx}]: medians={meds}  means={means}  stdevs={stds}")
    print()

    print("# Per-run idle mean/stdev for IDLE-RPM-CAND bytes (engine-on means ≠ engine-off)")
    for row in rows:
        if "IDLE-RPM-CAND" not in row["tags"]:
            continue
        arb, bidx = row["id"], row["byte"]
        idle_means = [round(safe_mean(data[r][arb][bidx]["idle"]) or 0, 2) for r in run_names]
        idle_stds = [round(safe_stdev(data[r][arb][bidx]["idle"]), 2) for r in run_names]
        off_means = [round(safe_mean(data[r][arb][bidx]["off"]) or 0, 2) for r in run_names]
        print(f"  {arb}[{bidx}]: idle_means={idle_means}  idle_stds={idle_stds}  off_means={off_means}")
    print()

    if args.csv:
        with (REPO_ROOT / "payload_classification.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["id", "byte", "tags", "detail"])
            w.writeheader()
            for row in rows:
                w.writerow(row)
        print(f"wrote {REPO_ROOT / 'payload_classification.csv'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
