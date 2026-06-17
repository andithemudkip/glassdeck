# Status

**Phase:** 1 — CAN logger / capture inventory.

**Last updated:** 2026-06-17

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
  - [`findings/bike/dash-warning-lights.md`](findings/bike/dash-warning-lights.md) — check-engine extinguishes ~1 s after engine start; ABS extinguishes once speed exceeds ~6 km/h.
- External references:
  - [`references/ktm-can-decoder.md`](references/ktm-can-decoder.md) — **new.** Cross-walk to the public ktm-can decoder (2020 KTM 690 Enduro R). Shares the Bosch ECU broadcast scheduler with this platform: 5 of our 11 IDs have a KTM hypothesis to test (`120`, `129`, `12A`, `450`, `540`). Confirmed lesson: byte positions can shift ±1 byte between Bosch ECU variants (coolant temp at D5,D6 on Husqvarna vs D6,D7 on KTM).

## Blocked on

- Nothing — choose any item from "Next actions" below.

## Next actions — per-input experiments (Phase 1 main work)

The payload-diff has narrowed the search space dramatically. Each remaining signal has a KTM hypothesis at a specific (ID, byte/bit) location and a residual ~20–40 candidate bytes per ID after subtracting STATIC/LOW-CARD-stationary. Pick from these:

1. **Engine-off batch** (cheapest, no engine, ~15 min each):
   - **Throttle sweep** — engine off, twist throttle slowly from 0 to wide-open and back. Hypothesised target: `120` D2 (range 0-255 per KTM). Also catches `12A` D0 bit 1 (throttle open/closed flag) and `12A` D1 bit 6 (requested map).
   - **Kill switch toggle** — engine off, toggle the kill switch a few times with hotkey `k`. Hypothesised target: `120` D3 bit 4 per KTM, **but our static read says bit 4 = 0 while kill is in run position**, which conflicts with KTM. The toggle resolves it.
   - **Gear shift cycle** — engine off, clutch in, cycle 1-N-2-N-3-N etc. Hypothesised target: `129` D0 hi nibble + `540` D3 lo nibble.
   - **Clutch in/out** — engine off, pump clutch lever. Hypothesised target: `129` D0 bit 3.
   - **Side stand up/down** — engine off. Hypothesised target: `540` D4 bit 0.
2. **Engine-on stationary batch:**
   - **ROAD ↔ SUPERMOTO mode toggle** — `12A` D1 bit 6 candidate.
   - **Throttle blip while idling** — confirm `120` D2 maps the same way as engine-off, and pick up any RPM-driven secondary signals.
   - **Trip reset / dash button presses** — likely targets in the body-controller / instrument-cluster Slow-decay-group IDs (`12A`, `12E`, `450`, `541`).
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
