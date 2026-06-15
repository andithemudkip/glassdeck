# 0003 — Firmware framework: ESP-IDF, built via PlatformIO

**Date:** 2026-06-16
**Status:** Accepted

## Context

The ESP32-S3 family supports several development frameworks: Espressif's native ESP-IDF, Arduino-ESP32, or a wrapper like PlatformIO over either. The choice locks in build tooling, dependency management, and the surface of APIs used across every subproject under `firmware/`.

The first subproject is `can-logger/` — small and self-contained — but the next is `dashboard/`, which will likely want LVGL via Espressif's component manager, finer RTOS control, and possibly ESP-NOW for telemetry. The framework decision now should anticipate both.

Relevant facts about TWAI specifically: Arduino-ESP32's CAN API is a thin wrapper over the same `driver/twai.h` from ESP-IDF. Using Arduino doesn't hide IDF concepts (`twai_general_config_t`, `TWAI_MODE_LISTEN_ONLY`, etc.) — it just adds a translation layer that has to be unwound when reading reference docs.

## Decision

- **Framework:** ESP-IDF (native Espressif framework, not Arduino-ESP32).
- **Build wrapper:** PlatformIO (`platformio.ini` per subproject), targeting the `espressif32` platform with `framework = espidf`.
- IDF version is pinned via PlatformIO so "clone the repo and build" reproduces across machines without manual IDF setup.
- Each subproject under `firmware/` is its own PlatformIO project.

## Consequences

- TWAI driver is used directly via `driver/twai.h` — no Arduino abstraction. Listen-only mode, bitrate, filters, alerts all configured through the IDF API.
- PlatformIO handles toolchain and IDF version pinning. Contributors install PlatformIO (CLI or VSCode extension); they do not separately install ESP-IDF.
- Component-manager components (LVGL, etc.) are available to future subprojects without framework migration.
- Cost: PlatformIO's first-time install is heavier than `idf.py` alone, and IDF builds are slower than Arduino's. Acceptable for the reproducibility win.
- If a contributor strongly prefers raw `idf.py`, the project layout doesn't prevent that — `platformio.ini` and `CMakeLists.txt` coexist. PlatformIO remains the documented default.
- Switching framework later (e.g. to ESP-HAL Rust) would supersede this ADR.
