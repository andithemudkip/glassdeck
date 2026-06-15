# can-logger

Phase 1 listen-only CAN logger for the 2020 Husqvarna Svartpilen 401.

Reads frames off the bike's CAN bus via the SN65HVD230 transceiver and streams them out the ESP32-S3's USB-CDC serial as SLCAN ASCII for the host-side capture script under `scripts/` to consume.

**Status:** scaffold only — no code yet.

## Hardware

- ESP32-S3-DevKitC-1 (WROOM-1-N16R8 module).
- SN65HVD230 breakout (3.3V CAN transceiver, on-board termination, fixed high-speed mode).
- TWAI TX = GPIO4, TWAI RX = GPIO5.
- Powered over USB-CDC from the host laptop during development.

Full wiring: [`docs/hardware/can-adapter.md`](../../docs/hardware/can-adapter.md). BOM: [`docs/hardware/bom.md`](../../docs/hardware/bom.md).

## Design decisions

This subproject is governed by:

- [ADR 0001](../../docs/decisions/0001-usb-power-during-development.md) — USB power during development, F7 not wired.
- [ADR 0002](../../docs/decisions/0002-twai-gpio-assignment.md) — TWAI on GPIO4 / GPIO5.
- [ADR 0003](../../docs/decisions/0003-firmware-framework-esp-idf.md) — ESP-IDF via PlatformIO.
- [ADR 0004](../../docs/decisions/0004-logger-wire-format-slcan.md) — SLCAN over USB-CDC, firmware-to-host only.

## Behavior

1. Initialise the TWAI driver in **listen-only mode** (`TWAI_MODE_LISTEN_ONLY`). The peripheral never transmits, never acks — golden rule of the project until OEM messages are decoded.
2. Start at **500 kbps**. If the first capture is silent, the documented fallback is to rebuild at 250 kbps. Whichever rate produces traffic is captured as a finding under `docs/findings/can/`.
3. For each received frame, format as SLCAN (`t...` for 11-bit, `T...` for 29-bit) and write to USB-CDC serial, line-terminated with `\r`.
4. No host→adapter command handling. Configuration is compile-time.

Bitrate is the only thing meant to change between builds at this stage; expose it as a `Kconfig` option or a `#define` at the top of `main.c`.

## Build / flash

To be filled in once the PlatformIO scaffolding lands. Expected commands:

```
pio run                       # build
pio run --target upload       # flash via USB
pio device monitor            # raw SLCAN stream on serial
```

## Tagging captures

Every capture session records the firmware commit it used in its `session.md` (see `logs/` convention in `CLAUDE.md`). When this logger gets meaningful changes, capture sessions are tagged with the git short hash of the firmware they ran.

## Out of scope for v1

- Timestamping in firmware (host adds timestamps; revisit per ADR 0004 if jitter ever matters).
- SD card logging (USB-tethered captures are sufficient for stationary work; mounted test rides are a deferred sub-project per ADR 0001).
- Frame filtering (capture everything; filter downstream).
- Any TX path.
