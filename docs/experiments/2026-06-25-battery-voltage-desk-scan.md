---
date: 2026-06-25
status: partial
phase: 1
related:
  findings:
    - battery-voltage-absent-from-always-on-broadcasts
    - always-on-broadcast-ids
    - byte-d7-cycle-hash
    - signal-engine-torque
  decisions: []
  logs:
    - 2026-06-17-key-on-cold-boot
    - 2026-06-17-engine-idle-run-1
    - 2026-06-17-engine-idle-run-2
    - 2026-06-17-engine-idle-run-3
    - 2026-06-19-side-stand-toggle
    - 2026-06-19-gear-cycle-clutch-A-clutch-only
    - 2026-06-19-throttle-sweep-engine-off
    - 2026-06-22-wheel-spin-paddock-stand
    - 2026-06-23-engine-driven-rear-spin
    - 2026-06-24-front-wheel-hand-spin
    - 2026-06-24-front-wheel-decay-mark
---

# Battery-voltage byte hunt — desk-only scan across existing captures

Hunt for the byte (or byte pair) that carries battery voltage on the always-on broadcast bus, using only captures already on disk. Motivated by the `Low Battery` warning entry in [[bike/dash-warning-catalog]] (trigger ≤ 10.5 V) — the dash must source the value from somewhere.

## Hypothesis

Battery voltage is broadcast on one of the 11 always-on CAN IDs ([[always-on-broadcast-ids]]) as either a single uint8 or a 16-bit BE pair. We expect three signatures:

  1. **Engine-OFF → engine-ON step.** Resting battery ~12.4–12.8 V; alternator-regulated ~13.8–14.4 V. At 0.1 V/LSB that's a clean +10..+20 LSB step; at 0.01 V/LSB BE uint16 it's ~+150.
  2. **Stable within each phase.** Voltage is quiet at both rest and under regulation.
  3. **Cross-session-consistent.** Three idle runs span cold / partial-warm / hot coolant ([[2026-06-17-engine-idle-baseline-x3]]), so a voltage byte should have ~equal engine-on means across them while coolant-keyed bytes diverge.

Bonus discriminators we can exploit desk-only:

  - **RPM-sweep stability.** Alternator regulation holds voltage flat through the B1..B5 RPM sweep in [[2026-06-23-engine-driven-rear-spin]]; RPM-keyed bytes drift.
  - **High-beam load test.** [[2026-06-24-front-wheel-decay-mark]] toggles the high beam 6× engine-off — ~50 W ≈ 4 A draw should give a ~0.1–0.3 V dip (1–3 LSB at 0.1 V/LSB) on a voltage byte. Nothing else on the bus should track it.

## Setup

Desk-only. No new captures. Script: [`scripts/battery_voltage_scan.py`](../../scripts/battery_voltage_scan.py). Sources:

- **Engine-OFF windows** (10): pre-starter segments of `idle-run-1/2/3`, plus full-session key-on engine-off captures from `key-on-cold-boot` through `front-wheel-decay-mark` (heads only, to avoid the wheel-spin / push activity).
- **Engine-ON idle windows** (4): idle runs 1/2/3 (cold/warm/hot) starter+22 s → kill-5 s, plus rear-spin pre-sweep idle (starter+25 s → Phase A − 2 s).
- **Engine-ON RPM-swept windows** (5): each B1..B5 setpoint mark + 3 s skip + 8 s steady-state.

Per-window per-byte mean and std across all 11 always-on IDs. D7 excluded everywhere ([[byte-d7-cycle-hash]]). Score = `|Δ| / (1 + cs_off + cs_on + 0.5·within + 0.5·sweep_drift)`.

## Procedure

1. Parse each session's `events.csv` to anchor windows on `start` / `kill` / `setpoint` marks. Sessions without a `start` mark are treated as engine-off throughout and windowed from the first CAN frame.
2. Aggregate per-byte means and stds in each window.
3. Rank uint8 bytes by voltage-likeness score with KNOWN signals tagged (RPM, throttle, coolant, kill mirrors, warmup index, ignition-armed bit, side-stand mirror, engine-on counter, key-on ramp counter, twin int16 channels).
4. Repeat the same engine-off / engine-on Δ scan over uint16 BE adjacent pairs (D0:D1 .. D5:D6 per ID).
5. Print an exhaustive Δ table (including KNOWN bytes) sorted by `|Δ|` as a sanity check that nothing voltage-shaped is being filtered out.
6. Apply the high-beam load test to the top uint8 candidates: mean over [−2, −0.5] s pre-toggle vs [+0.5, +2.5] s post-toggle, for each of the 6 beam-mark events.

## Result

**No byte and no uint16 BE pair behaves like battery voltage under any captured condition.**

Top of the exhaustive Δ table (uint8, sorted by `|Δ|`):

| ID | Byte | off μ | on μ | Δ | known |
|---|---|---:|---:|---:|---|
| 121 | D1 | 167.00 | 18.21 | −148.79 | twin-int16-A-lo |
| 121 | D3 | 208.27 | 60.63 | −147.65 | twin-int16-B-lo |
| 120 | D1 | 0.00 | 145.72 | +145.72 | rpm-lo |
| 541 | D6 | 99.92 | 0.00 | −99.92 | key-on-ramp-counter |
| 541 | D4 | 0.00 | 80.21 | +80.21 | engine-on-counter |
| 540 | D2 | 64.00 | 0.00 | −64.00 | ignition-armed-bit |
| 121 | D2 | 1.00 | 59.97 | +58.97 | twin-int16-B-hi |
| 540 | D6 | 68.42 | 106.82 | +38.40 | coolant-lo |
| 121 | D0 | 0.00 | 17.51 | +17.51 | twin-int16-A-hi |
| 540 | D3 | 16.30 | 0.25 | −16.05 | side-stand + gear + ign-armed |
| 540 | D1 | 0.00 | 15.40 | +15.40 | warmup-index |
| 121 | D5 | 128.00 | 136.00 | +8.00 | kill-mirror (bit 3 = engine-running) |

Every Δ ≥ 1 LSB is fully attributable to a documented signal. The largest unattributed Δ is `541 D5` at −6.10 (the high byte of the same key-on ramp counter pattern as D6: scattered engine-off, zero engine-on — wrong shape for voltage). Beyond that, every remaining byte has `|Δ| ≤ 0.3 LSB` and the cross-session std exceeds the Δ — i.e. noise.

**uint16 BE pair scan:** no pair lands in plausible voltage ranges.

- At **0.001 V/LSB** (expect resting ~12500, alternator ~14000): closest non-known is `12A D1:D2` at 1244 / 1280 — three decimal orders of magnitude off. The pair `540 D2:D3` at 16400 / 0 is the ignition-armed bit at the top of an otherwise-zero byte.
- At **0.01 V/LSB** (expect resting ~1250, alternator ~1400): closest is again `12A D1:D2` at 1244 / 1280 — value range fits but Δ is only +36 (≈ +0.36 V) and is driven by a single-LSB drift on D1 that's already in the per-byte noise floor; D2 is essentially zero throughout. Wrong shape.

**High-beam load test:** of the top 3 unknown uint8 candidates (`541 D5`, `12A D1`, `12D D4`), none shows a consistent ±LSB pattern matching headlight on/off. `541 D5`'s +0.4 / 0 pattern is dominated by the byte sitting at 0 in 5 of 6 windows; `12D D4`'s −50 LSB mean is the rear-wheel-coarse mirror flickering during the front-wheel decay tail, not a load response.

**Sanity check that the scan works:** every known signal lands in the right place. RPM-lo (`120 D1`) shows the expected +146 step (engine off = 0, engine on = idle ≈ 1700 RPM → 145.72). Coolant-lo (`540 D6`) shows +38 (cold-warm spread across the 3 idle runs). Engine-on counter (`541 D4`) shows +80 (rises through each engine-on window). If a voltage byte existed it would have surfaced.

## Interpretation

**Hypothesis rejected, under the conditions captured.** Battery voltage is not carried in any of the 11 always-on broadcast IDs as a uint8 or as an adjacent BE uint16 pair, given:

- key-on engine-off resting,
- engine-on idle across coolant temps 25 °C → 92 °C,
- engine-on through an RPM sweep to ~5000 RPM,
- a small DC load step (high beam engine-off).

The dash still computes a `Low Battery` warning ([[bike/dash-warning-catalog]]), so voltage must reach the dash through *some* path. Three remaining possibilities, **re-ordered after rider observation that the dash is already powered by 12 V through the ignition switch — i.e. self-sense is essentially free for it**:

1. **The dash self-senses its own supply rail.** The 12 V ignition-switched feed already lives on the dash PCB; a resistor divider + ADC tap before the regulator gives battery voltage with no extra pin and no CAN/UDS traffic. Default implementation on automotive instrument clusters. Wire + ignition-switch contact drop is ~0.1–0.3 V — comfortably inside the 10.5 V warning margin. This makes the scan's negative result **the expected outcome**, not a puzzle. Strongest hypothesis. **Direct implication for [[dashboard-bike-portability]]**: our ESP32 replacement dash gets the same 12 V on the same connector and can do the exact same thing with ~3 components.
2. **Voltage is queried via UDS, not broadcast.** The OEM dash polls the ECU or body controller on demand. We wouldn't see it because nothing is currently issuing those requests. Same pattern we expect for fuel consumption ([[project-fuel-on-can]]). Possible but lower prior given (1) is available — the OEM would have no reason to add a UDS round-trip for a value it already has on-board.
3. **Voltage is broadcast only during cranking** (the one engine-state regime we haven't captured). Very low prior — the dash needs voltage continuously to evaluate the `≤ 10.5 V` threshold, so a cranking-only broadcast couldn't drive the warning on its own.

What this *doesn't* tell us:

- Whether voltage appears during cranking (case 2). A controlled crank capture is the cheapest test that closes it.
- Whether a UDS sniff with the OEM dash present would surface the voltage query (case 1). Already on the backlog as part of the fuel-consumption path ([[project-fuel-on-can]]); voltage would come for free.
- Whether the body controller emits voltage on a one-shot ID we haven't seen yet. Boot-order analysis ([[cold-boot-id-emergence]]) showed zero one-shot IDs at the keyed-on boot, so this would require a different trigger (e.g., kill→STOP, key-cycle, fault condition).

## Follow-ups

- **Finding written:** [[battery-voltage-absent-from-always-on-broadcasts]] — provisional, with self-sense flagged as the leading hypothesis after the re-rank.
- **Hardware path for the replacement dash:** spec out a 12 V → ADC divider on the ESP32 dash board. Trivial — a 10k/3.3k divider (or similar, sized for the ESP32 ADC range and a margin above 14 V) into one ADC pin, optionally with an RC filter. No CAN work needed for `Low Battery`. Belongs in the dashboard hardware doc once that's scoped.
- **Bonus side-observation to confirm separately:** `121 D5 bit 3` appears to be a clean engine-running indicator (128 → 136 lockstep with engine-off → engine-on, kill RUN throughout). Cross-check against [[engine-state-bits-decay-shape]] and the 2026-06-21 attribution work to see whether this is new or already attributed elsewhere — out of scope here.
- **Demoted, not deleted — incidental capture coverage:** a future engine-on session will include a crank window for free; the UDS sniff queued under [[project-fuel-on-can]] will surface a voltage query if one exists. Neither warrants a voltage-specific experiment now. If either incidental capture surfaces voltage, this experiment's negative result is what the analysis would re-examine.
