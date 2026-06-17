---
area: can
status: confirmed
established_by:
  - 2026-06-17-key-on-cold-boot
---

# Diagnostic-bus bitrate

The 2020 Husqvarna Svartpilen 401 (KTM 390 platform) diagnostic CAN bus runs at **500 kbps**, classic CAN (no CAN-FD), 11-bit standard identifiers. No 29-bit extended traffic has been observed on the diagnostic stub.

Frames decode cleanly with the SN65HVD230 + breakout's on-board 120 Ω termination still in place; no decode failures or truncated frames in the source capture. Time-to-first-frame from key-on is ~250 ms.

Bus is silent with the bike fully off (ignition position 0) — the diagnostic stub is unpowered when the key is off and no key-off keep-alive traffic was observed.

## Evidence

- [`docs/experiments/2026-06-17-key-on-cold-boot.md`](../../experiments/2026-06-17-key-on-cold-boot.md) — 72 916 frames over ~174 s of key-on, engine-off bus activity, 11 unique 11-bit IDs, stable median periods, no decode anomalies. Fallback 250 kbps build was prepared but never needed.
- [`docs/experiments/2026-06-17-key-off-baseline.md`](../../experiments/2026-06-17-key-off-baseline.md) — 0 frames in 62 s with ignition fully off (key-off silence baseline).

## Open

- Engine-on confirmation: bitrate has only been verified at key-on, engine-off. Phase 1 idle-baseline captures should re-confirm with the engine running before this finding is treated as fully settled. See [[always-on-broadcast-ids]].
