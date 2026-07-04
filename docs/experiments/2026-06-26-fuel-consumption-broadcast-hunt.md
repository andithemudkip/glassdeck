---
date: 2026-06-26
status: success
phase: 1
related:
  findings:
    - fuel-consumption-absent-from-broadcasts
    - always-on-broadcast-ids
    - byte-121-twin-int16
    - signal-engine-on-counter
  decisions: []
  logs:
    - 2026-06-17-engine-idle-run-1
    - 2026-06-17-engine-idle-run-2
    - 2026-06-17-engine-idle-run-3
    - 2026-06-17-key-on-cold-boot
    - 2026-06-19-gear-cycle-clutch-A-clutch-only
    - 2026-06-19-gear-cycle-clutch-B-gear-cycle
    - 2026-06-19-kill-switch-toggle
    - 2026-06-19-side-stand-toggle
    - 2026-06-19-throttle-sweep-engine-off
    - 2026-06-22-wheel-spin-paddock-stand
    - 2026-06-23-engine-driven-rear-spin
    - 2026-06-23-shift-lever-vs-clutch
    - 2026-06-24-front-wheel-decay-mark
    - 2026-06-24-front-wheel-hand-spin
---

# Fuel-consumption byte hunt — desk-only triple scan across existing captures

Definitively close (or open) the question of whether a fuel-rate / fuel-counter signal exists on this bike's CAN bus, using only captures already on disk. Motivated by the rider observation that the OEM dash's Avg Fuel Consumption / range estimate adapts to riding style — so the *inputs* exist somewhere, but it's not yet clear whether they're broadcast, UDS-polled, or computed locally on the dash.

## Hypothesis

One of three encodings carries fuel consumption on the bus:

1. **Rate-shaped byte** — a uint8 or uint16-BE in the 11 always-on broadcast IDs that scales with `RPM × throttle` (instantaneous injector flow proxy).
2. **Counter-shaped byte** — a monotonically-rising byte whose *tick rate* scales with `RPM × throttle` (cumulative fuel-injected integrator, analogous to `541 D4`'s 1 Hz engine-on seconds counter but at a fuel-proportional rate).
3. **UDS-polled** — the OEM dash queries the ECU for fuel data periodically over `0x7DF` / `0x7E0..0x7EF` (or 29-bit `0x18DAxxxx`); we'd see both request and response with the dash plugged in (it is, throughout every capture).

If all three return null, the only remaining possibility is that **the dash computes fuel locally** from CAN-derived RPM + throttle (both already decoded) plus an internal flow map.

## Setup

Desk-only. No new captures. Three scripts:

- [`scripts/injector_flow_scan.py`](../../scripts/injector_flow_scan.py) — rate-shaped scan.
- [`scripts/fuel_counter_scan.py`](../../scripts/fuel_counter_scan.py) — counter-shaped scan.
- One-off `python3 -c …` bus-wide arbitration-ID sweep — UDS scan.

Operating points used for rate + counter scans (from [[2026-06-23-engine-driven-rear-spin]] plus the three idle baselines):

| Window | RPM | Throttle | RPM·thr |
|---|---|---|---|
| run-1 / run-2 / run-3 neutral-idle | ~1700 | 0 | 0 |
| rear-spin neutral-idle (pre-Phase-A) | 1711 | 0.0 | 0 |
| rear-spin Phase-A (idle in 1st) | 1709 | 0.0 | 0 |
| rear-spin B1 | 1975 | 2.0 | 4039 |
| rear-spin B2 | 2131 | 3.6 | 7578 |
| rear-spin B3 | 3017 | 7.8 | 23 496 |
| rear-spin B4 | 3944 | 13.9 | 54 703 |
| rear-spin B5 | 4966 | 24.0 | 119 194 |
| rear-spin Phase-C (idle in 1st, post-sweep) | 1706 | 0.0 | 0 |

Two unexpected observations about this op-point grid set the scan's discrimination limits:

  - **Phase A reads `throttle = 0.0` identical to neutral idle.** Drivetrain drag at idle in 1st on a paddock stand is absorbed by the idle controller's bypass air below the TPS LSB. The "constant RPM, varying load" lever this point was supposed to give us doesn't exist.
  - **RPM and throttle on B1..B5 are ~collinear** (Pearson ~0.99). The regression can't separate `RPM`, `throttle`, and `RPM·throttle` cleanly — any monotonically-rising byte fits all three with similar R².

These limit the strength of a positive find but not a negative one — the scans look broader than any single regressor, scoring against (a) RPM·thr fit R², (b) within-window monotone tick rate vs RPM·thr, (c) Phase-A-vs-neutral-idle Δ, and (d) post-kill decay shape.

## Procedure

**Scan 1 — rate-shaped (`injector_flow_scan.py`).** For each uint8 byte and each uint16 BE adjacent pair in the 11 always-on IDs (excluding D7 cycle-hash ([[byte-d7-cycle-hash]]) and already-attributed bytes), compute the mean over each operating window, then fit `byte ≈ a + b·RPM + c·throttle + d·RPM·throttle` across the 11 windows. Rank by `R² × (|d|·max(RPM·thr) + Phase-A Δ) / range`.

**Scan 2 — counter-shaped (`fuel_counter_scan.py`).** For each candidate byte (uint8, mod 256) and pair (uint16 BE, mod 65 536), compute the signed tick rate within each setpoint window using wraparound-aware delta accounting. Filter for:

  - Monotone direction within each window (≥85 % same-sign deltas) — counters don't bit-bounce.
  - Non-trivial rate range across setpoints (>0.05 LSB/s difference between fastest and slowest setpoint) — a constant-rate counter like `541 D4` correctly fails this.
  - Engine-off rate small relative to engine-on range — fuel doesn't accumulate when injectors are off.

Score = `pearson(rates, RPM·throttle) × log1p(rate_range)`.

**Scan 3 — UDS sweep.** For each of the 14 captures (every engine-on session plus the cold-boot, all input-toggle and wheel-spin sessions), enumerate every arbitration ID seen, and flag any outside the 11 always-on set — with special attention to the diagnostic ranges `0x7DF`, `0x7E0..0x7EF`, `0x600..0x6FF`, and any 29-bit extended frame.

## Result

**Scan 1 — rate-shaped: no clean fuel candidate.** Top unknown candidates by composite score:

| Candidate | min..max | R² | Phase-A Δ | Verdict |
|---|---|---|---|---|
| `pair 5A0 D6:D7` | 127..130 (3 LSB) | 0.77 | 0.2 | tiny range; non-monotonic shape; not fuel |
| `pair 5B0 D6:D7` | 131..134 (3 LSB) | 0.79 | 0.4 | same shape |
| `pair 120 D1:D2` | 31 644..39 817 | 0.56 | 221.6 | artifact: `(rpm_lo << 8) \| throttle` — noise on rpm_lo |
| `pair 12D D2`, `pair 12D D1`, `pair 12D D6` | wide | 0.38..0.84 | high | rear-wheel-speed (already attributed) |
| `pair 129 D0` | 0..4096 | 0.44 | 4096 | gear nibble (already attributed) |
| `pair 121 D2` (int16-B) | 120..43 988 | 0.23 | 24 153 | [[byte-121-twin-int16]] — sanity check: low R² because of mid-RPM peak shape, correct |

The `5A0 D6` / `5B0 D6` candidates have a 3-LSB total range across the entire idle → 5000-RPM sweep — far too narrow to plausibly carry fuel rate, which needs ~10× dynamic range from idle to WOT. Most likely a small advance trim or similar low-resolution correction.

**Scan 2 — counter-shaped: zero unknown candidates.** Across all 11 IDs, the *only* monotone byte/pair candidates with non-trivial rate are:

| Candidate | Rates per setpoint (LSB/s) | Attribution |
|---|---|---|
| `byte 540 D6` & `pair 540 D5:D6` | +2.12 +2.00 +1.62 +1.75 +1.50 +1.62 | coolant low byte rising as engine warms; rate *decreases* with RPM (warmup curve, not fuel) |
| `pair 540 D6:D7` | +544 +512 +416 +448 +384 +416 | same coolant byte viewed through the D6:D7 pair window; D6 high-byte steps of 256 + LSB tick |
| `byte 541 D4` & `pair 541 D3:D4` | +1.00 ×6 | [[signal-engine-on-counter]] 1 Hz seconds counter (sanity check — correctly filtered out for zero rate range) |
| `pair 541 D4:D5` | +256 ×6 | same counter viewed through D4:D5 pair window |

Six entries, all corresponding to two known signals (coolant warming + engine-on seconds). The script correctly rejected coolant via the engine-off-rate filter (coolant drifts in engine-off captures too, as ambient temperature differs across days). **No fuel-shaped counter exists in the always-on broadcast set.**

**Scan 3 — UDS sweep: zero non-always-on IDs across 800 679 frames in 14 sessions.**

| Session | Frames | Non-always-on IDs |
|---|---|---|
| 2026-06-17-engine-idle-run-1 | 89 803 | none |
| 2026-06-17-engine-idle-run-2 | 88 872 | none |
| 2026-06-17-engine-idle-run-3 | 90 216 | none |
| 2026-06-17-key-on-cold-boot | 72 916 | none |
| 2026-06-19-gear-cycle-clutch-A-clutch-only | 37 593 | none |
| 2026-06-19-gear-cycle-clutch-B-gear-cycle | 29 988 | none |
| 2026-06-19-kill-switch-toggle | 30 289 | none |
| 2026-06-19-side-stand-toggle | 28 943 | none |
| 2026-06-19-throttle-sweep-engine-off | 26 838 | none |
| 2026-06-22-wheel-spin-paddock-stand | 77 694 | none |
| 2026-06-23-engine-driven-rear-spin | 118 416 | none |
| 2026-06-23-shift-lever-vs-clutch | 21 848 | none |
| 2026-06-24-front-wheel-decay-mark | 40 655 | none |
| 2026-06-24-front-wheel-hand-spin | 47 573 | none |
| **Total** | **800 679** | **0** |

Not a single frame in any UDS request range (`0x7DF`, `0x7E0..0x7EF`), no diagnostic band (`0x600..0x6FF`), no 29-bit extended frames. The OEM dash is on the bus and powered throughout every capture — if it were polling the ECU we would see the requests.

## Interpretation

All three broadcast hypotheses are ruled out. The only remaining possibility consistent with the rider's adaptive-range observation is that **the OEM dash computes fuel consumption locally from CAN-derived RPM and throttle** via an internal flow map — an `RPM × throttle × flow_const` integration over a sliding window. That's exactly the behavior the rider describes:

  - Aggressive throttle → higher integrated flow → lower computed range estimate
  - Tone down → lower flow → range estimate recovers
  - Steady cruise → stable computed rate

Indistinguishable from how a real fuel signal would behave from the rider's point of view, but with no CAN signal needed.

**What this does NOT tell us:**

  - Whether the OEM uses an internal `mg/stroke` lookup table keyed on `(RPM, MAP_estimate)` rather than `(RPM, throttle)` directly. We don't have a MAP-equivalent signal on the bus either — `121` D0:D3 was the strongest MAP candidate and was ruled out as ignition-advance-or-trim by [[byte-121-twin-int16]]. So MAP would also have to be derived locally if used. Practically the same constraint for our replacement.
  - Whether a fuel signal would appear under conditions not yet captured (overrun fuel cutoff during a real road decel, dealer mode, fault state). Possible but increasingly unlikely given coverage now spans 800k frames across cold boot, idle, RPM sweep, kill, gear cycling, clutch, side-stand, wheel spin engine-off, wheel spin engine-on, and three input-toggle sessions.

## Follow-ups

- **Finding to write:** [[fuel-consumption-absent-from-broadcasts]] at `confirmed` — combines all three scan nulls into a single load-bearing finding.
- **Finding to strengthen:** [[always-on-broadcast-ids]] — note the 800 679 / 0 UDS-clean confirmation, which firms the "11 IDs are the complete bus inventory" claim from "no one-shot at boot" to "no non-always-on traffic across every captured condition."
- **Status update:** close the fuel-rate / fuel-counter / UDS branches of the fuel-consumption queue in `docs/status.md`. Commit to the open-loop model as the canonical path; record that injector flow constant needs tank-fill-delta calibration on the first few full rides post-dashboard-deployment.
- **Battery voltage side effect:** the [[battery-voltage-absent-from-always-on-broadcasts]] finding lists "UDS sniff would still be incidental confirmation" as an open caveat. That caveat is now closed too — UDS is not in use on this bike. Voltage finding can be promoted from `provisional` to `confirmed` on that basis.
- **No further fuel-on-CAN experiments.** A future engine-on road capture with throttle/RPM decoupling could in principle re-open Scan 1, but the prior is now too low to justify dedicated scope. If a fuel-shaped byte ever surfaces incidentally in another capture, that would refute and reopen.
