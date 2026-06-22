# Status

**Phase:** 1 — CAN logger / capture inventory.

**Last updated:** 2026-06-21 (desk-batch complete: engine-state bit attribution, D7 byte character, cold-boot ID emergence, cross-session payload diff, bit-transition scan. Headlines: bus has ≥4 source modules with clean F/S-early/S-mid/S-late sub-grouping; D7 is a universal 6-cycle with per-ID XOR offsets — standard CRC-8 refuted; engine-state bits flat across 174 s of key-on-no-engine; cross-session diff refined `540` D2 bit 6 + D3 bit 4 to "ignition-armed permission" rather than pure engine-state and surfaced `540` D1 as a candidate derived-coolant signal; bit-transition scan found `129` D0 lo nibble = shift-lever sensor (lever-displaced + failed-shift flags, almost certainly the source of the dash `-` glyph), kill switch redundantly broadcast at `5B0` D0 bit 4 and `121` D5 bit 2, and `541` D4 = candidate ~1 Hz engine-on counter.)

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
  - [`findings/can/post-kill-decay-groups.md`](findings/can/post-kill-decay-groups.md) — `confirmed`. Clean 5-vs-6 decay split (Fast: `120`, `121`, `129`, `540`, `5B0`; Slow: `12A`, `12D`, `12E`, `450`, `541`, `5A0`). Boot-order analysis ([[2026-06-21-cold-boot-id-emergence]]) refines this further: Fast group is **one module** (all 5 IDs first-seen within ±1 ms); Slow group splits into 3 boot waves (S-early: `12D`/`12E`; S-mid: `12A`/`5A0`; S-late: `541`/`450`). Bus has **≥4 source modules**, not 2. Zero one-shot IDs at boot — the 11 always-on IDs are the complete bus inventory at idle.
  - [`findings/can/signal-rpm.md`](findings/can/signal-rpm.md) —`confirmed`. Engine RPM at `120` D0,D1 big-endian uint16. Idle ~1700 RPM.
  - [`findings/can/signal-coolant-temp.md`](findings/can/signal-coolant-temp.md) — `confirmed`. Coolant temp at `540` D5,D6 big-endian uint16 ÷10 °C. Range verified 25 °C → 92 °C.
  - [`findings/can/signal-kill-switch.md`](findings/can/signal-kill-switch.md) — `confirmed`. Kill switch at `541` D2 bit 4 (1=run, 0=stop). KTM polarity preserved, location moved (KTM placed it on `120` D3 bit 4). Same capture generalises [[post-kill-decay-groups]]: Fast group decays sub-second whenever kill→STOP, engine-on or engine-off.
  - [`findings/can/signal-throttle-position.md`](findings/can/signal-throttle-position.md) — `confirmed`. Throttle position at `120` D2 uint8, range 0–254 (not 255). KTM byte position transfers exactly. Refuted: `12A` D0 bit 1 is not the throttle-open flag.
  - [`findings/can/byte-d7-checksum-hypothesis.md`](findings/can/byte-d7-checksum-hypothesis.md) — `confirmed`. D7 = `cycle[counter mod 6] ⊕ per_ID_offset ⊕ f(D0..D6)`. Universal 6-element reference cycle `{0x35,0x5F,0x6A,0x8B,0xBE,0xD4}` (Gray-code in `{0x35,0x6A,0xE1}` XOR basis); per-ID offsets cataloged for 8 of 9 candidate IDs. Standard-CRC + counter-byte exhaustively refuted — algorithm has a hidden input (DataID, LFSR seed, or per-ID secret). Replay-style TX viable; novel-payload TX blocked until algorithm reproduced.
  - [`findings/can/engine-state-bits-decay-shape.md`](findings/can/engine-state-bits-decay-shape.md) — `provisional`. The 5 engine-state bits flagged by `payload_diff` (3 on `121`, 2 on `540`) hold engine-off mode flat across 174 s of key-on-no-engine (cold-boot) and hold idle mode through the Fast-group post-kill tail (<300 ms). None is a fast "engine-running" indicator — use [[signal-rpm]] for that. The two `540` bits are now refined to **"ignition-armed permission"** (transient drops during kill→STOP in the engine-off kill session, per [[2026-06-21-cross-session-payload-diff]]); the three `121` bits remain pure engine-physical-run indicators. Residual question is which sensor sources each bit (needs external mapping or hardware probing).
  - [`findings/can/signal-warmup-index.md`](findings/can/signal-warmup-index.md) — `provisional`. `540` D1 is engine-on-gated and **decreases** monotonically with coolant temp (~0x19 at 26 °C cold start → 0x0E at 92 °C operating temp). Hot restart at 75 °C reads 0x0E immediately with no transient, so it's a stateless thermal lookup, not a time-based cold-start timer. Most likely an ECU warm-up correction (cold-start enrichment factor or fast-idle / idle-air-bypass position) — not the dashboard gauge needle. Was previously catalogued as `signal-coolant-derived` with an inverted reading. Promote on a continuous overnight-cold → fan-cycle warm-up capture plus a physical-quantity ID.
  - [`findings/can/signal-shift-lever.md`](findings/can/signal-shift-lever.md) — **new**, `provisional`. `129` D0 lo nibble carries shift-lever sensor state, distinct from the gear position in the hi nibble. **Bit 3 = lever displaced** (sustained — strain-gauge / position sensor that feeds the factory quick shifter). **Bit 1 = shift attempt failed to engage target gear** (transient — fired specifically after both failed N→2 attempts in Phase B and never after successful shifts). Bit 1 likely explains the OEM dash `-` glyph directly from CAN. Both bits zero across throttle/kill/stand/clutch-only sessions — gear-session-specific. Engine-on shift capture confirms or refutes.
  - [`findings/can/signal-gear-position.md`](findings/can/signal-gear-position.md) — `partial`. Gear at `129` D0 hi nibble; N=0, 1=1 **confirmed**. Gears 2–6 (`0x2`–`0x6`) hypothesised per KTM mapping but unverified — engine-off shift on paddock stand could not engage above 1st. KTM redundant broadcast at `540` D3 lo nibble **refuted** (static `0x0`).
  - [`findings/can/signal-side-stand.md`](findings/can/signal-side-stand.md) — `confirmed`. Side-stand state at `540` D3 bit 0 (1=up, 0=down). KTM polarity preserved; location shifted -1 byte from KTM's D4. Second `540` -1-byte shift after coolant temp — pattern: "`540` byte positions shift one earlier on Husqvarna, polarity intact" is now load-bearing for future `540` hypotheses.
  - [`findings/bike/dash-warning-lights.md`](findings/bike/dash-warning-lights.md) — check-engine extinguishes ~1 s after engine start; ABS extinguishes once speed exceeds ~6 km/h.
- External references:
  - [`references/ktm-can-decoder.md`](references/ktm-can-decoder.md) — **new.** Cross-walk to the public ktm-can decoder (2020 KTM 690 Enduro R). Shares the Bosch ECU broadcast scheduler with this platform: 5 of our 11 IDs have a KTM hypothesis to test (`120`, `129`, `12A`, `450`, `540`). Confirmed lesson: byte positions can shift ±1 byte between Bosch ECU variants (coolant temp at D5,D6 on Husqvarna vs D6,D7 on KTM).

## Blocked on

- Nothing — choose any item from "Next actions" below.

## Next actions

Desk follow-ups still on the queue:

- ~~**Doc 2 of the desk batch** — D7 algorithm + `12D` character.~~ Done. See [[byte-d7-checksum-hypothesis]].
- ~~**Doc 3 of the desk batch** — cold-boot ID emergence.~~ Done. See [[post-kill-decay-groups]] (now F/S-early/S-mid/S-late) and [[always-on-broadcast-ids]] (boot inventory closed).
- ~~**`120` cycle close-out.**~~ Done. Offset = `0x00` (same as `12D`). Triggered an extended algorithm-reproduction attempt (Parts I/J of [[2026-06-21-d7-byte-character]]) — refuted the "no per-ID secret" hypothesis: f(D0..D6) is not a standard CRC-8 in any byte order with any polynomial. Algorithm stays open; remaining angles are external (read other open-source decoders or the ECU binary).
- ~~**Cross-session payload diff** — extend payload_diff to all 9 captures.~~ Done. See [[2026-06-21-cross-session-payload-diff]]. New candidate findings: [[signal-warmup-index]] (`540` D1) and [[signal-shift-lever]] (`129` D0 lo nibble — surfaced by a follow-up alignment of Phase B). Refined: [[engine-state-bits-decay-shape]] (`540` bits are ignition-permission, not pure engine-state). Refined: [[signal-gear-position]] (lo nibble re-attributed to shift lever, dash `-` likely from bit 1). 6/8 known signals reproduced cleanly; 2 coolant misses explained by ambient/residual temperature differences across capture days.
- ~~**Bit-level transition scan** — companion to the cross-session diff.~~ Done. See [[2026-06-21-bit-transition-scan]]. New: kill switch redundantly broadcast at `5B0` D0 bit 4 and `121` D5 bit 2 (both updated into [[signal-kill-switch]] secondary-locations table). New: [[signal-engine-on-counter]] — `541` D4 is a ~1 Hz binary counter, not the CRC originally tagged in payload_diff. Bit-level per-thermal-bin profile corroborates [[signal-warmup-index]]. Methodology note added to [[engine-state-bits-decay-shape]]: bit-level scanning has a blind spot for bits that flip only at engine-start/stop (outside the idle window) — byte-level cross-session table remains authoritative for those.

## Per-input experiments (Phase 1 main work)

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

- Surface `# bus_err=… rx_missed=… rx_overrun=…` from `capture.py` to a sidecar file before per-input captures (where a dropped frame could matter).
- Dark-LED fix: `pio run -e logger -DLED_GPIO=48 -t upload`, bench-verify with the bike disconnected.

## Open questions (from `docs/research.md`)

1. Can the OEM dashboard be completely disconnected?
2. Does the ECU expect messages from the dashboard?
3. How similar is the KTM 390 CAN map to the KTM 690 CAN map?
4. Which signals are already available as broadcasts?
5. How are ROAD/SUPERMOTO commands transmitted?
