#!/usr/bin/env python3
"""verify_signals.py — schema self-test against a known-good idle capture.

Walks logs/2026-06-17-engine-idle-run-3/capture.log (operating-temp idle,
bike on side stand, key on, kill=RUN, gear=N), decodes every confirmed
signal in docs/signals/signals.yaml, and asserts each falls within the
range documented in its finding. Exits 0 on PASS, 1 on FAIL.

This is the load-bearing "schema not drifted" check called for by
ADR 0005 §Verification.

Usage:
    python scripts/verify_signals.py
    python scripts/verify_signals.py --session logs/2026-06-17-engine-idle-run-1
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from signals import Signal, by_id, load_signals  # type: ignore  # noqa: E402

LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")

# Expected ranges per confirmed signal at idle-run-3 (operating-temp idle,
# bike on side stand, kill switch RUN, gear N). Provisional/partial signals
# are decoded and reported but not asserted.
EXPECTATIONS = {
    "rpm":              {"min_median": 1500, "max_median": 1900, "min_obs": 1000, "max_obs": 2500},
    "throttle_position": {"min_median": 0,    "max_median": 5,    "min_obs": 0,    "max_obs": 30},
    "coolant_temp":     {"min_median": 70,   "max_median": 95,   "min_obs": 60,   "max_obs": 100},
    "kill_switch":      {"only_value": "RUN"},
    "side_stand":       {"only_value": "DOWN"},
    "gear_position":    {"only_value": "N"},
}


def parse_log(path: Path, t0: float | None = None, t1: float | None = None):
    for line in path.open():
        m = LINE_RE.match(line)
        if not m:
            continue
        ts = float(m.group(1))
        if t0 is not None and ts < t0:
            continue
        if t1 is not None and ts >= t1:
            continue
        arb = int(m.group(2), 16)
        hex_data = m.group(3)
        if len(hex_data) % 2 or len(hex_data) != 16:
            continue
        yield ts, arb, bytes.fromhex(hex_data)


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
        "idle_settled": gm[1] if len(gm) >= 2 else (starter + 1.0 if starter else None),
        "kill": kill,
    }


def collect_decoded(frames, signals: list[Signal]) -> dict[str, list]:
    index = by_id(signals)
    out: dict[str, list] = {s.name: [] for s in signals}
    for _ts, arb, data in frames:
        for sig in index.get(arb, ()):
            value = sig.extract(arb, data)
            if value is not None:
                out[sig.name].append(value)
    return out


def check(sig: Signal, samples: list, expect: dict) -> tuple[bool, str]:
    if not samples:
        return False, f"no frames decoded (expected {sig.location_str()})"
    if "only_value" in expect:
        counts = Counter(samples)
        dominant, n = counts.most_common(1)[0]
        purity = n / len(samples)
        if dominant != expect["only_value"]:
            return False, f"dominant {dominant!r} ≠ expected {expect['only_value']!r} (purity {purity:.2%})"
        if purity < 0.95:
            return False, f"dominant {dominant!r} only at {purity:.2%} purity (n={len(samples)})"
        return True, f"{dominant} ×{n} ({purity:.2%})"
    numeric = [s for s in samples if isinstance(s, (int, float))]
    if not numeric:
        return False, "no numeric samples"
    med = statistics.median(numeric)
    lo, hi = min(numeric), max(numeric)
    if not (expect["min_median"] <= med <= expect["max_median"]):
        return False, f"median {med:.1f} outside [{expect['min_median']}, {expect['max_median']}]"
    if lo < expect["min_obs"] or hi > expect["max_obs"]:
        return False, f"observed range [{lo:.1f}, {hi:.1f}] outside [{expect['min_obs']}, {expect['max_obs']}]"
    return True, f"median {med:.1f}, range [{lo:.1f}, {hi:.1f}], n={len(numeric)}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="logs/2026-06-17-engine-idle-run-3",
                    help="Path to a session directory (must contain capture.log).")
    args = ap.parse_args()

    session = REPO_ROOT / args.session
    log_path = session / "capture.log"
    events_path = session / "events.csv"
    if not log_path.is_file():
        print(f"FAIL: {log_path} not found", file=sys.stderr)
        return 2

    signals = load_signals()
    events = parse_events(events_path) if events_path.is_file() else {}
    t0, t1 = events.get("idle_settled"), events.get("kill")
    window_desc = (
        f"idle_settled → kill ({t1 - t0:.0f}s)" if t0 and t1 else "(full capture, no idle window)"
    )
    print(f"# Verifying {len(signals)} signals against {session.name} — {window_desc}")
    print()

    decoded = collect_decoded(parse_log(log_path, t0, t1), signals)

    failures: list[str] = []
    for sig in signals:
        samples = decoded[sig.name]
        if sig.name in EXPECTATIONS:
            ok, detail = check(sig, samples, EXPECTATIONS[sig.name])
            tag = "PASS" if ok else "FAIL"
            print(f"  [{tag}] {sig.name:24s} {sig.status:11s} {detail}")
            if not ok:
                failures.append(sig.name)
        else:
            if samples and isinstance(samples[0], (int, float)):
                lo, hi = min(samples), max(samples)
                print(f"  [obs ] {sig.name:24s} {sig.status:11s} range [{lo}, {hi}], n={len(samples)}")
            else:
                counts = Counter(samples)
                top = ", ".join(f"{v}×{n}" for v, n in counts.most_common(3))
                print(f"  [obs ] {sig.name:24s} {sig.status:11s} {top}")

    print()
    if failures:
        print(f"FAIL: {len(failures)} signal(s) failed: {', '.join(failures)}")
        return 1
    print(f"PASS: all confirmed signals within expected ranges")
    return 0


if __name__ == "__main__":
    sys.exit(main())
