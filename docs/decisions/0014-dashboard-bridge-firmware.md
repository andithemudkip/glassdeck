# 0014 — Dashboard bridge firmware: BLE GATT notify, packed binary frame

**Date:** 2026-06-25
**Status:** Proposed — implementation deferred (2026-06-25)
**Deferred behind:** [ADR 0016](0016-wifi-dev-capture-and-live-view.md)

> **Deferral note (2026-06-25):** the design in this ADR remains the target architecture for the production rig, but implementation is deferred until the `signals.yaml` schema stabilises. Building the React Native + native BLE + codegen + frame-versioning stack now would mean churning it every time a `provisional` signal moves. In the interim, [ADR 0016](0016-wifi-dev-capture-and-live-view.md) ships a lighter WiFi-served browser live view as a dev tool that covers untethered rides during the signal-discovery phase. When the signal set settles, this ADR is implemented and ADR 0016's firmware target is deleted.

## Context

Before the physical dashboard exists, the cheapest way to validate the decoded signal set as a real dashboard is to render it on the rider's phone. That needs a second firmware subproject — `firmware/dashboard-bridge/` — that consumes the same TWAI capture path as `can-logger`, decodes signals on-device against [[ADR 0005]]'s `docs/signals/signals.yaml`, and ships the result to a phone.

ADR 0005 explicitly anticipated this: *"the eventual phone-app dashboard consumes the same schema over BLE for the same reason."* This ADR is the realisation of that consumer.

Phone-side stack is React Native ([[project-phone-app-stack]]). Transport options weighed:

- **BLE GATT notifications** — phone keeps cellular for maps/music while riding; low power; auto-reconnect; `react-native-ble-plx` is the standard RN library.
- **WiFi AP (ESP as hotspot)** — phone loses cellular while connected; iOS pops "no internet" warnings; fine for bench, painful on road.
- **WiFi STA (ESP joins phone hotspot)** — preserves cellular but adds pairing friction per phone and burns phone battery.

Bandwidth needed is trivial — ~20 signals × 10 Hz × a few bytes each ≈ 2 kbit/s, well inside BLE notification throughput.

## Decision

- **New subproject:** `firmware/dashboard-bridge/`. Self-contained PlatformIO project per ADR 0003. Reuses the TWAI read path from `can-logger`; the decode path is generated from `signals.yaml`, not hand-written.
- **CAN side:** listen-only, same TWAI config as the logger. The golden no-TX rule applies — the bridge is outbound-to-phone only.
- **Decoder source:** `docs/signals/signals.yaml` per ADR 0005, consumed at **build time** via a codegen step that emits C headers (one decode function per signal entry, plus a packed frame struct covering **every** entry regardless of status — `confirmed`, `provisional`, and `partial` all ride the wire together). Bridge firmware never parses YAML on-device. Promoting or editing a signal triggers a firmware rebuild, same ritual as updating any other signals-yaml consumer.
- **Phone transport:** BLE GATT notifications, NimBLE stack (ESP-IDF default). One service, one notification characteristic carrying a packed binary frame.
- **Frame format:** little-endian packed struct, versioned. First byte is `version:u8` — every layout change bumps it. The layout itself is generated from `signals.yaml` at build time, not hand-maintained. A small C header committed alongside the generator output is the human-readable form of the v_N contract; the phone app consumes the matching layout via a TypeScript file generated from the same source. The TS file preserves each signal's `status` from `signals.yaml` so the phone app can branch on it at render time.

- **Status-gated rendering on the phone:** the dashboard has a mode switch — **Normal** shows only `confirmed` signals; **Experimental / Debug** also shows `provisional` and `partial` signals, visibly marked as such (e.g. a status pill or muted styling). This is purely a phone-side concern; the firmware unconditionally streams everything in the schema. Keeps the bridge a dumb pipe and lets the dashboard double as a live debugging surface for in-flight findings without a parallel render path.
- **Versioning policy:** bump `version` on any field add/remove/reorder. Old phone app + new firmware = phone shows "unsupported frame version" rather than misrendering. No backward-compat layer inside the frame; phone app updates in lockstep with firmware.
- **Cadence:** notify at a fixed ~10 Hz regardless of underlying CAN broadcast rate. The bridge holds the latest decoded value per signal and snapshots on each tick. Avoids per-CAN-frame notify storms and gives the renderer a predictable update rhythm.
- **Dev-loop side channel:** USB-CDC stays live in the bridge firmware, emitting the same packed frame as a hex line. Lets the RN renderer be developed against a laptop-tethered ESP without a phone in the loop. Not stripped from production builds.

## Consequences

- Adds a second firmware target. The TWAI-read code is shared via a `firmware/lib/` directory (or PlatformIO `lib_deps` pointing at a shared component); the decode code is *not* shared — it's generated per-target from `signals.yaml`, so any signal-schema change rebuilds both consumers equivalently.
- `signals.yaml` becomes load-bearing for firmware, not just host scripts. A malformed entry now breaks a build, not just a script run — the codegen step should validate the schema and fail loudly. Worth a CI check.
- The frame contract is *defined by* `signals.yaml` at a given commit, not by a hand-curated list in the firmware. Adding a signal to the v_N+1 frame is just adding it to `signals.yaml` and bumping the version byte in the codegen output. This is the right loop — the canonical schema drives every consumer.
- Because the frame includes provisional and partial signals, the wire format churns more often (every new provisional signal bumps the version). Acceptable: phone app and firmware update in lockstep already, and the cost is a recompile + reinstall, not a protocol negotiation. If churn ever becomes painful, the lever is to split the frame into a stable confirmed half and a variable experimental half — defer until felt.
- BLE pairing is "just works" — no PIN. Anyone within range can subscribe. Acceptable for a listen-only outbound stream of public bike telemetry; revisit if anything sensitive ever rides on this channel.
- Phone app must be a dev build (Expo Go can't load native BLE modules). Not a constraint on this ADR but worth flagging for whoever scaffolds the RN project.
- Unblocks Phase 3 against currently-confirmed signals without waiting on physical-hardware selection. Phase 4 (controls) and the physical display stay deferred.
- No CAN-TX path is introduced. Phase 5 active-CAN features stay gated behind their own per-message ADRs as the golden rule requires.
