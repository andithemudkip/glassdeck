# Hardware

Wiring, pinouts, connectors, BOM, schematics for the bike-side and dashboard-side hardware.

Suggested files as they become relevant:

- `diagnostic-connector.md` — pinout of the bike's diagnostic connector
- `dash-connector.md` — pinout of the OEM combination-instrument connector (P10 X10, 12-pin)
- `can-adapter.md` — listen-only adapter wiring (ESP32-S3 + transceiver)
- `f7-power.md` — F7 (switched 12V) → 5V power chain for untethered captures
- `f7-power-sourcing.md` — Romanian-availability notes on the F7 chain parts
- `fuel-level-sender.md` — analog front-end for the fuel level sender tap
- `bom.md` — current parts list with sources and prices
- `wiring/` — schematics, KiCad sources, photos

Confirmed hardware *behaviors* (e.g. "transceiver X needs 5V on pin 8 to wake up") belong in `docs/findings/hardware/` once verified — keep this directory for the physical setup itself.
