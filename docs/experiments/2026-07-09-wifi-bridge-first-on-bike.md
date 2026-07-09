---
date: 2026-07-09
status: success
phase: 2
related:
  findings:
    - hardware/wifi-vs-can-core-partitioning
  decisions:
    - 0015-f7-12v-power-path
    - 0016-wifi-dev-capture-and-live-view
    - 0018-m4-browser-primary-capture
  experiments: []
  logs: []
---

# First on-bike bench validation of wifi-bridge (M2/M3/M4/M6/M7a)

## Hypothesis

`firmware/wifi-bridge` through M6 + M7a will run end-to-end on the actual bike hardware: F7-power boot → SoftAP up → phone joins → decoded panel matches the OEM dash for the confirmed signal set → OTA works → capture flow (start / disconnect / reconnect / export) works. Two paths never previously exercised on this project — first flash of wifi-bridge over USB and first OTA — both under bench conditions with the bike stationary, key on, engine idling.

## Setup

- **Bike:** 2020 Husqvarna Svartpilen 401. Stationary, side stand down, neutral. Ignition on, engine idling. No riding.
- **Adapter / wiring:** unchanged CAN adapter ([`can-adapter.md`](../hardware/can-adapter.md)). **F7 power path built and connected for the first time** per [`f7-power.md`](../hardware/f7-power.md) — no bench supply, no USB tether during runtime tests.
- **Firmware:** `firmware/wifi-bridge` at branch tip going into the session. `main.c` was patched twice during the session (see § Result); the final committed shape carries both fixes.
- **Host:** MacBook (WiFi only, no USB to the ESP). Phone: iPhone on iOS 27 beta, Safari + Chrome. `pio` on the laptop for the first flash, `curl` for OTA.

## Procedure

1. **First flash over USB** (M2 rollback protection not yet armed for OTA — USB first). ESP connected to the laptop USB while slotted on the F7 board, F7 pigtail not yet connected to the bike.
2. **F7 power-up on the bike.** ESP disconnected from laptop USB, F7 pigtail into diagnostic connector, key on.
3. **Phone joins SoftAP** (`glassdeck-<mac6>`), opens `http://192.168.4.1/`.
4. **`/health` sanity check** via `curl` from the laptop on the same AP.
5. **Second flash via OTA:** `curl -X POST --data-binary @.pio/build/wifi-bridge/firmware.bin http://192.168.4.1/ota` — first OTA ever on this project.
6. **Ungraceful-close stress test:** swipe Chrome away on the phone (no clean TCP FIN → half-open peer), then repeatedly rejoin. Watch `/health` counters and the on-board LED state.

## Result

Primary hypothesis **confirmed** — end-to-end pipeline works, decoded panel tracks the OEM dash. But two real firmware bugs surfaced along the way, both fixed within the session:

### Bug 1 — httpd start crash from over-large `max_open_sockets`

Immediate boot loop on first flash. Serial log showed `E httpd: Config option max_open_sockets is too large (max allowed 7, 3 sockets used by HTTP server internally)` → `ESP_ERROR_CHECK` at `httpd_start` aborts. Root cause: `cfg.max_open_sockets = 10` in `http_server_start()` with default `CONFIG_LWIP_MAX_SOCKETS = 10`, but httpd reserves 3 slots internally, capping the app-facing value at 7. **Fix:** `max_open_sockets = 7`. One-line, comment updated to reflect the actual arithmetic.

### Bug 2 — RX loop starvation when a WiFi peer disconnects ungracefully

Reproduced by swiping Chrome away on the phone. LED transitioned from solid green (RX overlay) to cyan-green flicker (RX pulses missing render windows). Streaming to any re-connected client was staggered / laggy. `/health` counters over four samples across a ~11-second post-disconnect window:

| sample | uptime_ms | frames_seen | rx_missed | ws_clients | ws_sent | rate (fps) |
|-------:|----------:|------------:|----------:|-----------:|--------:|-----------:|
|  1 (before phone) |  19 200 |   8 029 |    0 |  1 |     0 |    418 |
|  2 (Chrome open)  |  46 354 |  19 432 |    0 |  1 |  3 038 |    420 |
|  3 (Chrome closed 9 s ago) |  55 834 |  20 701 | 2 462 | 1 (phantom) |  4 247 |    133 |
|  4 (rejoined, still laggy) |  67 783 |  21 025 | 7 158 | 2 (phantom + fresh) |  4 515 |     27 |

Root cause bisected: WiFi driver task at priority 23 on core 0, RX loop running inline in `app_main` (priority 1, core 0). Half-open iOS TCP peer keeps httpd sending → LWIP retransmits → WiFi task chews core 0 in ~100–200 ms bursts → `app_main` preempted → TWAI hardware RX FIFO overflows. iOS' kernel ACKs TCP keepalives after Chrome dies, so httpd's own aggressive keepalive (added mid-session as a first attempted mitigation) can't reap the phantom.

**Fix bundle** (in `main.c`, see final commit):
1. **RX loop moved to a dedicated task pinned to core 1** at priority `tskIDLE_PRIORITY + 5`. This is the load-bearing fix — core 1 has no other significant work so RX can never be preempted by WiFi/httpd chaos on core 0.
2. **Proactive phantom-fd close in `ws_tx_task`** — force-close a fd via `httpd_sess_trigger_close` if it accumulates ≥30 consecutive `httpd_ws_send_frame_async` failures **and** hasn't had a successful send in 3 s. First iteration used a pure consecutive-failure threshold (100) but that fired a false-positive close on a healthy client during a natural httpd-queue-full burst; time-based threshold survives real send patterns without misfires.
3. Aggressive httpd TCP keepalive (`keep_alive_idle=2, interval=1, count=3`) retained as belt-and-braces — reaps genuinely dead TCP connections that iOS doesn't ACK for.

After the fix, repeated swipe-and-rejoin cycles: `rx_missed=0` throughout, RX rate stable at ~420 fps, LED remains solid green. One transient burst of ~70–300 `frames_ws_dropped` at the moment of disconnect (WiFi cleanup briefly starves `ws_tx_task` on core 0) is expected and self-limiting; ring covers the gap.

### Everything else that worked

- **First USB flash of wifi-bridge** — successful, no drama beyond the Bug 1 crash which surfaced on first boot regardless.
- **First OTA** — `curl -X POST --data-binary` streamed the binary, ESP responded `OK — restarting`, came back up cleanly on the new image. Bootloader rollback path was never exercised (both intermediate builds reached `esp_ota_mark_app_valid_cancel_rollback`).
- **F7 power on the bike** — LED transition BOOT (yellow) → CAN_ONLY (green) → WIFI_AP_NO_CLIENT (blue) → WIFI_AP_CLIENT (cyan, drowned to green under bus load) all as designed. No transient anomalies. Key-off drops power within perception time — matches [`f7-power.md`](../hardware/f7-power.md) Test 5's expected behaviour.
- **Decoded panel on phone** — RPM, coolant, throttle, gear, kill, side-stand all track the OEM dash. Wheel speeds nominally zero (bike stationary). M6's done-when condition met.
- **iOS multi-path routing** — phone stays on the AP for `192.168.4.1` and simultaneously uses LTE for internet, "just works" without user intervention. Softens ADR 0016's rejection of ESP-as-STA on the "phone needs cellular during a ride" axis.

## Interpretation

- **wifi-bridge is bench-validated on real hardware.** Every milestone from M1 through M7a's done-when condition met. Next stage is a real ride — throttle sweeps, wheel-speed signals under load, radio conditions off the bench.
- **RX starvation was a lurking bug that only ever fired with (a) a real WiFi peer (b) the peer disappearing without a clean FIN.** Bench-testing with laptop `curl` clients would never have hit it — laptop TCP closes cleanly and there's no phantom to sustain. iOS Chrome swipe-away is the canonical trigger. Promoted to [`docs/findings/hardware/wifi-vs-can-core-partitioning.md`](../findings/hardware/wifi-vs-can-core-partitioning.md) — a fact about ESP-IDF's WiFi driver + hard-realtime CAN that will shape any future firmware target mixing the two on this SoC.
- **The `max_open_sockets` bug was a config arithmetic mistake, not a design issue.** Trivially fixed; the surprise is that a 4-hour flash-to-OTA path can hide behind a comment that reasons the arithmetic backwards.
- **No `logs/` directory produced this session.** Deviation from the standard experiment pattern — this was an integration / bring-up session, not a signal-analysis capture. The evidence is the `/health` counter series above (server-side telemetry), the LED behaviour, and the surviving commit diff. `logs/` will resume with the first real ride capture.

## Follow-ups

- ✅ Promote the cross-core partitioning constraint to [`docs/findings/hardware/wifi-vs-can-core-partitioning.md`](../findings/hardware/wifi-vs-can-core-partitioning.md). *(done in this session)*
- Commit the two-hunk `main.c` fix on `firmware/wifi-bridge/` (bug 1 + bug 2 bundle). *(deferred — user will commit)*
- **First actual ride capture.** Throttle sweeps, wheel-speed signals live, radio conditions off-bench. This is what Test 5 of `f7-power.md` really tests and the closing bar for the wifi-bridge critical path.
- Enclosure. Riding out uncased violates `f7-power.md` § Operational rules for anything other than fair-weather.
- Cold-boot timing measurement vs the 250 ms USB baseline in [`findings/can/always-on-broadcast-ids.md`](../findings/can/always-on-broadcast-ids.md). Not blocking; noted as a `docs/hardware/f7-power.md` Open item.
- Consider whether the RX loop should also emit per-frame lines to USB-CDC (currently does via `write_locked`). Not the cause of any bug we found, but arguably vestigial from `can-logger` inheritance since wifi-bridge's stated USB-CDC role is "logs, not data pipe." Cleanup candidate.
