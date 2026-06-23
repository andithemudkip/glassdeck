# 0011 — Live anomalies pane: stable status surface, co-occurrence, mark halo

**Date:** 2026-06-23
**Status:** Accepted
**Supersedes:** ADR 0007 §4 (render rules for the continuous discovery pane). §§1–3, 5 of ADR 0007 remain in force — the underlying baseline-aware detection, the mark-driven pane, and the group-by-ID rendering rule are unchanged.

## Context

ADR 0007 §4 introduced an always-on "Live anomalies" pane that surfaces every bit-flip the EWMA scores as anomalous (or in warmup) over a retention window. The detection rule is sound, and the data the pane has access to is exactly the right data. But the **render** has three structural problems that make the pane unreadable in practice once the bus is busy:

1. **No real columns.** `state.py:_render_group_row` is a space-joined f-string with a variable-width `render_bits()` field. Column 4 in one row lands where column 2 in another row lands. The eye cannot scan vertically.
2. **Newest-first sort + no row stability.** `discovery_text` sorts by `-latest_ts` so every fresh anomaly reshuffles the list. An ID that just had a flip jumps to row 1, displacing the row the operator was looking at. The eye never anchors.
3. **It's a log, not a status pane.** The pane shows a deque of recent events with no per-ID aggregation, no memory of how often each ID has been firing in the window, and µ/σ debug numbers (useful for tuning, not for in-session pattern matching) that eat the line.

A symptom of (3): the pane gives no way to see that two IDs fire together. Cross-ID structure — the most interesting discovery signal — is invisible at the per-row resolution.

A fourth, smaller concern is interaction with the mark-driven pane (ADR 0007 §3). Today they are two visually distinct surfaces. When the operator presses a mark hotkey, the answer to "what touched the bus?" appears in the mark-driven pane, but the continuous pane has the same information and does not visually acknowledge the mark. The two panes split the operator's attention.

We considered and **rejected**:

- **Live plotting widgets** — ADR 0007 already rejected this; not relitigated.
- **Hide unsettled bits at session start** (suppress until WARMUP_FLIPS + K extra flips). Would break the rare-event case that warmup was built for. A single kickstand flip would never surface. The startup-chatter cost ADR 0007 §97 accepts is the lesser evil.
- **Three-tier brightness** (bold / normal / dim). In Textual's default theme bold reads as fussy and competes with the co-occurrence accent. Two tiers (default / dim) is enough.
- **Sort by max_z descending.** Stable in the absence of new tail events, but still reshuffles every time a higher-z anomaly arrives. Stable-by-arb is the only sort that doesn't move rows in response to new data.
- **Color-decay across more steps.** Linear age → color mapping looks busy; a binary fresh-or-dim is cleaner.

## Decision

Redesign the continuous "Live anomalies" pane around four ideas, in descending order of leverage. The detection algorithm, retention semantics, CLI flags, and on-disk artifacts are all unchanged.

### 1. Stable rows + fixed columns + activity sparkline

One row per arbitration ID present in the retention window, sorted **arb ascending**. Rows are at fixed column offsets:

```
  0x290  ⊞  D3 b2,b5            ▁▁▁▂▃▅█▇▅▃▁▁  │  z=4.2   -0.4s
  0x4A1  ·  D0 b0                ▁▁▁▁▁▁▁▁▁▁█▁  │  z=∞    -3.1s
  0x123  ↻  D4 b7                ▁▂▁▂▁▂▁▂▁▂▁▂  │  z=3.5  -1.2s
```

- `arb` 7 chars, glyph 3 chars, bits 18 chars, sparkline `SPARKLINE_WIDTH` (12) chars, ` │ ` separator, score 9 chars, age 6 chars right-aligned.
- The **activity sparkline** buckets the retention window into 12 cells; each cell's height is the count of anomalies for that ID in that bucket. Aligned across rows: two IDs that fire in the same physical event have spikes in the same column. This delivers historical co-occurrence for free without grouping or merging rows.
- Rows that age out (no anomaly in the retention window) drop off the bottom. Aged-out rows in the middle shift the rows below them up by one — acceptable jitter for the no-reshuffle win.

### 2. Implicit co-occurrence accent

The activity sparkline shows historical co-occurrence. To highlight **right-now** co-occurrence, a single render-time pass clusters rows whose `latest_ts` falls within `ANOMALY_COOCCUR_SECS` (0.3 s) of each other AND whose latest event is recent (within `ANOMALY_HOT_SECS`, 3 s). Clusters of size ≥2 get an accent color from `("cyan", "magenta", "green", "yellow")`, applied to the **arb token only** (not the whole row — composes safely with brightness decay).

Singletons and stale clusters get nothing. The operator's eye picks up "those three IDs just fired together" from the matching color on the leftmost column. Past four clusters in one window the colors recycle — at that point the pane is showing a burst storm and accent meaning is already saturated.

### 3. Mark halo

When the operator presses a mark hotkey, `last_event_ts` and `window_end_ts` already track the 0.5 s post-mark window (ADR 0007 §3 machinery). The redesigned pane reuses this: for `ANOMALY_HALO_SECS` (4 s) after the mark hotkey, any row whose `latest_ts` falls inside `[last_event_ts, last_event_ts + FLIP_WINDOW_SECS]` gets a `▶` prefix and a `[bold yellow]` arb token.

Halo overrides co-occurrence accent on the affected rows — the operator's intentional gesture is the strongest signal there is. The mark-driven pane (ADR 0007 §3) is unchanged; halo is a soft bridge so the operator can read the answer to "what touched the bus when I pressed the key?" in the same surface they were already watching.

### 4. Shape-of-anomaly glyph

Each row gets a one-character glyph computed from the group:

- `⊞` if ≥2 bits flipping on the same byte — looks like a real signal change.
- `↻` if a single bit AND `mu < 0.5s` AND `z` is finite — fast-cycling baseline with a tail interval (counter-like).
- `·` otherwise — isolated single-bit flip.

The glyph pre-classifies the row so the operator's eye doesn't need to mentally re-derive "signal vs counter" from the bits column on every refresh.

### Shared visual language with `active_bytes_text` (ADR 0008)

The byte-activity pane row format is tweaked minimally to share the ` │ ` separator and trailing-metric layout. No data fields change; the two panes now scan as one logical surface.

## Consequences

- **The pane is now readable while moving.** Fixed columns + stable rows + activity strip turn a stream-of-events log into a status surface. The operator anchors on row positions and notices change-in-place rather than scrolling-of-rows.
- **Cross-ID structure becomes visible passively.** Two IDs that fire together produce matching spikes in their activity strips (any time) and a matching accent color on their arb tokens (right now). The hardest discovery question — "what fires with what?" — gets a partial answer without operator action.
- **The mark-driven and continuous panes converge in attention.** Halo means the operator who pressed a hotkey sees the answer in the pane they were already watching; the mark-driven pane is still the authoritative grouped view, but the operator doesn't need to glance between two surfaces.
- **Aged-out-middle jitter.** When a middle row drops off the bottom, rows below it shift up by one. Smaller jitter than full reshuffle, but not zero. Accepted.
- **Accent saturation under burst storms.** When more than 4 simultaneous clusters appear the colors recycle and stop being informative. In practice 4 clusters within 300 ms is already "the bus is doing many things at once," at which point the operator's job is to wait for it to calm down, not to read accents. Accepted.
- **µ/σ are off the default render.** They remain available in the bit-detail hypothesis modal (`_snapshot_anomaly_bit_rows`, unchanged) for tuning. If in-session µ/σ visibility turns out to be load-bearing, the response is a `--verbose` flag, not undoing the redesign.
- **Startup chatter is unchanged.** The pane still flashes with warmup-tier anomalies in the first ~10 s; ADR 0007 §97 explicitly accepts this and we agree. The settled-bit suppression alternative was rejected because it would break the rare-event surfacing (one-shot kickstand flip) that warmup exists for.
- **No detection-algorithm changes.** EWMA, warmup escape hatch, z-threshold, retention pruning — all unchanged. This ADR is purely render-layer; ADR 0007 §§1–3, 5 remain in force.
- **No on-disk artifact changes.** `events.csv`, `capture.log`, `live_decode.csv`, `snapshot-N.json` schemas unchanged. The pane state is UI-only.
- **Implementation touch points.** `scripts/live_view/constants.py` (new `ANOMALY_*` constants), `scripts/live_view/state.py` (`GroupedRow` extended with `count` + `bucket_timeline`, new `_render_anomaly_row` / `_anomaly_sparkline` / `_anomaly_glyph` / `is_halo_active` / `is_hot` helpers; `_render_group_row` preserved for the mark-driven pane), `scripts/live_view/app.py` (`_group_rows_by_arb` optionally produces bucket timelines; `discovery_text` rewritten; `active_bytes_text` minor alignment tweak; new `_anomaly_accents` helper). No changes to `screens.py`, `modals.py`, `bridge.py`, `signals.py`, or `capture.py`. No changes to the mark-driven pane.
