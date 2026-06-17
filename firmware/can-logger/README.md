# can-logger

Phase 1 listen-only CAN logger for the 2020 Husqvarna Svartpilen 401.

Reads frames off the bike's CAN bus via the SN65HVD230 transceiver and streams them out the ESP32-S3's USB-CDC serial as SLCAN ASCII for the host-side capture script under `scripts/` to consume.

**Status:** v1 — listen-only logger, SLCAN over USB-CDC. Bench-confirmed on a 2020 Svartpilen 401 at 500 kbps (see [`docs/experiments/2026-06-17-key-on-cold-boot.md`](../../docs/experiments/2026-06-17-key-on-cold-boot.md)). Known issue: WS2812 activity LED dark on at least one DevKitC-1 board revision — likely GPIO48 instead of GPIO38 (see "On-board activity LED" below).

## Hardware

- ESP32-S3-DevKitC-1 (WROOM-1-N16R8 module).
- SN65HVD230 breakout (3.3V CAN transceiver, on-board termination, fixed high-speed mode).
- TWAI TX = GPIO4, TWAI RX = GPIO5.
- Powered over USB-CDC from the host laptop during development.

Full wiring: [`docs/hardware/can-adapter.md`](../../docs/hardware/can-adapter.md). BOM: [`docs/hardware/bom.md`](../../docs/hardware/bom.md).

## Design decisions

This subproject is governed by:

- [ADR 0001](../../docs/decisions/0001-usb-power-during-development.md) — USB power during development, F7 not wired.
- [ADR 0002](../../docs/decisions/0002-twai-gpio-assignment.md) — TWAI on GPIO4 / GPIO5.
- [ADR 0003](../../docs/decisions/0003-firmware-framework-esp-idf.md) — ESP-IDF via PlatformIO.
- [ADR 0004](../../docs/decisions/0004-logger-wire-format-slcan.md) — SLCAN over USB-CDC, firmware-to-host only.

## Behavior

1. Initialise the TWAI driver in **listen-only mode** (`TWAI_MODE_LISTEN_ONLY`). The peripheral never transmits, never acks — golden rule of the project until OEM messages are decoded.
2. Start at **500 kbps**. If the first capture is silent, the documented fallback is to rebuild at 250 kbps. Whichever rate produces traffic is captured as a finding under `docs/findings/can/`.
3. For each received frame, format as SLCAN (`t...` for 11-bit, `T...` for 29-bit) and write to USB-CDC serial, line-terminated with `\r`.
4. Every 2 s, emit a SLCAN comment line summarising TWAI driver health:

   ```
   # bus_err=0 rx_missed=0 rx_overrun=0 state=running\r
   ```

   `bus_err` ticking up with zero frames is the bitrate-mismatch signature; growing `rx_missed`/`rx_overrun` means the host can't keep up draining USB-CDC. The host capture script's SLCAN parser ignores any line not starting with `t/T/r/R`, so these are safe to mix into the stream — they're visible in `pio device monitor` and discarded by the capture script.
5. No host→adapter command handling. Configuration is compile-time.

Bitrate is the only thing meant to change between builds at this stage; expose it as a `Kconfig` option or a `#define` at the top of `main.c`.

### On-board activity LED

The on-board WS2812 RGB LED (GPIO38 on DevKitC-1 v1.1) pulses dim green whenever frames are arriving — minimum 50 ms on-time per blink so even sparse traffic is visible. Bus silent → LED dark. This is the fastest bench check: if the LED stays dark with the bike at key-on, the bitrate or wiring is wrong before you even look at the laptop.

Older board revisions route the LED to GPIO48 — build with `-DLED_GPIO=48` to switch. Disable the LED entirely with `-DLED_ENABLE=0`. The WS2812 is driven directly via ESP-IDF's `rmt_tx` driver, no external components required.

## Build / flash

The board talks to the host over the **port labelled `USB`** (native USB-Serial/JTAG, wired to the S3 on GPIO19/20) — that single port is used for both flashing and the SLCAN data stream. The other port (labelled `UART` or `COM` depending on board revision — USB-to-UART bridge to GPIO43/44) is unused by this firmware and will look silent if you try to capture from it.

```
cd firmware/can-logger

pio run                          # default 500 kbps build
pio run -t upload                # flash via USB-Serial/JTAG
pio device monitor               # raw 't' / 'T' SLCAN lines scroll past

# fallback build if the bike's bus turns out to be 250 kbps
pio run -e logger-250k -t upload
```

Bitrate is the only build-time knob; it's set by the `CAN_BITRATE_KBPS` define in `platformio.ini` (`[env:logger]` = 500, `[env:logger-250k]` = 250). Adding more rates means adding more envs.

## First capture

```
# (one-time) install host-side deps
pip install -r scripts/requirements.txt

# from the repo root, with the adapter plugged in and the bike at key-on
python scripts/capture.py --port /dev/tty.usbmodem101 --label key-on
```

The script creates `logs/<date>-key-on/`, streams frames into `capture.log` (candump format, host timestamps), and prints a live frames/sec status line. Press `?` during the session for the hotkey legend; every keystroke is timestamped into `events.csv` so rider actions can be correlated to frame patterns later. Ctrl-C (or `q`) stops the capture and writes a `session.md` stub for you to finish filling in.

If the bus stays silent for the first ~5 s, the script prints a multi-line bring-up checklist (continuity, key position, try the 250 kbps build). Until any frames arrive, **nothing has confirmed the bitrate hypothesis** — the first successful capture is what promotes 500 kbps (or 250) to a finding under `docs/findings/can/`.

## Tagging captures

Every capture session records the firmware commit it used in its `session.md` (see `logs/` convention in `CLAUDE.md`). When this logger gets meaningful changes, capture sessions are tagged with the git short hash of the firmware they ran.

## Out of scope for v1

- Timestamping in firmware (host adds timestamps; revisit per ADR 0004 if jitter ever matters).
- SD card logging (USB-tethered captures are sufficient for stationary work; mounted test rides are a deferred sub-project per ADR 0001).
- Frame filtering (capture everything; filter downstream).
- Any TX path.
