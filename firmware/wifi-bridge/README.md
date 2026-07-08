# wifi-bridge

Phase 2+ untethered CAN capture + browser-served live view for the 2020 Husqvarna Svartpilen 401.

Reads frames off the bike's CAN bus, streams them out over WiFi as SLCAN over WebSocket, and serves a static browser page that decodes them live. Replaces the USB tether for ride captures; `can-logger/` stays alive as the desk USB-CDC path.

**Status:** milestones 1–3, 5, 6 code-complete (compile-verified, bench check pending hardware plug-in). Milestone 4 (PSRAM ring + `/capture` download) waits on the F7 power perfboard. M7 (marks) is being re-scoped and folded into M8 (dev view) — see below. See § Milestones for what's staged and where we are, § Current state for the next step.

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
- [ ] SLCAN frames in the ring and WS stream carry on-device timestamps (default format: `(<sec>.<us>) t120800...` matching what `scripts/capture.py` writes to disk). Without this, `GET /capture` returns timestamp-free SLCAN, which is a regression from today's USB-tethered captures. Design context + format options + downstream impact live in § Deferred / open; the actual choice + amended ADR get written when this milestone starts.

**Done when:** power the rig from F7 with the bike off, key on, ride a lap of the block, key off, park, connect phone, download `/capture`, drop it into `logs/YYYY-MM-DD-<condition>/`, run `scripts/inventory_ids.py` on it — output matches what a USB capture of the same drive would produce.

### 5 — Static HTML shell + raw-frame ticker

- [x] One HTML file, vanilla JS, no build step, embedded in the binary via `EMBED_FILES`, gzipped at CMake configure time (~3 KB on the wire).
- [x] Layout skeleton per ADR 0016 § Live view: bus-health header (WS state, RSSI, uptime, TWAI state, frames seen, WS-dropped) up top; empty middle placeholder for M6's decoded panel; raw-frame ticker at the bottom (last 100 frames, dimmest-to-brightest by age).
- [x] Connects to `/stream`, renders raw frames; polls `/health` every 1 s for header state; auto-reconnects on WS drop with 1→2→4→5 s backoff.
- [x] **Added mid-milestone:** eager `execute_process` gzip + `.S` generation in `main/CMakeLists.txt`. PlatformIO's SCons wrapper scans sources at CMake configure time and can't consume ninja custom-command outputs, so both the `.gz` and the ESP-IDF-generated embed `.S` must exist on disk before `idf_component_register` returns. Mirrors what `espidf.py` does internally for mbedtls's cert bundle.

**Done when:** phone browser at `http://192.168.4.1/` shows a scrolling raw-frame ticker with a bus-health header that updates. No decoding yet — this validates the browser side of the transport.

**Post-milestone amendment:** the raw-frame ticker was removed from the rider view mid-M6 once the decoded panel landed and it was clear the ticker was consuming ~30 vh for content unreadable at bike CAN rates (300+ frames/s). The transport-liveness signal moved to a 1-px amber pulse under the header. The ticker itself moves to the dev view (M8) where it belongs alongside anomaly panels; the WS transport / auto-reconnect / bus-health header from this milestone are unchanged.

### 6 — Decoded panel + `signals.yaml` codegen

- [x] Firmware build step reads `docs/signals/signals.yaml`, generates a JS module with a decoder for each `confirmed` signal, embeds it in the HTML. `scripts/gen_wifi_bridge_index.py` (imports `scripts/signals.py`'s validated loader) emits a `SIGNALS[]` table + generic `decodeSignal()` — a direct JS port of `Signal._extract_raw` semantics — into the HTML template at CMake configure time. Data-table + one decoder (not one function per signal) is the same shape the Python side already ships and keeps the gzipped payload smaller.
- [x] Middle panel displays the `confirmed` decoded signals (RPM, coolant, throttle, gear, kill, side stand, clutch, front + rear wheel speeds, engine on/off counters). Status-gated by codegen: `provisional`/`partial` entries in `signals.yaml` don't reach the browser at all. Design pass bundled: verification-cell layout with per-signal arb-ID location strings, peak-value chip for scalars (mirrors the Textual live-view watch pins), and a per-cell freshness bar that decays to zero over 500 ms of arb-ID silence — the "halo" indicator so the operator sees when the surface is lying (ADR 0011). RPM promoted to a hero cell that spans two columns on ≥720 px.
- [x] CI check: `signals.yaml` parses cleanly at build time; broken schema fails the build with a useful error. `load_signals()`'s `SchemaError` surfaces from the codegen script's non-zero exit into CMake `FATAL_ERROR` with the offending entry index attached.

**Done when:** decoded panel matches the OEM dash for the `confirmed` signals during a stationary engine-on test at the desk — RPM, coolant, throttle, gear, kill, side-stand all track.

**Status:** code-complete, compile-verification pending PlatformIO run against the actual ESP-IDF toolchain. Codegen verified standalone (11 confirmed signals emitted; malformed YAML fails with a `SchemaError` naming the entry). Browser design verified in headless Chrome at 375 / 390 / 430 / 844 / 1024 px viewports with mocked SLCAN frames — decoded values match `scripts/signals.py` for the same raw payloads (RPM 1700 from `06 A4`, coolant 87.0 from `03 66`, wheel_speed_front 20.0 from the 12-bit packed slot). Bench check against the bike still owed. **Follow-up refactor:** the raw-frame ticker from M5 was removed from the rider view and the panel expanded to full viewport; a 1-px amber liveness bar under the header replaces the ticker's "yes, frames are arriving" signal. Ticker is not deleted, just relocated — it lands on `/dev` in M8. Rationale: at 300+ frames/s the ticker is an unreadable blur, and the rider view is a glanceable instrument, not a debug surface.

### 7 — `/mark` endpoint (firmware side)

- [ ] `POST /mark?label=<text>` inserts a `# MARK <label>` line into the ring at the current position. Compatible with `scripts/capture.py`'s existing `m` hotkey mark format so downstream tools don't need changes.

Split from the original M7: the endpoint stays here because it's firmware and depends on M4's ring. The **UI** side — a mark button + label input in the browser — moved into M8 where the operator-facing dev view actually lives. The rider view is glanceable-instrument territory; a mark button belongs where the operator is looking (stationary tests, procedure-driven captures, desk replay), not on a phone mounted at handlebar height. See also [[experiment-design-hand-driven-marks]] — riders often can't press marks in real time anyway.

**Done when:** a `curl -X POST 'http://192.168.4.1/mark?label=test'` during an active capture, then a `GET /capture`, produces a file containing `# MARK test` at the right offset, and `scripts/inventory_ids.py` handles it identically to USB-captured marks.

### 8 — Dev view + Active-unknown-bytes port

Second browser-served page at `/dev` (or similar route), served alongside the rider view at `/`. Home for the raw-frame ticker (moved out of M5's rider shell), the anomaly panels borrowed from `scripts/live_view/`, and the mark button. Two pages, one binary — the codegen pattern from M6 extends to a second embedded HTML asset.

- [ ] Route split: `/` (rider view, unchanged) and `/dev` (new, its own embedded HTML). Both served from the same binary via a second `execute_process` + `.S` embed in `main/CMakeLists.txt`. Small header nav on each page linking to the other.
- [ ] Raw-frame ticker restored on `/dev` — same last-N-frames render logic that shipped in M5. Not filtered here; the operator wants to see everything.
- [ ] Active unknown bytes panel — JS port of `ByteActivityStats` from `scripts/live_view/state.py` (per-byte rolling range vs EWMA baseline, peak ratio per activity episode, ADR 0008 + 0012). Filters out bytes covered by `signals.yaml` confirmed entries so the noise floor stays low; surfaces what's happening on the bus that isn't already decoded above. Renders as one row per active `(arb, byte)` with the row's peak ratio, a small display-buffer sparkline, and HOT/WARM/HALO decay tiering identical to the TUI's Active unknown bytes pane.
- [ ] M7b: mark button + label input in the header of `/dev`. Fires `POST /mark?label=<text>` (M7a). Debounces double-taps; toasts a "mark inserted" confirmation.

**Done when:** with the bike running, `/dev` shows a scrolling raw ticker + a live Active unknown bytes panel that highlights bytes changing more than usual (verified by re-running an existing capture through the browser and cross-checking against `scripts/analyze.py`'s output for the same log). The mark button inserts marks that survive to the downloaded `/capture` file.

Not included, deferred to later milestones as they're needed: the per-bit anomaly z-score system (`BaselineStats` from `state.py`), watch pins with sparklines, procedure-driven step sequencing, hypothesis / expect-shape workflow. Those are what the TUI does beyond raw + Active bytes; the long-arc goal is enough parity that `/dev` supersedes `scripts/live_view/`, but this milestone lands only the anomaly panel that has the highest signal-per-line for R&D work. See § Deferred / open.

## Current state

Milestones 1–3, 5, and 6 code-complete and compile-clean. Bench verification against the bike is the next step — one flash validates the WS transport (M3), the browser shell (M5), and the decoded panel (M6) together: flash wifi-bridge, join the AP, open `http://192.168.4.1/` on the phone with the bike on, expect the decoded cells (RPM, coolant, throttle, gear, kill, side-stand, wheel speeds, clutch) to track the OEM cluster and the amber liveness bar under the header to stay lit while the bus is active. Freshness bars should decay to zero within ~500 ms of turning off the ignition. Regression check on M3 (uses the raw stream, which is unchanged): `websocat -n ws://192.168.4.1/stream | python scripts/capture.py --stdin --label ws-smoke` for 60 s, then `python scripts/inventory_ids.py logs/YYYY-MM-DD-ws-smoke/capture.log` — expected output matches prior USB captures (11 always-on IDs, familiar periods).

Milestone 4 (PSRAM ring + `/capture`) and untethered ride captures still wait on the F7 power perfboard. M7a (`/mark` endpoint) is small and can land in the same session as M4 since it writes into the same ring. M8 (dev view + Active unknown bytes port) is a self-contained next chunk that doesn't need hardware.

## Deferred / open

- **Multi-client WS.** ADR 0016 doesn't require it. Only decide if a use case surfaces (e.g. laptop + phone both subscribed).
- **Live view design pass.** Bundled into M6 — the decoded panel got a deliberate visual pass (verification-cell layout, Husqvarna competition amber accent, freshness-bar halo, peak chips). Any further iteration is now down to what a real ride surfaces.
- **STA-mode fallback.** ADR 0016 rejected ESP-as-STA for the dev phase but flagged revisiting if a long ride surfaces where keeping phone cellular matters. Not a milestone here; a follow-up ADR when the need appears.
- **Long-term role vs ADR 0016 § Retirement.** ADR 0016 assumes this target gets deleted once ADR 0014's BLE bridge ships. That's likely too aggressive — WiFi + browser has real long-term value the BLE bridge can't cheaply replicate: high-bandwidth log pull after a ride, diagnostic mode for the production dashboard, a fallback path if BLE fails in the field, and a debug channel that any device with a browser can hit without a native app. When ADR 0014 gets close to shipping, revisit as an amended or superseding ADR — decide then whether this target retires, or stays as a dev/diagnostic sidecar alongside BLE. Nothing to do until then; flagged so the "just delete it" assumption in ADR 0016 doesn't get taken as settled.
- **On-device timestamps for the ring + WS stream (M4 companion).** ADR 0016 § Out of scope currently says "Timestamping in firmware — SLCAN wire format, host adds timestamps — same as `can-logger/`." That worked when the only egress was USB-CDC into a live host that stamped on receive. Once M4 lands and `GET /capture` starts returning ring dumps hours after the fact, host-side stamping no longer applies — the download is timestamp-free SLCAN, which loses ordering precision every analysis script downstream is used to. Fix: stamp in the RX loop using `esp_timer_get_time()` (int64 µs since boot, already used for `/health` uptime — no RTC, no NTP, monotonic relative-time, same semantics `capture.py` produces on disk today). Effort is ~15 lines of C in the TWAI RX loop + a `slcan_format_frame_ts()` variant in `firmware/lib/slcan/`. Format decision to make when we build it — three candidates:
  - **`(<sec>.<us>) t120800...`** (recommended default). Matches `capture.py`'s on-disk format byte-for-byte; existing analysis scripts consume the stream with zero changes. ~14 extra bytes/frame → ~30% larger ring footprint (4 MB ring: ~5 min at 300 fps → ~4 min).
  - **Canusb `T` extension:** 4-hex-digit ms suffix on the SLCAN line (`t120800...XXXX\r`), gated by a session-mode command. ~4 bytes/frame. Wraps every 60 s; needs host-side unwrapping. Compatible with third-party CAN tooling.
  - **Raw `<us_hex> t120800...`** prefix. Small, monotonic, no wrap, but no downstream tool speaks it — every consumer needs a new parser branch.

  Downstream: `capture.py --stdin` needs a regex loosen to accept both prefixed and unprefixed lines (existing captures don't have timestamps). Everything else in `scripts/` that goes through `signals.py` is timestamp-agnostic and needs no change.

  Kicker: this needs to land in M4, not after — the ring format is what `GET /capture` serialises, so retrofit means invalidating older captures or dual-format code. Amend ADR 0016's "no firmware timestamps" line via a new ADR (`docs/decisions/NNNN-on-device-timestamps.md`, project convention is supersede-don't-rewrite) at the same time.
- **`/dev` view superseding `scripts/live_view/`.** The Textual TUI does much more than an anomaly panel: watch pins with sparklines, per-bit z-score anomalies (ADR 0007's `BaselineStats`), procedure-driven step sequencing off a `.procedure.yaml`, the hypothesis / expect-shape workflow, operator vs analysis screens, session mark orchestration. M8 is the first step (raw ticker + Active unknown bytes) but full parity is several milestones out — probably one per subsystem, roughly in the order R&D leans on them. The intent is that once parity lands, `scripts/live_view/` retires and `capture.py` speaks to the ESP for procedures + marks instead of driving the TUI directly. Not a milestone here; captured so the direction is on file.

## Out of scope

- Any TX path.
- SD card logging.
- Frame filtering in firmware.
- Timestamping in firmware (SLCAN wire format, host adds timestamps — same as `can-logger/`).
- Native phone app.
