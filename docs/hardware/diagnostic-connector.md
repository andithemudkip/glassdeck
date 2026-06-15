# Diagnostic connector pinout

Bike: 2020 Husqvarna Svartpilen 401.

| Pin | Label | Wire colors | Function |
|-----|-------|-------------|----------|
| 2   | CH    | green / blue    | CAN Bus High |
| 3   | GD    | blue / yellow   | Ground |
| 4   | F7    | grey / pink     | Power (switched, key-on) |
| 5   | CL    | yellow / blue   | CAN Bus Low |

Pins 1 and 6 are not used for the listen-only adapter.

## Source

User-supplied, 2026-06-15. Treat as confirmed for wiring purposes; verify continuity with a multimeter before connecting the transceiver.

## Wiring to the listen-only adapter

Full adapter pinout (connector → SN65HVD230 → ESP32-S3) lives in [can-adapter.md](can-adapter.md). F7 (pin 4) is intentionally left unconnected during development — see [ADR 0001](../decisions/0001-usb-power-during-development.md).

## Notes

- CAN bitrate not yet confirmed. KTM 390 platform is most commonly reported as 500 kbps; verify against captured traffic before trusting.
- Termination state at the diagnostic port is unknown — if the bus is not seen, check whether a 120Ω termination resistor is needed at the adapter end.
