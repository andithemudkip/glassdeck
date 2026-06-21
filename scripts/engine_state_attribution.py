#!/usr/bin/env python3
"""engine_state_attribution.py — attribute the unattributed engine-state bits.

Three desk-only analyses against the idle-baseline-x3 corpus + cold-boot:

  1. Post-kill decay shape per flagged bit — classifies as "data signal"
     (bit reverts to engine-off mode before host ID goes silent) vs
     "stuck-then-silent" (bit holds idle mode until the broadcast stops, which
     conflates power-rail-derivative and latched-startup-flag — distinguishable
     only with more capture coverage).
  2. Fan-on hunt across Run 3 — surfaces any bit whose dominant value changes
     within Run 3's idle window (early vs mid vs late) and was STATIC across
     all of Run 1 + Run 2 + the cold-boot capture.
  3. `540` D3 nibble inventory — decomposes the four LOW-CARD(4) values into
     (bit 0, bit 4, other) to check whether side-stand + engine-state fully
     account for D3 at idle.

Reads:
  logs/2026-06-17-engine-idle-run-{1,2,3}/{capture.log,events.csv}
  logs/2026-06-17-key-on-cold-boot/{capture.log,events.csv}

Output: stdout. Three sections, one per analysis.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
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

COLD_BOOT_PATH = "logs/2026-06-17-key-on-cold-boot"

FLAGGED_BITS = [
    ("121", 1, 5, 1, 0),
    ("121", 1, 7, 1, 0),
    ("121", 5, 3, 0, 1),
    ("540", 2, 6, 1, 0),
    ("540", 3, 4, 1, 0),
]

DECAY_SUBWINDOWS = [
    ("decay-0",   0.000, 0.500),
    ("decay-1",   0.500, 1.000),
    ("decay-2",   1.000, 2.000),
    ("decay-3",   2.000, 5.000),
    ("decay-4",   5.000, float("inf")),
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


def dominant_bit(bits: list[int]) -> tuple[int | None, float, int]:
    """Return (dominant_value, purity, sample_count)."""
    if not bits:
        return (None, 0.0, 0)
    c0 = bits.count(0)
    c1 = bits.count(1)
    n = len(bits)
    if c1 >= c0:
        return (1, c1 / n, n)
    return (0, c0 / n, n)


def bits_for(frames, arb, byte_idx, bit_idx):
    return [(b[byte_idx] >> bit_idx) & 1 for ts, a, b in frames if a == arb]


def load_run(path: Path):
    events = parse_events(path / "events.csv")
    frames = parse_log(path / "capture.log")
    return events, frames


# ---------- Analysis 1: post-kill decay shape ----------

def analysis_decay_shape():
    print("=" * 78)
    print("# Analysis 1 — post-kill decay shape of the 5 flagged bits")
    print("=" * 78)
    print()
    print("Each cell: dominant_value (purity, n_frames). '—' = no frames in this window.")
    print("ENGINE-OFF mode and IDLE mode reproduced from payload_diff for reference.")
    print()

    runs_loaded = []
    for name, path, thermal in RUNS:
        events, frames = load_run(REPO_ROOT / path)
        runs_loaded.append((name, thermal, events, frames))

    for arb, byte_idx, bit_idx, off_mode, idle_mode in FLAGGED_BITS:
        print(f"## {arb} D{byte_idx} bit {bit_idx}    (engine-off mode = {off_mode}, idle mode = {idle_mode})")
        header_windows = ["off", "idle"] + [w[0] for w in DECAY_SUBWINDOWS]
        print(f"  {'run':<6} " + " ".join(f"{w:>14}" for w in header_windows))
        for name, thermal, events, frames in runs_loaded:
            off_frames  = in_window(frames, events["key_on"], events["starter"])
            idle_frames = in_window(frames, events["idle_settled"], events["kill"])
            kill = events["kill"]

            cells = []
            for win_frames in (off_frames, idle_frames):
                bits = bits_for(win_frames, arb, byte_idx, bit_idx)
                dv, pur, n = dominant_bit(bits)
                cells.append(("—" if dv is None else f"{dv}({pur:.2f},{n})"))
            for label, lo, hi in DECAY_SUBWINDOWS:
                sub = in_window(frames, kill + lo, kill + hi)
                bits = bits_for(sub, arb, byte_idx, bit_idx)
                dv, pur, n = dominant_bit(bits)
                cells.append("—" if dv is None else f"{dv}({pur:.2f},{n})")
            print(f"  {name:<6} " + " ".join(f"{c:>14}" for c in cells))
        print()

    # Classification — for each bit, take the first decay window with ≥10 frames
    # in any run and see whether its dominant value matches engine-off mode.
    print("## Classification")
    print()
    print("  'reverts'      — first non-empty decay window's dominant value matches ENGINE-OFF mode.")
    print("  'holds-idle'   — first non-empty decay window's dominant value matches IDLE mode.")
    print("                   (Power-rail-derivative vs latched-flag indistinguishable without longer coverage.)")
    print("  'silent'       — host ID stopped broadcasting before any decay frame arrived.")
    print()
    print(f"  {'bit':<14} {'first_window':>14}  {'verdict':<14}  notes")
    for arb, byte_idx, bit_idx, off_mode, idle_mode in FLAGGED_BITS:
        # Aggregate decay across all runs into the same sub-window structure.
        agg = {label: [] for label, _, _ in DECAY_SUBWINDOWS}
        for name, thermal, events, frames in runs_loaded:
            kill = events["kill"]
            for label, lo, hi in DECAY_SUBWINDOWS:
                sub = in_window(frames, kill + lo, kill + hi)
                agg[label].extend(bits_for(sub, arb, byte_idx, bit_idx))
        first_label = None
        first_dv = None
        first_pur = 0.0
        for label, _, _ in DECAY_SUBWINDOWS:
            if len(agg[label]) >= 10:
                first_label = label
                first_dv, first_pur, _ = dominant_bit(agg[label])
                break
        if first_label is None:
            verdict = "silent"
            notes = "no decay window had ≥10 frames across all 3 runs combined"
        elif first_dv == off_mode and first_pur >= 0.80:
            verdict = "reverts"
            notes = f"bit returned to engine-off mode in {first_label}"
        elif first_dv == idle_mode and first_pur >= 0.80:
            verdict = "holds-idle"
            notes = f"bit stayed at idle mode in {first_label}"
        else:
            verdict = "mixed"
            notes = f"first decay window {first_label} dominant={first_dv} pur={first_pur:.2f} — neither pure off nor pure idle"
        bitname = f"{arb} D{byte_idx} b{bit_idx}"
        fl = first_label or "—"
        print(f"  {bitname:<14} {fl:>14}  {verdict:<14}  {notes}")
    print()


# ---------- Analysis 2: Run-3 fan-on hunt ----------

def analysis_fan_hunt():
    print("=" * 78)
    print("# Analysis 2 — fan-on hunt in Run 3 (late idle window)")
    print("=" * 78)
    print()
    print("Strategy:")
    print("  For every (ID, byte, bit), require:")
    print("    (a) STATIC across all of Run-1-idle + Run-2-idle + cold-boot (purity ≥0.99 for one value).")
    print("    (b) In Run 3, the dominant value in idle-r3-late differs from idle-r3-early,")
    print("        each at ≥0.95 purity, with ≥30 frames per sub-window.")
    print("  Surfaced bits are candidates for fan-on, thermostat-open, or any late-thermal-stage signal.")
    print()

    # Load Run 1, Run 2, Run 3, cold-boot.
    runs = {}
    for name, path, thermal in RUNS:
        events, frames = load_run(REPO_ROOT / path)
        runs[name] = (events, frames)

    cb_events = parse_events(REPO_ROOT / COLD_BOOT_PATH / "events.csv")
    cb_frames = parse_log(REPO_ROOT / COLD_BOOT_PATH / "capture.log")
    # Cold-boot "idle" surrogate = key-on + 5 s onward to end of capture (engine-off the whole time).
    cb_start = cb_events["key_on"]
    cb_end   = max((ts for ts, _, _ in cb_frames), default=cb_start + 0)

    # Helpers
    def static_check(frames_window, arb, byte_idx, bit_idx) -> tuple[bool, int | None, float]:
        bits = bits_for(frames_window, arb, byte_idx, bit_idx)
        if len(bits) < 30:
            return (False, None, 0.0)
        dv, pur, _ = dominant_bit(bits)
        return (pur >= 0.99, dv, pur)

    # All IDs we care about: the 11 always-on.
    always_on = ["120", "121", "129", "12A", "12D", "12E", "450", "540", "541", "5A0", "5B0"]

    # Build Run-1/Run-2 idle windows and cold-boot post-key-on window.
    static_windows = []
    for rname in ("run1", "run2"):
        events, frames = runs[rname]
        w = in_window(frames, events["idle_settled"], events["kill"])
        static_windows.append((f"{rname}-idle", w))
    cb_window = in_window(cb_frames, cb_start, cb_end)
    static_windows.append(("cold-boot-keyon", cb_window))

    # Run-3 sub-windows.
    r3_events, r3_frames = runs["run3"]
    r3_idle_start = r3_events["idle_settled"]
    r3_idle_end   = r3_events["kill"]
    r3_idle_dur   = r3_idle_end - r3_idle_start
    third = r3_idle_dur / 3
    r3_early = in_window(r3_frames, r3_idle_start, r3_idle_start + third)
    r3_mid   = in_window(r3_frames, r3_idle_start + third, r3_idle_start + 2 * third)
    r3_late  = in_window(r3_frames, r3_idle_start + 2 * third, r3_idle_end)
    print(f"Run-3 idle duration: {r3_idle_dur:.1f} s — partitioned into 3 equal sub-windows of {third:.1f} s each.")
    print(f"  early:  {len(r3_early):>6} frames")
    print(f"  mid:    {len(r3_mid):>6} frames")
    print(f"  late:   {len(r3_late):>6} frames")
    print()

    candidates = []
    for arb in always_on:
        for byte_idx in range(8):
            for bit_idx in range(8):
                # (a) static across the three reference windows
                static_ok = True
                static_vals = []
                for _, sw in static_windows:
                    ok, dv, pur = static_check(sw, arb, byte_idx, bit_idx)
                    if not ok:
                        static_ok = False
                        break
                    static_vals.append(dv)
                if not static_ok:
                    continue
                if len(set(static_vals)) != 1:
                    continue
                static_val = static_vals[0]
                # (b) Run-3 dominant in early differs from late, both ≥0.95 purity, ≥30 frames
                early_bits = bits_for(r3_early, arb, byte_idx, bit_idx)
                late_bits  = bits_for(r3_late,  arb, byte_idx, bit_idx)
                if len(early_bits) < 30 or len(late_bits) < 30:
                    continue
                e_dv, e_pur, _ = dominant_bit(early_bits)
                l_dv, l_pur, _ = dominant_bit(late_bits)
                if e_dv == l_dv:
                    continue
                if e_pur < 0.95 or l_pur < 0.95:
                    continue
                mid_bits = bits_for(r3_mid, arb, byte_idx, bit_idx)
                m_dv, m_pur, _ = dominant_bit(mid_bits) if mid_bits else (None, 0.0, 0)
                candidates.append((arb, byte_idx, bit_idx, static_val, e_dv, m_dv, l_dv, e_pur, m_pur, l_pur))

    if not candidates:
        print("No (ID, byte, bit) met all criteria. Either the fan did not engage in Run 3 (most likely — peak")
        print("coolant was 91.7 °C, below typical engagement threshold), or the late-thermal-stage signal is")
        print("not a single-bit flip in the always-on broadcast set.")
    else:
        print(f"{'ID':>4}  {'byte':>4} {'bit':>3}  {'static_val':>10}  {'r3_early':>10}  {'r3_mid':>10}  {'r3_late':>10}")
        for arb, b, bi, sv, edv, mdv, ldv, ep, mp, lp in candidates:
            edv_s = f"{edv}({ep:.2f})"
            mdv_s = "—" if mdv is None else f"{mdv}({mp:.2f})"
            ldv_s = f"{ldv}({lp:.2f})"
            print(f"{arb:>4}  {b:>4} {bi:>3}  {sv:>10}  {edv_s:>10}  {mdv_s:>10}  {ldv_s:>10}")
    print()


# ---------- Analysis 3: 540 D3 nibble inventory ----------

def analysis_540_d3_inventory():
    print("=" * 78)
    print("# Analysis 3 — `540` D3 byte/bit decomposition at idle")
    print("=" * 78)
    print()
    print("`540` D3 was LOW-CARD(4) across the idle-baseline-x3 corpus. Side-stand confirmed D3 bit 0;")
    print("payload_diff flagged D3 bit 4 as engine-state. Together they should generate at most 4 values")
    print(": {0x00, 0x01, 0x10, 0x11} (bit-0 × bit-4). Anything else in D3 is unexplained.")
    print()

    # Aggregate D3 values across all engine-off + idle windows of the 3 runs.
    all_off_d3 = []
    all_idle_d3 = []
    for name, path, thermal in RUNS:
        events, frames = load_run(REPO_ROOT / path)
        off  = in_window(frames, events["key_on"], events["starter"])
        idle = in_window(frames, events["idle_settled"], events["kill"])
        all_off_d3.extend(b[3] for ts, a, b in off if a == "540")
        all_idle_d3.extend(b[3] for ts, a, b in idle if a == "540")

    print(f"{'window':<10} {'distinct values':<35}  total frames")
    off_c = Counter(all_off_d3)
    idle_c = Counter(all_idle_d3)
    print(f"{'off':<10} {dict((f'0x{k:02X}', v) for k, v in sorted(off_c.items()))!s:<35}  {sum(off_c.values())}")
    print(f"{'idle':<10} {dict((f'0x{k:02X}', v) for k, v in sorted(idle_c.items()))!s:<35}  {sum(idle_c.values())}")
    print()

    # Now decompose each observed value into (bit 0, bit 4, other).
    all_vals = sorted(set(all_off_d3) | set(all_idle_d3))
    print(f"{'value':>6}  {'bit0':>4}  {'bit4':>4}  {'other_bits_mask':>16}  off_count  idle_count")
    other_mask_set = set()
    for v in all_vals:
        b0 = v & 1
        b4 = (v >> 4) & 1
        other = v & ~((1 << 0) | (1 << 4)) & 0xFF
        other_mask_set.add(other)
        print(f"  0x{v:02X}  {b0:>4}  {b4:>4}  0x{other:02X}             {off_c.get(v, 0):>9}  {idle_c.get(v, 0):>9}")
    print()
    if other_mask_set == {0}:
        print("VERDICT: All observed D3 values decompose into bit 0 + bit 4 + zero in other bits.")
        print("         The byte is fully accounted for at idle by side-stand + engine-state.")
    else:
        nonzero = sorted(other_mask_set - {0})
        print(f"VERDICT: D3 has unexplained bits set in addition to bits 0 and 4. Other-mask values: {[f'0x{m:02X}' for m in nonzero]}")
        print("         Future captures should look at which bit(s) within these masks vary.")
    print()


def analysis_cold_boot_long_hold():
    print("=" * 78)
    print("# Analysis 4 — flagged bits over the 174 s cold-boot key-on-no-engine hold")
    print("=" * 78)
    print()
    print("Strategy:")
    print("  The cold-boot capture is exactly key-on → 174 s idle → key-off, with no engine start.")
    print("  Per-bit time-series check over thirds of the post-key-on window: if any of the 5 flagged")
    print("  bits shifts dominant value across thirds at ≥0.95 purity per third, the engine-off mode")
    print("  is not actually stable — there's an internal timer or self-test stage we missed.")
    print()

    events = parse_events(REPO_ROOT / COLD_BOOT_PATH / "events.csv")
    frames = parse_log(REPO_ROOT / COLD_BOOT_PATH / "capture.log")
    t_start = events["key_on"]
    t_end = max((ts for ts, _, _ in frames), default=t_start)
    duration = t_end - t_start
    third = duration / 3

    print(f"Cold-boot key-on hold: {duration:.1f} s. Per-third duration: {third:.1f} s.")
    print()
    print(f"{'bit':<14} {'expected_off_mode':>17}  {'third-1':>16}  {'third-2':>16}  {'third-3':>16}  verdict")
    for arb, byte_idx, bit_idx, off_mode, idle_mode in FLAGGED_BITS:
        cells = []
        all_pur_ge = True
        all_same = True
        first_dv = None
        for k in range(3):
            sub = in_window(frames, t_start + k * third, t_start + (k + 1) * third)
            bits = bits_for(sub, arb, byte_idx, bit_idx)
            dv, pur, n = dominant_bit(bits)
            cells.append(f"{dv}({pur:.2f},{n})" if dv is not None else "—")
            if dv is None or pur < 0.95:
                all_pur_ge = False
            if first_dv is None:
                first_dv = dv
            elif dv != first_dv:
                all_same = False
        if all_same and all_pur_ge and first_dv == off_mode:
            verdict = "flat at off-mode"
        elif all_same and all_pur_ge:
            verdict = f"flat at {first_dv} (NOT off-mode {off_mode}!)"
        else:
            verdict = "MOVES across thirds — investigate"
        bitname = f"{arb} D{byte_idx} b{bit_idx}"
        print(f"  {bitname:<12} {off_mode:>17}  {cells[0]:>16}  {cells[1]:>16}  {cells[2]:>16}  {verdict}")
    print()


def main() -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    analysis_decay_shape()
    analysis_fan_hunt()
    analysis_540_d3_inventory()
    analysis_cold_boot_long_hold()
    return 0


if __name__ == "__main__":
    sys.exit(main())
