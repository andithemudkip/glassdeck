# Capturing — operator's guide

Practical instructions for running `capture.py` and reading the live TUI. For the *why* (architecture, threading model, decode path) read ADR 0005–0007 and `scripts/live_view/__init__.py`.

---

## Quick start

1. Flash a `can-logger` build onto the ESP32-S3 (`-e logger` for 500 kbps, `-e logger-250k` for 250).
2. Plug the adapter into the bike's diagnostic line and into your laptop's USB.
3. Activate the venv: `source .venv/bin/activate` (one-time setup: `python3.14 -m venv .venv && .venv/bin/python -m pip install -r scripts/requirements.txt`).
4. Key the bike on.
5. Run one of:

```
python scripts/capture.py --port /dev/cu.usbmodem101 --label key-on              # plain
python scripts/capture.py --port /dev/cu.usbmodem101 --label idle --live         # live TUI
python scripts/capture.py --port /dev/cu.usbmodem101 --watch                     # watch-only, no logs
python scripts/capture.py --port /dev/cu.usbmodem101 --label kill \
    --experiment docs/experiments/2026-06-20-kill-switch.procedure.yaml          # rider-driven
```

6. Press `q` (or Ctrl-C) to stop. Then **fill in `session.md`** — bike state, rider narrative, anomalies. A capture without context is half-useless a week later. (`--watch` skips this — nothing is written.)

Adapter port on macOS: usually `/dev/cu.usbmodem<N>`. Find it with `ls /dev/cu.usbmodem*` after plugging in.

---

## Which mode do I want?

| Situation | Use |
|---|---|
| Just dumping frames; you'll analyse offline | plain `capture.py` |
| You want to *see* what flips when you press a button | `--live` |
| You're poking the bike to learn how it behaves, nothing worth keeping yet | `--watch` |
| You're running a scripted procedure with a rider | `--experiment <yaml>` (implies `--live`) |
| You want signals decoded into the capture | `--live` (writes `live_decode.csv`) |

`--live` and `--experiment` cost a bit of CPU but never alter what's written to `capture.log` / `events.csv`. The TUI is a *view* onto the same files an offline decoder would read. `--watch` is the same TUI with the disk writes turned off — nothing in `logs/`, no `--label` needed.

---

## Scenarios

### "I just want to watch the bus without committing to a session"

```
python scripts/capture.py --port /dev/cu.usbmodem101 --watch
```

Same live TUI as `--live`, but nothing lands in `logs/`: no session dir, no `capture.log`, no `events.csv`, no `live_decode.csv`, no `session.md` stub to fill in. `--label` is unnecessary (and ignored).

Hotkeys still baseline flip windows, so you can press `i`/`k`/`t`/etc. and read the unknown-bits pane exactly as in a real capture. The one caveat: `.` (snapshot) is disabled in watch mode — it pops a Textual notification instead of writing a file. If you see something worth saving, exit and re-run without `--watch` to do the real capture.

Good for: bench bring-up, exploring an unfamiliar mode of the bike, verifying the adapter sees frames before a real session, demos.

### "I want to see live what flips when I press a button"

```
python scripts/capture.py --port /dev/cu.usbmodem101 --label indicator-probe --live
```

1. Let the bus settle a few seconds — frame count climbing, no `dropped` in red.
2. Press the hotkey for the action you're about to take (e.g. `i` for indicator). The press *itself* is the baseline mark — the live view watches the next 500 ms for flips.
3. Do the physical action immediately after.
4. Read the **Unknown bits flipped** pane: rows are grouped by arbitration ID, sorted by z-score. Top of the list = the bits most-likely caused by your action.
5. Anything interesting? Press `.` to dump a `snapshot-N.json` next to the capture — this is what you cite in an experiment writeup.

If the action takes longer than 500 ms (gear shift, side stand) the dominant signal still surfaces — the bit's first transition fires within the window.

### "I want to track a specific bit or signal across the whole session"

Press `w`, type either:
- a signal name (e.g. `rpm`, with substring matching) → pinned with its decoded value + sparkline
- a raw triplet `0x290:3.2` (ID:byte.bit) → pinned as a 0/1 square-wave

The watch row stays at the top of the analysis screen as long as the app runs. Press `u` to unpin.

Useful when you've half-identified a bit and want to *watch* it react to other inputs before promoting to a finding.

### "I'm running a rider through a scripted procedure"

Write the procedure as `docs/experiments/<slug>.procedure.yaml` (see ADR 0006 for schema, and the `--experiment` flag's help text). Then:

```
python scripts/capture.py --port /dev/cu.usbmodem101 --label <slug> --experiment <path>
```

The TUI starts on the **operator screen** — a big-prompt-and-countdown view designed for the rider to glance at, not read. Each step:
- Big text = what to do.
- Countdown = seconds until the *next* step fires. The cue runs during the trailing seconds of the current settle.
- "Coming up:" preview = next 3 steps.

Auto-marks fire at each step's start moment (same `_mark()` path as a hotkey press). The procedure file is copied into the session dir as `procedure.yaml.snapshot` so the exact script that drove the run is preserved.

Hotkeys during a procedure:

| Key | What it does |
|---|---|
| `Space` | Pause the procedure (capture itself never pauses — just the countdown) |
| `←` | Rewind one step. Logs a `procedure-rewind` event but does NOT re-fire the step's auto-mark |
| `Tab` | Flip to the analysis screen to peek at decoded/flipped panes mid-run; Tab again to return |
| `q` | Stop |

Any other hotkey still works (`.` snapshot, `w` watch, etc.) — the operator screen is just a different render of the same app.

### "The bike isn't connected — am I seeing anything?"

Even with no bus, the firmware emits `# bus_err=0 rx_missed=0 rx_overrun=0 state=running` every ~2 s on the USB-CDC line. `capture.py` silently ignores these. To see them with your own eyes:

```
pio device monitor -p /dev/cu.usbmodem101 -b 115200
```

Healthy bench: status lines flowing, all counters zero, LED dark.  
Healthy bus: status lines flowing, LED pulsing dim green (board-dependent), frames in `capture.log`.

---

## Hotkey cheat sheet

These are the *current* defaults. The full table also lives in `scripts/capture.py` and updates faster than this doc — when in doubt run with `--live` and press `?` for the in-app legend.

**Always available:**

| Key | What |
|---|---|
| `Space` | Generic event mark |
| `q` / Ctrl-C | Stop the capture |
| `?` | Hotkey legend (in `--live`) |

**Marks for known rider actions** (each one baselines a 500 ms flip window):

| Key | Mark | | Key | Mark |
|---|---|---|---|---|
| `i` / `I` | indicator L / R | | `m` | ROAD/SUPERMOTO toggle |
| `b` | high beam | | `r` | trip reset |
| `g` | gear shift | | `t` | throttle blip |
| `n` | neutral | | `k` | kill switch |
| `h` | horn | | `s` | starter button |
| `e` | idle settled | | `j` | side stand |
| `c` | clutch pump | | | |

Any other printable key gets recorded raw — label it later from your notes.

**Live-mode only:**

| Key | What |
|---|---|
| `.` | Dump current flipped table to `snapshot-<n>.json` AND log a referencing mark |
| `w` | Pin a signal or `0x<id>:<byte>.<bit>` to the watch pane |
| `u` | Unpin a watch |

**Procedure mode only:**

| Key | What |
|---|---|
| `Tab` | Toggle operator ↔ analysis screen |
| `Space` | Pause / resume countdown |
| `←` | Rewind one step |

---

## Reading the live view

Five panes top-to-bottom:

1. **Watch** — your pinned signals (`w` to add). Each row: name · current value · 12-cell sparkline · pin origin. Booleans render as a square wave; numbers auto-scale to the buffer's own min/max so a stationary signal looks flat, not noisy.

2. **Decoded signals** — every entry from `signals.yaml`, with its current value and `(stale)` if no frame for that signal in the last 2 s.

3. **Known signals changed** *(left)* — schema-mapped signals whose value differs from baseline. Read first: "X went from A to B."

4. **Unknown bits flipped** *(right)* — bits *not* covered by any signal, scored against their own EWMA baseline. Top rows = most-anomalous-for-this-bit. Warmup rows show `z=∞`. D7 (checksum) is hidden by default — pass `--show-d7` to include it.

5. **Live anomalies** — same scoring as #4 but *continuous* (no mark required). Surfaces bits that are reacting to *something* even when you haven't pressed a hotkey. Newest-first, ages out after `--discovery-retention-secs` (default 60).

6. **Status** — elapsed · frames · unique IDs · marks · snapshots. `dropped N` in red = the UI thread is falling behind; capture itself is unaffected (the worker thread writes `capture.log` directly).

---

## Tuning the noise level

Defaults are tuned for "first look at a new input." Drop the threshold to fish for subtler signals; raise it to cut chatter:

```
--anomaly-z-threshold 3.0         # default; lower = noisier panes
--anomaly-warmup-flips 5          # rows surface as z=∞ for this many flips
--discovery-retention-secs 60     # how long the bottom pane remembers
--show-suppressed                 # also show bits the EWMA threw out (debug)
--show-d7                         # include the D7 checksum byte
```

---

## After the capture

The session dir holds:

```
logs/<date>-<label>/
├── capture.log              raw frames, candump format (always)
├── events.csv               every keystroke + auto-mark (always)
├── session.md               header auto-populated; **you fill the body**
├── live_decode.csv          per-frame decoded values (only with --live)
├── snapshot-N.json          one per `.` press (only with --live)
└── procedure.yaml.snapshot  copy of the procedure file (only with --experiment)
```

Then:

```
python scripts/analyze.py logs/<date>-<label>/
```

— picks the right per-input scanner (`kill_switch_scan.py` etc.) based on what marks landed, writes `analyze_report.txt` into the session dir. See the catalog in `scripts/README.md` for what each scanner does.

**`session.md` is the part future-you cares about most.** Fill in: bike state (cold/warm, gear, clutch, side stand, ROAD/SUPERMOTO), rider narrative (what you actually did, in order), anomalies (anything weird — backfires, error codes, the rider misclicking).

---

## Troubleshooting

**No frames at all.** Check `ls /dev/cu.usbmodem*` matches your `--port`. Sniff the raw line with `pio device monitor` — if you see status lines but no `t…` / `T…` lines, the firmware can see the adapter but not the bus (wiring, bitrate mismatch, key not on).

**`dropped N` in red and climbing.** UI thread can't keep up. Capture itself is fine (worker thread is independent), but the live view is lossy from that point. Lower the load: drop `--anomaly-z-threshold` higher (fewer rows), unpin watches you don't need, close the operator screen if you don't need it. The dropped counter is recorded — `capture.log` is still complete.

**Decoded pane shows `—` for a signal that should be live.** The signal isn't being broadcast in this bus state (some IDs only run with engine on), OR `signals.yaml` has the wrong coordinates. Cross-check against `inventory_ids.py` output.

**A capture re-run refuses to start.** `capture.py` won't overwrite a non-empty `capture.log`. Bump the label: `--label key-on-2`.

**Bitrate mismatch.** `--bitrate` is metadata only — the actual rate is fixed by the firmware build. Pass the value that matches the build so `session.md` doesn't lie.

**Firmware hash looks wrong.** Auto-detected via `git log -n 1 -- firmware/can-logger`. If you have uncommitted firmware edits, that hash is stale — pass `--firmware-rev <truth>` manually.

**Mid-capture USB unplug.** Recoverable: `capture.py` logs a `disconnect` event and writes the partial session out cleanly. The frames up to the drop are intact.
