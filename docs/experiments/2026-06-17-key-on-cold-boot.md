---
date: 2026-06-17
status: success
phase: 0
related:
  findings:
    - can/bitrate
    - can/always-on-broadcast-ids
    - bike/dash-warning-lights
  decisions:
    - 0001-usb-power-during-development
    - 0002-twai-gpio-assignment
    - 0004-logger-wire-format-slcan
  experiments:
    - 2026-06-17-key-off-baseline
  logs:
    - 2026-06-17-key-on-cold-boot
---

# Key-on cold-boot bitrate lock + initial broadcast inventory

## Hypothesis

1. **Primary:** the Svartpilen 401's diagnostic CAN bus runs at **500 kbps** and the `firmware/can-logger` default build will see decodable frames within 1–2 s of turning the ignition to position 1 (key-on, engine off). Basis: KTM 390 / Husqvarna 401 community reports collated in [`docs/references/husqvarna-community-notes.md`](../references/husqvarna-community-notes.md) consistently describe a 500 kbps single-bus layout.
2. **Fallback:** if 500 kbps stays silent for the full key-on window, the bus is at **250 kbps**. The fallback build `pio run -e logger-250k` should then immediately see traffic. Both rates are pre-compiled and ready to flash.
3. **Secondary:** there is a brief cold-boot dash↔ECU handshake (ABS / TC / QS initialisation) within ~2 s of key-on that does not repeat during steady-state idle. Starting the capture **before** key-on is required to catch it. Basis: same community notes.

## Setup

- **Bike:** 2020 Husqvarna Svartpilen 401. Battery healthy, cold start (engine has not run today), neutral, side stand down. Fuel level + ambient temperature recorded in `session.md`.
- **Adapter / wiring:** unchanged from Session 0 ([2026-06-17-key-off-baseline](2026-06-17-key-off-baseline.md)). Breakout's on-board 120 Ω termination still in place. Diagnostic pin 4 (12V switched) still not wired.
- **Firmware:** start with `firmware/can-logger` @ `a9f53db`, env `logger` (500 kbps). Have `logger-250k` ready in a second terminal for the fallback path.
- **Host:** `scripts/capture.py`, venv per `scripts/README.md`. Two captures may happen in this session — `key-on-cold` (500k) and, only if the first is silent, `key-on-cold-250k`.

## Procedure

1. Confirm Session 0 passed (or its anomaly is documented and understood). Do not run this session if Session 0 returned unexplained frames.
2. Adapter plugged in, bike key off, firmware on the `logger` (500 kbps) build. From the repo root:
   ```
   source .venv/bin/activate
   python scripts/capture.py --port /dev/cu.usbmodem101 --label key-on-cold
   ```
3. **Wait 5 s** with capture running and key still off — gives a final blank-bus baseline at the head of the file and lets the firmware's first `# bus_err=0 ...` status line through.
4. Turn the key to position 1 (key-on, engine off). Press space on the laptop to drop a `generic mark` into `events.csv` at the moment of key-on. (Critical — this is the anchor for "boot t=0" in later analysis.)
5. Let the capture run for **90 s** through the dash self-test and into steady-state idle. Watch the live status line:
   - First frames should arrive ≤ 2 s after key-on. LED should start pulsing green.
   - If silent at 10 s: see step 7 (fallback).
6. Press `q` to stop. **Fill in session.md** with: cold/hot state, fuel %, ambient temperature, dash readout at key-on (any warning lights), confirmed connector pinout, breakout termination state.
7. **Fallback path** — only if step 5 saw zero frames after 10 s of key-on:
   - Press `q` to stop the silent capture. Keep its `logs/<date>-key-on-cold/` directory; it's evidence that 500 kbps is wrong.
   - In a second terminal: `cd firmware/can-logger && pio run -e logger-250k -t upload`.
   - Re-run capture: `python scripts/capture.py --port /dev/cu.usbmodem101 --label key-on-cold-250k --bitrate 250000`. Repeat from step 3.
   - If 250 kbps is also silent: stop. Do not turn the engine over. Write a new experiment (`2026-06-17-bitrate-mismatch.md`) capturing what was tried; the next step is hardware (wiring, scope on CANH/CANL, re-check connector).

## Result

Capture ran 2026-06-17T15:39:19Z → 15:42:20Z (~181 s total: ~7 s of pre-key-on silent head, ~174 s of post-key-on bus activity). Key-on was anchored with a `generic mark` keystroke at 15:39:26.39 — used as t=0 for everything below. Stopped cleanly with `q`. Re-derive any number here with `python scripts/inventory_ids.py logs/2026-06-17-key-on-cold-boot/`.

- **Bitrate that produced traffic:** **500 kbps** (primary hypothesis confirmed; fallback build never flashed).
- **Time-to-first-frame after key-on:** **+254 ms** (first frame: `12D#0000000000000000`).
- **Total frames captured:** **72 916** over ~174 s post-key-on → ~419 frames/s average.
- **Unique IDs observed: 11**, all 11-bit standard frames, no 29-bit traffic. Inventory below; all timestamps relative to the key-on mark:

  | ID    | count  | first_rel | last_rel  | median period | classification |
  |-------|-------:|----------:|----------:|--------------:|----------------|
  | `12D` | 17 419 | +0.254 s  | +173.753 s |        10.6 ms | continuous     |
  | `12E` |  8 675 | +0.279 s  | +173.731 s |        19.4 ms | continuous     |
  | `121` |  8 673 | +0.288 s  | +173.734 s |        19.6 ms | continuous     |
  | `129` |  8 673 | +0.289 s  | +173.735 s |        19.7 ms | continuous     |
  | `540` |  1 735 | +0.289 s  | +173.695 s |        99.4 ms | continuous     |
  | `5B0` |  1 735 | +0.289 s  | +173.695 s |        99.4 ms | continuous     |
  | `120` |  8 673 | +0.289 s  | +173.735 s |        19.8 ms | continuous     |
  | `12A` |  3 470 | +0.302 s  | +173.734 s |        50.3 ms | continuous     |
  | `5A0` |  1 735 | +0.349 s  | +173.734 s |        99.1 ms | continuous     |
  | `541` |  8 663 | +0.499 s  | +173.735 s |        19.9 ms | continuous     |
  | `450` |  3 465 | +0.524 s  | +173.713 s |        50.2 ms | continuous     |

  Period cohorts: one ID at 10 ms (`12D`), five at 20 ms (`12E 121 129 120 541`), two at 50 ms (`12A 450`), three at 100 ms (`540 5B0 5A0`). Min/max inter-arrivals span roughly ±half the median for every ID; this is consistent with USB-CDC bunching of frames at the host (ADR 0004) rather than bus-side jitter, so the median is the load-bearing periodicity figure.
- **IDs seen only during the boot window:** **none**. All 11 IDs that appeared after key-on continued through to the end of the capture. The cold-boot dash↔ECU handshake hypothesised in #3 did not produce a distinct boot-only ID set — see Interpretation.
- **IDs seen continuously through steady-state idle:** **all 11**. This is the always-on broadcast set for the engine-off / key-on state.
- **Firmware status-line health:** not directly observed during this run (`capture.py` discards `# bus_err=…` comments and no shadow `pio device monitor` was attached). Indirect evidence the bitrate is right and the driver was healthy: 11 cleanly-decoded IDs with stable medians, no truncated or oddly-short lines in `capture.log`, no `disconnect` row in `events.csv`. A `pio device monitor` cross-check is planned for the next session.
- **LED behaviour:** **dark throughout** despite ~419 frames/s arriving — anomaly logged in `session.md` and below. Most plausible cause: board revision routes the LED to GPIO48 rather than the default GPIO38. Not capture-affecting.
- **Frame decode quality:** clean. Spot-checked head and tail of `capture.log`; every line matches `(<ts>) can0 <3-hex-id>#<even-hex-data> R` with full 8-byte payloads on the broadcast IDs. No partial frames.
- Raw capture: `logs/2026-06-17-key-on-cold-boot/capture.log` (+ `events.csv`, `session.md`). Fallback `key-on-cold-250k` directory was never created — 500 kbps worked first try.

## Interpretation

- **500 kbps produces clean traffic — bitrate hypothesis confirmed.** Promoted to [`docs/findings/can/bitrate.md`](../findings/can/bitrate.md). The breakout's on-board 120 Ω termination, plus whatever the bike-side network already terminates with, was tolerated at this bitrate over this stub length: no decode errors, stable periods. This resolves the open termination question in [`can-adapter.md`](../hardware/can-adapter.md#termination) **for the diagnostic-stub configuration used here** — leave the breakout's termination in place going forward unless a future session shows decode degradation.
- **No boot-only ID set materialised**, contrary to secondary hypothesis #3. Two non-exclusive explanations: (a) the cold-boot dash↔ECU handshake described in community notes lives on a different bus segment than the diagnostic stub we're sampling (some platforms split a "body" or "instrument" CAN from the powertrain bus); (b) any boot-time exchange completed inside the 254 ms gap between key-on and our first decoded frame, or used an ID that happens to also broadcast continuously thereafter. Either way, the experiment can't distinguish — flagging as an open question, not a contradiction. Re-run after Phase 1 idle baselines have nailed down the always-on set; anything anomalous in the first 1–2 s of a fresh cold-boot will then stand out.
- **The 11-ID broadcast set is the working "always-on at key-on, engine off" inventory.** Promoted to [`docs/findings/can/always-on-broadcast-ids.md`](../findings/can/always-on-broadcast-ids.md) as provisional — Phase 1's idle×3 captures will harden the period figures and confirm none of these IDs are key-on-only artifacts that drop out once the engine is running.
- **LED anomaly is tooling, not capture.** Capture is the source of truth; the LED is a glance-friendly indicator. Resolution path is a focused tooling experiment (flash with `-DLED_GPIO=48` or scope GPIO38), not blocking.

## Follow-ups

- ✅ Promote bitrate to [`docs/findings/can/bitrate.md`](../findings/can/bitrate.md). *(done in this session)*
- ✅ Promote initial broadcast inventory to [`docs/findings/can/always-on-broadcast-ids.md`](../findings/can/always-on-broadcast-ids.md). *(done in this session)*
- ✅ Update [`docs/status.md`](../status.md) — transition Phase 0 → Phase 1. *(done in this session)*
- Update [`docs/hardware/can-adapter.md`](../hardware/can-adapter.md) "Open items" — bitrate confirmed, termination tentatively closed pending engine-on confirmation. *(deferred — touch up alongside the next experiment that uses the adapter)*
- Phase 1 / Session 2–4: run [2026-06-17-engine-idle-baseline-x3](2026-06-17-engine-idle-baseline-x3.md) to harden the broadcast inventory under engine-on conditions and unmask any RPM/throttle-driven IDs that are silent at engine-off.
- Tooling: open a small experiment for the dark-LED issue — likely just `pio run -e logger -DLED_GPIO=48` (or expose `LED_GPIO` as a Kconfig/env knob) and bench-verify. Not on the critical path.
- Cold-boot handshake remains an open question — revisit after the idle baselines, with a tighter pre-key-on head (≤2 s) to minimise the dead-time window.
