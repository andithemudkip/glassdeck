# Glassdeck

I'm building an open-source dashboard for my 2020 Husqvarna Svartpilen 401. It's a KTM 390 platform bike, so a lot of this might transfer to the Duke 390, RC 390, Vitpilen 401, and the 250 variants.

Shout out to [ktm-can](https://github.com/blalor/ktm-can) for being a very useful resource at the start of this project, even though most signals didn't map out cleanly between bikes.

Right now it's not a dashboard yet. It's a pile of CAN captures and a slowly growing map of what the OEM broadcasts on the diagnostic bus.

## Why bother

The stock dash is _fine_ but the small stuff adds up. One combined blinker icon instead of separate left/right (why). No phone connection. Convoluted menus that I still don't remember how to navigate after owning the bike for 3 years. Membrane buttons that are hard to press, which you also can't use unless you're at a full stop because they're mounted on the dashboard itself (smart) (not).

There are closed replacement dashes out there. None of them publish the CAN definitions they figured out, which means every person who wants to build something on this platform has to redo the reverse-engineering from scratch. That's the actual motivation. Even if I never finish the dashboard, having a public signal map for the 390 platform seemed worth doing.

## What's decoded

The bike puts out 11 arbitration IDs, 8 bytes each, at 500 kbps on the diagnostic port. 88 payload bytes total. So far, across 15 sessions and about 1.2M frames:

|                                                          | bytes |   % |
| -------------------------------------------------------- | ----: | --: |
| Decoded (primary signal, fully or partially)             |    28 | 32% |
| D7 structural hash (6-cycle XOR ⊕ 5-bit GF(2) of D0..D6) |     9 | 10% |
| Always zero everywhere                                   |    44 | 50% |
| Static non-zero constant                                 |     4 |  5% |
| Redundant mirror of a decoded signal                     |     3 |  3% |
| Undecoded                                                |     0 |  0% |

Confirmed signals: RPM, throttle, gear, clutch, front and rear wheel speed, coolant temp, side stand, kill switch (three redundant copies), engine torque, and engine on/off counters. Provisional: ABS lamp (with a mirror on `12E`), quickshifter cut/blip, shift-failed, fuel-injection setpoint, and a coarse rear-speed band.

Zero undecoded bytes remain, but that's not the same as "fully mapped". Unknown structure still lives inside partially-decoded bytes (bits within an `S◐` cell) and behind the 44 always-zero bytes, some of which could carry latent signals under rider inputs we haven't exercised yet.

Full map: [`docs/signals/coverage.md`](docs/signals/coverage.md). Encoding-authoritative source: [`docs/signals/signals.yaml`](docs/signals/signals.yaml). Per-signal writeups: [`docs/findings/can/`](docs/findings/can/).

## Hardware

The Aliexpress special:

- ESP32-S3-DevKitC-1 (WROOM-1-N16R8)
- SN65HVD230 CAN transceiver breakout (3.3V, has termination on-board)
- TWAI on GPIO4 (TX) and GPIO5 (RX)
- Powered off the bike's F7 12V accessory rail via a small buck

Wiring, pinout, BOM: [`docs/hardware/`](docs/hardware/).

## Firmware

Two subprojects (so far), both share code out of `firmware/lib/`:

- [`firmware/can-logger/`](firmware/can-logger/) is the desk-tethered logger. SLCAN over USB. This is what produced every capture in `logs/` up until [`logs/2026-07-22-first-moving-ride`](logs/2026-07-22-first-moving-ride/).
- [`firmware/wifi-bridge/`](firmware/wifi-bridge/) is the untethered version for moving captures. WiFi soft-AP, SLCAN over WebSocket, a browser live view at `http://192.168.4.1/`, and OTA reflash via `POST /ota`.

ESP-IDF via PlatformIO. Build/flash notes in [`firmware/README.md`](firmware/README.md).

## Scripts

Python stuff in [`scripts/`](scripts/). The three that got most use, at least in the beginning:

- `scripts/capture.py` reads SLCAN from the logger (USB or WebSocket), writes a labelled directory under `logs/`, and can drive a rider through a scripted procedure step by step.
- `scripts/inventory_ids.py` gives per-ID frame counts, periods, active bytes.
- `scripts/unknown_byte_sweep.py` does a corpus-wide correlation sweep against the known signals. It's how most of the mirror-byte and always-zero classifications got made.

Operator guide (what to actually do on a capture day): [`docs/guides/capturing.md`](docs/guides/capturing.md).

## Quick start

If you have the parts and a 390-platform bike, you can be capturing in about 15 minutes.

1. **Build the adapter.** DevKitC-1 + SN65HVD230, wired per [`docs/hardware/can-adapter.md`](docs/hardware/can-adapter.md). TX to GPIO4, RX to GPIO5. Plug into the diagnostic connector with the bike keyed off.

2. **Flash the logger.** With [PlatformIO](https://platformio.org/):

   ```
   cd firmware/can-logger
   pio run -e logger -t upload
   ```

   If you get silence at 500 kbps (though you shouldn't), try `-e logger-250k`.

3. **Python side.** From the repo root:

   ```
   python3.14 -m venv .venv
   source .venv/bin/activate
   pip install -r scripts/requirements.txt
   ```

4. **Capture.** Key the bike on, find the port (`ls /dev/cu.usbmodem*` on macOS), then:

   ```
   python scripts/capture.py --port /dev/cu.usbmodem101 --label first-capture --live
   ```

   The TUI shows frames and decodes known signals live. `q` to stop, then fill in the `session.md` it writes (bike state, what you did, anything weird).

5. **Sanity check.**

   ```
   python scripts/inventory_ids.py logs/YYYY-MM-DD-first-capture/
   ```

   You should see the 11 always-on IDs from the [coverage map](docs/signals/coverage.md) at the periods listed there. If you're missing one, something's off with the wiring or the bike's not fully awake.

For ride captures, flash `firmware/wifi-bridge/` instead and pipe the WebSocket into `scripts/capture.py --stdin`. See [`firmware/wifi-bridge/README.md`](firmware/wifi-bridge/README.md). Since the laptop's gone at that point, the adapter runs off the bike's switched 12V (F7, pin 4 of the diagnostic connector) through a small perfboard: fuse, reverse-polarity diode, transient cap, 12V→5V buck. Build in [`docs/hardware/f7-power.md`](docs/hardware/f7-power.md), rationale in [ADR 0015](docs/decisions/0015-f7-12v-power-path.md).

## Repo layout

```
CLAUDE.md                agent working instructions
docs/
  research.md            project brief + phase plan
  status.md              what I'm on now
  decisions/             ADRs (choice + reasoning)
  experiments/           chronological log, failures included
  findings/               current-best knowledge, one file per thing
  signals/               canonical signal defs + coverage map
  hardware/              wiring, pinouts, BOM
  guides/                operator-facing how-tos
  references/            external sources, datasheets, related projects
logs/                    raw captures
scripts/                 Python parsers, decoders, analyzers
firmware/                ESP32 subprojects (can-logger, wifi-bridge)
```

## Where to start reading

- **You have a 390 platform bike and want the CAN map.** [`docs/signals/coverage.md`](docs/signals/coverage.md), then [`docs/findings/can/`](docs/findings/can/).
- **You're doing your own CAN reverse-engineering on some other bike.** [`docs/experiments/`](docs/experiments/) and [`docs/decisions/`](docs/decisions/) are how I've been going about it. You might find that the methodology transfers even if the bike doesn't.

## Caveats

Any of this could be wrong. Findings marked `provisional` haven't been replicated across bikes or sessions. It is not a dashboard yet, and plenty of structure inside partially-decoded and always-zero bytes is still unaccounted for. If you have another 390-platform bike and want to help, another capture on the same experiments is more useful than almost anything else right now.

## AI usage

I use Claude Code a lot on this. It writes a big chunk of the Python, drafts firmware, and I bounce analysis off it. Check out [`CLAUDE.md`](CLAUDE.md) for the setup I use.

The bike side is fully done by me, obviously: planning, riding, wiring, running captures, and deciding when a hypothesis is solid enough to become a finding. Even though I am a software engineer by trade, guiding Claude along rather than writing everything myself has proved immensely fruitful.

One thing worth mentioning: LLMs are pretty good at producing decodes that sound right and aren't. A byte that's actually a hash gets confidently named as a counter, that sort of thing. The "no finding without an experiment" rule is partly there to catch that. Everything in `docs/findings/` links back to the raw log behind it, so you can go check.

## License

MIT, see [`LICENSE`](LICENSE).
