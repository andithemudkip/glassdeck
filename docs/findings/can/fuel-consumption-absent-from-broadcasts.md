---
area: can
status: confirmed
established_by:
  - 2026-06-26-fuel-consumption-broadcast-hunt
references:
  - svartpilen-401-dash-user-manual
---

# Fuel consumption is not carried on this bike's CAN bus

Across every captured condition to date — three engine-idle baselines spanning cold / partial-warm / hot coolant, a full RPM sweep from idle to ~5000 RPM in 1st gear on a paddock stand, plus every input-toggle and wheel-spin session — **no broadcast byte and no UDS request carries a fuel-rate, fuel-counter, or instantaneous-consumption signal**. The OEM dash's Avg Fuel Consumption / range estimate must therefore be computed locally from CAN-derived RPM and throttle.

## What was tested

[[2026-06-26-fuel-consumption-broadcast-hunt]] ran three independent scans against existing logs:

1. **Rate-shaped scan** ([`scripts/injector_flow_scan.py`](../../../scripts/injector_flow_scan.py)) — for every uint8 byte and uint16 BE pair in the 11 always-on broadcast IDs, fit `byte ≈ a + b·RPM + c·throttle + d·RPM·throttle` across 11 operating points (4 neutral-idle windows + Phase A idle-in-1st + B1..B5 RPM setpoints + Phase C post-sweep idle). Rank by composite of R² and Phase-A-vs-neutral-idle differential.

2. **Counter-shaped scan** ([`scripts/fuel_counter_scan.py`](../../../scripts/fuel_counter_scan.py)) — for every uint8 byte and uint16 BE pair, compute the signed tick rate within each setpoint window using wraparound-aware delta accounting. Filter for monotone direction (≥85 % same-sign deltas), non-trivial rate range across setpoints, and engine-off rate small relative to engine-on range. Score by `pearson(rates, RPM·throttle) × log1p(rate_range)`.

3. **UDS sweep** — enumerate every arbitration ID seen across 14 sessions (800 679 frames total), flagging any outside the 11 always-on set, with special attention to the diagnostic ranges `0x7DF`, `0x7E0..0x7EF`, `0x600..0x6FF`, and any 29-bit extended frame.

## What the scans actually found

**Rate scan:** no clean candidate. Top unknown candidates by composite score were either tiny-range advance trims (`5A0 D6:D7` and `5B0 D6:D7` at 3-LSB total range across the full RPM sweep — too narrow to plausibly carry fuel rate, which needs ~10× dynamic range from idle to WOT) or fit artifacts from already-attributed bytes (`(rpm_lo << 8) | throttle` reading as a "fit" because both components are in the regressor). [[byte-121-twin-int16]] correctly ranked low (R² = 0.23) because its mid-RPM peak shape doesn't fit a linear `RPM·throttle` model — confirms scan discrimination is working.

**Counter scan:** zero unknown candidates. Six monotone byte/pair hits total across all 11 IDs, every single one already attributed:

| Candidate | What it is |
|---|---|
| `byte 540 D6` + `pair 540 D5:D6` | coolant low byte rising as engine warms; rate *decreases* with RPM (warm-up curve asymptotes, not a fuel-rate shape) |
| `pair 540 D6:D7` | same coolant byte viewed through D6:D7 window |
| `byte 541 D4` + `pair 541 D3:D4` | [[signal-engine-on-counter]] 1 Hz constant — correctly filtered for zero rate range |
| `pair 541 D4:D5` | same counter viewed through D4:D5 window |

**UDS sweep:** 0 / 800 679 frames outside the 11 always-on IDs across 14 sessions. The OEM dash is plugged in and powered throughout every capture, so if it polled the ECU we would see both request and response frames. We see neither. This also retroactively closes the UDS-might-still-surface-it caveat in [[battery-voltage-absent-from-always-on-broadcasts]].

## Interpretation

The rider's adaptive-range observation (range estimate drops with aggressive riding, recovers when toned down) is fully consistent with **the OEM dash computing fuel locally** via an internal flow map keyed on `(RPM, throttle)` and integrated over a sliding window:

  - Aggressive throttle → higher integrated flow → lower range estimate
  - Tone down → lower flow → range estimate recovers
  - Steady cruise → stable computed rate

This is indistinguishable from a real fuel signal at the rider's interface, but requires no CAN signal beyond what we already have decoded ([[signal-rpm]], [[signal-throttle-position]]).

## What this does NOT cover

  - Whether the OEM uses an `mg/stroke` lookup keyed on `(RPM, MAP_estimate)` rather than `(RPM, throttle)` directly. No MAP-equivalent signal is on the bus either ([[byte-121-twin-int16]] was the strongest candidate and turned out to be ignition advance or fuel trim). MAP would have to be locally derived too — same constraint for our replacement.
  - Conditions not yet captured: fuel cutoff during real-road overrun, dealer mode, fault state. A fuel byte could in principle appear there, but coverage now spans cold boot, idle, RPM sweep, kill, gear cycling, clutch, side-stand, wheel spin engine-off, wheel spin engine-on, and three input-toggle sessions — 800k frames with no anomalies — so the prior is low.

## Consequences for the replacement dashboard

  - **Fuel consumption signal closes as derived-locally.** We compute it from already-decoded CAN channels. The specific model has moved (2026-07-22) from `∫(RPM × throttle) dt` to a torque-based `∫(RPM × max(0, 121_A)) dt` — see [[fuel-consumption-derivation-from-torque]]. Change was driven by `121_A` being identified as leading-candidate signed engine torque, which gives (a) physical grounding (torque × RPM = mechanical power = fuel × combustion efficiency), and (b) automatic decel fuel-cut modelling (`121_A` goes negative during overrun; clipped to zero → no fuel). The old `RPM × throttle` plan is preserved in [[project-fuel-consumption-derivation]] memory's Older section.
  - **Calibration constants (2, unchanged from the old plan) refined against tank-fill deltas** on the first few rides post-deployment.
  - **Fuel level is a separate concern** — see [[project-fuel-on-can]]: the tank sender is expected to be on the harness, not on CAN. Needs its own hardware tap if we want a level reading rather than just a consumption-derived range estimate.
  - **No further fuel-on-CAN experiments.** If a fuel-shaped byte ever surfaces incidentally during future engine-on captures, that would refute and reopen.

See also: [[always-on-broadcast-ids]], [[signal-rpm]], [[signal-throttle-position]], [[signal-engine-on-counter]], [[byte-121-twin-int16]], [[battery-voltage-absent-from-always-on-broadcasts]].
