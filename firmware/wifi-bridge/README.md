# wifi-bridge

Phase 2+ untethered CAN capture + browser-served live view for the 2020 Husqvarna Svartpilen 401.

Reads frames off the bike's CAN bus, streams them out over WiFi as SLCAN over WebSocket, and serves a static browser page that decodes them live. Replaces the USB tether for ride captures; `can-logger/` stays alive as the desk USB-CDC path.

**Status:** milestones 1–3 code-complete (compile-verified, bench check pending hardware plug-in). See § Milestones for what's staged and where we are, § Current state for the next step.

## Goal

Deliver an untethered dev-phase capture rig with a rider-visible live decoded view, without committing to the React Native + BLE stack that ADR 0014 will eventually build for the production dashboard. Full context and the discarded alternatives (microSD, BLE-now, ESP-as-STA) are in [ADR 0016](../../docs/decisions/0016-wifi-dev-capture-and-live-view.md); the wire format is unchanged SLCAN so every existing `scripts/` tool consumes downloaded captures with no changes.

## Design decisions

- [ADR 0002](../../docs/decisions/0002-twai-gpio-assignment.md) — TWAI on GPIO4 / GPIO5 (unchanged).
- [ADR 0003](../../docs/decisions/0003-firmware-framework-esp-idf.md) — ESP-IDF via PlatformIO (unchanged).
- [ADR 0015](../../docs/decisions/0015-f7-12v-power-path.md) — 12V-from-F7 power path; USB stays available at the desk.
- [ADR 0016](../../docs/decisions/0016-wifi-dev-capture-and-live-view.md) — this subproject. WiFi-AP, HTTP + WebSocket, PSRAM ring, browser-served live view.

Golden no-TX rule applies. `TWAI_MODE_LISTEN_ONLY` at boot, no compile-time TX option.

## Milestones

Ordered so each step is independently verifiable. USB-powered at the desk is fine until milestone 4 — power source is transparent to everything above the TWAI driver.

### 1 — Scaffold + shared TWAI lib

- [x] Extract the TWAI init + read loop from `can-logger/main/` into `firmware/lib/twai/` — shared code both targets depend on. `can-logger/` migrates to consume the lib in the same change, no functional change to its behavior.
- [x] Extract SLCAN formatter into `firmware/lib/slcan/` alongside — added mid-milestone to avoid duplicate `format_slcan()` copies once wifi-bridge also emits SLCAN.
- [x] `platformio.ini` for `wifi-bridge/` targeting the S3-DevKitC-1 with the same ESP-IDF version `can-logger/` uses; consumes `firmware/lib/twai/`.
- [x] Boot logs the SDK version, TWAI state, and PSRAM size on USB-CDC. Intentional divergence from `can-logger/`: bridge USB-CDC isn't a data pipe, so logs are visible (no `_LOG_LEVEL_WARN` muting).

**Done when:** flashing the target reads frames off the bike and prints SLCAN to USB-CDC, exactly like `can-logger/` does today, *and* `can-logger/` still passes its bench check on the same bike after the lib extraction. Proves the TWAI half in isolation and that the extraction didn't regress the existing logger.

**Status:** builds pass for both `can-logger` (500k + 250k envs) and `wifi-bridge`. Bench check against the bike deferred to a milestone 2/3 end-to-end run.

### 2 — WiFi AP + `/health` + OTA update endpoint

- [x] AP mode, SSID `bike-dash-<lower6 of MAC>`, WPA2 password from `main/wifi_secrets.h` (with `.example` in-tree, real file `.gitignore`'d).
- [x] Boot prints the SSID + password + IP to USB-CDC.
- [x] HTTP server up at `192.168.4.1`, `GET /health` returning JSON with uptime, TWAI health (state + bus_err + rx_missed + rx_overrun), frames-seen counter, connected-client count + RSSI.
- [x] **Added mid-milestone:** OTA-capable partition table (`partitions.csv`, 2× 3 MB app slots on 8 MB flash). Default 1 MB `factory` partition was already 79% full after the WiFi stack pulled in; this gives ~10× headroom and lets subsequent milestones flash over WiFi.
- [x] **Added mid-milestone:** `POST /ota` endpoint (streams a `firmware.bin` from the client into the inactive OTA slot, marks bootable, restarts). Bootloader rollback (`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y`) reverts to the previous slot if the new firmware fails to reach the "WiFi + HTTP up" mark in `app_main`.

**Done when:** phone joins the AP, `curl 192.168.4.1/health` from the laptop on the same AP returns sensible JSON, frames-seen counter increments while bike is on, `curl -X POST --data-binary @firmware.bin http://192.168.4.1/ota` boots the new image cleanly.

### 3 — WebSocket `/stream`

- [x] WebSocket endpoint at `/stream`, one CAN frame per text message, exact SLCAN format `scripts/capture.py` already parses. Wire format is byte-identical to `can-logger/`'s USB-CDC output by construction — both go through `slcan_format_frame` in `firmware/lib/slcan/`.
- [x] Multi-client support falls out of the ESP-IDF API — `httpd_get_client_list` + `httpd_ws_get_fd_info` per outgoing frame, no manual fd tracking or mutex. Framework handles disconnects.
- [x] Backpressure: bounded FreeRTOS queue (64 slots × 33 bytes) between RX loop and WS sender task. `xQueueSendToBack(..., 0)` drops new frames when full; `frames_ws_dropped` counter on `/health` is the "capture degraded" signal.
- [x] **Added mid-milestone:** `scripts/capture.py --stdin` — reads SLCAN from stdin instead of a serial port so the done-when integration test works without a bridge script (`websocat -n ws://192.168.4.1/stream | capture.py --stdin --label ws-smoke`).

**Done when:** `wscat`/`websocat` from the laptop against `ws://192.168.4.1/stream` produces SLCAN lines identical to what `can-logger/` emits over USB-CDC, and piping them into `scripts/capture.py --stdin` produces the same decoded output as a USB capture of the same bike state. This is the end-to-end transport validation — cheapest possible integration test with the rest of the toolchain.

### 4 — PSRAM ring + `/capture` download

- [ ] 4 MB ring buffer in PSRAM, allocated at boot. TWAI reader writes into the ring *before* WiFi is up so cold-boot frames aren't lost (per ADR 0016 § Capture buffer).
- [ ] Drop-oldest on overflow. Drop counter surfaced on `/health`.
- [ ] `GET /capture` streams the ring as a `.log` file with `Content-Disposition: attachment; filename="capture-<uptime>-<frames_seen>.log"` — filename embeds enough to disambiguate two downloads from one boot.

**Done when:** power the rig from F7 with the bike off, key on, ride a lap of the block, key off, park, connect phone, download `/capture`, drop it into `logs/YYYY-MM-DD-<condition>/`, run `scripts/inventory_ids.py` on it — output matches what a USB capture of the same drive would produce.

### 5 — Static HTML shell + raw-frame ticker

- [ ] One HTML file, vanilla JS, no build step, embedded in the binary (SPIFFS image or `EMBED_FILES`), gzipped.
- [ ] Layout skeleton per ADR 0016 § Live view: bus-health header (RSSI, uptime, frames seen, frames dropped) up top; empty middle; raw-frame ticker at the bottom (last N frames, dimmest-to-brightest by age).
- [ ] Connects to `/stream`, renders raw frames.

**Done when:** phone browser at `http://192.168.4.1/` shows a scrolling raw-frame ticker with a bus-health header that updates. No decoding yet — this validates the browser side of the transport.

### 6 — Decoded panel + `signals.yaml` codegen

- [ ] Firmware build step reads `docs/signals/signals.yaml`, generates a JS module with a decoder for each `confirmed` signal, embeds it in the HTML.
- [ ] Middle panel displays the `confirmed` decoded signals (RPM, coolant, throttle, gear, kill, side stand, clutch, wheel speeds). Status-gated: signals whose status isn't `confirmed` don't render at all in v1.
- [ ] CI check: `signals.yaml` parses cleanly at build time; broken schema fails the build with a useful error.

**Done when:** decoded panel matches the OEM dash for the `confirmed` signals during a stationary engine-on test at the desk — RPM, coolant, throttle, gear, kill, side-stand all track.

### 7 — `/mark` endpoint

- [ ] `POST /mark?label=<text>` inserts a `# MARK <label>` line into the ring at the current position.
- [ ] Live view exposes a mark button that hits the endpoint.
- [ ] Compatible with `scripts/capture.py`'s existing `m` hotkey mark format so downstream tools don't need changes.

**Done when:** a downloaded capture contains `# MARK <label>` lines at the right positions, and existing mark-aware analysis tools (`inventory_ids.py`, etc.) treat them identically to USB-captured marks.

## Current state

Milestones 1–3 code-complete and compile-clean. Bench verification against the bike is now the next step — all three milestones get validated in one shot by flashing wifi-bridge, joining the AP, and running `websocat -n ws://192.168.4.1/stream | python scripts/capture.py --stdin --label ws-smoke` for 60 s with the bike on, then `python scripts/inventory_ids.py logs/YYYY-MM-DD-ws-smoke/capture.log` — expected output matches prior USB captures (11 always-on IDs, familiar periods). Untethered ride captures still wait on the F7 power perfboard (milestone 4+).

## Deferred / open

- **Multi-client WS.** ADR 0016 doesn't require it. Only decide if a use case surfaces (e.g. laptop + phone both subscribed).
- **Live view design pass.** Layout, typography, decoded-panel visual language — deferred until milestone 5 lands and there's something concrete to iterate on.
- **STA-mode fallback.** ADR 0016 rejected ESP-as-STA for the dev phase but flagged revisiting if a long ride surfaces where keeping phone cellular matters. Not a milestone here; a follow-up ADR when the need appears.
- **Long-term role vs ADR 0016 § Retirement.** ADR 0016 assumes this target gets deleted once ADR 0014's BLE bridge ships. That's likely too aggressive — WiFi + browser has real long-term value the BLE bridge can't cheaply replicate: high-bandwidth log pull after a ride, diagnostic mode for the production dashboard, a fallback path if BLE fails in the field, and a debug channel that any device with a browser can hit without a native app. When ADR 0014 gets close to shipping, revisit as an amended or superseding ADR — decide then whether this target retires, or stays as a dev/diagnostic sidecar alongside BLE. Nothing to do until then; flagged so the "just delete it" assumption in ADR 0016 doesn't get taken as settled.

## Out of scope

- Any TX path.
- SD card logging.
- Frame filtering in firmware.
- Timestamping in firmware (SLCAN wire format, host adds timestamps — same as `can-logger/`).
- Native phone app.
