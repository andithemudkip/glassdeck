# Scripts

Python tooling for working with captures and signal definitions: parsers, decoders, log analyzers, plot generators.

Conventions:

- Pure-Python where possible; use a `pyproject.toml` or `requirements.txt` once dependencies appear.
- Reads from `logs/`, writes derived artifacts beside the original capture (`*.decoded.csv` etc.) or to `docs/findings/` for prose.
- Never writes inside `logs/<session>/` over an existing file unless the filename ends in `.decoded.*` or similar — captures are immutable.
- Scripts that drive hardware (read/write CAN) go in `firmware/` or a clearly named `scripts/hw/` if they're ad-hoc; document them in `docs/experiments/` when used.

A script that reaches a stable shape and gets reused should get a one-line entry below.

## Environment

Python 3.14+. From the repo root:

```
python3.14 -m venv .venv
.venv/bin/python -m pip install -r scripts/requirements.txt
```

Activate the venv for an interactive shell session so `python` resolves to the venv interpreter:

```
source .venv/bin/activate     # bash/zsh
# .venv/bin/activate.fish     # fish
# deactivate                  # to leave
```

All commands below assume the venv is active (`python …`); if you'd rather not activate, prefix every invocation with `.venv/bin/python` instead. Pinned versions live in `requirements.txt`.

## Running a capture

With the adapter plugged in and the bike at key-on:

```
python scripts/capture.py --port /dev/cu.usbmodem101 --label key-on
```

The script creates `logs/<date>-<label>/`, opens the ESP32-S3 USB-CDC port with `pyserial`, and parses the firmware's SLCAN-formatted line stream directly into `can.Message` objects (see ADR 0004 Update 2026-06-17 for why we don't use `python-can`'s `slcan` interface). The live status line shows elapsed time, frame count, unique IDs, event-mark count.

**Pre-flight on the firmware side.** Even with no CAN bus connected, the can-logger emits `# bus_err=0 rx_missed=0 rx_overrun=0 state=running\r` on the USB-CDC stream every ~2 s. `capture.py`'s SLCAN parser ignores anything that doesn't start with `t/T/r/R`, so these are silently dropped — to see them with your own eyes, sniff the raw port (`pio device monitor -p /dev/cu.usbmodem101 -b 115200` or a one-shot `python -c "import serial; print(serial.Serial('/dev/cu.usbmodem101',115200,timeout=4).read(800).decode())"`). On a healthy bench: status lines flowing, all counters at zero, LED dark. On a live bus: same status lines, LED pulsing dim green (board-dependent — see `firmware/can-logger/README.md`), frames in `capture.log`.

**Hotkeys** during the session (single keypress, no Enter):

| Key | Mark | | Key | Mark |
|---|---|---|---|---|
| space | generic mark | | `m` | ROAD/SUPERMOTO toggle |
| `i` / `I` | indicator L / R | | `r` | trip reset |
| `b` | high beam | | `t` | throttle blip |
| `g` | gear shift | | `k` | kill switch |
| `n` | neutral | | `s` | starter button |
| `h` | horn | | `?` | print legend |
| `e` | idle settled | | `q` or Ctrl-C | stop capture |
| (any other printable key) | recorded raw, label later | | | |

Each keypress lands a timestamped row in `events.csv` with both ISO-UTC and `time.monotonic()` clocks so it can be cross-referenced against capture.log timestamps later.

**On exit** (`q`, Ctrl-C, or USB unplug) the script writes:

- `capture.log` — raw frames, candump format with host timestamps
- `events.csv` — keystroke marks (and a `disconnect` row if the bus dropped mid-capture)
- `session.md` — auto-populated header (firmware rev, bitrate, frame/ID counts, start/end timestamps) plus TODOs for bike state, rider narrative, and anomalies. **Fill these in before walking away** — a session without bike state context is half-useless a week later.

**Useful flags:**

- `--bitrate 250000` — metadata only. The value is recorded in `session.md` but is not sent to the adapter; the actual bus rate is fixed by the firmware build you flashed (`-e logger` = 500 kbps, `-e logger-250k` = 250 kbps). Pass the rate that matches the build so session metadata stays truthful.
- `--label` — becomes the directory suffix. The script refuses to overwrite an existing non-empty `capture.log`, so re-runs need a new label (`key-on-2`, etc.).
- `--firmware-rev` — override the auto-detected git short hash. Auto-detect uses `git log -n 1 -- firmware/can-logger`; if you've edited firmware without committing, that hash is stale — pass the truth manually.

See `python scripts/capture.py --help` for the full list.

## Dependencies

Listed in `requirements.txt` (`python-can`, `pyserial`). Install with the venv command above.

## Catalog

- `capture.py` — host-side CAN capture for the `firmware/can-logger` adapter. Opens the ESP32-S3 USB-CDC port with `pyserial`, parses the SLCAN line stream inline, writes `logs/<date>-<label>/capture.log` (candump format with host timestamps) via `can.Logger`, records keystroke event marks to `events.csv`, drops a `session.md` stub on exit, and survives mid-capture USB unplugs by logging a `disconnect` event and writing the partial session out cleanly.
- `inventory_ids.py` — summarises a capture session: per-ID frame counts, first/last-seen times relative to a named event mark, and min/median/max inter-arrival periods in ms; classifies each ID as `BOOT-ONLY`, `continuous`, or `intermittent`. Read-only against `logs/<session>/`; prints to stdout. Default anchor is the first `generic mark` keystroke (spacebar) — pass `--no-anchor` for raw epoch times or `--anchor-label LABEL` for any other event row.
- `payload_diff.py` — classifies every payload byte of the 11 always-on broadcast IDs across the three engine-idle baseline captures. Reads each session's `events.csv` to partition frames into engine-off / steady-idle / post-kill windows, then tags each (ID, byte) pair as STATIC / LOW-CARD / COUNTER / CRC-LIKE / ENGINE-STATE / COOLANT-TEMP-CAND / IDLE-RPM-CAND / UNKNOWN. Also emits a bit-level engine-state map (which individual bits flip mode between engine-off and idle in all three runs). Run-set is hard-coded to the 2026-06-17 captures — read the top of the file to point it at new sessions. Output goes to stdout; pass `--csv` to also write `payload_classification.csv` for downstream tools.
- `kill_switch_scan.py` — finds the bit that tracks the kill switch in a `k`-marked toggle capture. Partitions the session into seven RUN/STOP windows (initial state = RUN, six toggles after), trims debounce slop around each flick, and scans every (ID, byte, bit) for the one whose dominant value alternates in lockstep at high per-window purity. Falls back to a whole-byte dominant-value scan if no clean bit is found. Also prints a targeted check on the KTM hypothesis (`120` D3 bit 4). Defaults to `logs/2026-06-19-kill-switch-toggle` — `--session` to point at another capture.
- `throttle_sweep.py` — decodes the throttle channel from an engine-off `t`-marked sweep capture. Partitions the session into three phases (slow sweep / step response / repeat sweep) from the three throttle marks, prints per-phase summary stats for `120` D2 (min/max/mean), checks the engine-off RPM invariant on `120` D0,D1, scans `12A` D0 bit 1 and D1 bit 6 for throttle correlation, runs a frame-by-frame Pearson correlation of `120` D7 vs `120` D2 (dual-sensor APP hypothesis), and emits a bus-wide range scan flagging any byte whose (max − min) crosses `--range-threshold` (default 20) during phase 1. Writes `120_d2_timeseries.decoded.csv` beside the capture for external plotting. Defaults to `logs/2026-06-19-throttle-sweep-engine-off` — `--session` to point at another capture.
- `clutch_scan.py` — looks for the bit that tracks the clutch lever in a `c`-marked clutch-pump capture. Defines a settle window (key-on + 25 s) and an active window (first `c` → last `c` + 2 s), counts bit transitions per (ID, byte, bit) in each window, and ranks the active-window movers. Robust to whether `c` is pressed once per pump or once per edge — it finds movers from the payload itself and then overlays `c` marks against the dominant transition timestamps for visual sanity-check. Targeted check on the KTM hypothesis (`129` D0 bit 3). Pass `--exclude-d7` to skip byte D7 (known checksum churn — see [[byte-d7-checksum-hypothesis]]). Defaults to `logs/2026-06-19-gear-cycle-clutch-A-clutch-only` — `--session` to point at another capture.
- `side_stand_scan.py` — finds the bit that tracks the side stand in a `j`-marked toggle capture. Same window-aware scan as `kill_switch_scan.py` (seven DOWN/UP windows from six toggles, starting DOWN) but with a longer 1.2 s post-toggle head trim — the rider keys `j` at the moment of intent to move the stand, and the stand's physical travel takes ~1 s, so a shorter trim leaves stale-state frames in each window and depresses purity (the lag is rider/mechanical, not bus). Targeted check on the KTM hypothesis (`540` D4 bit 0); falls back to a whole-byte dominant-value scan if no clean bit is found; final block prints per-toggle press-to-flip times for `540` D3 bit 0. Defaults to `logs/2026-06-19-side-stand-toggle` — `--session` to point at another capture.
- `gear_scan.py` — tabulates candidate gear-position fields in a `g`/`n`-marked gear-cycle capture. Builds one window per inter-mark span (300 ms trim on each side) and reports the dominant value + purity per window for the two KTM hypotheses (`129` D0 hi nibble, `540` D3 lo nibble), plus `540` D3 hi nibble for context. Then runs a broad scan over all (ID, byte, nibble) and full bytes (D7 excluded) for any field whose per-window dominant values are distinct across `--min-windows-distinct` (default 3) windows at purity ≥ `--purity` (default 0.80). Defaults to `logs/2026-06-19-gear-cycle-clutch-B-gear-cycle` — `--session` to point at another capture.
