# Capturing — operator's guide

Practical instructions for running `capture.py` and reading the live TUI. For the *why* (architecture, threading model, decode path) read ADR 0005–0011 and `scripts/live_view/__init__.py`.

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

### "I just surfaced a likely signal and want to record it without breaking flow"

Press `Ctrl-N`. A modal opens listing the top rows currently in the **Active unknown bytes** pane (default tab) and, on `Tab`, the **Live anomalies** pane. Workflow:

1. Pick the row with `↑`/`↓` — the highlighted row is the one that'll be captured.
2. Type a working name (e.g. `throttle_hint`). Required.
3. Encoding is pre-filled from the classifier (`sensor`→`uint`, `boolean`→`bool`, `counter`→`uint`, `step`→`enum`; bit rows default to `bool`). Edit if you have a better guess.
4. `Ctrl-P` toggles the "pin to watch" checkbox (defaults on).
5. `Enter` submits; `Esc` cancels.

The stanza lands in `<session_dir>/hypotheses.yaml` (created on first capture, append-only thereafter):

```yaml
- name: throttle_hint
  status: hypothesis
  arbitration_id: '0x290'
  byte: 2
  bit_length: 8
  encoding: uint
  scale: 1
  offset: 0
  notes: Captured live 2026-06-22T14:32:01; range 142, ratio 23.5×, shape=sensor.
```

A `hypothesis` mark also lands in `events.csv` so you can locate the moment in the raw capture later. If "pin to watch" was on, the row also appears in the Watch pane immediately.

**`hypotheses.yaml` is not a finding.** Per the project's golden rule, hypotheses become findings (and entries in `docs/signals/signals.yaml`) only after a confirming experiment. The session file is the raw material the next experiment is designed around.

`--watch` mode disables capture (no session dir to write into); the modal pops a notification and bails.

### "I'm hunting a specific kind of signal — accent the matches"

You have a hypothesis ("RPM is some analog-ish sensor somewhere", "the kill-switch lives in a step-state byte"). Press `Ctrl-E`, pick a shape (`1`=sensor, `2`=counter, `3`=step, `4`=boolean; `0` clears). Matching rows in both discovery panes get a green-accented arb token; the byte pane also dims non-matches. See [Cue reference](#cue-reference) for the full behavior — and note that nothing is ever hidden, so an unexpected counter that turns out to be RPM still surfaces, just without preferential treatment.

The lens is session-local — never persisted, no CLI flag. Press `Ctrl-E` again to change shape or clear.

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
| `→` | Skip the current step. Logs a `procedure-skip` event tagged with the skipped step's auto-mark (`[mark=key\|label]`) so analysers can retract it, then advances and fires the next step's mark normally. No-op on the last step |
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
| `F1`..`F5` | Collapse / expand analysis pane (top→bottom; the side-by-side bit panes share slot 3) |
| `F6` / `F7` | Bump anomaly z-threshold by +0.5 / −0.5 (clamped ≥0.5). Live re-filters the bit-flip panes |
| `Shift-→` / `Shift-←` | Bump byte-activity ratio by +0.5 / −0.5 (clamped ≥0.5). Live re-filters the active-bytes pane |
| `Ctrl-D` | Toggle D7 visibility in the active-bytes pane |
| `Ctrl-Y` | Toggle "show suppressed" in the mark-driven flipped pane |
| `Ctrl-N` | Open the hypothesis-capture modal (see scenario above) |
| `Ctrl-E` | Open the expect-shape picker — accents matching rows in the discovery panes (ADR 0013) |

Function-key bindings are session-local — they never persist back to disk. If a setting always wants a non-default starting value, pass the CLI flag.

**Procedure mode only:**

| Key | What |
|---|---|
| `Tab` | Toggle operator ↔ analysis screen |
| `Space` | Pause / resume countdown |
| `←` | Rewind one step |
| `→` | Skip one step (logs `procedure-skip`) |

---

## Reading the live view

Six panes top-to-bottom, each fold-toggle-able with its function key. Status row always visible at the bottom.

### 1. Watch (`F1`) — pinned signals

Your `w`-pinned signals. Each row: name · current value · 12-cell sparkline · pin origin. Booleans render as a square wave; numbers auto-scale to the buffer's own min/max so a stationary signal looks flat, not noisy.

### 2. Decoded signals (`F2`)

Every entry from `signals.yaml`, with its current value and `(stale)` if no frame for that signal in the last 2 s.

### 3. Known signals changed / Unknown bits flipped (`F3`, side-by-side)

Both depend on a mark — empty until you press a hotkey, then baselined against the bus state at that moment.

- *Known signals changed* (left, cyan): schema-mapped signals whose value differs from baseline. Read first — "X went from A to B."
- *Unknown bits flipped* (right, yellow): bits not covered by any signal, scored against their own EWMA baseline. Top rows = most-anomalous-for-this-bit. Warmup rows show `z=∞`. D7 (checksum) hidden by default — `Ctrl-D` (or `--show-d7`) includes it. `Ctrl-Y` (or `--show-suppressed`) reveals bits the EWMA threw out.

### 4. Live anomalies (`F4`; ADR 0011) — continuous bit-flip discovery

Same scoring as Unknown bits flipped, but *continuous* (no mark required). Surfaces bits reacting to something even when you haven't pressed a hotkey. **One row per arbitration ID, sorted by arb ascending** — rows don't jump when new events arrive; they brighten in place and dim when they age out. Ages out after `--discovery-retention-secs` (default 60).

```
  0x290  ⊞  D3 b2,b5            ▁▁▁▂▃▅█▇▅▃▁▁  │  z=4.2   -0.4s
▶ 0x4A1  ·  D0 b0                ▁▁▁▁▁▁▁▁▁▁█▁  │  z=∞    -1.1s
  0x123  ↻  D4 b7                ▁▂▁▂▁▂▁▂▁▂▁▂  │  z=3.5  -1.2s
```

Five visual cues per row:

- **Glyph** — `⊞` / `↻` / `·`; see [Cue reference](#cue-reference).
- **Activity sparkline** (12 cells, aligned across rows) — each cell counts anomalies in one bucket of the retention window (5 s/cell at default). Aligned vertically: two IDs spiking in the same column fired together. A tall right-edge bar with blanks left = "just woke up"; a flat ramp across all 12 cells = persistent counter chatter.
- **Co-occurrence accent** (colored arb token) — when ≥2 rows have their most recent event within ~300 ms AND in the last 3 s, their arb tokens go colored (cyan / magenta / green / yellow, recycling). Same color = those rows just fired together.
- **Mark halo** (`▶ ` prefix + bold yellow arb) — when you press a mark hotkey, rows whose latest event falls inside the 500 ms mark window get `▶` for ~4 s. Bridges the continuous pane and the mark-driven pane during scripted procedures.
- **Brightness decay** — rows render bright while `latest_ts < 20 s` old, then dim. Stable arb sort + brightness decay together make the pane readable while moving.

Precedence when cues collide: mark halo > co-occurrence accent > expect-shape accent (operator gesture is the strongest signal).

**Startup chatter.** First ~10 s of any session, every bit is in EWMA warmup (`z=∞`) and every flip surfaces — the pane lights up with `·`-glyph rows then settles. Wait it out; this is what catches once-per-session events (a kickstand flip) that a stricter warmup would hide.

### 5. Active unknown bytes (`F5`; ADR 0008, render ADR 0012) — byte-level discovery

For each (arb, byte), maintains a rolling-window range and a long EWMA baseline; surfaces bytes whose current range is `--byte-activity-ratio`× the baseline. Bytes covered by `signals.yaml` are excluded (they belong to the decoded pane). Each row: ID · byte · current value · sparkline · `peak=N.N×` · time-since-peak · shape hint (`sensor` / `boolean` / `counter` / `step` / `(first activity)`). D7 hidden by default (`Ctrl-D`). The `Ctrl-N` modal pulls from this pane.

```
  0x290 D2   value=234 / 0xEA   ▁▂▃▄▅▆▇█      │  peak=4.2×   -0.3s   sensor
  0x4A1 D0   value=  3 / 0x03   ▁▁▁▁▁▁▁█      │  peak=∞      -1.1s   (first activity)
[dim]  0x123 D4   value= 12 / 0x0C   ▁▂▁▂▁▂▁▂  │  peak=2.8×   -8.2s   counter[/dim]
```

Two-tier brightness (ADR 0012):

- **HOT** (bright) — byte is currently above ratio OR was within `--byte-activity-hysteresis-secs` (default 5). Sparkline is live, sampled ~4 Hz from actual byte values.
- **DIM** (`[dim]`-wrapped) — past hysteresis but within `--byte-activity-retention-secs` (default 30). Sparkline **freezes** at the snapshot from when activity ended — the peak shape that made you look is preserved through decay.
- **Drop** — past retention. Row vanishes and `peak_ratio` resets, so the next episode for that byte starts clean.

Rows sort by **peak ratio descending** (not current ratio), so a row that just hit `peak=5×` stays near the top through its decay even as the current ratio falls. `peak=∞` = byte was flat-zero through the whole baseline window and just woke up — the strongest possible signal.

### 6. Status row (always visible)

Three lines: elapsed · frames · unique IDs · marks · snapshots; current tunables (`z=… ratio=…× d7=… suppressed=…`, plus `expect=<shape> <glyph>` when the lens is armed); key-cheat line. `dropped N` in red = UI thread falling behind; capture itself is unaffected (the worker thread writes `capture.log` directly).

Collapsed state is session-local — re-collapse next launch. Defaults are all-expanded so the layout never shifts on startup.

---

## Cue reference

### Live anomalies glyphs

| Glyph | Means | What it usually is |
|---|---|---|
| `⊞` | ≥2 bits flipping on the same byte | Real signal change — multi-bit field updating in lockstep (gear position, indicator, multi-bit enum). Investigate first. |
| `↻` | One bit; fast-cycling baseline (µ < 0.5 s); finite z | Counter glitch or brief bus stall, not a new signal. Lower priority unless one ID's `↻` repeats. |
| `·` | Everything else — isolated single-bit flips | Rare event (kickstand, button) or warmup noise. Cross-check with the sparkline — one spike = real event, regular pattern = chatter. |

### Expect-shape accent (`Ctrl-E`, ADR 0013)

Arming a shape (`sensor` / `counter` / `step` / `boolean`) gives matching rows in both discovery panes a **green-accented arb token**.

- **Byte pane** — matches accented; non-matches `[dim]`-wrapped regardless of HOT tier; unclassified and `(first activity)` rows stay neutral (the row you're trying to find during the first ~1 s of a sweep shouldn't be punished).
- **Anomaly pane** — accent only, no dimming (pane too dense). Expect-accent yields to co-occurrence accent and mark halo when both apply.

The lens is a viewing aid, never a filter — every row the classifier surfaced still appears. Status row shows `expect=<shape> <glyph>` while armed.

---

## Tuning the noise level

The two discovery panes are driven by **per-thing baselines, not absolute thresholds**. The pane doesn't ask "is this value high?" — it asks "is this value surprising for *this specific* bit / byte's recent history?". That matters for tuning: you're not setting a value, you're setting *how much weirder than usual* something has to be before it surfaces.

The two live-tunable knobs are `z-threshold` (bit-flip pane) and `ratio` (byte pane). Everything else is structural — set at startup, rare to change mid-session.

### `--anomaly-z-threshold` — bit-flip surprise (live: `F6`/`F7`, default 3.0)

**What it measures.** Every bit on the bus maintains an EWMA of how long the typical gap is between its flips (µ = mean interval, σ = std-dev of that interval). When the bit flips again, the new interval gets a **z-score**: how many standard deviations the gap was from the mean. `z = (this gap − µ) / σ`.

- `z = 0`: the interval matched the bit's usual pacing. Boring.
- `z = 3`: the interval was 3σ longer than typical for this bit. Statistically rare under "this is the same regime" — about 0.1% of intervals if the noise were Gaussian.
- `z = ∞`: rendered when the bit is still in EWMA warmup (first 5 flips by default). No baseline yet, so every flip surfaces unconditionally — this is what catches rare-but-real events like a kickstand flip that only happens once or twice per session.

Importantly: z-threshold is **per bit**, not global. A 50 ms-cycle counter and a 10 s-cycle rare bit get measured against their own baselines. A 200 ms gap on the counter is huge (z ≈ 30); a 200 ms gap on the rare bit is invisible (z ≈ 0). So lowering or raising the threshold doesn't favour fast-or-slow bits — it just changes "how unusual is unusual."

**Raise z (3.0 → 5 / 8 / 10)** when:
- Engine running and the pane is flooded with rows you don't care about (counter / checksum chatter that just barely crosses the threshold).
- You're hunting one specific class of event and want only the strongest signal at the top.
- Net effect: only the rarest tail events for each bit surface. Subtle signals get hidden, but the eye can scan the pane in one glance.

**Lower z (3.0 → 2.0 / 1.5)** when:
- The pane stays empty even though you know the bus reacted (you just pressed a button and nothing showed up).
- You're hunting a subtle / slow signal that might be just inside the bit's normal envelope.
- You suspect something is being treated as "within tolerance" when it isn't.
- Net effect: more rows surface, including some real signals that were sitting at z ≈ 2.5. Cost: more counter noise rides up with them.

**Floor (below ~1.5).** Z drops below 2 and you're essentially asking "show me every flip" — useful for one-off diagnostics, useless as a baseline.

### `--byte-activity-ratio` — byte sweep surprise (live: `Shift-←→`, default 3.0×)

**What it measures.** Every byte on the bus maintains two things over a rolling window (default 2 s):
- `short_range` — the (max − min) of that byte's values in the current window.
- `baseline_range_ewma` — a long-running smooth of `short_range` (~100-sample EWMA).

A byte surfaces in the Active unknown bytes pane when `short_range ≥ ratio × baseline_range_ewma`. So `ratio = 3.0` means "this byte is sweeping 3× wider in the last 2 s than it usually does."

Unlike z-threshold, ratio doesn't have a warmup escape hatch — but it doesn't need one. A previously-flat byte has baseline ≈ 0, so the first sweep trips against `BASELINE_FLOOR` (≈4 counts) and ratio → ∞ on its own. That's what the `(first activity)` suffix means: this byte has been flat the whole session and just started moving. Strongest signal you can get.

**Raise ratio (3.0 → 5 / 10)** when:
- Pane is busy with bytes you've already identified or don't care about.
- Many bytes legitimately sweep some, and you only want the dramatic standouts.
- Engine running and several sensor bytes are doing 4–5× sweeps as normal operation — raise to filter them.

**Lower ratio (3.0 → 1.5 / 2.0)** when:
- You're chasing a byte that probably only changes slightly (e.g. a fuel level that ticks down by 1 count at a time).
- The pane is showing nothing but you know an input you pressed touched the bus.

**Floor (below ~1.5).** A byte at ratio ≈ 1.0 is just doing its usual thing — surfacing it is a sign your threshold is too loose, not that you're being more sensitive.

### Other tunables (structural — CLI-only)

#### `--anomaly-warmup-flips` (default 5)

How many flips a bit gets before the EWMA-based z-score kicks in. Below this count, every flip surfaces with `z=∞`. Larger = the bit needs to repeat more times before becoming "boring," so more startup chatter but more catching-of-rare events. Smaller = baselines settle faster but a bit that fires only 3 times all session will go from "warmup, surfaced" to "boring, not enough data."

Default of 5 is tuned to catch the kickstand case (a once-or-twice-per-session bit always surfaces). Lower it if startup chatter is genuinely intolerable; raise it if you suspect the EWMA is locking onto a non-representative early sample.

#### `--discovery-retention-secs` (default 60)

How long the Live anomalies pane remembers anomalous flips. Affects three things:
- How long aged rows stay visible before dropping off (decay-then-disappear).
- The width of one cell in the per-row activity sparkline (`retention / 12` seconds per cell — 5 s at the default).
- How long-back the co-occurrence sparkline alignment goes.

Raise to ~120–300 s for long-arc analysis ("did this byte react to anything I did in the last 5 min?"). The sparkline buckets get coarser. Lower to ~30 s for tight "what just happened *now*" focus and finer-grained buckets. ADR 0011 §3 also notes that 60 s is roughly the floor for an operator to act, look up, read, and react before the entry ages out.

#### `--byte-activity-window-secs` (default 2.0)

The rolling window inside which `short_range` is computed. Smaller = twitchier pane that reacts faster to brief sweeps but also flickers more. Larger = smoother, slower to react, catches sustained sweeps better. The trade is responsiveness vs stability — at 2 s, a 1 s burst is visible; at 5 s, it would only show after the second second of sustained activity.

#### `--byte-activity-hysteresis-secs` (default 5.0; ADR 0012 changed semantics)

How long a row stays in the **HOT** (default-brightness) tier of the Active unknown bytes pane after activity ends. Past this, the row drops into the **DIM** tier (still visible, `[dim]`-wrapped) and stays there until `retention_secs` expires.

Raise (5.0 → 10–15) when you want recently-active rows to stay bright for longer (useful during a maneuver where activity comes in waves and you want each wave to register as "fresh"). Lower (5.0 → 2–3) when the HOT tier gets crowded with rows you've already seen and you want them dimmed sooner.

#### `--byte-activity-retention-secs` (default 30.0; ADR 0012)

Total time a row stays visible in the Active unknown bytes pane after activity ends. The first `hysteresis_secs` are HOT; the remainder is DIM. Past this, the row vanishes AND its `peak_ratio` resets so the next activity episode for that byte starts clean.

Raise (30 → 60–120) when you're doing a long arc of work and want to see "what bytes have been active in the last 2 minutes" at a glance. The DIM tier grows; the pane gets visually busier but no row is ever ripped away unread. Lower (30 → 10) for tight "right now" focus — rows vanish faster, pane stays sparse. A row that you genuinely want to keep visible regardless of timing is what the Watch panel (`w`) is for.

The `--byte-activity-hysteresis-secs` value must be ≤ this; otherwise the DIM tier would be empty (the row would drop before it had a chance to dim).

#### `--show-d7` (live: `Ctrl-D`, default off)

D7 is the universal checksum byte (see `findings/can/byte-d7-cycle-hash.md`) — it cycles every frame on every always-on ID and would otherwise dominate both discovery panes. Toggle on only when you specifically suspect a non-checksum signal on D7 of one ID, or you're investigating the checksum algorithm itself.

#### `--show-suppressed` (live: `Ctrl-Y`, default off)

Shows bits the EWMA scored *below* the z-threshold in the mark-driven flipped pane (renders them dim, marked `[suppressed]`). Useful for two debugging cases:
- "Why isn't bit X surfacing?" — toggle on to see the z-score the EWMA actually computed for it. If z=2.8 and threshold is 3.0, that's why; lower the threshold or accept the verdict.
- "I think the threshold is too aggressive in this session." — quick way to eyeball how many real-looking rows are sitting just under it before committing to a permanent threshold change.

EWMA internals (window sizes, σ floor, baseline floor) live in `scripts/live_view/constants.py` and are tuned in ADRs 0007 / 0008. Don't touch them unless you've read those.

### Summary card

```
# Bit-flip discovery (ADR 0007, render redesigned in ADR 0011)
--anomaly-z-threshold 3.0         # live: F6 raise / F7 lower
--anomaly-warmup-flips 5          # CLI-only; rare-event coverage knob
--discovery-retention-secs 60     # CLI-only; pane memory window
--show-suppressed                 # live: Ctrl-Y; debug "why no row?"
--show-d7                         # live: Ctrl-D; include checksum byte

# Byte-activity discovery (ADR 0008, render redesigned in ADR 0012)
--byte-activity-window-secs 2.0       # CLI-only; rolling-range twitchiness
--byte-activity-ratio 3.0             # live: Shift-→ raise / Shift-← lower
--byte-activity-hysteresis-secs 5.0   # CLI-only; HOT-tier extension before DIM
--byte-activity-retention-secs 30.0   # CLI-only; total row visibility window
```

Live-tunable knobs are session-local — they never persist. If a non-default value should be the *starting* point every session, pass the CLI flag.

---

## Cheatsheet — "I see X, what do I do?"

Quick-glance interpretation for the panes you're most likely to be reading mid-session.

### Live anomalies pane

| You see | What it means | Next move |
|---|---|---|
| Two rows light up with the **same accent color** | Those two IDs just fired within ~300 ms — likely physically linked | If you'd just done a physical action: those are your candidates. Press `Ctrl-N` to capture the most suggestive one. |
| A `▶` halo on one row right after a mark hotkey | That row's latest event fell inside your 500 ms mark window | That ID reacted to whatever you just did. Same response as above — `Ctrl-N` if it looks new. |
| `⊞` glyph on a row | Multi-bit on one byte flipped together — looks like a signal field | High-priority investigation target. Multi-bit-same-byte rarely happens by chance. |
| `↻` glyph repeatedly on the same arb | Counter bit had a tail interval | Usually noise. Bump `F6` to raise the z-threshold if these are dominating the pane. |
| `·` rows flooding the pane in the first ~10 s | Warmup chatter — every bit's first 5 flips surface unconditionally | Wait. After ~10 s the baseline learns and the pane calms down. ADR 0007 §97. |
| Sparkline is a flat ramp across all 12 cells | This ID has been firing constantly through the whole window | Probably persistent counter noise that's tripping the threshold. Bump `F6` or investigate the bit (might be a counter signal worth decoding). |
| Sparkline has one tall bar at the right edge | This ID just woke up (one recent burst, nothing before) | Cross-reference with what you were doing. Good candidate. |
| Row stays dim even after you act | Latest event for that ID is > 20 s old — the row is showing history, not "now" | Ignore unless you care about the historical co-occurrence (look at the sparkline). |
| `(idle — no anomalous flips yet)` | The pane is empty because the EWMA hasn't flagged anything in the retention window | Either the bus is quiet (engine off, ignition off) or the z-threshold is too high. Try `F7` to lower it. |

### Active unknown bytes pane

| You see | What it means | Next move |
|---|---|---|
| A row with `shape=sensor` and a steady-amplitude sparkline | Byte is varying continuously with motion or load | Almost certainly a real signal. `Ctrl-N` and name it `<guess>_hint`. |
| `shape=counter` rolling | Modulo counter byte | Useful for sync but not a "signal" in the dashboard sense. Note it; move on. |
| `shape=boolean` | Two-state byte | Either a real boolean signal or a flag bit packed into the LSB. Worth `Ctrl-N`-ing. |
| `(first activity)` suffix | This byte was flat-zero for the whole baseline and just started moving | Strongest signal you can get — this byte was *waiting* for whatever you just did. Top priority. |
| `[dim]` row with high `peak=N.N×` near the top | Byte was loud a few seconds ago and is now quiet; row preserved through decay (ADR 0012) | This is the "I saw it react and now I'm reading the row" case. `Ctrl-N` if the peak shape (sparkline) looks like a real signal — the frozen sparkline preserved it for you. |
| Row near the top with sparkline visibly settling | Recently peaked but still active above threshold | Wait a beat for the row to enter decay (sparkline freezes at peak), then read it without time pressure. |
| Pane saturated with rows you don't care about | Threshold too low OR retention too long | Bump `Shift-→` to raise ratio. If many DIM-tier rows are crowding HOT rows, lower `--byte-activity-retention-secs` for next session. |

### Known signals changed / Unknown bits flipped (mark-driven)

| You see | What it means | Next move |
|---|---|---|
| Top row says "RPM went 1700 → 1740" | Known signal moved across the mark window | If that's not what you expected, write it in `session.md`. |
| Many rows in unknown-flips, none with very high z | Bus is noisy this session OR mark was poorly timed | Re-mark closer to the actual action. The 500 ms window cuts off — if your action takes longer (gear shift), only the first transition lands. |
| Pane stays empty after `(no decoded delta)` | Mark fired but nothing on the bus changed in 500 ms | Either the input doesn't touch CAN (purely mechanical) or it's slower than 500 ms. |
| Same bit appears on every mark | That bit flips on *anything* — counter, frame ID rolling, etc. | Add to mental "noise floor" list. `Ctrl-Y` to see it next to its EWMA verdict. |

### Status row

| You see | What it means | Next move |
|---|---|---|
| `dropped N` climbing in red | UI thread can't keep up; live view is lossy | Capture itself is fine. Fold panes you aren't watching (`F1..F5`), bump thresholds. See Troubleshooting. |
| Frame count flat / not climbing | No new frames arriving | Bus is silent (engine + ignition off?) OR adapter/firmware/wiring issue. See Troubleshooting. |
| `marks: 0` after pressing hotkeys | Hotkey isn't bound | Check the hotkey table — anything *not* in HOTKEYS is recorded raw but doesn't open a mark window. |

---

## After the capture

The session dir holds:

```
logs/<date>-<label>/
├── capture.log              raw frames, candump format (always)
├── events.csv               every keystroke + auto-mark (always)
├── bus_status.log           firmware health lines: bus_err / rx_missed / rx_overrun (always)
├── session.md               header auto-populated; **you fill the body**
├── live_decode.csv          per-frame decoded values (only with --live)
├── snapshot-N.json          one per `.` press (only with --live)
├── hypotheses.yaml          one stanza per `Ctrl-N` capture (only with --live; append-only)
└── procedure.yaml.snapshot  copy of the procedure file (only with --experiment)
```

Then:

```
python scripts/analyze.py logs/<date>-<label>/
```

— picks the right per-input scanner (`kill_switch_scan.py` etc.) based on what marks landed, writes `analyze_report.txt` into the session dir. See the catalog in `scripts/README.md` for what each scanner does.

**`session.md` is the part future-you cares about most.** Fill in: bike state (cold/warm, gear, clutch, side stand, ROAD/SUPERMOTO), rider narrative (what you actually did, in order), anomalies (anything weird — backfires, error codes, the rider misclicking). If `hypotheses.yaml` was written, cross-link it: a line or two per stanza saying what made you press `Ctrl-N` and what you'd want the next experiment to confirm.

---

## Troubleshooting

**No frames at all.** Check `ls /dev/cu.usbmodem*` matches your `--port`. Sniff the raw line with `pio device monitor` — if you see status lines but no `t…` / `T…` lines, the firmware can see the adapter but not the bus (wiring, bitrate mismatch, key not on).

**`dropped N` in red and climbing.** UI thread can't keep up. Capture itself is fine (worker thread is independent), but the live view is lossy from that point. Lower the load: bump the thresholds (`F6` for z, `Shift-→` for ratio — fewer rows in the discovery panes), fold panes you aren't watching (`F1`..`F5`), unpin watches you don't need. The dropped counter is recorded — `capture.log` is still complete.

**Decoded pane shows `—` for a signal that should be live.** The signal isn't being broadcast in this bus state (some IDs only run with engine on), OR `signals.yaml` has the wrong coordinates. Cross-check against `inventory_ids.py` output.

**A capture re-run refuses to start.** `capture.py` won't overwrite a non-empty `capture.log`. Bump the label: `--label key-on-2`.

**Bitrate mismatch.** `--bitrate` is metadata only — the actual rate is fixed by the firmware build. Pass the value that matches the build so `session.md` doesn't lie.

**Firmware hash looks wrong.** Auto-detected via `git log -n 1 -- firmware/can-logger`. If you have uncommitted firmware edits, that hash is stale — pass `--firmware-rev <truth>` manually.

**Mid-capture USB unplug.** Recoverable: `capture.py` logs a `disconnect` event and writes the partial session out cleanly. The frames up to the drop are intact.
