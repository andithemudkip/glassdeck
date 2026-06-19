# Status

**Phase:** 1 — CAN logger / capture inventory.

**Last updated:** 2026-06-19 (side-stand toggle — `540` D3 bit 0 confirmed, KTM `540` D4 bit 0 refuted; second `540` -1-byte shift after coolant temp)

## Hardware on hand

- ESP32-S3-DevKitC-1 (WROOM-1-N16R8 module) — see `docs/hardware/bom.md`
- SN65HVD230 breakout (fixed high-speed mode, on-board 120 Ω termination still in place — tolerated at 500 kbps on the diagnostic stub, see [`findings/can/bitrate.md`](findings/can/bitrate.md))
- Adapter assembled and plugged into the bike's diagnostic connector
- Diagnostic connector pinout confirmed — see `docs/hardware/diagnostic-connector.md`

## In progress

- Hardware decisions locked: pinout, GPIO assignment, transceiver mode, power path, termination plan — see `docs/hardware/can-adapter.md`.
- Framework + wire format decisions locked — see ADRs 0003 (ESP-IDF via PlatformIO) and 0004 (SLCAN over USB-CDC).
- `firmware/can-logger/` v1 built and flashed @ `a9f53db` — listen-only on GPIO4/5, SLCAN emit @ 500 kbps. **Known issue:** WS2812 activity LED dark on this DevKitC-1 revision despite frames arriving (likely GPIO48 vs default GPIO38); capture path unaffected.
- `scripts/capture.py` working end-to-end (reads serial via `pyserial`, parses SLCAN inline; `python-can`'s `slcan` backend hangs in `tcdrain()` against this firmware — see ADR 0004 Update 2026-06-17).
- `scripts/inventory_ids.py` — derives per-ID counts, first-seen offsets, and median periods from a capture session.
- Phase 0 complete:
  - [`2026-06-17-key-off-baseline`](experiments/2026-06-17-key-off-baseline.md) — bus silent with ignition off, as expected.
  - [`2026-06-17-key-on-cold-boot`](experiments/2026-06-17-key-on-cold-boot.md) — bitrate locked at 500 kbps, 11 always-on broadcast IDs identified, time-to-first-frame ~250 ms.
- Phase 1 baseline + first decode wins complete:
  - [`2026-06-17-engine-idle-baseline-x3`](experiments/2026-06-17-engine-idle-baseline-x3.md) — **all 3 runs done.** Same 11 IDs across all power cycles, period spread ≤4 % per ID. Three runs ended up spanning cold / partial-warm / operating-temp.
  - [`2026-06-17-payload-diff-idle`](experiments/2026-06-17-payload-diff-idle.md) — **desk-only follow-up.** Per-byte classification of all 88 payload bytes of the 11 IDs; cross-validated against the published ktm-can decoder. Two confirmed signal mappings out (RPM, coolant). 47 of 88 bytes are STATIC across all observed conditions — most of the payload is unused at idle.
- Findings established:
  - [`findings/can/bitrate.md`](findings/can/bitrate.md) — 500 kbps, classic CAN, 11-bit IDs.
  - [`findings/can/always-on-broadcast-ids.md`](findings/can/always-on-broadcast-ids.md) — `confirmed`. 11 IDs in 10/20/50/100 ms cohorts; ID set invariant with engine state.
  - [`findings/can/post-kill-decay-groups.md`](findings/can/post-kill-decay-groups.md) — `confirmed`. Clean 5-vs-6 split (Fast: `120`, `121`, `129`, `540`, `5B0`; Slow: `12A`, `12D`, `12E`, `450`, `541`, `5A0`).
  - [`findings/can/signal-rpm.md`](findings/can/signal-rpm.md) —`confirmed`. Engine RPM at `120` D0,D1 big-endian uint16. Idle ~1700 RPM.
  - [`findings/can/signal-coolant-temp.md`](findings/can/signal-coolant-temp.md) — `confirmed`. Coolant temp at `540` D5,D6 big-endian uint16 ÷10 °C. Range verified 25 °C → 92 °C.
  - [`findings/can/signal-kill-switch.md`](findings/can/signal-kill-switch.md) — `confirmed`. Kill switch at `541` D2 bit 4 (1=run, 0=stop). KTM polarity preserved, location moved (KTM placed it on `120` D3 bit 4). Same capture generalises [[post-kill-decay-groups]]: Fast group decays sub-second whenever kill→STOP, engine-on or engine-off.
  - [`findings/can/signal-throttle-position.md`](findings/can/signal-throttle-position.md) — `confirmed`. Throttle position at `120` D2 uint8, range 0–254 (not 255). KTM byte position transfers exactly. Refuted: `12A` D0 bit 1 is not the throttle-open flag.
  - [`findings/can/byte-d7-checksum-hypothesis.md`](findings/can/byte-d7-checksum-hypothesis.md) — `confirmed` as an observation. D7 on 9 of 11 always-on IDs behaves like a checksum/hash over D0..D6: 6 unique values on static-payload IDs, 100+ on active-payload IDs. Algorithm not yet reproduced.
  - [`findings/can/signal-gear-position.md`](findings/can/signal-gear-position.md) — `partial`. Gear at `129` D0 hi nibble; N=0, 1=1 **confirmed**. Gears 2–6 (`0x2`–`0x6`) hypothesised per KTM mapping but unverified — engine-off shift on paddock stand could not engage above 1st. KTM redundant broadcast at `540` D3 lo nibble **refuted** (static `0x0`).
  - [`findings/can/signal-side-stand.md`](findings/can/signal-side-stand.md) — `confirmed`. Side-stand state at `540` D3 bit 0 (1=up, 0=down). KTM polarity preserved; location shifted -1 byte from KTM's D4. Second `540` -1-byte shift after coolant temp — pattern: "`540` byte positions shift one earlier on Husqvarna, polarity intact" is now load-bearing for future `540` hypotheses.
  - [`findings/bike/dash-warning-lights.md`](findings/bike/dash-warning-lights.md) — check-engine extinguishes ~1 s after engine start; ABS extinguishes once speed exceeds ~6 km/h.
- External references:
  - [`references/ktm-can-decoder.md`](references/ktm-can-decoder.md) — **new.** Cross-walk to the public ktm-can decoder (2020 KTM 690 Enduro R). Shares the Bosch ECU broadcast scheduler with this platform: 5 of our 11 IDs have a KTM hypothesis to test (`120`, `129`, `12A`, `450`, `540`). Confirmed lesson: byte positions can shift ±1 byte between Bosch ECU variants (coolant temp at D5,D6 on Husqvarna vs D6,D7 on KTM).

## Blocked on

- Nothing — choose any item from "Next actions" below.

## Next actions — per-input experiments (Phase 1 main work)

The payload-diff has narrowed the search space dramatically. Each remaining signal has a KTM hypothesis at a specific (ID, byte/bit) location and a residual ~20–40 candidate bytes per ID after subtracting STATIC/LOW-CARD-stationary. Pick from these:

1. **Engine-off batch** (cheapest, no engine, ~15 min each):
   - ~~**Throttle sweep**~~ — done 2026-06-19, see [[signal-throttle-position]]. `120` D2 confirmed, full scale 254 not 255. `12A` D0 bit 1 refuted; `12A` D1 bit 6 unconfirmed (engine-off suppresses; re-test engine-on). Side finding [[byte-d7-checksum-hypothesis]] surfaced from the same capture. Reusable analysis: [`scripts/throttle_sweep.py`](../scripts/throttle_sweep.py).
   - ~~**Kill switch toggle**~~ — done 2026-06-19, see [[signal-kill-switch]]. Bit is at `541` D2 bit 4, not `120` D3. Reusable analysis: [`scripts/kill_switch_scan.py`](../scripts/kill_switch_scan.py).
   - **Gear shift cycle** — engine off, clutch in, cycle 1-N-2-N-3-N etc. Phase B done 2026-06-19, **partial**: `129` D0 hi nibble = gear confirmed for N (0x0) and 1 (0x1); paddock stand + engine off couldn't engage 2nd; gears 2–6 deferred to engine-on. `540` D3 lo nibble redundant-broadcast hypothesis refuted. See [[signal-gear-position]]. Reusable analysis: [`scripts/gear_scan.py`](../scripts/gear_scan.py).
   - ~~**Clutch in/out** — engine off, pump clutch lever~~ — Phase A done 2026-06-19, **null result**: no clutch signal in D0–D6 of any always-on ID; `129` D0 stays `0x00` throughout (KTM hypothesis rejected). Clutch deferred to engine-on stationary batch. Reusable analysis: [`scripts/clutch_scan.py`](../scripts/clutch_scan.py).
   - ~~**Side stand up/down**~~ — done 2026-06-19, see [[signal-side-stand]]. `540` D3 bit 0 confirmed (1=up, 0=down). KTM `540` D4 bit 0 hypothesis refuted. Reusable analysis: [`scripts/side_stand_scan.py`](../scripts/side_stand_scan.py).
2. **Engine-on stationary batch:**
   - **Gear sweep 2–6 + clutch revalidation** — [[2026-06-19-engine-on-gear-clutch]]. Close [[signal-gear-position]] for all 7 values; re-test whether clutch surfaces with engine running.
   - **ROAD ↔ SUPERMOTO mode toggle, trip reset, dash buttons, throttle blip** — [[2026-06-18-engine-on-stationary-inputs]]. Independent of the above; can run in either order during the same warm-up session.
3. **First motion capture** (push the bike a few metres in neutral, engine off):
   - **Wheel-speed hunt.** `12D` is the only 10 ms always-on broadcast and its payload is essentially empty at zero motion (bytes 0–6 all STATIC `0x00`). KTM 690's `12B` (also 10 ms) carries wheel speed; `12D` is the prime candidate to encode the same on Husqvarna.

## Tooling follow-ups

- Add an `idle_settled` hotkey (suggest `e`) to `scripts/capture.py`'s `HOTKEYS` dict.
- Surface `# bus_err=… rx_missed=… rx_overrun=…` from `capture.py` to a sidecar file before per-input captures (where a dropped frame could matter).
- Dark-LED fix: `pio run -e logger -DLED_GPIO=48 -t upload`, bench-verify with the bike disconnected.

## Open questions (from `docs/research.md`)

1. Can the OEM dashboard be completely disconnected?
2. Does the ECU expect messages from the dashboard?
3. How similar is the KTM 390 CAN map to the KTM 690 CAN map?
4. Which signals are already available as broadcasts?
5. How are ROAD/SUPERMOTO commands transmitted?
