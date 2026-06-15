# Firmware

ESP32 firmware. Subprojects appear here as they're built:

- `can-logger/` — Phase 1 listen-only CAN logger (microSD or serial out)
- `dashboard/` — Phase 3+ dashboard application

Each subproject is self-contained: its own `platformio.ini` / `CMakeLists.txt` / build config, its own README describing how to flash and run.

## Hard rules

- Default to **listen-only** (`CAN_MODE_LISTEN_ONLY` or equivalent). Transmit mode must be opt-in, gated behind a compile-time flag, and authorized by a `docs/decisions/` ADR for each TX'd message.
- Firmware behavior that has been verified on the bench or on the bike gets recorded in `docs/findings/hardware/` — don't let the source code be the only documentation.
- Capture sessions identify the firmware they used in their `session.md` — tag firmware versions or commit hashes accordingly.
