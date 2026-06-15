# Listen-only CAN adapter

Full pinout for the Phase 0 / Phase 1 adapter: bike diagnostic connector → SN65HVD230 CAN transceiver → ESP32-S3.

Listen-only by firmware default (`CAN_MODE_LISTEN_ONLY` / TWAI no-ack). The hardware itself is capable of TX; the gate against transmission lives in firmware, per the project's golden rule.

## Block diagram

```
Bike diagnostic connector          SN65HVD230 breakout              ESP32-S3
─────────────────────────          ──────────────────              ────────
  pin 2  CH  ───────────────────►  CANH
  pin 5  CL  ───────────────────►  CANL
  pin 3  GD  ───────┬───────────►  GND  ──────────────┬──────────►  GND
                    │                                 │
                    │                  3V3  ◄─────────┼──────────── 3V3
                    │                  CTX  ◄──────────────────────  GPIO4 (TWAI TX)
                    │                  CRX  ──────────────────────►  GPIO5 (TWAI RX)
  pin 4  F7  ─ ─ ─ ─┘ (not wired — USB-powered during development, see ADR 0001)
```

## Bike-side connector

Bike-side pin assignments live in [diagnostic-connector.md](diagnostic-connector.md). Summary:

| Connector pin | Signal | To |
|---|---|---|
| 2 | CANH | SN65HVD230 pin 7 |
| 5 | CANL | SN65HVD230 pin 6 |
| 3 | GND  | Adapter ground rail |
| 4 | +12V switched | Not connected during development — see [ADR 0001](../decisions/0001-usb-power-during-development.md) |

## SN65HVD230 breakout board (3.3V CAN transceiver)

The breakout exposes 6 pins; the chip's Rs and Vref are handled on-board (Rs is typically tied to GND through a small resistor for high-speed mode).

| Pin  | Connection | Notes |
|------|------------|-------|
| 3V3  | ESP32-S3 3V3 rail | 3.3V only — do **not** connect to 5V or to bike 12V. |
| GND  | Adapter ground | Common with ESP32 GND and bike GND (diagnostic pin 3). |
| CTX  | ESP32-S3 GPIO4 | Chip's D/TXD pin. Held recessive by firmware in listen-only mode. |
| CRX  | ESP32-S3 GPIO5 | Chip's R/RXD pin. |
| CANH | Diagnostic connector pin 2 (CH) | |
| CANL | Diagnostic connector pin 5 (CL) | |

### Termination

The bike's CAN bus already has termination at the ECU/dash ends of the backbone (2× 120 Ω → 60 Ω bus impedance). The diagnostic port is a stub.

The common SN65HVD230 breakout boards ship with a termination resistor populated between CANH and CANL. Adding it in parallel with the bike's existing termination drops bus impedance to ~40 Ω, which is out of spec — but at 500 kbps over a short stub, listen-only reception usually still works.

**Plan:** leave the breakout's resistor in place for the first capture session and see what happens. Don't desolder blind — the board can't be cleanly measured without a multimeter, and the mod is irreversible.

- If frames decode cleanly → document as a finding (`docs/findings/hardware/adapter-termination.md`): "extra 120 Ω at the diagnostic port is tolerated on this bike at 500 kbps." Leave it.
- If no traffic, or CRC / bit errors → measure the resistor, log an experiment under `docs/experiments/`, then desolder and recapture.

## ESP32-S3 side

Board: ESP32-S3-DevKitC-1 — see [bom.md](bom.md).

| ESP32-S3 pin | Connection | Notes |
|---|---|---|
| GPIO4 | Breakout CTX | TWAI controller TX. Locked by [ADR 0002](../decisions/0002-twai-gpio-assignment.md). |
| GPIO5 | Breakout CRX | TWAI controller RX. Locked by [ADR 0002](../decisions/0002-twai-gpio-assignment.md). |
| 3V3 | Breakout 3V3 | Transceiver power. |
| GND | Breakout GND + diagnostic pin 3 | Single common ground. |
| USB | Laptop / USB battery | Power during development per [ADR 0001](../decisions/0001-usb-power-during-development.md). |

## Open items

- [ ] Confirm CAN bitrate by capture (hypothesis: 500 kbps).
- [ ] Confirm first capture works with the breakout's on-board termination in place; remove it only if traffic is bad.
- [ ] 12V power path for mounted test rides — deferred per ADR 0001.
