---
date: 2026-06-17
status: success
phase: 0
related:
  findings: []
  decisions:
    - 0001-usb-power-during-development
    - 0002-twai-gpio-assignment
    - 0004-logger-wire-format-slcan
  logs:
    - 2026-06-17-key-off-baseline
---

# Key-off wiring sanity baseline

## Hypothesis

With the bike's ignition fully off, the diagnostic port's CAN backbone is unpowered and the bus should be electrically idle. The adapter, plugged into the diagnostic connector and laptop-powered over USB, should read **zero frames** for the duration of the capture.

If frames *do* appear, that's either (a) the bike has a key-off keep-alive on its CAN bus (unexpected per current understanding of the platform — see [`docs/references/husqvarna-community-notes.md`](../references/husqvarna-community-notes.md)), or (b) the transceiver / wiring is fabricating bits (ground loop, mis-bias, intermittent contact). Either way, we need to know before trusting any later capture.

This session also gives us our first physical sanity check on adapter wiring and on the breakout's on-board 120 Ω termination [(see can-adapter.md → Termination)](../hardware/can-adapter.md#termination): we expect silence regardless of termination state with the bus depowered, so any noise points at the adapter, not the bike.

## Setup

- **Bike:** 2020 Husqvarna Svartpilen 401, key fully **off** (ignition position 0), engine cold, in neutral, side stand down. Battery connected, nothing else touched.
- **Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230 breakout per [`docs/hardware/can-adapter.md`](../hardware/can-adapter.md). Breakout's on-board termination **in place** for this session (not yet desoldered — first contact decides).
- **Connection:** diagnostic connector pin 2 (CANH) → breakout CANH, pin 5 (CANL) → CANL, pin 3 (GND) → common ground. Pin 4 (12V switched) intentionally not wired ([ADR 0001](../decisions/0001-usb-power-during-development.md)).
- **Power:** ESP32 powered from the laptop USB only.
- **Firmware:** `firmware/can-logger` @ `a9f53db` — listen-only, 500 kbps build (`pio run -e logger`).
- **Host:** `scripts/capture.py` from the same commit, Python 3.14 venv per [`scripts/README.md`](../../scripts/README.md).

## Procedure

1. Bike key verified off. Adapter not yet plugged into the diagnostic port — only into the laptop. Sanity-check: in a one-shot raw read of `/dev/cu.usbmodem101`, confirm the firmware is emitting `# bus_err=0 rx_missed=0 rx_overrun=0 state=running` every ~2 s. LED dark (no frames). This is the bench-only state.
2. With ignition still off, plug the adapter into the diagnostic connector. **Don't touch the key.**
3. From the repo root:
   ```
   source .venv/bin/activate
   python scripts/capture.py --port /dev/cu.usbmodem101 --label key-off-baseline
   ```
4. Let the capture run for **60 s**. Watch the live status line for frame/ID counts. Watch the on-board LED — it should stay dark.
5. Press `q` to stop. Fill in `logs/2026-06-17-key-off-baseline/session.md` with: confirmed bike state, ambient temperature, exact diagnostic-connector pinout used, whether the breakout's termination is still in place.

## Result

Capture ran 2026-06-17T15:31:54Z → 15:32:56Z (~62 s), then stopped cleanly with `q`. Hypothesis confirmed: the bus is silent with the bike key-off.

- **Frames captured:** 0
- **Unique IDs:** 0
- **Event marks:** 0
- **LED behaviour:** dark throughout (firmware only pulses on frame RX, and no frames arrived).
- **Firmware `# ...` status lines:** not explicitly inspected during the run — `capture.py` consumes and discards them so they don't show up live, and `pio device monitor` would have contended for the port. No `disconnect` events landed in `events.csv`, which is consistent with the driver staying in `state=running` for the full window.
- Raw capture: `logs/2026-06-17-key-off-baseline/capture.log` (0 bytes — kept anyway as evidence of the silent window).
- Session metadata: `logs/2026-06-17-key-off-baseline/session.md`.

First successful run of `scripts/capture.py` end-to-end. Earlier in the day the script hung in `python-can`'s SLCAN `set_bitrate()` against a firmware that doesn't answer host commands — the capture path was rewritten to read SLCAN lines directly with `pyserial`, see the **Update 2026-06-17** section of [ADR 0004](../decisions/0004-logger-wire-format-slcan.md). The aborted attempt left no usable capture, only this run counts.

## Interpretation

**Silent — expected outcome.** Wiring is electrically benign with the bus depowered: the adapter, plugged into the diagnostic connector with the bike off, does not generate spurious frames and the SN65HVD230's input bias is not fabricating bits. This is the floor we needed before trusting any later capture: anything we see in Session 1 (key-on) is the bike, not the adapter.

This session does **not** resolve the termination question — the bus is depowered, so the breakout's on-board 120 Ω being in place can't be distinguished from absent. That decision is still deferred to whatever frame quality Session 1 produces.

## Follow-ups

- ✅ Proceed to [2026-06-17-key-on-cold-boot](2026-06-17-key-on-cold-boot.md) (Session 1) — bitrate lock + cold-boot dash↔ECU window.
- Termination decision still open; revisit after Session 1 per [`can-adapter.md`](../hardware/can-adapter.md#termination).
- Tooling: the `pyserial` rewrite of `capture.py` is now the only path; if the original `python-can` SLCAN failure mode resurfaces (e.g. on Linux where `tcdrain()` behaves differently), update [ADR 0004](../decisions/0004-logger-wire-format-slcan.md).
