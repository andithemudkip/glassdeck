# 0016 — Dev-phase WiFi capture and live view

**Date:** 2026-06-25
**Status:** Accepted (§ Retirement amended 2026-07-05 — see Update below)
**Relates to:** [ADR 0014](0014-dashboard-bridge-firmware.md) (production BLE bridge, deferred behind this ADR)

## Update 2026-07-05 — retirement clause reopened

The original § Retirement below assumes `firmware/wifi-bridge/` is deleted the moment ADR 0014's BLE bridge ships. That commitment is walked back: the delete-when-BLE-ships plan is no longer settled. WiFi + browser has real long-term value the BLE bridge can't cheaply replicate:

- **Post-ride log pull.** BLE at the 1M PHY can't pump a full ride's ring buffer off the ESP in seconds. HTTP over WiFi can.
- **Diagnostic mode for the production dashboard.** A browser-served page any laptop or phone can hit — no native app, no BLE dance — is the cheapest possible field-debug surface.
- **Fallback if BLE fails.** BLE stacks fail in the field in ways that are hard to predict from bench testing. A parallel WiFi ingress is insurance.
- **Codegen path already exists.** Once milestone 6 of the build ships the `signals.yaml` → JS decoder, keeping the WiFi target alive costs only occasional maintenance, not new mechanism.

The actual decision — retire vs. keep as a sidecar — is deferred to a follow-up ADR near ADR 0014 shipping, when we can weigh what BLE is actually delivering against what the WiFi target still provides. Nothing in the rest of this ADR changes; the build plan in [`firmware/wifi-bridge/README.md`](../../firmware/wifi-bridge/README.md) treats retirement as an open question rather than a locked outcome.

The § Retirement section below is preserved as originally written.

## Context

[ADR 0015](0015-f7-12v-power-path.md) unblocks untethered rides. The remaining piece is data egress: with no USB cable to the laptop, where do CAN frames go, and how does the rider see live data while riding?

Three options were weighed:

- **microSD card on the adapter.** Canonical capture path, no BLE bandwidth worries, decoupled from any phone app. Adds hardware (SD breakout + four GPIOs + retention policy + a firmware writer task with backpressure handling). The rider still gets no live view.
- **BLE GATT (ADR 0014).** Right answer for the production rig, but everything ADR 0014 builds — React Native scaffold, native BLE modules, codegen, frame versioning, status-gated rendering — is heavy machinery that has to churn every time a `provisional` signal moves. Doing it now means iterating on that stack alongside the still-shifting signal schema.
- **WiFi from the ESP32-S3.** Bandwidth is two orders of magnitude beyond what the bus produces. ESP-IDF supports it natively. No native phone app required if the live view ships as a browser page served by the ESP itself.

The third option collapses the problem. The ESP becomes a tiny HTTP + WebSocket server: it streams raw frames to whoever's connected, and serves a static HTML/JS live view that any browser can render. No native app, no SD slot, no MFi-style pairing dance. When ADR 0014 eventually ships for the production rig, this firmware target gets retired — it is explicitly a dev tool.

The price is connectivity ergonomics: ESP-as-AP means the connected phone loses cellular while subscribed. Acceptable for dev rides that are short, near home, and primarily about validating decoded signals against rider observation. Not acceptable for a polished consumer dashboard — which is what ADR 0014 is for, eventually.

### Considered and rejected

- **SD card alongside or instead.** Adds hardware and a firmware writer task; no rider-facing live view; the canonical-capture-fidelity argument is real but does not outweigh the rider's stated need to see decoded signals while riding (e.g. confirming the wheel-speed LSB against the OEM speedo).
- **ESP-as-STA joining phone hotspot.** Preserves phone cellular. Adds per-device SSID/password provisioning and a captive-portal or compiled-in credentials story. Defer; ESP-AP is simpler and covers the dev use case. Revisit if a longer trip turns up where keeping cellular matters.
- **WiFi over BLE for the live render right now.** BLE is the right transport for the production rig (cellular preserved, lower power, auto-reconnect), but its real bandwidth ceiling at the 1M PHY is uncomfortably close to raw-frame throughput, and the React Native + native-module path is significant work. Deferring it preserves option value: when signals settle, ADR 0014 ships against a stable schema and a known-good frame format.

## Decision

### Firmware target

New subproject: `firmware/wifi-bridge/`. Self-contained PlatformIO project per [ADR 0003](0003-firmware-framework-esp-idf.md). Reuses the TWAI read path from `firmware/can-logger/`; shares the listen-only configuration and GPIO assignment ([ADR 0002](0002-twai-gpio-assignment.md)). Golden no-TX rule applies.

The existing `firmware/can-logger/` target is retained for USB-CDC desk dev. Two targets, picked at flash time, same TWAI core. `wifi-bridge/` is the canonical untethered target.

### WiFi topology

- **Mode:** AP (ESP is the access point).
- **SSID:** `glassdeck-<lower6 of MAC>` (e.g. `glassdeck-a1b2c3`). Stable per device, no compile-time config needed for SSID.
- **Password:** WPA2, compiled in. Stored in a header that lives outside source control (`firmware/wifi-bridge/main/wifi_secrets.h`, `.gitignore`'d, with `.example` checked in). Default password rotates with the firmware build — print it on the serial console at boot for the operator to copy.
- **IP:** ESP serves at `192.168.4.1` (ESP-IDF AP default). Live view at `http://192.168.4.1/`. No DNS, no mDNS dependency — the IP is stable and printed on boot.

### Server

A single ESP-IDF HTTP server task exposing:

| Path | Method | Returns |
|------|--------|---------|
| `/` | GET | Static HTML+JS+CSS live view (gzipped, embedded in the binary as a SPIFFS image or `EMBED_FILES`). |
| `/stream` | WebSocket | Live raw frame stream — text frames in the same SLCAN format `scripts/capture.py` already parses. One CAN frame per WebSocket text message. |
| `/capture` | GET | Downloads the in-RAM ring buffer as a `.log` file in the SLCAN format. `Content-Disposition: attachment; filename="capture-<unix-ts>.log"`. |
| `/health` | GET | JSON: uptime, frames seen, frames dropped, bus error counters, WiFi RSSI of the connected client. |

The wire format on `/stream` and `/capture` is the existing SLCAN text format — identical to what `scripts/capture.py` reads off USB-CDC today. Downloaded files drop straight into `logs/YYYY-MM-DD-<condition>/` and feed every existing analysis script (`inventory_ids.py`, `payload_diff`, `bit-transition-scan`, etc.) with no changes.

### Capture buffer

- **Storage:** PSRAM ring buffer, 4 MB by default (configurable in `sdkconfig`). At ~100 kbps SLCAN-text throughput that's ~5 minutes of continuous capture; at lower idle rates, much more. The DevKitC-1's 8 MB octal PSRAM has headroom for 6 MB if needed; 4 MB leaves room for WebSocket buffers and IDF heap.
- **Boot order:** TWAI read task starts on boot, *before* WiFi association, writing into the ring immediately. WiFi takes 1–3 s to bring up the AP; any frames in that window land in the ring and stream out once the first client connects. **Cold-boot CAN traffic is not lost.**
- **Drop policy:** drop-oldest on overflow. The drop counter is exposed via `/health` and surfaced on the live view as a visible "capture degraded" indicator. Never silently lose frames without telling the operator (same principle as ADR 0011 §"halo" — the operator sees when the surface is lying).
- **Persistence across reconnects:** the ring outlives WebSocket reconnects. A client that drops out and rejoins gets the buffered tail on `/capture` and the live stream from the rejoin point on `/stream`. No replay over the WebSocket — `/capture` is the catch-up path.

### Live view (browser-served)

Out of scope for this ADR to fully spec — it gets its own design pass once the firmware is up. Minimum viable shape:

- One HTML file, vanilla JS, no build step. Edit-and-reflash loop is fast because the file is small and embedded.
- Top: bus-health header (RSSI, uptime, frames seen, frames dropped).
- Middle: decoded signal panel for the `confirmed` signals from `signals.yaml` (RPM, coolant, throttle, gear, kill, side stand, clutch, wheel speeds). Status-gated mirror of what ADR 0014 will eventually do over BLE.
- Bottom: raw-frame ticker (last N frames, dimmest-to-brightest by age) for the operator to spot-check.

The decoded panel reads from `signals.yaml` via a small TypeScript/JS module generated at firmware build time from the same schema the existing host scripts use. The codegen step here is much lighter than ADR 0014's because there's no versioned binary frame format — the wire is SLCAN text, decoding happens in the browser. Schema changes mean editing the generated JS module and reflashing or refreshing; no protocol versioning.

### Operational rules

- **Listen-only.** No CAN-TX. Same as every other firmware target.
- **WiFi-only when in use.** USB-CDC stays present in the binary (it's free, it's how the operator sees the SSID/password on boot), but it is not a parallel capture path. One canonical egress to avoid divergent log files for the same session.
- **Session marking.** The live view exposes a "mark" button that calls `POST /mark?label=<text>` to insert a `# MARK <label>` line into the capture, replacing the laptop-side keyboard hotkeys for ride sessions where the rider can press a phone button but not a laptop key. Compatible with the existing `m`-mark machinery in `scripts/capture.py`. (Hand-driven inputs that can't be marked — see [[experiment-design-hand-driven-marks]] — still need procedure-driven step boundaries, but for two-handed actions like opening throttle or hitting the kill switch, on-phone marks are now possible.)

### Retirement

*Amended 2026-07-05 — see the Update at the top of this ADR. The delete-when-BLE-ships plan below is no longer settled; the actual decision is deferred to a follow-up ADR near ADR 0014 shipping. Original text preserved below.*

When [ADR 0014](0014-dashboard-bridge-firmware.md) ships, this firmware target is deleted. The `firmware/wifi-bridge/` directory is removed; ADR 0014's BLE bridge becomes the sole untethered egress for the production rig. This ADR stays on file as the historical dev tool.

## Consequences

- **Phase 2+ untethered rides unblocked** without committing to the React Native + BLE stack.
- **No SD card hardware.** Adapter board stays small. F7 + transceiver + buck + ESP32 + nothing else.
- **No phone app to ship.** Any browser works — iOS Safari, Android Chrome, desktop browsers when the laptop is on the same AP. Reduces the support matrix for the dev phase to zero.
- **Phone loses cellular while subscribed.** Acceptable for dev rides; explicitly the trade-off this ADR accepts.
- **`signals.yaml` becomes a firmware build input** for the live view's decoded panel — same constraint ADR 0014 introduces, but with a much lighter codegen step. Worth a CI check that the schema parses cleanly.
- **Logs land as files via download, not via SD pull.** Operationally identical to USB capture: connect, download, drop into `logs/YYYY-MM-DD-<condition>/`, write a `session.md`. The download endpoint should embed the ESP's uptime + frames-seen in the filename so two captures from one boot don't collide.
- **`firmware/can-logger/` stays alive** as the USB-CDC desk path. Two targets, one TWAI core. Shared code goes into `firmware/lib/` per ADR 0014's pattern — pull it forward to here.
- **No CAN-TX. No backwards-compat shims.** When ADR 0014 supersedes this, the directory is deleted clean.
- **ADR 0014 is now formally deferred** — see the note added at the top of that ADR.
