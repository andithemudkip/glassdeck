# Status

**Phase:** 0 — establishing CAN access.

**Last updated:** 2026-06-16

## Hardware on hand

- ESP32-S3-DevKitC-1 (WROOM-1-N16R8 module) — see `docs/hardware/bom.md`
- SN65HVD230 breakout (fixed high-speed mode, on-board termination present)
- Diagnostic connector pinout confirmed — see `docs/hardware/diagnostic-connector.md`

## In progress

- Hardware decisions locked: pinout, GPIO assignment, transceiver mode, power path, termination plan — see `docs/hardware/can-adapter.md`.
- Framework + wire format decisions locked — see ADRs 0003 (ESP-IDF via PlatformIO) and 0004 (SLCAN over USB-CDC).
- `firmware/can-logger/` scaffolded (README only — no code yet).

## Blocked on

- Nothing structural — ready to write the logger firmware and the host-side capture script.

## Next actions

1. Build the physical adapter: ESP32-S3 + SN65HVD230 + connector pigtail, per `docs/hardware/can-adapter.md`.
2. Stand up `firmware/can-logger/` PlatformIO project: ESP-IDF target, TWAI in listen-only mode on GPIO4/5, SLCAN emit loop. Start at 500 kbps with a `#define` or Kconfig to drop to 250 kbps if needed.
3. Write the host-side capture script under `scripts/` — `python-can` SLCAN bus → raw capture file into `logs/YYYY-MM-DD-key-on/`.
4. First capture session: **start logging before key-on** and run continuously through the full self-test into steady-state idle. Goal is to confirm bus is alive, lock the bitrate, and capture the boot-time dash↔ECU exchange that initializes ABS/TC/QS — community reports (see `docs/references/husqvarna-community-notes.md`) suggest this window contains traffic that's easy to miss with a late capture start.
5. Promote the confirmed bitrate to a finding under `docs/findings/can/`.

## Open questions (from `docs/research.md`)

1. Can the OEM dashboard be completely disconnected?
2. Does the ECU expect messages from the dashboard?
3. How similar is the KTM 390 CAN map to the KTM 690 CAN map?
4. Which signals are already available as broadcasts?
5. How are ROAD/SUPERMOTO commands transmitted?
