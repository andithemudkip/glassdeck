# wifi-bridge

Phase 2+ untethered CAN capture + browser-served live view for the 2020 Husqvarna Svartpilen 401.

Reads frames off the bike's CAN bus, streams them out over WiFi as SLCAN over WebSocket, and serves a static browser page that decodes them live. Replaces the USB tether for ride captures; `can-logger/` stays alive as the desk USB-CDC path.

**Status:** not built yet — this README is the build plan. See § Milestones for what's staged and where we are.

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

### 1 — Scaffold + TWAI reader

- [ ] `platformio.ini` targeting the S3-DevKitC-1 with the same ESP-IDF version `can-logger/` uses.
- [ ] Lift the TWAI init + read loop out of `can-logger/main/` into shared code. ADR 0016 mentions `firmware/lib/`; either place it there now or fork-and-clean-up later — decide when we start, don't pre-commit here.
- [ ] Boot logs the SDK version, TWAI state, and PSRAM size on USB-CDC so bench bring-up looks the same as `can-logger/`.

**Done when:** flashing the target reads frames off the bike and prints SLCAN to USB-CDC, exactly like `can-logger/` does today. Proves the TWAI half in isolation.

### 2 — WiFi AP + `/health`

- [ ] AP mode, SSID `bike-dash-<lower6 of MAC>`, WPA2 password from `main/wifi_secrets.h` (with `.example` in-tree, real file `.gitignore`'d).
- [ ] Boot prints the SSID + password + IP to USB-CDC.
- [ ] HTTP server up at `192.168.4.1`, single route: `GET /health` returning JSON with uptime, TWAI state, frames-seen counter, WiFi RSSI of connected client.

**Done when:** phone joins the AP, `curl 192.168.4.1/health` from the laptop on the same AP returns sensible JSON, TWAI counter increments while bike is on.

### 3 — WebSocket `/stream`

- [ ] WebSocket endpoint at `/stream`, one CAN frame per text message, exact SLCAN format `scripts/capture.py` already parses.
- [ ] Multi-client support isn't required — a single subscriber is fine for the dev phase. If it falls out of the ESP-IDF WS API for free, keep it; don't spend time on it otherwise.
- [ ] Backpressure: if the WS send queue backs up, drop frames from the WS path (the ring in milestone 4 is the durable copy). Increment a drop counter surfaced on `/health`.

**Done when:** `wscat` from the laptop against `ws://192.168.4.1/stream` produces SLCAN lines identical to what `can-logger/` emits over USB-CDC, and piping them into `scripts/capture.py`'s parser produces the same decoded output as a USB capture of the same bike state. This is the end-to-end transport validation — cheapest possible integration test with the rest of the toolchain.

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

Milestone 1 not started. Waiting on the F7 power perfboard for the untethered bring-up path (§ Milestone 4+ from the bike), but milestones 1–3 can run entirely on desk USB power in parallel.

## Deferred / open

- **Shared TWAI code placement.** ADR 0016 says pull `can-logger/`'s TWAI path into `firmware/lib/`. Decide at milestone 1 whether to do the extraction now or fork-and-clean-up later. Neither is wrong; a fork gets us to a working `/stream` faster, a shared lib avoids drift once both targets are live.
- **Multi-client WS.** ADR 0016 doesn't require it. Only decide if a use case surfaces (e.g. laptop + phone both subscribed).
- **Live view design pass.** Layout, typography, decoded-panel visual language — deferred until milestone 5 lands and there's something concrete to iterate on.
- **STA-mode fallback.** ADR 0016 rejected ESP-as-STA for the dev phase but flagged revisiting if a long ride surfaces where keeping phone cellular matters. Not a milestone here; a follow-up ADR when the need appears.
- **Retirement plan.** When ADR 0014's BLE bridge ships, this whole subproject gets deleted (ADR 0016 § Retirement). Nothing to do until then; noted so it's not a surprise later.

## Out of scope

- Any TX path.
- SD card logging.
- Frame filtering in firmware.
- Timestamping in firmware (SLCAN wire format, host adds timestamps — same as `can-logger/`).
- Native phone app.
