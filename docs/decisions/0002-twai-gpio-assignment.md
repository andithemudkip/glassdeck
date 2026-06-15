# 0002 — TWAI TX/RX GPIO assignment on the ESP32-S3-DevKitC-1

**Date:** 2026-06-16
**Status:** Accepted

## Context

The ESP32-S3 TWAI controller (the CAN peripheral) routes through the GPIO matrix, so TX and RX can be assigned to any free GPIO. Locking the choice in early means the wiring diagram, firmware pin macros, and future hardware photos all reference the same pins.

The board is the [ESP32-S3-DevKitC-1](../hardware/bom.md). Constraints for this board:

- Strapping pins must not be driven the wrong way at boot: **GPIO0, GPIO3, GPIO45, GPIO46.**
- Native USB-OTG occupies **GPIO19 / GPIO20** (right-hand USB-C).
- UART0 / the serial console occupies **GPIO43 / GPIO44** (left-hand USB-C, labelled TX/RX on the silkscreen).
- The onboard RGB LED is on **GPIO48**.
- **GPIO26–32** aren't broken out — internally tied to flash.
- **GPIO33–37** are consumed by octal PSRAM on this module (confirmed **WROOM-1-N16R8** — see [bom.md](../hardware/bom.md)). Off-limits as general I/O.

That leaves the GPIO4–18 range as universally safe, plain-function GPIOs.

## Decision

- **TWAI TX = GPIO4** → SN65HVD230 breakout `CTX`
- **TWAI RX = GPIO5** → SN65HVD230 breakout `CRX`

Rationale:

- Top of the left-hand header — easy to find, easy to probe.
- Adjacent pins → tidy two-wire run to the transceiver, no crossover (matches the `CTX, CRX` order printed on the breakout).
- No strapping role, no peripheral conflict, clear of the octal PSRAM range on N16R8.
- Leaves the adjacent GPIO6/7 pair free for a future I²C bus (display, IMU) without splitting wiring across the board.

## Consequences

- Firmware pin macros (`CAN_TX_PIN`, `CAN_RX_PIN` or equivalent) are fixed at GPIO4 / GPIO5. Any subproject under `firmware/` that talks to the bus uses these.
- The wiring diagram in [can-adapter.md](../hardware/can-adapter.md) is locked to these pins.
- If a future build switches dev board or module (e.g. to a XIAO ESP32-S3 or a custom PCB), the pin numbers will likely change — that change gets its own ADR superseding this one.
- GPIO6/7 are informally reserved for I²C; no other firmware should grab them without an ADR.
