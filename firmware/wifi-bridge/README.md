# wifi-bridge

Phase 2+ untethered CAN capture + browser-served live view for the 2020 Husqvarna Svartpilen 401.

Reads frames off the bike's CAN bus, streams them out over WiFi as SLCAN over WebSocket, and serves a static browser page that decodes them live. Replaces the USB tether for ride captures; `can-logger/` stays alive as the desk USB-CDC path.

**Status:** milestones 1–6 + M7a code-complete (compile-verified, bench check pending hardware plug-in). Milestone 4 (gap-fill ring + browser-side OPFS capture) landed alongside the firmware-side of M7 (`POST /mark`) — see M4/M7a below. Only the M7b UI (mark button on the dev view) is deferred into M8. See § Milestones for what's staged and where we are, § Current state for the next step.

## Goal

Deliver an untethered dev-phase capture rig with a rider-visible live decoded view, without committing to the React Native + BLE stack that ADR 0014 will eventually build for the production dashboard. Full context and the discarded alternatives (microSD, BLE-now, ESP-as-STA) are in [ADR 0016](../../docs/decisions/0016-wifi-dev-capture-and-live-view.md); the wire format is unchanged SLCAN so every existing `scripts/` tool consumes downloaded captures with no changes.

## Design decisions

- [ADR 0002](../../docs/decisions/0002-twai-gpio-assignment.md) — TWAI on GPIO4 / GPIO5 (unchanged).
- [ADR 0003](../../docs/decisions/0003-firmware-framework-esp-idf.md) — ESP-IDF via PlatformIO (unchanged).
- [ADR 0015](../../docs/decisions/0015-f7-12v-power-path.md) — 12V-from-F7 power path; USB stays available at the desk.
- [ADR 0016](../../docs/decisions/0016-wifi-dev-capture-and-live-view.md) — this subproject. WiFi-AP, HTTP + WebSocket, PSRAM ring, browser-served live view.
- [ADR 0018](../../docs/decisions/0018-m4-browser-primary-capture.md) — amends 0016 for M4: browser-primary OPFS capture, ~512 KB gap-fill ring, `(<sec>.<us>)` on-device timestamps, `?since=` splice protocol.

Golden no-TX rule applies. `TWAI_MODE_LISTEN_ONLY` at boot, no compile-time TX option.

## Milestones

Ordered so each step is independently verifiable. USB-powered at the desk is fine throughout — power source is transparent to everything above the TWAI driver. F7 becomes necessary only for actual on-bike ride captures, not for milestone validation.

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

### 4 — Gap-fill ring + browser-side OPFS capture

Scope narrowed from ADR 0016's original 4 MB / phone-free-ride framing — see [ADR 0018](../../docs/decisions/0018-m4-browser-primary-capture.md) for the amended design. Primary log sink is the browser's OPFS, written continuously as frames arrive; the firmware ring is a short-lived backstop that lets the browser splice over transient WS disconnects.

- [x] ~512 KB PSRAM ring (`RING_SLOTS = 8192` × 64-byte slots), ~27 s at 300 fps with the timestamp prefix. Allocated at boot via `heap_caps_malloc(MALLOC_CAP_SPIRAM)`; TWAI reader writes into it *before* WiFi is up so cold-boot frames aren't lost. Drop-oldest on overflow, `frames_ring_dropped` counter surfaced on `/health`.
- [x] On-device timestamps in the RX loop via `esp_timer_get_time()` (µs since boot, monotonic — same clock `/health` uptime already uses). Ring entries and WS-emitted frames carry the same stamp. Wire format: **`(<sec>.<us>) t120806A4...\r`** — byte-for-byte match to what `scripts/capture.py` writes to disk today (~14 extra bytes/frame). Locked in ADR 0018 § On-device timestamps. Buffer sizing: `SLCAN_TS_PREFIX_MAX = 24` sibling constant added to `firmware/lib/slcan/include/slcan.h`; `SLCAN_MAX_LINE_BYTES = 56` is the combined-buffer ceiling used by the ring + WS queue slot.
- [x] `GET /capture?since=<ts_us>` streams every ring entry with `ts > since`, in order, chunked. Bare `GET /capture` returns the full current ring. `X-Bike-Gap-Ms: <ms>` response header when `since` precedes the ring's earliest surviving entry. Snapshot-under-spinlock read pattern; writer never blocks.
- [x] Browser writes frames to OPFS via `navigator.storage.getDirectory()` + `createWritable({keepExistingData:true})` in ~500 ms batches. Tracks `lastPersistedTs` in memory; snapshots to `active-capture.json` in OPFS on every flush so a page reload picks up mid-capture.
- [x] **Backfill protocol on WS reconnect:** live consumption pauses into `resumeBuffer` → `GET /capture?since=<lastPersistedTs>` → append body to OPFS → advance `lastPersistedTs` to the highest ts returned → drain `resumeBuffer` dropping frames already covered → resume live-WS→OPFS. Runs identically for the 1st, 2nd, Nth reconnect. Also fires on the first WS connect after a page reload if the sidecar shows a resumed capture.
- [x] Gap markers: on `X-Bike-Gap-Ms: <ms>`, browser writes `# GAP <ms>\r\n` into OPFS immediately before the backfill body. Same comment-prefix convention as `# MARK` (M7a).
- [x] Wake-lock + install path: rider view acquires `navigator.wakeLock` on capture start; releases on stop/export; reacquires on `visibilitychange`. iOS Safari sees an "Add to Home Screen" hint (dismissible, persisted in `localStorage`). Chrome desktop / Android Chrome call `navigator.storage.persist()` on start; iOS ignores it and relies on the install path.
- [x] Export flow: header "Export" button (visible after Stop or on page reload with a sidecar) reads the OPFS file as a `Blob` and triggers a download named `capture-<startIso>-<frames>.log`. Single code path across platforms.
- [x] **Existing browser-view parsers.** M6's decoded panel now strips the `(<sec>.<us>) ` prefix in `ws.onmessage` before dispatching to `parseSlcan`/`routeFrame`; `lastFrameTs` is captured for the backfill anchor. Backward compatible with an unprefixed frame (drops through untouched).
- [x] Downstream: `scripts/capture.py --stdin` accepts both prefixed and unprefixed lines; when the prefix is present the parsed µs seconds replace the host `time.time()` as `msg.timestamp` so the on-disk `capture.log` carries firmware-side timing end-to-end. `scripts/inventory_ids.py` logs `# GAP <ms>` markers to stderr (log-and-skip); `# MARK` continues to fall through silently.

**Done when:** USB-power the rig at the desk with the bike attached and key-on, phone on the AP, load `192.168.4.1/`, Add to Home Screen, Start capture, toggle phone WiFi off for ~10 s, back on, Stop, Export. Downloaded log is byte-identical to what a continuous USB `can-logger/` capture of the same bike state would produce, minus at most a handful of frames right at the reconnect boundary. Then repeat with a ~60 s disconnect (> ring capacity): downloaded log contains exactly one `# GAP <ms>` marker at the boundary, `ms` value matches wall-clock disconnect time within a second, `scripts/inventory_ids.py` handles the marker cleanly.

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

- [x] `POST /mark?label=<text>` inserts a `# MARK <label>` line into the ring at the current position and also fans it out on `/stream` so live viewers see it immediately. Label is URL-decoded, trimmed, capped at 63 chars, control characters replaced with `?`. Empty label → 400. Compatible with `scripts/capture.py`'s existing `m` hotkey mark format so downstream tools don't need changes.

Split from the original M7: the endpoint landed with M4 because it writes into the same ring. The **UI** side — a mark button + label input in the browser — moved into M8 where the operator-facing dev view actually lives. The rider view is glanceable-instrument territory; a mark button belongs where the operator is looking (stationary tests, procedure-driven captures, desk replay), not on a phone mounted at handlebar height. See also [[experiment-design-hand-driven-marks]] — riders often can't press marks in real time anyway.

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

Milestones 1–6 + M7a code-complete and compile-clean (both `wifi-bridge` and `can-logger` build with the `SLCAN_MAX_LINE_BYTES` bump). Bench verification against the bike is the next step — one flash validates the WS transport (M3), the decoded panel (M6), the new capture pipeline (M4), and marks (M7a) together:

1. `curl -X POST --data-binary @.pio/build/wifi-bridge/firmware.bin http://192.168.4.1/ota` — OTA the new build (bootloader rollback fires if it can't reach WiFi+HTTP).
2. `curl 'http://192.168.4.1/capture' | head` — expect `(<sec>.<us>) t...\r` lines (M4 timestamps land).
3. `curl -X POST 'http://192.168.4.1/mark?label=smoke'` → `curl 'http://192.168.4.1/capture' | grep '# MARK'` — expect `# MARK smoke\r` (M7a).
4. On the phone: open `http://192.168.4.1/`, Add to Home Screen, **Start capture**, toggle WiFi off for ~10 s, back on, Stop, Export.
5. Downloaded file → `python scripts/capture.py --stdin --label m4-smoke < downloaded.log` — writes `logs/YYYY-MM-DD-m4-smoke/capture.log` with firmware-side timestamps.
6. `python scripts/inventory_ids.py logs/YYYY-MM-DD-m4-smoke/` — 11 always-on IDs, familiar periods, `# GAP` lines (if any) on stderr.

Ring-overflow test: repeat step 4 with a ~60 s disconnect (> ring capacity) and expect exactly one `# GAP <ms>` marker at the boundary, `ms` within ~1 s of wall-clock.

M8 (dev view + Active unknown bytes port) is the next self-contained chunk and doesn't need hardware. Actual on-bike ride captures still wait on the F7 power perfboard, but that's a validation-scope question.

## Deferred / open

- **Multi-client WS.** ADR 0016 doesn't require it. Only decide if a use case surfaces (e.g. laptop + phone both subscribed).
- **Live view design pass.** Bundled into M6 — the decoded panel got a deliberate visual pass (verification-cell layout, Husqvarna competition amber accent, freshness-bar halo, peak chips). Any further iteration is now down to what a real ride surfaces.
- **STA-mode fallback.** ADR 0016 rejected ESP-as-STA for the dev phase but flagged revisiting if a long ride surfaces where keeping phone cellular matters. Not a milestone here; a follow-up ADR when the need appears.
- **Long-term role vs ADR 0016 § Retirement.** ADR 0016 assumes this target gets deleted once ADR 0014's BLE bridge ships. That's likely too aggressive — WiFi + browser has real long-term value the BLE bridge can't cheaply replicate: high-bandwidth log pull after a ride, diagnostic mode for the production dashboard, a fallback path if BLE fails in the field, and a debug channel that any device with a browser can hit without a native app. When ADR 0014 gets close to shipping, revisit as an amended or superseding ADR — decide then whether this target retires, or stays as a dev/diagnostic sidecar alongside BLE. Nothing to do until then; flagged so the "just delete it" assumption in ADR 0016 doesn't get taken as settled.
- **Phone-free / ESP-only ride captures.** ADR 0016's original M4 framing (4 MB ring, standalone rig on the bike, download at the desk hours later) was scoped for this — leave the ESP on the bike, ride, come back, grab the file. M4's redesign drops it: everyone reverse-engineering a bike has a phone, and requiring the phone in the loop simplifies the firmware substantially (small gap-fill ring instead of a large capture ring, no `/capture` filename disambiguation for multi-boot downloads, one storage clock instead of two). If a contributor eventually wants ESP-only rides — an audience without a suitable phone, or a "leave the rig running for a week and grab data" workflow — the extension is straightforward: grow the ring, keep `GET /capture` responding to the bare no-`since` form, keep the timestamp format. File an issue when the need is concrete rather than pre-building for it.
- ~~**On-device timestamp format (M4 open decision).**~~ Closed by [ADR 0018](../../docs/decisions/0018-m4-browser-primary-capture.md) § On-device timestamps. Wire format is `(<sec>.<us>) t120806A4...\r` — byte-for-byte match to what `capture.py` writes to disk today; every existing `scripts/` tool consumes the stream with the regex loosen in `parse_slcan_line`. ~14 extra bytes/frame → ~27 s ring at 300 fps in the 512 KB budget.
- **`/dev` view superseding `scripts/live_view/`.** The Textual TUI does much more than an anomaly panel: watch pins with sparklines, per-bit z-score anomalies (ADR 0007's `BaselineStats`), procedure-driven step sequencing off a `.procedure.yaml`, the hypothesis / expect-shape workflow, operator vs analysis screens, session mark orchestration. M8 is the first step (raw ticker + Active unknown bytes) but full parity is several milestones out — probably one per subsystem, roughly in the order R&D leans on them. The intent is that once parity lands, `scripts/live_view/` retires and `capture.py` speaks to the ESP for procedures + marks instead of driving the TUI directly. Not a milestone here; captured so the direction is on file.

## Out of scope

- Any TX path.
- SD card logging.
- Frame filtering in firmware.
- Native phone app.
