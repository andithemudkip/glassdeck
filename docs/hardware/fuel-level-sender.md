# Fuel level sender interface

Analog front-end for reading the bike's fuel level sender from the ESP32-S3 dashboard.

**Status:** starting-point reference. Sender type and wiring topology confirmed from the OEM repair-manual schematic (2026-07-01); resistance range still assumed from a KTM RC 390 online source, not yet Husky-verified. Authoritative decision: [ADR 0017](../decisions/0017-fuel-tracking-and-consumption-model.md). Load-bearing prior: [[fuel-consumption-absent-from-broadcasts]] — the level exists physically but is not on the CAN bus, so the replacement dash must sense the sender directly.

## Why a hardware tap

Rider observation: OEM dash displays 8 fuel bars at a full tank (9.5 L) and drops to 1 blinking bar at ~4.5 L remaining (measured from pump numbers). Bars track tank state, not accumulated consumption — so the OEM dash reads a physical sender. [[fuel-consumption-absent-from-broadcasts]] establishes that no fuel-level or fuel-rate signal is broadcast on CAN, so the sender wire runs directly from tank to dashboard through the harness, bypassing the ECU. The replacement dash must tap the same wire.

## Sender type and wiring

Confirmed from the OEM repair-manual schematic (component **B32**, fuel level sensor):

- **Resistive float sender.** Variable-resistor symbol on the schematic. Two terminals.
- **Two-wire routing to the dashboard, chassis-isolated at the sender.** The sender's return terminal (pin 3) runs back to the combination-instrument connector rather than being grounded at the sender. This is the standard automotive pattern for isolating an analog reading from ground-loop noise across the harness.
- **Wire colours + destination:**
  - Sender pin 2 → **gn-rd** → dashboard connector X10 pin 6 (signal).
  - Sender pin 3 → **pk-rd** → dashboard connector X10 pin 3 (sensor ground / return).
- Harness connector chain: sender X33 → intermediate X37 (CU/4 → AN/4) → dash-side X32 → P10 X10. Recorded in [dash-connector.md](dash-connector.md).

**Resistance range not on the schematic.** Public data on the platform-mate KTM RC 390 reports **10 Ω at full → 110 Ω at empty**. Assumed monotonic, non-linear over the range (float-arm geometry + non-cuboid tank shape). Multimeter verification still required — see § Bike-side verification.

Implication: 100 Ω dynamic range on top of a 10 Ω floor. Small range → moderate pull-up current needed for usable ADC SNR.

## ADC front-end sketch

Baseline: voltage-divider read, sender pulled up to 3.3 V on the signal wire (gn-rd), board ground bonded to the sender-return wire (pk-rd) rather than to chassis. ESP32-S3 ADC1 pin (must be ADC1, not ADC2 — ADC2 is unavailable while WiFi is active).

```
        3.3V (board)
         │
         │
      ┌──┴──┐
      │ 47Ω │   (pull-up)
      │ ¼ W │
      └──┬──┘
         │
         ├─────► ADC1 pin (via RC filter + protection, see below)
         │
     gn-rd (X10 pin 6, signal)
         │
      ┌──┴──┐
      │  R  │   B32 sender: 10 Ω (full) → 110 Ω (empty)
      │sender│
      └──┬──┘
         │
     pk-rd (X10 pin 3, sensor return)
         │
        GND (dashboard board ground — NOT chassis)
```

**Bonding board GND to pk-rd matters.** The OEM design routes the sender return all the way back to the dash so the ADC reference floats with sender-side noise rather than picking it up as offset. If we ground the sender-return wire to chassis at the dashboard instead, we defeat that. Simplest correct implementation: the pk-rd wire from the harness becomes the dashboard's local ground reference for this ADC channel; if there's any ground offset between chassis and the sensor-return line, it doesn't corrupt the reading.

Voltage at ADC pin, for a 47 Ω pull-up to 3.3 V:

- Full (10 Ω): 3.3 × 10 / (10 + 47) ≈ **0.58 V**
- Empty (110 Ω): 3.3 × 110 / (110 + 47) ≈ **2.31 V**
- Range ≈ 1.73 V — good spread across the 3.3 V ADC input.

Pull-up dissipation: worst case (full tank) = 3.3² / 57 ≈ 190 mW. A **1/4 W** resistor is required, 1/2 W preferred for margin. Continuous current from the 3.3 V rail is ~60 mA at full tank, dropping to ~20 mA at empty — needs to be budgeted into the F7 power chain.

**Alternative pull-up values.** Higher values (e.g. 100 Ω) drop the voltage spread to ~1.4 V and cut current draw in half; lower values (33 Ω) push spread past 1.7 V but dissipate 250 mW. 47 Ω is the sweet spot for hand-built.

**Alternative topology.** Pull up to 5 V through a higher resistor and buffer/divide before the ADC — cleaner but more parts and no benefit given the current spread is already comfortable. Deferred.

## Protection network

The sender wire runs through the bike harness — exposed to transients, and (with the OEM dash removed) potentially to accidental shorts to +12 V or chassis ground during wiring. The bare ADC pin cannot tolerate either.

Between the pull-up node and the ADC pin:

- **Series resistor** (~1 kΩ) — limits fault current into the ESP32 clamp diodes if the sender wire is momentarily driven above 3.3 V or below GND.
- **RC low-pass filter** — the series R plus a 100 nF cap to GND gives a corner around 1.6 kHz. Kills harness-picked-up noise and averages sender contact chatter. Cap value adjustable up to 1 µF if sloshing noise turns out to be worse than expected — corner drops to ~160 Hz which is still fast enough for a level reading.
- **Optional TVS** to 3.3 V and GND (SMAJ3.3CA or similar) — belt-and-braces against 12 V shorts. Cheap insurance; skip if TVS parts aren't locally available.

## Filtering strategy (software)

The sender is a float on an arm in a fuel-slosh environment. Raw ADC values will be noisy on any road with corners, braking, or acceleration. Approach:

- **Long moving average** — 10–30 s window on the raw ADC reading. Level changes on a real riding timescale are minutes-to-hours; anything faster is noise or slosh.
- **Median-of-N** as a prefilter if a single-corner slosh pulls the moving-average visibly. Cheap, effective on outlier rejection.
- **Reject transitions faster than physically plausible.** Tank cannot empty faster than the model predicts — if the ADC reading claims a 1 L drop in 5 seconds, discard. Similarly for rises (fillup detection has its own path, § Fillup detection).

Bar display quantisation happens after filtering, off the filtered value.

## Calibration procedure

The sender-resistance → litres-remaining curve is not linear. Multi-point calibration against physical fuel state, taken over one or two tank cycles:

1. **Fill the tank until the pump auto-cuts.** Record ADC value (post-filter). This is "full" (9.5 L).
2. **Ride until each bar drop, and either:**
   - Record ADC value at the transition — gives a mapping from ADC to "8 bars boundary," "7 bars boundary," etc. Assumes OEM bar boundaries are what we want to reproduce, which is convenient because the rider already knows the behaviour.
   - Or: at each fillup, record how many litres were needed to refill from the ADC-observed state. Every fillup is a fresh data point.
3. **Blinking-1-bar transition** is a critical calibration anchor — rider observation: 4.5 L remaining at first blink. This point must land correctly regardless of the rest of the curve.
4. **Fit a curve.** Piecewise-linear between measured points is more than sufficient — the ADC resolution and slosh noise dominate any interpolation error.

Calibration constants live in NVS (ESP32 non-volatile storage), editable via the phone app or a serial console. **Do not hardcode** — the sender-vs-litres curve may drift with fuel composition, temperature, or sender wear.

## Fillup detection

Rising edge on the filtered level. If the filtered ADC value moves toward "full" by more than N LSB in under M seconds (both TBD, but the ignition-off window during a fillup makes the timing recoverable even for filtered signals), interpret as a fillup event. Reset any fuel-used-since-fillup counter, log the event for the phone app, snap the displayed bar count to the new state.

Fillup detection also gives us an **automatic consumption calibration point**: `Δlitres_added` from a fillup, divided by `∫(RPM × throttle) dt` between the previous fillup and this one, updates the flow constant in the consumption model. Details in the pending fuel-consumption ADR — this hardware doc just needs to preserve the raw signal that makes it possible.

## Bike-side verification

One question the desk work cannot answer (dash-side pinout is now closed — see [dash-connector.md](dash-connector.md)):

1. **Does the Husqvarna 401 sender match the KTM RC 390's 10–110 Ω?**
   - Multimeter across the sender terminals, tank at known level. Two data points (near-full and near-empty) confirm or refute.
   - Sender is usually accessible from under the seat or through the fuel-pump inspection cover; disconnect from harness before measuring.
   - Short bike-side session; ignition off, engine not required.

## Open items

- [ ] **Confirm sender resistance range on the Husqvarna 401.** See § Bike-side verification.
- [ ] **Bench-verify the ADC front-end.** Once components are in hand, build the divider + protection network on breadboard, sweep a decade pot 10–110 Ω through the sender position, capture ADC values, confirm the predicted 0.58–2.31 V spread lands where expected.
- [ ] **Sender datasheet hunt.** If any KTM/Husky/Bosch part number for the tank sender surfaces, add it here. Might reveal linearity data, temperature coefficient, or a formal resistance curve better than the online 10/110 endpoints.
- [ ] **Sender wire routing under a shared harness.** If we tap the sender wire while the OEM dash is still present (for characterisation), we parallel our pull-up with the OEM's — corrupting both readings. Characterisation must happen either with OEM disconnected, or by reading the raw voltage on the wire without adding a pull-up.
- [ ] **ADC pin assignment on the dashboard MCU.** Deferred until the dashboard schematic starts. Constraint: must be ADC1 (WiFi-compatible), single-ended.
