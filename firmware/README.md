# Firmware

ESP32 firmware. Subprojects appear here as they're built:

- `can-logger/` — Phase 1 listen-only CAN logger, SLCAN over USB-CDC.
- `wifi-bridge/` — Phase 2+ untethered capture + browser-served live view. WiFi soft-AP, HTTP `GET /health`, OTA-capable partition table with `POST /ota` (rollback enabled) — iterate over WiFi, no need to unplug USB. See [ADR 0016](../docs/decisions/0016-wifi-dev-capture-and-live-view.md) and `wifi-bridge/README.md` for milestones.
- `dashboard/` — Phase 3+ dashboard application (not yet started).

Each subproject is self-contained: its own `platformio.ini` / `CMakeLists.txt` / build config, its own README describing how to flash and run.

Shared code lives in `lib/`, consumed by subprojects via ESP-IDF's `EXTRA_COMPONENT_DIRS` mechanism (set in each subproject's top-level `CMakeLists.txt`):

- `lib/twai/` — TWAI (CAN) driver ownership: listen-only init, receive wrapper, health-counter accessor. Consumed by `can-logger/` and `wifi-bridge/`.
- `lib/slcan/` — SLCAN (Lawicel ASCII) frame formatter. Consumed by `can-logger/` and `wifi-bridge/`.
- `lib/status_led/` — WS2812 on-board pixel with a state model (boot / CAN-only / wifi-no-client / wifi-client / error) and a CAN-RX pulse overlay. Colors are independent surfaces: base color = which services are up, brief green flashes = frames arriving. Consumed by `can-logger/` and `wifi-bridge/`.

## Hard rules

- Default to **listen-only** (`CAN_MODE_LISTEN_ONLY` or equivalent). Transmit mode must be opt-in, gated behind a compile-time flag, and authorized by a `docs/decisions/` ADR for each TX'd message.
- Firmware behavior that has been verified on the bench or on the bike gets recorded in `docs/findings/hardware/` — don't let the source code be the only documentation.
- Capture sessions identify the firmware they used in their `session.md` — tag firmware versions or commit hashes accordingly.
