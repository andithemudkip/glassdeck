# Live-view roadmap

Planned UI/UX improvements to `firmware/wifi-bridge/main/index.html` (the browser-served live-decode view). Ordered by impact, not by planned sequence. Nothing here has an owner or a milestone — capture ideas as they come up, revisit before the next UI push.

## 1 — Ride mode vs Diagnostic mode

The single biggest structural gap. This surface serves two audiences with one identical layout: a developer at a desk debugging CAN, and a rider glancing at a phone mid-corner. Their needs barely overlap.

- **Ride mode:** RPM + GEAR + rear wheel speed 2–3× current size, everything else hidden or shrunk. Header (ws/rssi/uptime/…) collapses to a single health pip.
- **Diagnostic mode:** what we have today.

Toggle sits in the capture bar. Reuses the hide/order/hero prefs infrastructure already built — Ride mode is really "saved layout preset A". Also unlocks per-mode threshold-band and stale-warning behaviours (see #3, #5).

## 2 — Discrete signals collapse into a warning-light strip

KILL, STAND, CLUTCH, ABS, QS ERR each own a ~90×72 cell to display 3–5 characters. On a portrait phone that's ~7 rows spent on booleans that rarely change while riding.

Replace with a single-row LED strip along the top (or bottom) of `#mid`: one coloured dot per discrete signal, tap for detail. Frees ~40% of mobile vertical viewport for scalars that do change.

## 3 — Value-in-context: sparklines + threshold bands

A number without shape is dev telemetry, not rider information.

- **Sparkline** per scalar: a 60-sample ring buffer drawn on a `<canvas>` behind `.val`. The per-signal `state` map already holds enough — extend with `history: Float32Array`.
- **Threshold bands** for signals with known safe/warn/danger ranges. Coolant: blue <60 / green 60–100 / amber >100 / red >110. RPM: white / amber near redline. Throttle: neutral <95% / accent ≥95%.

Turns the panel from an instrument readout into a legible timeline. Ride mode almost certainly needs both.

## 4 — Strip diagnostic noise in Ride mode

The 6-cell header (`ws/rssi/uptime/twai/seen/dropped`) and the per-cell `.loc` (`120 D0:D1`) are diagnostic-only.

- Header collapses to a single-pip health indicator: green if ws-open + twai-run + frames-arriving, else red. Tap expands to the current 6-cell view.
- `.loc` hides entirely in Ride mode.

Recovers ~50 px of vertical real estate on landscape phones, which is the tightest layout we support.

## 5 — Stale is a fade — that's backwards for safety signals

Today, staleness = opacity fade at 500 ms. Fine for a bus-quiet scalar. Wrong for a warning lamp: ABS last updated 5 s ago should be *louder* than 5 ms ago, not dimmer.

Two tiers:
- **Soft-stale** (opacity fade, current behaviour) for scalars.
- **Hard-stale** (red outline / persistent warning) for a `SAFETY` set: ABS, KILL, STAND — signals whose absence changes the meaning of everything else on screen.

Ties into #2: the warning strip is the natural home for hard-stale rendering.

## Runners-up (smaller wins)

- **Layout presets.** Named profiles ("Rider", "QS tuning", "Coolant walk-down") on top of the hide/reorder prefs. Complements the current customization; removes the friction of hand-rebuilding a layout each session.
- **Peak reset.** Tap `▲` to clear the accumulated peak for that signal — currently peaks accumulate for the entire page lifetime with no way to reset after (say) warmup.
- **Sunlight theme.** Amber accent + dark bg is beautiful indoors, hard to read in direct sun. A "high-contrast outdoor" theme option would help daytime rides.
- **Orientation lock** for phone-on-bike landscape mount, so tilting doesn't flip the view.
- **Haptic on drag start/end** in edit mode (`navigator.vibrate([30])`) — cheap discoverability win on touch.

## Sequencing suggestion

If tackling this end-to-end: **#2 (warning strip)** → **#3 (sparklines + bands)** → **#4 (strip diagnostic noise)** → wire them together as **#1 (Ride mode)**. #5 slots in with #2. Each is roughly one evening in isolation, but #1 really needs #2/#3/#4 to be more than a rearrangement.
