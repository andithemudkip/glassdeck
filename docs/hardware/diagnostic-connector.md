# Diagnostic connector pinout

Bike: 2020 Husqvarna Svartpilen 401.

| Pin | Label | Schematic code | Colour           | Function |
|-----|-------|----------------|------------------|----------|
| 2   | CH    | gn-bu          | green / blue     | CAN Bus High |
| 3   | GD    | bl-ye          | black / yellow   | Ground |
| 4   | F7    | gr-pk          | grey / pink      | Power (switched, key-on) |
| 5   | CL    | ye-bu          | yellow / blue    | CAN Bus Low |

Pins 1 and 6 are not used for the listen-only adapter.

Colour codes cross-checked against the manual's own legend on page 341 of the wiring diagrams — see `dash-connector.md` for the full legend. Note: `bl = Black`, `bu = Blue`. The original user-supplied pinout described pin 3 as "blue / yellow", which is a colour-code ambiguity — the wire is black / yellow per the schematic. Same wire, corrected label.

## Source

User-supplied 2026-06-15; wire colours cross-checked against the repair manual wiring diagram 2026-07-01. The schematic (page 8 of the wiring diagrams, connector X295 designated QM/6) confirms the pinout and wire routing. Verify continuity with a multimeter before connecting the transceiver.

## Wiring to the listen-only adapter

Full adapter pinout (connector → SN65HVD230 → ESP32-S3) lives in [can-adapter.md](can-adapter.md). F7 (pin 4) is intentionally left unconnected during development — see [ADR 0001](../decisions/0001-usb-power-during-development.md).

## Notes

- CAN bitrate not yet confirmed. KTM 390 platform is most commonly reported as 500 kbps; verify against captured traffic before trusting.
- Termination state at the diagnostic port is unknown — if the bus is not seen, check whether a 120Ω termination resistor is needed at the adapter end.
