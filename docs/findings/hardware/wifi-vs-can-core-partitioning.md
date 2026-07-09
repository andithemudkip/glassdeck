---
area: hardware
status: confirmed
established_by:
  - 2026-07-09-wifi-bridge-first-on-bike
---

# ESP32-S3 needs cross-core partitioning for WiFi + hard-realtime CAN

Running the TWAI RX drain on the same core as the ESP-IDF WiFi driver task is not viable at this project's frame rate (~420 fps). It works while everything is healthy but collapses catastrophically the moment a WiFi peer disconnects ungracefully — RX rate drops from ~420 fps to ~27 fps and the TWAI hardware buffer overflows at ~490 missed frames/sec. Pin the RX task to core 1 (`xTaskCreatePinnedToCore`, priority ≥5); leave WiFi + LWIP + httpd on core 0. This is not a workaround — it's the standard ESP32-S3 partition for any application mixing WiFi with a hard-realtime workload.

## Root cause

The WiFi driver task runs at priority 23 on its assigned core and is greedy — it doesn't cooperatively yield when it has work. LWIP TCP handling (retransmits, keepalive processing, socket teardown) is bursty. When a client disappears without a clean FIN — iOS Chrome swiped away is the canonical case, since the kernel keeps ACKing keepalives after the app dies — the httpd keeps trying to send to the phantom fd. The resulting retransmit / cleanup work chews core 0 in ~100-200 ms bursts. FreeRTOS is preemptive: an application task at the main-task default priority (1) gets zero CPU during those bursts. The TWAI ISR keeps firing during that time, filling the driver's internal RX FIFO (~16 slots on IDF defaults), which overflows and increments `rx_missed`.

Priority alone won't save you on a single core — WiFi is designed with the assumption that it wins on its assigned core. Only cross-core isolation works.

## Confidence

Direct measurement on the actual hardware + bike. Before fix: `frames_seen` rate 420 → 27 fps and `rx_missed` +490/s within seconds of a peer disappearing. After fix (RX pinned to core 1): `rx_missed=0` across the same test cycle, LED overlay stayed solid green (i.e. per-frame RX pulse fired every render tick).

## Applies to

- Any firmware target on this project that runs both WiFi and TWAI on ESP32-S3 with per-frame work in the RX path. Currently: `firmware/wifi-bridge/`.
- `firmware/can-logger/` is unaffected — USB-CDC only, no WiFi task to contend with.
- BLE-only future targets (e.g. the eventual production dashboard per ADR 0014) don't hit this in the same way — BLE controller work is much less bursty than TCP retransmit storms and doesn't chew hundreds of ms on peer disappearance. Cross-core partitioning is still the recommended shape but the failure mode is far less sharp.

## Evidence

- Bench session 2026-07-09, `wifi-bridge` on F7 power, phone (iOS Chrome) on the SoftAP. `/health` counter comparison before/after fix captured in the session log; experiment writeup pending under `docs/experiments/2026-07-09-wifi-bridge-first-on-bike.md`.
- Implementation: `firmware/wifi-bridge/main/main.c` — `rx_task` (pinned to core 1, priority `tskIDLE_PRIORITY + 5`), spawned from `app_main` after WiFi + httpd + `ws_tx_task` are up.
- Complementary fix in the same commit: proactive phantom-fd close in `ws_tx_task` (time-based reap on ≥30 failures + no successful send in 3 s). Reduces the WiFi/httpd busywork on core 0 but is not on the critical path for RX correctness — the pinning is what actually protects RX.

## Open

- Verify the pinning holds during real ride captures, not just stationary bench with the bike idling. Throttle sweeps and moving-bike bus load may look different.
