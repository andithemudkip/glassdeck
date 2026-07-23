# Live-view roadmap

Planned UI/UX improvements to `firmware/wifi-bridge/main/index.html` (the browser-served live-decode view). Ordered by impact, not by planned sequence. Nothing here has an owner or a milestone — capture ideas as they come up, revisit before the next UI push.

## Shipped in the ride-mode push (v1)

The first four numbered items plus hard-stale (#5) and peak-reset landed together as one push.

- **Ride vs Diagnostic mode toggle** — `#modeBtn` in the capture bar, persisted per-browser in `livePrefs.mode`. Ride tags a small tier set (RPM/GEAR/WHEEL R hero, THROTTLE/COOLANT second-tier) via `data-tier`; CSS hides everything else, resizes heroes, collapses the header to a single health pip, and repositions sparklines below the digits instead of behind them.
- **Warning strip** (`#warnStrip`) — one dot per discrete signal above the decoded grid, tap to expand labels. Same colour polarity as the per-cell enum-ok / enum-err classes.
- **Sparklines + threshold bands** — 60-sample ring buffer per scalar, canvas polyline via `panelTick`. Bands (`cold_below` / `warn_above` / `danger_above` / `accent_above`) declared per-signal in `docs/signals/signals.yaml` and codegen'd through `SIGNALS[]`. Initial values: RPM 8500/9500, coolant 60/100/110, throttle accent-above 241 (~95%). Redline number needs verification against a real high-RPM capture.
- **Hard-stale for safety signals** — SAFETY set `{abs_lamp, kill_switch, side_stand, clutch}` gets a red outline + strobe on the warn-strip dot when `dt >= STALE_MS`, instead of just fading.
- **Peak reset** — tap the `▲` chip on any scalar to clear the accumulated max. Works in any mode.

## Not yet shipped

- **Layout presets.** Named profiles ("QS tuning", "Coolant walk-down") on top of the hide/reorder prefs. Complements the current customization; removes the friction of hand-rebuilding a layout each session. Ride mode is the first hard-coded preset; presets generalize that.
- **Sunlight theme.** Amber accent + dark bg is beautiful indoors, hard to read in direct sun. A "high-contrast outdoor" theme option would help daytime rides.
- **Orientation lock** for phone-on-bike landscape mount, so tilting doesn't flip the view.
- **Haptic on drag start/end** in edit mode (`navigator.vibrate([30])`) — cheap discoverability win on touch.
- **Fixed-time sparkline window** instead of fixed 60-sample count. Currently 60 samples means very different wall-time coverage for 100 Hz RPM vs 2 Hz counters. Do this if the fixed-sample look becomes confusing on slower signals.
- **Auto Ride/Diagnostic switch** — heuristic on orientation + network + rider state. Deferred; explicit toggle is fine for v1.
