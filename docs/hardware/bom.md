# Bill of materials

Parts in current use for the listen-only adapter (Phase 0 / Phase 1).

| Part | Specifics | Role | Notes |
|------|-----------|------|-------|
| ESP32-S3-DevKitC-1 | Module: **ESP32-S3-WROOM-1-N16R8** (16 MB flash, 8 MB octal PSRAM). Dual USB-C (UART + native USB-OTG). | Microcontroller, host-side logger | Octal PSRAM reserves **GPIO33–37** — do not use these as general I/O. TWAI pins (GPIO4/5) chosen to sit clear of this — see [ADR 0002](../decisions/0002-twai-gpio-assignment.md). |
| SN65HVD230 breakout | 6-pin breakout: 3V3, GND, CTX, CRX, CANH, CANL | 3.3V CAN transceiver | Ships with an on-board termination resistor between CANH and CANL. Plan is to leave it in place for the first capture — see [can-adapter.md § Termination](../hardware/can-adapter.md#termination). |
| Diagnostic connector pigtail | Mating connector for the bike's 6-pin diagnostic port | Bike-side wiring | Pinout in [diagnostic-connector.md](diagnostic-connector.md). |
| USB-C cable | Data-capable | Power + serial console during development | Per [ADR 0001](../decisions/0001-usb-power-during-development.md). |

Behaviors of these parts (e.g. "the breakout's on-board termination is tolerated on this bike") get promoted to `docs/findings/hardware/` once verified. This file is the parts list itself.
