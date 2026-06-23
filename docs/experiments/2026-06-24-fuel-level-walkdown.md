---
date: 2026-06-24
status: planned
phase: 2
related:
  findings:
    - can/always-on-broadcast-ids
  experiments: []
  logs: []
---

# Fuel level walkdown — find the gauge byte via bar-count progression

## Hypothesis

Fuel level is encoded in a payload byte of one of the 11 always-on broadcast IDs ([[always-on-broadcast-ids]]) — most plausibly in the 100 ms cohort (`540`, `5A0`, `5B0`), which is the slow-update group the dashboard cluster reads from.

A first pass with [`scripts/fuel_byte_scan.py`](../../scripts/fuel_byte_scan.py) against the existing 11 capture sessions returned **no fuel-shaped candidate**. Every non-checksum byte in the always-on inventory was either flat across all sessions or moved in a non-fuel pattern (binary engine-state flip; non-monotonic key-on settle). The leading explanation is that none of those sessions burned enough fuel to overcome 1-LSB quantisation — total engine-on time is ~15 min across all of them, almost all at idle/paddock-stand.

This experiment supplies the missing dimension: **a series of captures, each labelled with the bar count at the time of capture**. No required cadence or step size — opportunistic captures whenever the rider can pull over are fine. Spacing is free-form; what matters is that bar count is recorded each time and that the series spans a wide enough range to overcome 1-LSB quantisation.

Any byte tracking fuel level must (a) be approximately monotonic with the recorded bar counts across the series, and (b) have within-session stdev ≤ 2 LSB inside each settled capture. Two or more captures at the same bar count are useful too — they give a noise-floor estimate for free.

Competing outcomes:

1. **A clean candidate appears.** A byte tracks the recorded bar counts monotonically across the series and is stable within each capture. Promote to `signal-fuel-level` after confirming polarity and rough scale.
2. **No candidate moves cleanly.** Then fuel level is not in the always-on broadcast set. Most likely explanation: it's a UDS / ISO-TP poll-on-request signal that the OEM dash queries from the ECU and that doesn't appear unless someone asks for it. Forces a different experiment shape (sniff active dash, or experiment with UDS request frames — but the latter would break the listen-only golden rule and needs an ADR).
3. **Multiple candidates pass.** Disambiguate with a post-refuel capture: only the fuel byte jumps upward; everything else continues monotonically or stays put.

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. Fuel tank starting somewhere in the working range — at least 3 bars above empty so we can drop two bars without crossing the reserve threshold (which may add a confound).
- Capture rig: ESP32-S3 CAN logger at the diagnostic-port stub, host running `scripts/capture.py`. Listen-only. Firmware commit recorded in each session's `session.md`.
- Engine: warmed up to operating temperature before Capture 1, so the coolant/warmup bytes are stable across all three captures and don't pollute the scan.
- Settle: side-stand down, engine idling, **at least 60 s** between parking and starting each capture, so fuel slosh damps out. Slosh inside the capture window would inflate within-session stdev and bury the signal.
- **Bar count recorded in each session's `session.md`.** This is the load-bearing observation. The existing logs lack it and that's most of why the first pass returned nothing — let's not repeat that.

## Procedure

Each capture is a plain ~2 min idle. No procedure YAML, no per-step marks. The operator obligations are:

1. **Warm engine and settle ≥60 s before starting the capture.** This damps fuel slosh and keeps coolant-derived bytes stable across the series.
2. **Record the bar count in `session.md` for every capture.** Also note the reserve light if visible. This is the only load-bearing observation — without it the capture is useless for this experiment.
3. **Use a recognisable label.** Suggested: `fuel-walkdown-N` (N = 1, 2, 3...). A post-refuel capture is most useful labelled `fuel-walkdown-N-postfuel` so the upward jump is obvious in the analysis.

Between captures, ride normally. No fixed cadence — capture opportunistically whenever you can pull over and settle. Aim for the series to span at least 3–4 bars of total drop so the byte (if quantised coarsely) has multiple LSB transitions to fit against.

## Analysis

Pre-registered to avoid hunting:

1. Run `python scripts/fuel_byte_scan.py --logs-dir logs` (or scoped at the new sessions).
2. **Selection criteria for a fuel byte:**
   - Within-session stdev ≤ 2 LSB in every capture (level shouldn't slosh inside a settled idle window).
   - Per-session medians correlate monotonically with the recorded bar counts (Spearman r ≥ 0.9 across the series). Captures at the same bar count should also have closely matching medians.
   - Same byte ranks in both engine-on rankings *and* (if any engine-off frames exist before/after the captures) engine-off ranking — fuel level is independent of engine state.
   - Does not correlate with coolant temp across the captures — rules out warmup/thermal bytes that happen to drift.
3. If multiple bytes pass: a post-refuel capture provides the upward-step witness — keep only the byte that jumps up.
4. If no byte passes: outcome (2) above. Record the negative result, open a follow-up experiment for the UDS-poll hypothesis.

## Result

*Not yet run.*

## Interpretation

*To be filled after capture.*

## Follow-ups

- [ ] Outcome 1 → draft `docs/findings/can/signal-fuel-level.md`. Re-run scan against all prior sessions to back-fill approximate fuel levels for previously-uninstrumented logs.
- [ ] Outcome 2 → new experiment doc for the UDS-poll hypothesis. Requires sniffer-only first (passive listen for any request/response traffic when the OEM dash is present); active UDS probing would need a separate ADR.
- [ ] Outcome 3 → Cap 4 if not already taken; otherwise schedule a refuel-bracketed pair.
- [ ] If a fuel byte is found, audit whether a single-bit reserve warning lives in the same ID — those usually broadcast together.
