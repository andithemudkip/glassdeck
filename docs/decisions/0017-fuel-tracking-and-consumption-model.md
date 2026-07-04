# 0017 — Fuel tracking: sender tap primary, rate model secondary

**Date:** 2026-07-01
**Status:** Proposed

## Context

The replacement dashboard needs to reproduce three fuel behaviours the OEM dash provides:

1. **Fuel level display** — 8-bar quantised readout of tank state, 1-blink low-fuel warning at ~4.5 L remaining ([[project-fuel-consumption-baseline]]).
2. **Average fuel consumption** — L/100 km readout, adaptive to riding style, per user manual.
3. **Range estimate** — km-remaining projection, updated on a rolling window (rider observation: starts lower after aggressive riding, recovers upward if pace steadies). Capped at 290 km — a full tank divided by the rider's steady-state best consumption of ~3.28 L/100 km.

Load-bearing priors:

- **Fuel level is not on CAN.** [[fuel-consumption-absent-from-broadcasts]] confirmed via triple-scan of 800 k frames across 14 sessions. The sender wire runs directly from tank to OEM dash through the harness — the ECU is not in the loop.
- **Fuel level is physically observable.** Rider observation that bars track pump numbers (not accumulated consumption), combined with the OEM repair-manual schematic (component **B32**, two-wire resistive float sender wired directly to the combination-instrument connector X10 at pins 6 (signal) and 3 (sensor return)), confirms a straightforward analog tap is possible. Sender pinout on the dash side is documented in `docs/hardware/dash-connector.md`. Public data on the platform-mate KTM RC 390 puts the resistance at 10 Ω (full) → 110 Ω (empty); Husky range not on the schematic — assumed to match to first order pending multimeter verification. [[project-fuel-on-can]].
- **Fuel consumption is not on CAN either.** No fuel-rate, injector-pulse-width, or accumulated-flow signal in the always-on broadcasts. The OEM dash computes consumption locally from RPM + throttle.
- **UDS is not in use.** No diagnostic frames anywhere in the corpus — the OEM dash is not polling the ECU for a hidden fuel signal.

Two approaches were considered:

- **Pure-model.** Integrate an instantaneous fuel-rate model (`k · RPM · throttle` or similar) to get accumulated consumption. Remaining fuel = tank size − accumulated. Requires manual "I filled up + I added N litres" UX from the rider. Calibration is one data point per fillup; converging on `k` takes multiple tank cycles across varied riding styles. This is the shape stored in [[project-fuel-consumption-derivation]].

- **Sender tap + model hybrid.** Hardware ADC read on the sender wire gives an authoritative fuel-remaining reading. Rate model is retained but only for short-window range projection responsiveness — sender delta noise over sub-minute windows is dominated by slosh, so a smoothed model is more useful for the "km remaining" display. Calibration of the model becomes automatic (sender delta over long windows divided by RPM·throttle integral over the same window). Fillup detection becomes a rising edge on the filtered sender reading — no rider UX required.

The sender-tap approach eliminates every hard problem the pure-model approach was working around, at the cost of an additional analog input on the dashboard hardware. Analog front-end sketched in `docs/hardware/fuel-level-sender.md`.

## Decision

### Primary architecture: sender tap + rate model

Fuel state is derived from a single-channel ADC read on the fuel sender wire. The rate model is retained solely as a short-window smoothing layer for range projection — not as a source of truth for fuel remaining.

### Sender interface

Per `docs/hardware/fuel-level-sender.md`: 47 Ω pull-up to 3.3 V, series-R + RC filter + optional TVS between pull-up node and an ESP32-S3 ADC1 pin (must be ADC1 — ADC2 is unavailable while WiFi is on). Filtering: 10–30 s moving average on raw ADC values, with a median-of-N prefilter for outlier rejection. Raw values are noisy on any road with corners; the filter timescale must be shorter than a meaningful bar drop (~minutes) but longer than a corner (~seconds).

### Sender-to-litres calibration

Non-linear (float-arm geometry + non-cuboid tank). Multi-point calibration against physical fuel state, established during initial commissioning:

- ADC value at pump auto-cut ⇔ 9.5 L (full).
- ADC value at 1-blink transition ⇔ 4.5 L (rider-observed anchor).
- Additional intermediate points captured as bar-drop transitions or per-fillup deltas over the first two tank cycles.
- Piecewise-linear interpolation between measured points. ADC resolution and slosh noise dominate any interpolation error, so a fitted curve is not warranted.

Calibration table lives in NVS, editable via the phone app or serial console. **Not hardcoded** — sender behaviour may drift with fuel composition, temperature, or age.

### Bar display and low-fuel warning

Bar count is a fixed quantisation of the filtered litres-remaining value. The 8-bar / 1-blink layout matches OEM behaviour and preserves the rider's existing muscle memory:

| Bars | Litres remaining |
|------|------------------|
| 8 | ≥ 8.5 L |
| 7 | 7.5–8.5 L |
| ... | ... (evenly spaced) |
| 2 | 4.5–5.5 L |
| 1 (blinking) | < 4.5 L |

Boundaries editable in NVS. Low-fuel warning fires with the 1-blink transition — no separate threshold. This is more conservative than we technically need (1.5 L / ~45 km would suffice), but reproducing OEM behaviour on this UX-critical detail is worth more than the extra range.

### Fuel-rate model

Instantaneous fuel rate, computed each tick from CAN-derived signals:

```
if throttle == 0 and RPM > 1.5 × RPM_idle:
    rate_L_per_h = 0                       # decel-fuel-cutoff
else:
    rate_L_per_h = a · RPM  +  b · RPM · throttle_frac
```

Two constants:
- `a` — idle / motoring-burn coefficient, dimensioned L/(h·RPM).
- `b` — load-burn coefficient, dimensioned L/(h·RPM·throttle-unit).

`throttle_frac` is the decoded `120` D2 uint8 normalised to 0.0–1.0 against its 254 full-scale (per [[signal-throttle-position]]).

Decel-cutoff threshold uses `1.5 × RPM_idle` (~2550 RPM for a 1700 RPM idle) to distinguish "coasting in gear, ECU cuts fuel" from "at idle, ECU maintains idle burn." Threshold conservative — better to under-model cutoff than to falsely zero out fuel during a real idle stop.

### Model calibration (automatic)

`a` and `b` fit continuously from paired observations:
- **Instantaneous points:** every second we have `(RPM, throttle, dADC/dt → dlitres/dt)`. Aggregated across the operating envelope over a single tank cycle, this is a huge dataset for fitting two constants. Weight by `1/slosh_variance` to down-weight noisy corners.
- **Integrated points:** at each detected fillup, compare cumulative model-predicted consumption since the last fillup against the sender-delta actual. Feeds a residual correction into `(a, b)`.

Prior values before any calibration data exists: seed `(a, b)` such that the model produces ~3.4 L/100 km at typical cruise (per [[project-fuel-consumption-baseline]]). Numerical seed values TBD during first bench-run; the rider's 3.3–3.5 L/100 km observed band is the acceptance test.

Fitted values persist in NVS. Refit runs incrementally — no need to accumulate all raw data indefinitely.

### Fillup detection

Rising edge on the filtered sender-derived litres value:
- Litres delta ≥ 1.0 L over a window of ≤ 60 s of ignition-off time.
- Confirmed by ignition-on transition (fillups always involve key cycling).

On detection:
- Log a fillup event (timestamp, litres before, litres after) for the phone app.
- Feed the observed delta into the model calibrator.
- Reset any "fuel-used-since-fillup" counter used for the phone app trip screen.

No manual "I filled up" UX in the phone app. If auto-detection ever proves unreliable in practice, a manual override can be added — but it should not be the primary path.

### Range projection

```
range_km = min(
    range_cap,
    fuel_remaining_L × 100 / recent_avg_consumption_L_per_100km
)
```

- `fuel_remaining_L` from the calibrated sender reading.
- `recent_avg_consumption_L_per_100km` from a rolling 10-minute window on the model output (window length TBD from tuning against rider expectation; 10 min is the starting point).
- `range_cap` derived from `tank_size_L × 100 / floor_consumption_L_per_100km`, where `floor_consumption` is the rider's steady-state best observed (currently 3.28 L/100 km, giving a 290 km cap that matches OEM behaviour). Refined by calibration data over time.

Why use the model output rather than direct sender dL/dt for the rolling window: sender noise over 10 minutes is comparable in magnitude to the actual consumption delta. Model output is smooth by construction and tracks throttle behaviour instantly, giving the OEM-like "range responds to riding style" behaviour the rider expects.

### Signal surface for the phone app / BLE bridge

The following computed signals are exposed to the ADR 0014 BLE frame (all dashboard-local, not from CAN):

| Signal | Type | Notes |
|--------|------|-------|
| `fuel_level_l` | float32 | filtered litres remaining |
| `fuel_bars` | uint8 (0–8) | quantised bar count |
| `fuel_low_warning` | bool | 1 iff bar count == 1 |
| `fuel_rate_instant_l_h` | float32 | current model output |
| `fuel_avg_consumption_l_100km` | float32 | rolling 10-min window |
| `range_km` | uint16 | with the cap applied |
| `fuel_used_since_fillup_l` | float32 | integrated model since last fillup edge |

These entries are added to `docs/signals/signals.yaml` per ADR 0005 with a `source: computed` (or equivalent) tag, so the codegen in ADR 0014 emits them into the BLE frame alongside CAN-decoded signals.

### Fallback path

If sender tap turns out to be impractical (wire location unreachable, sender damage, harness constraint discovered during bike-side verification), fall back to the pure-model approach documented in [[project-fuel-consumption-derivation]]: rider inputs fillup events via the phone app, calibration is per-tank-fill only, no bar display available (rider must use trip odometer + estimated remaining). Range projection continues to work from the model but with degraded accuracy. This ADR is written primary-path-first; the fallback is documented but not preferred.

## Consequences

- **Dashboard hardware BOM grows by one ADC input + protection network.** ~5 passive components. Full sketch in `docs/hardware/fuel-level-sender.md`. Pull-up current draw (~60 mA at full tank, ~20 mA at empty) is budgeted into the F7 power chain — well inside the ~500 mA rig budget assumed in ADR 0015.
- **A short bike-side verification session is still required before this can be built:** multimeter across the B32 sender terminals at known tank levels to confirm the 10–110 Ω range transfers from the KTM RC 390 reference. Dash-side wire location is already resolved via the repair-manual schematic (`docs/hardware/dash-connector.md`). Ignition off, no engine required.
- **NVS schema needed** for: sender-to-litres calibration table, bar-boundary thresholds, model constants `(a, b)`, fillup history for calibration replay. Not designed here — falls into the dashboard firmware ADR when that lands. Keep the schema versioned from day one.
- **`docs/signals/signals.yaml`** gains the seven computed fuel signals above with a `computed` source. This is the first case of a signal that isn't decoded from CAN — ADR 0005's schema and the ADR 0014 codegen need to handle non-CAN sources cleanly (or explicitly reject them and require another emission path). Worth resolving before implementation.
- **Rate model is CAN-portable.** The `a · RPM + b · RPM · throttle` shape depends only on decoded RPM and throttle, both of which are canonical signals across the bike-portability intent ([[dashboard-bike-portability]]). Sender interface is bike-specific; rate model transfers.
- **No CAN-TX introduced.** Golden rule preserved. All fuel data is inbound-only on CAN, outbound-only via BLE.
- **Doesn't gate on any remaining CAN discovery.** Even if a fuel-related signal surfaces from the shortlist of undecoded bytes (`12A` D1 / `12E` D6 / `5A0` D4 / `121` twin int16), the sender tap remains the source of truth for level; a discovered rate signal would replace the `RPM · throttle` load proxy in the model but the architecture is otherwise invariant.
- **[[project-fuel-consumption-derivation]] memory entry is superseded by this ADR** on the primary path; the pure-model approach it documents is the fallback path referenced above. Update the memory description to reflect that once this ADR is Accepted.
- **`floor_consumption` in the range cap is currently a rider-observation constant.** If future calibration reveals a steady-state consumption better than 3.28 L/100 km on this bike, the cap and the OEM's 290 km cap diverge — acceptable, since the replacement dash is not obligated to match OEM once we have better data.
