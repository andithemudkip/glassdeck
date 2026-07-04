# Bill of materials

Parts in current use for the listen-only adapter (Phase 0 / Phase 1).

| Part | Specifics | Role | Notes |
|------|-----------|------|-------|
| ESP32-S3-DevKitC-1 | Module: **ESP32-S3-WROOM-1-N16R8** (16 MB flash, 8 MB octal PSRAM). Dual USB-C (UART + native USB-OTG). | Microcontroller, host-side logger | Octal PSRAM reserves **GPIO33–37** — do not use these as general I/O. TWAI pins (GPIO4/5) chosen to sit clear of this — see [ADR 0002](../decisions/0002-twai-gpio-assignment.md). |
| SN65HVD230 breakout | 6-pin breakout: 3V3, GND, CTX, CRX, CANH, CANL | 3.3V CAN transceiver | Ships with an on-board termination resistor between CANH and CANL. Plan is to leave it in place for the first capture — see [can-adapter.md § Termination](../hardware/can-adapter.md#termination). |
| Diagnostic connector pigtail | Mating connector for the bike's 6-pin diagnostic port | Bike-side wiring | Pinout in [diagnostic-connector.md](diagnostic-connector.md). |
| USB-C cable | Data-capable | Desk dev: flashing + USB-CDC console | Desk dev only (originally per [ADR 0001](../decisions/0001-usb-power-during-development.md), now superseded by [ADR 0015](../decisions/0015-f7-12v-power-path.md) for the untethered/ride power source). |
| LM2596 buck module | Adjustable buck, 4–40 V input, 3 A capable, on-board output pot | F7 12V → 5V step-down for untethered rides | Per [ADR 0015](../decisions/0015-f7-12v-power-path.md); full chain in [f7-power.md](f7-power.md). **Pot must be pre-set to 5.00 V before connecting the ESP32** (see f7-power.md § Operational rules). Pololu D24V10F5 or Recom R-78E5.0-1.0 are direct upgrades if available. |
| 1N5819 Schottky | 40 V, 1 A, DO-41 axial through-hole (SMD equivalent: SS14) | Reverse-polarity protection on the F7 line | Per [f7-power.md](f7-power.md). |
| 470 µF / 63 V radial electrolytic | Aluminum electrolytic, polarised | Bulk transient absorption on the 12V rail | Per [f7-power.md](f7-power.md). No dedicated clamp in this build — risk-accepted; upgrade paths (MOV, TVS, SCR crowbar) documented in f7-power.md § Transient protection tradeoff. |
| *Optional: 1N4734A Zener (5.6 V, 1 W, DO-41)* | Through-hole axial | Downstream over-voltage clamp on the 5 V rail — cheap ESP insurance against buck pass-through failure | Per [f7-power.md](f7-power.md) § Transient protection tradeoff. Skip if not locally available. |
| 500 mA inline fuse + holder | Glass 5×20 mm fast-blow (in-enclosure) or ATO-mini blade. 0.5 A primary, 1 A acceptable fallback. | Bike-side overcurrent protection on F7 | Per [f7-power.md](f7-power.md). RO-sourceable picks in [f7-power-sourcing.md](f7-power-sourcing.md). |

Behaviors of these parts (e.g. "the breakout's on-board termination is tolerated on this bike") get promoted to `docs/findings/hardware/` once verified. This file is the parts list itself.
