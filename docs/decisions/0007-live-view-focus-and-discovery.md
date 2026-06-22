# 0007 — Live view: focus panel, baseline-aware discovery, grouped unknowns

**Date:** 2026-06-22
**Status:** Accepted

## Context

`scripts/live_view.py` (introduced in ADR 0005) renders three panes during capture: decoded signals, known-signals-changed-since-last-mark, and unknown-bits-flipped-since-last-mark. In practice the UI has two readability problems that bite as soon as the engine is running:

- **The decoded pane is a uniform firehose.** Every entry in `signals.yaml` refreshes at 4 Hz with equal visual weight. Fast-moving signals (rpm, frame counters, anything ticking with the engine) draw the eye away from the slow ones the operator usually wants to watch. There is no mechanism to elevate "I care about this right now" against "the bus is alive."
- **The unknown-flips pane saturates instantly under engine load.** The current rule is "every bit that transitioned in the 0.5 s window after the last mark." With the engine running, dozens of bits flip every 0.5 s — checksum/counter bits in particular — and the pane spills to `+30/50 more` before the rider has even completed the maneuver they're trying to attribute a flip to. The signal the operator pressed the hotkey to find is buried under the noise floor of the bus itself.
- **Discovery only happens when the operator presses a hotkey.** The unknown-flips pane is mark-driven by construction: nothing surfaces unless the operator anchors a window. That's the right shape when the operator has a specific question ("what touched the bus when I shifted?"), but useless during open-ended discovery sessions where the workflow is "ride around, see what stands out." Today the rider would have to keep mashing a generic mark key just to keep the pane populated.

A fourth, smaller friction: unknown flips are rendered one row per `(ID, byte, bit)`. A multi-bit signal (e.g. a gear position) shows up as 4–8 separate rows, vertically fragmenting one event across the screen.

The user's reflexive ask — "wouldn't it be neat to plot certain IDs/bits live" — is a symptom of these readability problems rather than a missing feature. A SavvyCAN-style graph plotter would be a much larger lift than the underlying problem warrants, and the project already does time-series work post-hoc via `scripts/analyze.py` where re-cutting windows is cheap.

We considered and explicitly rejected: live plotting widgets (rebuilding SavvyCAN), search/filter UI (lower leverage than pin), color-coding by category (cosmetic), audible mark cues (different ergonomic axis), and a ring-buffer rewind for mis-timed marks (low-frequency problem, adds keybind complexity, makes event timestamps fuzzier vs `events.csv`).

## Decision

Five coordinated changes to `live_view.py`'s `AnalysisScreen`. All preserve ADR 0005's principle that the UI is presentation only: every datum still lands in `events.csv`, `capture.log`, `live_decode.csv`, or `snapshot-N.json` as it does today.

### 1. Watch panel + inline sparklines (focus mode)

A new pinned-watch pane renders above the existing decoded pane. Operators add a signal (or a raw `(ID, byte, bit)`) to the watch list with a keybind; pinned entries render with larger column widths and a 12-character inline sparkline alongside the current value:

```
Watch
  rpm                 1840    ▁▂▃▅▆▇█▇▅▄▃▂   rpm
  gear                3rd     ____▔▔▔▔▔▔▔▔   gear
  side_stand_bit      DOWN    ▔▔▔▔▔▔__▔▔▔▔   raw 0x290 D3.2
```

- Sparkline buffer is a small ring (≈12 samples) per pinned entry, sampled at the existing decoded-refresh tick. Bars use the eighth-block ramp `▁▂▃▄▅▆▇█` scaled to the entry's running min/max in the buffer. Boolean / enum signals render with `_` / `▔` segments based on raw transitions.
- The unpinned decoded list continues to render below the watch pane, with no change in semantics. This keeps the firehose available — pinning is additive focus, not a filter that hides things.
- Input mechanic: detail intentionally left to implementation. A simple workable form is `w` enters a command prompt that accepts a signal name (with completion against `signals.yaml`) or an `ID:byte.bit` triplet; same key unpins. The watch list is session-local — not persisted across runs — to keep first-use friction low. If a watch list across sessions becomes valuable later, persist it in the session dir.

### 2. Baseline characterisation (shared by panes #3 and #4)

Changes #3 and #4 both ask the same question: "is this flip surprising given the bit's recent history?" A simple global threshold (`quiet ≥ 2 s`) was the strawman; it fails on mid-counter bits whose natural quiet periods exceed 2 s, on slow-but-noisy bits whose normal interval is multiple seconds, on bus-mode transitions (engine startup turns rare-flippers into active-flippers), and on any bit whose inter-flip distribution has meaningful variance. The right model learns each bit's empirical distribution and surfaces tail events relative to *its own* baseline.

**Algorithm — exponentially-weighted moving statistics with a warmup escape hatch.** Per bit, maintain:

- `last_flip_ts` — wall-clock timestamp of the most recent transition (already proposed)
- `μ_ewma` — exponentially-weighted mean of inter-flip intervals
- `σ²_ewma` — exponentially-weighted variance (EWMA of squared deviations from `μ_ewma`)
- `flip_count` — total flips this session for this bit

On every transition:

1. Compute `interval = now - last_flip_ts` (skip on the very first flip — no prior interval to score).
2. If `flip_count < WARMUP_FLIPS` (default 5): this bit is "rare" — unconditionally surface the flip with `z = ∞` as the annotation. This handles bits like the side-stand that only flip a handful of times per session and would otherwise never accumulate a meaningful baseline.
3. Otherwise compute `z = (interval - μ_ewma) / max(σ_ewma, σ_floor)`. Surface if `z ≥ Z_THRESHOLD` (default 3.0). The `σ_floor` (≈ 5 ms) prevents pathological z-scores when σ collapses to zero for a perfectly-periodic counter.
4. Update `μ_ewma` and `σ²_ewma` with `interval`, using a smoothing factor `α` chosen so the EWMA has an effective window of ~32 samples (`α ≈ 2/(N+1)`, here `α ≈ 0.06`). This lets the baseline adapt to genuine regime changes (engine on→off shifts a bit's typical rate) within ~32 flips of the new regime, without making the baseline so flighty that a single outlier reshapes it.

Why this combination handles the failure modes:

- **Fast counters (50 ms cycle):** μ ≈ 50 ms, σ ≈ a few ms. A normal flip has z ≈ 0; even a 200 ms hiccup yields z ≈ 30 — surfaces only on genuinely abnormal stalls, not on every tick.
- **Slow-but-noisy bits (5 s typical interval):** μ ≈ 5 s, σ ≈ 1 s. A normal flip has z ≈ 0; suppressed. A 30 s gap → z ≈ 25; surfaces.
- **Engine-startup regime change:** for the first WARMUP_FLIPS post-startup, the bit is treated as rare and every flip surfaces (which is what we want — the operator sees that the bit "woke up"). After warmup, the EWMA has learned the new regime and subsequent ticks suppress correctly.
- **Variable-rate bits:** σ is naturally large, only true tail events break z=3.
- **Rare event bits (side stand, gear position):** never reach WARMUP_FLIPS in a typical session → every flip surfaces.

Considered and rejected: per-bit ring buffer of last K intervals with empirical p95. Slightly more accurate on bimodal distributions, but K floats × ~1300 bits is meaningfully more memory and percentile compute is per-flip vs O(1). The EWMA approach wins on the simplicity-vs-robustness curve and is easy to debug because μ and σ are scalars the pane can display.

**Debuggability:** the rendered row shows `z=N.N` alongside `μ=X ±Y` so the operator can see *why* a bit was flagged and tune `Z_THRESHOLD` by eye. A flip surfacing with `z=4.2 μ=0.05s ±0.02s` is qualitatively different from `z=∞ (warmup)`, and the operator should be able to tell at a glance.

CLI flags: `--anomaly-z-threshold` (default 3.0), `--anomaly-warmup-flips` (default 5). The previous `--flip-stability-secs` proposal is dropped — it's the wrong abstraction.

### 3. Mark-driven baseline-aware unknown-flips pane

Replace the current "every bit that flipped in the 0.5 s post-mark window" filter with the baseline-aware rule from change #2 applied to the post-mark window.

- The continuous per-bit EWMA stats from #2 are maintained at all times.
- At mark time, a post-mark flip is shown in the unknown pane only if it scored `z ≥ Z_THRESHOLD` (or was in warmup) when it happened. Engine counters and checksums have tight (μ, σ) and never score; rare events do.
- Render the surviving rows with three annotations: `+Δt` after mark, `quiet Ns` (the actual `interval` for that flip), and `z=N.N` (or `warmup`):

  ```
  Unknown bits flipped  (kill +0.42s, z ≥ 3.0)
    0x290  D3 bit 2   0→1   +0.12s   quiet 8.4s   z=∞ (warmup)
    0x4A1  D0 bit 0   0→1   +0.31s   quiet 5.1s   z=4.2  μ=0.8s ±1.0s
  ```

- Sort by z descending (with warmup bits at the top, since `z=∞` is the strongest signal you can have).
- The current `--show-d7` checksum-noise toggle becomes mostly redundant under this rule (checksum bits have z≈0) but stays as an explicit override.

The known-signals-changed pane (`flipped_texts` → `_known_signal_rows`) is unaffected: it's already a small list driven by the schema, and its "no decoded delta" hint already suppresses the most common noise case.

### 4. Continuous discovery pane (always-on)

Add a fourth pane that surfaces anomalous flips *without* requiring a mark. It runs continuously, reusing the same baseline machinery from change #2.

- Every time a bit transitions, the algorithm in #2 already produces a verdict (warmup / pass / suppress). On any non-suppress verdict, push an entry into a recent-anomalies log: `(timestamp, arb, byte, bit, transition, interval, z)`.
- The pane renders the most recent N entries from that log (N bounded by screen real estate, ~10–15 rows), sorted **newest first** so the operator looks at the top to see "what just happened." Sorting by recency rather than by z keeps the pane responsive — the most-anomalous-ever event doesn't sit pinned at the top blocking newer signal.
- **Entries age out after a fixed retention window** (`--discovery-retention-secs`, default 60.0). 60 s is the smallest value that still gives an operator time to perform an action, look up, read the pane, and react before the entry disappears. The watch panel (change #1) is the escape valve for "I want this to stay visible" — pin the bit and it stays.
- **No warmup gate at the pane level.** The first few flips of any bit will surface with `z=∞ (warmup)`, which means the pane flashes with startup chatter in the first ~10 s. We accept this — operators learn within a session that early flips are warmup noise, and the `(warmup)` annotation makes them visually distinct from learned-baseline anomalies. The alternative (gate the pane until the bus has been observed for some wall-clock period) adds tuning surface for a problem that resolves itself.
- The continuous pane and the mark-driven pane **coexist** rather than one replacing the other. They answer different questions:
  - Mark-driven: "I just did the thing. What touched the bus in this specific window?"
  - Continuous: "I'm riding around / fiddling with switches. Tell me when the bus reacts."

  Marks remain meaningful regardless of the continuous pane — they still anchor `events.csv` and the post-hoc decoders that key off labeled timelines (ADR 0006).
- Same ID-grouping rule applies (see change #5).

### 5. Group unknown flips by ID

Render both flip panes (mark-driven and continuous) with **one row per arbitration ID**, listing every flipped bit on that ID inline:

```
Unknown bits flipped  (kill +0.42s, z ≥ 3.0)
  0x290   D3 b2,b5   2 bits   +0.12s   z=∞ (warmup)
  0x4A1   D0 b0      1 bit    +0.31s   z=4.2  μ=0.8s ±1.0s
```

- When multiple bits on one ID flip in the same window, show the earliest `+Δt` and the strongest `z` (the strongest evidence summary). The per-bit detail is still on disk in `snapshot-N.json` — no information is lost.
- The on-disk JSON snapshot remains per-bit (machine-readable), since post-hoc consumers want the granularity. Only the on-screen render groups.
- If an ID has more bits flipping than fit on a row, render `D3 b0..b4 (+2)` and the full set is in the snapshot.

## Consequences

- **The "engine on → pane saturates" failure mode goes away** for the discovery case the user actually wants to use the pane for: eliciting an action and asking "what did that touch?". The new rule learns per-bit baselines rather than applying a global threshold, so it adapts to whatever the bus is doing — engine-noise bits self-classify regardless of the operator's settings. If a class of legitimate events is being suppressed in practice, the response is to lower `--anomaly-z-threshold` for that session rather than reintroduce the firehose.
- **Three cognitive modes are now first-class on `AnalysisScreen`.** Watch = focus (you have a hypothesis; confirm a value). Mark-driven unknowns = directed discovery (you have an action; what did it touch?). Continuous unknowns = open-ended discovery (you're exploring; the bus tells you when to look). The three panes coexist on one screen rather than gating behind modes, because in practice all three are useful in any non-trivial session and switching between them mid-capture is a cognitive tax the rider can't afford. Operator screen from ADR 0006 is unaffected.
- **The continuous pane changes the shape of "early discovery" sessions.** Today the workflow for "ride around and see what's interesting" is to mash a generic hotkey periodically. After this change, the operator can ride passively and the pane fills with anomalous flips as the bus reacts to whatever the rider does — marks become an act of *labeling* the moment, not of triggering analysis. Downstream decoders that key off labeled marks still need real marks, so this doesn't eliminate marking; it just removes the "mark constantly to keep the pane alive" coping behavior.
- **Startup chatter is a known UX wart, not a bug.** First ~10 s of any session, the continuous pane lights up because every bit is in `WARMUP_FLIPS` mode and surfaces unconditionally. Documented; ignored. The `(warmup)` annotation on each row makes these visually distinct from learned-baseline anomalies, which is enough for the operator to mentally filter. If it becomes a real complaint, the fix is to gate the pane on a wall-clock minimum age — not to suppress the rare-bit logic that warmup exists for.
- **Watch list is intentionally non-persistent.** No `watch.yaml`, no session-dir snapshot of pins. If watch lists turn out to recur across sessions (e.g. "always watch rpm + gear + side-stand"), promote them later with a real file; until then, fast in-session input is more important than persistence.
- **Per-bit baseline state is small and permanent.** Each bit gets four scalars (`last_flip_ts`, `μ_ewma`, `σ²_ewma`, `flip_count`). For a bus with O(20) IDs × 8 bytes × 8 bits, the upper bound is ~1300 bits × 4 floats — negligible. The continuous pane's recent-anomalies log is also bounded: entries past the retention window are dropped on every refresh, so log size is `O(rate of anomalies × retention_secs)` — typically tens of entries even in a busy session.
- **Sparkline rendering is bounded.** Ring buffer of 12 samples × pinned-entry count. Pinning is operator-driven and self-limiting (you only pin what fits on screen). No memory concern.
- **No new artifacts on disk.** `events.csv`, `capture.log`, `live_decode.csv`, and `snapshot-N.json` keep their current schemas. The watch-list / pin state is UI-only. An agent reading a session dir reconstructs everything from the existing artifacts.
- **Scope discipline.** This ADR is about live-view ergonomics during a capture. It does not introduce live plotting, search/filter UI, audible cues, or rewind. If a future experiment exposes a concrete need one of those rejected ideas would solve, that's a new ADR — not creeping into this one.
- **Implementation touch points.** All inside `scripts/live_view.py`: two new panes in `AnalysisScreen.compose` (watch + continuous discovery), a `watch_*` state plus a small input modal/prompt on `LiveCaptureApp`, a per-bit baseline-stats dict (`{(arb,byte,bit): BaselineStats}`) maintained on every transition in the frame handler, a recent-anomalies deque populated in the same handler when a flip passes the z-threshold or is in warmup, a verdict-aware filter/sort in `_flip_rows`, a grouping change in `flipped_texts`, and a new render method for the continuous pane. No changes required in `signals.py` or `procedure.py`. `capture.py` gets three new CLI flags: `--anomaly-z-threshold` (default 3.0), `--anomaly-warmup-flips` (default 5), and `--discovery-retention-secs` (default 60.0).
