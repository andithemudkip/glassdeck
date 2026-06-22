# 0008 — Live view: byte-level activity discovery

**Date:** 2026-06-22
**Status:** Draft

## Context

ADR 0007 introduced bit-flip discovery on `AnalysisScreen` — mark-driven and continuous panes, both filtered by a per-bit EWMA-of-intervals baseline. This addresses one half of the discovery surface well: status bytes that pack independent flags (kill / side-stand / gear / engine-state in a single byte) decompose cleanly into per-bit events, and a flip is the right unit to detect.

The other half — continuous-valued bytes — is not addressed. An RPM byte sweeping 0 → 200 as the rider blips the throttle trips most of its 8 bits, but the human-relevant signal is the *value sweep*, not the bit-level activity. After 0007 lands, that byte's bits would all warmup, then settle into noisy-counter baselines, and the pane would stop highlighting it — exactly when the operator would most benefit from seeing it move. The current decoded pane only surfaces bytes already covered by `signals.yaml`; anonymous bytes are invisible until someone manually inspects raw frames in `analyze.py` post-hoc.

Concretely, the discovery loop for a sensor-shaped byte today looks like: ride, capture, post-hoc grep raw frames for bytes that show range, hypothesise mapping, add to `signals.yaml`, redecode. The whole live-view loop is bypassed. Live byte-value visualisation is exactly the affordance "a simpler SavvyCAN" was reaching for — and unlike live plotting (rejected in 0007), it fits naturally on top of the sparkline + baseline infrastructure 0007 already adds.

Two distinct flavours of byte exist on this bus, and they want different ergonomics:

- **Status bytes:** independent bits, each with discrete meaning. Bit-level discovery (0007) is correct.
- **Sensor bytes:** byte value tracks a continuous physical quantity (rpm, throttle, temperature, speed). Byte-level visualisation is correct; bit-level decomposition loses the meaning.

Both are common and both deserve first-class live discovery. This ADR adds the byte-level surface; the bit-level surface from 0007 is unchanged.

We considered and rejected: merging byte and bit panes into a single "unknown activity" view (more compact but conflates two abstractions with different rendering and different baselines); always-on enumeration of all anonymous bytes with sparklines (information-dense but uses far more screen real estate than the value warrants — 95% of bytes are constant or counters and aren't worth a row); a separate browser screen reachable by tab key (extra navigation friction, and the activity pane already surfaces the bytes worth looking at).

## Decision

Add per-byte activity tracking and a new **Active unknown bytes** pane on `AnalysisScreen`. The pane behaves more like a live dashboard ("what's currently active") than a recent-events log ("what just happened"), which is the appropriate abstraction for continuous values.

### 1. Per-byte activity baseline

Per `(arb_id, byte_index)`, maintain:

- A short rolling buffer of recent `(timestamp, value)` samples covering `ACTIVITY_WINDOW_SECS` (default 2.0 s). Used to compute current activity.
- `short_range` = `max(buffer) - min(buffer)` over the window. The single most useful activity metric: it catches "byte became non-constant" and "byte's range expanded" with one number, and is robust to whether the value is monotonic or oscillating (both count as active).
- `baseline_range_ewma` = exponentially-weighted mean of `short_range` over time, smoothing factor `α ≈ 0.02` (effective window ≈ 100 short-range samples).

A byte is **active** when:

```
short_range > max(BASELINE_FLOOR, ACTIVITY_RATIO × baseline_range_ewma)
```

`ACTIVITY_RATIO` (default 3.0) is the multiplicative threshold; `BASELINE_FLOOR` (default 4) prevents zero-baseline division pathologies and suppresses noise floor — a byte whose current range is just a few LSBs of jitter doesn't trip even if its history was perfectly flat.

Why range and not variance / per-sample delta / per-change interval:

- **Variance** is nearly equivalent but more expensive to maintain online and harder to read; range gives the same signal for the patterns we care about.
- **Per-sample delta** misses slow sweeps (small ticks accumulating into a big sweep) and over-fires on noisy sensors.
- **Per-change interval** (the 0007 metric) is wrong for continuous values: a sensor byte changes every tick whether or not it's doing anything interesting.

No warmup escape hatch is needed (unlike the bit-flip case): the first time a byte's value moves, `short_range` jumps from 0 to nonzero against a baseline of 0, naturally producing a divide-by-floor anomaly. Rare bytes get surfaced for free.

### 2. "Active unknown bytes" pane

A fourth pane (fifth counting the watch pane from 0007) below the continuous bit-flip pane. Lists every byte currently satisfying the activity condition above, excluding bytes covered by any signal in `signals.yaml` (those belong in the decoded pane). Render:

```
Active unknown bytes
  0x290 D2   value=187 / 0xBB    [▁▃▅▆▇█▇▆▅▃]   range 142  ratio=23.5×
  0x4A1 D5   value=42  / 0x2A    [▔▔▔▔▔▆▇▆▔▔]   range 18   ratio=4.1×
  0x230 D0   value=0   / 0x00    [▁▂▃▂▁_____]   range 6    ratio=∞   (first activity)
```

Each row shows:

- Arbitration ID + byte index (`0x290 D2`)
- Current value in decimal and hex
- A 12-character sparkline of the rolling buffer, using the same eighth-block ramp `▁▂▃▄▅▆▇█` that the watch pane uses, scaled to the buffer's running min/max
- `range N` — the absolute `short_range` value
- `ratio=N.N×` — `short_range / baseline_range_ewma` (or `∞` if baseline is at floor)

Sorting: descending by `ratio`. Most-surprising-relative-to-its-own-history bytes float to the top. A byte whose range is large but consistently has been large (a 16-bit counter low byte) has `ratio ≈ 1` and sinks to the bottom or doesn't qualify at all.

Aging: a byte exits the pane when `short_range` falls back below the activity threshold *and* has stayed below it for `ACTIVITY_HYSTERESIS_SECS` (default 3.0). Hysteresis prevents flicker on bytes that hover near the threshold.

Pane height bounded to ~10–15 rows; overflow renders `… and N more` (same convention as 0007's bit panes).

### 3. Sparkline rendering reuses 0007's primitive

The watch pane (0007 change #1) already implements eighth-block sparkline rendering from a ring buffer. The same helper is reused here — no second implementation, no per-call shape decisions. Boolean / enum signals in the watch pane use `_` / `▔` segments; byte-value sparklines use the full ramp. Difference is internal to the helper, not a separate concept.

### 4. CLI flags

Three new flags on `capture.py`, all with sensible defaults so the bare command continues to work:

- `--byte-activity-window-secs` (default 2.0) — rolling window for `short_range`
- `--byte-activity-ratio` (default 3.0) — multiplicative threshold over baseline
- `--byte-activity-hysteresis-secs` (default 3.0) — how long a byte must stay quiet before leaving the pane

No on-disk artifacts. The pane is pure presentation, like every other panel on `AnalysisScreen`. The values themselves are already recorded frame-by-frame in `capture.log`; any post-hoc analysis can reconstruct everything the pane displayed.

### 5. Mark-driven byte pane — deferred

A natural symmetric extension is a mark-driven byte pane: "which bytes became active in the post-mark window." This is straightforward (snapshot baseline ranges at mark time, list bytes whose post-mark range exceeded threshold), but it's not the gap the user identified — they specifically pointed at "watching values change," which is the continuous case. Defer until a concrete experiment shows the mark-driven byte view would have changed an outcome. Same data is in `capture.log`; post-hoc analysis already handles the offline version.

## Consequences

- **The "RPM byte invisible until manually mapped" loop closes.** A sensor-shaped byte announces itself in the live view the moment it sweeps; the operator notices, makes a hypothesis (e.g. "byte D2 of 0x290 tracks throttle"), can immediately design a confirmatory experiment, and adds it to `signals.yaml`. This compresses the discovery loop from "session → post-hoc analysis → next session" to a single session.
- **Status and sensor bytes are both first-class.** 0007's bit panes catch one category; this ADR catches the other. Both run in parallel — no mode switching, no operator decision about which view to look at. The bus naturally has both kinds of bytes and the screen shows both.
- **One more pane to fit on `AnalysisScreen`.** Total budget after both ADRs: Watch, Decoded, Known-changed (mark), Unknown bits (mark), Continuous unknown bits, Active unknown bytes, Status. Seven panes — tight but feasible on a typical terminal. If real-world use shows the screen is overloaded, the right fix is to make panes collapsible (one-key toggle) rather than to remove any of them; they serve different cognitive modes.
- **Per-byte state is small.** Per `(arb_id, byte_index)`: one ring buffer of ~30 samples and three scalars. For a bus with ~20 IDs × 8 bytes, that's ~160 bytes-of-state × 30 samples × 8 bytes-per-sample ≈ 40 KB. Negligible.
- **Anonymous-byte filter depends on `signals.yaml` coverage.** As the project decodes more bytes, the pane naturally shrinks — bytes graduate from "anonymous and active" to "named in the decoded pane." That's a feature: the pane is a live to-do list of "bytes worth investigating next."
- **No warmup affordance.** Unlike the bit case where a rare bit needs explicit warmup to surface, the range metric handles rare activity naturally (any move from a flat baseline trips the ratio against the floor). Simpler.
- **Future extension: byte classifier.** A natural follow-on is to annotate each row with a guessed shape — `counter`, `sensor`, `step`, `boolean-ish` — based on the buffer's pattern. Out of scope here; would need either heuristics or a small classifier and warrants its own ADR if it ever clears the bar.
- **Future extension: pane unification.** If experience shows that "active unknown bytes" and "continuous unknown bits" answer the same operator question often enough, they could merge into one "unknown activity" pane keyed on `(arb_id, byte_index)` with bit annotations inline. Not pre-decided — let usage drive it.
- **Scope discipline.** This ADR is byte-level activity for the live view only. It is not a plotter, not a frame browser, not a DBC editor, not byte-level mark-driven analysis (deferred above). Each of those is a separate decision if pressure exists.
- **Implementation touch points.** All inside `scripts/live_view.py`: per-byte ring buffer + EWMA state, updated in the frame handler alongside the per-bit stats from 0007; a new pane in `AnalysisScreen.compose` and a corresponding render method; the existing sparkline helper used unchanged; the `signals.yaml` coverage check (already computed in `_bit_to_signal`) extended to a `_byte_to_signal` index. `capture.py` gains three CLI flags. No changes to `signals.py`, `procedure.py`, or any on-disk format.
