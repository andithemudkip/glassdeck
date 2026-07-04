# Dashboard connector pinout (P10 / X10)

Bike: 2020 Husqvarna Svartpilen 401. Connector on the OEM combination instrument (P10 in the repair manual), designated **X10**, 12-pin (repair-manual label `LL/12`). P10 has only this one connector — no secondary.

**All 12 pins mapped** as of 2026-07-01 from the repair-manual schematic (pages 1, 3, 7, 9 of the wiring diagram set).

| Pin | Wire (schematic) | Colour | Signal | Source page |
|-----|------------------|--------|--------|-------------|
| 1   | wh    | White              | **Permanent 12 V** via F2 (10 A fuse). Memory/clock backup rail; hot even with ignition off. | 30.1 |
| 2   | gr-pk | Grey / pink        | **Ignition-switched 12 V** — same rail that feeds the diagnostic connector's F7 pin. This is the dashboard's main supply. | 30.3 |
| 3   | pk-rd | Pink / red         | Fuel sender **return / sensor ground** (B32 pin 3, via harness X33 → X37 → X32). | 30.7 |
| 4   | bl-ye | Black / yellow     | **Ground.** Common return for dashboard. | 30.3 |
| 5   | pk-bl | Pink / (light) blue | Signal from S34 right combination switch (kill-switch RUN position mirror). Also routed to A11 ECU pin 33 — same wire feeds both. Redundant with the CAN kill-switch broadcast at `541` D2 bit 4 (see [[signal-kill-switch]]). | 30.1 |
| 6   | gn-rd | Green / red        | Fuel sender **signal** (B32 pin 2, resistive float sender). | 30.7 |
| 7   | br-pk | Brown / pink       | **Oil pressure sensor** (B35, switch-to-ground). Discrete state, not analog. | 30.7 |
| 8   | rd-bl | Red / black        | **High-beam indicator sense** — tapped from the E75 headlight unit's high-beam drive line via the K12 light relay chain. 12 V high when high beam is on. | 30.3 |
| 9   | ye-bu | Yellow / blue      | **CAN Low.** Same net as diagnostic connector pin 5 and the ABS ECU (A30) pin 4. | 30.9 |
| 10  | gn-bu | Green / blue       | **CAN High.** Same net as diagnostic connector pin 2 and the ABS ECU (A30) pin 3. | 30.9 |
| 11  | gn    | Green              | **Left turn-indicator mirror** — tapped from the P41 + P45 bulb bus, driven via S33 pin 4 from the K20 flasher relay. 12 V pulsed when left indicator is on. | 30.7 |
| 12  | gr    | Grey               | **Right turn-indicator mirror** — tapped from the P42 + P46 bulb bus, driven via S33 pin 3 from the K20 flasher relay. 12 V pulsed when right indicator is on. | 30.7 |

## Source

Repair manual schematic pages 30.1, 30.3, 30.7, 30.9, user-supplied PDF 2026-07-01. Colour codes decoded via the manual's own legend on page 341:

```
bl = Black    br = Brown    bu = Blue     gn = Green
gr = Gray     lbu = Lightblue  or = Orange
pk = Pink     pu = Violet   rd = Red
wh = White    ye = Yellow
```

Note the trap: `bl` is **Black**, not blue; `bu` is Blue. Ground wires (`bl-ye`) are black/yellow, not blue/yellow. Cross-check any prior wire-colour notes against this legend — see [Fix note](#fix-note-diagnostic-connector-colour-code) below.

Title strip on every schematic sheet reads **"Svartpilen 401 non US 2021-2022"** — our bike is a 2020, same platform generation, so the wiring is very likely identical. Verify continuity with a multimeter on the 2020 bike before soldering to any replacement dashboard.

Component designators referenced above (from the manual's component keys on pages 325, 329, 337, 341):

- **A11** — engine control unit (ECU)
- **A30** — ABS control unit
- **B32** — fuel level sensor
- **B35** — oil pressure sensor
- **E75** — headlight unit
- **F2** — fuse (10 A, permanent B+ feed for the dash)
- **K12** — light relay (ECU-driven)
- **K20** — turn signal relay (flasher)
- **P10** — combination instrument (this dashboard)
- **P41 / P42 / P45 / P46** — front-left / front-right / rear-left / rear-right turn signals
- **S33** — combination switch, left (handlebar cluster with turn-indicator selector)
- **S34** — combination switch, right (handlebar cluster with kill switch, start button)
- **X10** — the 12-pin connector on P10

## What this unlocks for the replacement dashboard

- **Power in:** pin 2 (gr-pk, ignition-switched 12 V) → ESP32 buck chain, mirroring the F7 setup in [ADR 0015](../decisions/0015-f7-12v-power-path.md). Same electrical rail as the diagnostic connector's F7, so the entire F7 fuse-Schottky-cap-buck chain applies unchanged.
- **Backup power:** pin 1 (wh, permanent 12 V through F2) available if we want NVS-backup or a real-time-clock circuit that survives ignition off. Optional.
- **Ground:** pin 4 (bl-ye).
- **CAN:** pins 9 (CAN Low) + 10 (CAN High) — read via the SN65HVD230 as we already do on the diagnostic port.
- **Fuel sender:** pins 6 (signal) + 3 (return). ADC front-end per [`fuel-level-sender.md`](fuel-level-sender.md).
- **12 V state inputs (need level-shifted to 3.3 V GPIO):** pin 5 (kill-switch RUN mirror), pin 7 (oil-pressure switch), pin 8 (high-beam sense), pin 11 (left indicator), pin 12 (right indicator). Voltage divider or opto-isolator per input.

That's the entire OEM sensor + status surface accounted for. Zero unknown pins remaining.

## Notes

- **Fuel sender topology.** Two-wire — signal (pin 6) + dedicated return (pin 3) — not sender-chassis-grounded locally. Full analog front-end discussion in [fuel-level-sender.md](fuel-level-sender.md).
- **Harness connector chain sender → dash:** B32 → X33 (near sender) → X37 (CU/4 → AN/4 crossover) → X32 (dash-side) → X10 (P10 connector). All intermediate segments are 4-pin sub-connectors.
- **Oil pressure sensor.** B35 is drawn as a switch-to-ground, so pin 7 reads as a discrete state (OK vs low oil pressure), not an analog reading. Feeds the "Low Oil Pressure" warning currently listed as `open` in [`dash-warning-catalog.md`](../findings/bike/dash-warning-catalog.md).
- **Turn indicators are off-bus.** Same pattern as fuel level ([[fuel-consumption-absent-from-broadcasts]]) and auto-headlight ([[bike/dash-warning-lights]]) — the dashboard reads state directly from a dedicated wire rather than a CAN broadcast. Replacement dashboard reads pins 11 and 12 as GPIO inputs. Interpretation: any activity in the last ~1.5 s (longer than the flasher period) = indicator on. Bonus: OEM shows a single indicator lamp for both directions; we get separate left/right arrows for free.
- **High beam is also off-bus.** Pin 8 (rd-bl) is tapped straight from the headlight-unit high-beam drive line via the K12 relay chain. 12 V present = high beam on, driven by the OEM headlight switch (S33 or S34 — need to confirm from other schematic pages). Same as pin 5 / 11 / 12: level-shift before feeding a GPIO. Closes the "High beam" `open` entry in the warning catalog.
- **Kill switch is doubly-wired.** Both a physical mirror (pin 5) and CAN broadcasts (at `541` D2 bit 4, `5B0` D0 bit 4, `121` D5 bit 2 per [[signal-kill-switch]]). Replacement dash can use either; CAN is preferred because it doesn't need a level-shifter, but the physical wire is a fallback if CAN drops out.
- **The dashboard does not draw the headlight.** K12 (light relay) is controlled by ECU pin 43 (pu-rd), not by any dash output. This confirms [[bike/dash-warning-lights]] — the auto-headlight logic is inside the ECU, keyed on rear-wheel speed. The dash only *senses* whether the high-beam element is on, via pin 8.

## Fix note (diagnostic connector colour code)

The existing [`diagnostic-connector.md`](diagnostic-connector.md) describes pin 3 GD as "blue / yellow". Per this schematic's legend (`bl = Black`), the correct interpretation is **black / yellow**. Same wire — the "blue" transcription was almost certainly a colour-code ambiguity (`bl` looking like an abbreviation of "blue"). Fix pending.
