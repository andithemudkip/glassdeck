# 0012 — Active unknown bytes pane: retention, frozen sparkline, decay

**Date:** 2026-06-23
**Status:** Accepted
**Supersedes:** ADR 0008's retention/hysteresis behaviour and the render rules in §6 only. The detection algorithm (rolling-range vs EWMA baseline, `BASELINE_FLOOR`, first-activity), the shape classifier, the `--show-d7` gate, and `--byte-activity-window-secs` are unchanged.

## Context

ADR 0008 introduced the Active unknown bytes pane: a per-byte rolling-range view that surfaces bytes sweeping wider than their long-running EWMA baseline. The detection rule has held up well in real use. The **render** loses rows too quickly to be useful:

1. **Short hysteresis.** A row is visible while `active_now OR now − last_active_ts < hysteresis_secs` (default 3.0 s). Once activity tapers, the operator gets 3 s of grace and then the row vanishes — often before they've finished reading it or decided to capture a hypothesis.
2. **Sparkline washes out during the tail.** The same `(ts, val)` buffer that drives the rolling-range detection (window = 2 s) also drives the sparkline. As soon as activity dies, new flat samples push the interesting shape out the left of the buffer within ~2 s. The operator sees the sparkline visibly degrading toward a flat line, then the row disappearing — they can't even read what shape the byte made at peak.

Bumping hysteresis alone doesn't fix this — it just means staring at a flat line for longer.

The natural complement to ADR 0011's anomaly-pane redesign is to give the byte pane the same "stable presence + brightness decay" treatment, adapted for byte semantics: a byte's *shape* (sensor curve, counter sawtooth, step) matters where the anomaly pane's *anomaly density* matters.

We considered and **rejected**:

- **Just bump hysteresis to 30 s.** Fixes the disappearance problem but not the sparkline-washout problem. Operator would stare at a flat line for the extended grace period and learn nothing.
- **Stable-by-arb sort (like the anomaly pane).** The byte pane is fundamentally "what's anomalous right now"; top-by-priority sort is load-bearing. Stable-by-arb would put a quiet-in-tail row next to a hot row arbitrarily.
- **Drop the rolling-range buffer and use the display buffer for both detection and rendering.** The two have different needs (detection wants time-based eviction so the threshold doesn't lag; display wants fixed-rate sampling so the sparkline shows ~3 s of shape regardless of broadcast rate). Coupling them was the original bug.
- **Show a small inset plot or text summary of the peak.** More moving parts than the eye can scan in the half-second the pane gets attention. A persistent `peak=N.N×` annotation in the same column position is cheaper to read.

## Decision

Five coordinated changes to `scripts/live_view/`. All preserve ADR 0005's render-only principle; on-disk artifacts are unchanged.

### 1. Separate display buffer from detection buffer

Per `ByteActivityStats`, add:

- `display_buffer: deque[float]` of fixed length `SPARKLINE_BUFFER` (12), sampled at ~`BYTE_ACTIVITY_SAMPLE_SECS` (0.25 s) cadence. Spans ~3 s of byte values regardless of broadcast rate.
- `last_display_sample_ts: float` gates appends to that cadence — a byte broadcasting at 100 Hz and one at 10 Hz both end up sampled at 4 Hz.

The existing `buffer` (rolling 2 s of `(ts, val)`) continues to drive the threshold check unchanged.

### 2. Freeze the display buffer at the active→tail transition

When the row enters the tail tier (active_now goes False), the render loop snapshots `list(display_buffer)` into `frozen_buffer: list[float]`. The sparkline renders `frozen_buffer` while it's non-empty (i.e. throughout the decay tier) and `display_buffer` otherwise.

Activity resumes (a future tick has `active_now` True again) → `_update_byte_activity` clears `frozen_buffer` and live rendering resumes. The display buffer kept sampling throughout, so it reflects current values immediately, not the frozen shape from before.

### 3. Real retention window past hysteresis

New `BYTE_ACTIVITY_RETENTION_SECS = 30.0` (CLI: `--byte-activity-retention-secs`). A row stays visible until `active_now is False AND age >= retention_secs`. Past retention, the row drops AND `peak_ratio` / `peak_ratio_ts` reset so the next activity episode for that byte starts clean.

`ACTIVITY_HYSTERESIS_SECS` (CLI: `--byte-activity-hysteresis-secs`) is repurposed — was "total exit grace" (default 3.0 s), now "HOT-tier extension past active_now before the row dims" (default bumped to 5.0 s). Same flag, same axis-of-meaning, larger total visible window with a brightness transition inside it.

### 4. Two-tier brightness decay

- **HOT** (`active_now OR age < hysteresis_secs`): default brightness, live `display_buffer` sparkline (or `frozen_buffer` if it's a hot-tier tail row).
- **DIM** (`hysteresis_secs ≤ age < retention_secs`): row wrapped in `[dim]`, `frozen_buffer` sparkline.

Two visible tiers matches ADR 0011's pattern. The fresh/recent distinction is the readable one; finer gradations read as fussy.

### 5. Peak-ratio annotation that persists across tiers

The trailing-metric column changes from `ratio=N.N×   range NNN` to `peak=N.N×   -N.Ns`:

- `peak_ratio` — highest ratio seen during the current activity episode (`math.inf` for first-activity rows). Updated in `_update_byte_activity` whenever a fresh tick is `active_now` AND the current ratio exceeds the stored peak.
- `peak_ratio_ts` — wall-clock of that peak, used both for the `-N.Ns` time-since-peak annotation and for retention reset.

The peak survives intact through the tail and decay tiers. The operator sees how loud the row was at its loudest, regardless of whether they're looking at it 0.5 s or 25 s after the fact.

### Sort

Switch from current ratio descending to **peak ratio descending**. Recently-loud rows stay anchored at the top through their decay tier — current ratio drops to near 0 in tail and would otherwise sink the row to the bottom right as the operator went to look at it.

### Visual contract

```
  0x290 D2   value=234 / 0xEA   ▁▂▃▄▅▆▇█      │  peak=4.2×   -0.3s   sensor
  0x4A1 D0   value=  3 / 0x03   ▁▁▁▁▁▁▁█      │  peak=∞      -1.1s   (first activity)
[dim]  0x123 D4   value= 12 / 0x0C   ▁▂▁▂▁▂▁▂  │  peak=2.8×   -8.2s   counter[/dim]
```

Skeleton matches ADR 0011: `0x<arb> … <sparkline> │ <metric>`, ` │ ` separator preserved.

## Consequences

- **The "byte vanished before I could read it" failure mode goes away.** Rows persist for `retention_secs` (default 30 s) with a brightness transition at `hysteresis_secs` (default 5 s) so the operator can tell "this just happened" from "this happened a moment ago."
- **The sparkline preserves byte shape through decay.** The frozen snapshot at active→tail means the operator can keep reading "this byte made a sensor curve" or "this byte counted up" for the full retention window. The display buffer's separate sampling cadence also smooths out broadcast-rate jitter that the original window-bound buffer would have shown.
- **Sort changes behave intuitively.** Peak-ratio sort means rows stay where they were when they were loud; nothing sinks to the bottom of the pane as the operator's reading it.
- **The pane is busier in tail tier.** Acceptable: the HOT/DIM tiers visually separate "current" from "historical," and the eye still reads the HOT rows first. If a session has so many quietly-fading bytes that the DIM tier crowds out HOT rows, the response is to lower `--byte-activity-retention-secs` (or `--byte-activity-hysteresis-secs` to flip more rows to DIM faster). The structural flags are right where you'd reach for them.
- **`--byte-activity-hysteresis-secs` semantics shifted.** Same flag name, slightly different meaning: was "exit grace" (3 s default), now "HOT-tier extension" (5 s default). Users passing a custom value get a sensible reinterpretation — a longer value still means "more time at default brightness" — and the pane behaviour is strictly more visible than before, not less. Documented in the guide.
- **`peak_ratio` reset at retention boundary is necessary.** Without it, a byte that fires once and then again 5 minutes later would inherit the first episode's peak forever. The reset ties peak to "the current activity episode."
- **Memory cost is trivial.** Per byte: 12 floats for `display_buffer` + up to 12 floats for `frozen_buffer` + 4 scalars. For ~20 IDs × 8 bytes × ~120 bytes/instance ≈ 20 KB.
- **No detection-algorithm changes.** Rolling-range threshold, EWMA baseline, `BASELINE_FLOOR`, first-activity detection — all unchanged. ADR 0008 §§1–5 remain in force. The first-activity render (`peak=∞`, `(first activity)` suffix) is preserved.
- **No on-disk artifact changes.** `events.csv`, `capture.log`, `live_decode.csv`, `snapshot-N.json`, `hypotheses.yaml` schemas unchanged. Pane state is UI-only.
- **No `screens.py` changes.** The pane is wired identically; only `app.py:active_bytes_text` + `active_bytes_summary` + `_update_byte_activity` are touched.
- **Implementation touch points.** `scripts/live_view/constants.py` (`BYTE_ACTIVITY_RETENTION_SECS`, `BYTE_ACTIVITY_SAMPLE_SECS`, bumped `ACTIVITY_HYSTERESIS_SECS`), `scripts/live_view/state.py` (extended `ByteActivityStats`, new `_render_byte_row` helper next to `_render_anomaly_row`), `scripts/live_view/app.py` (`_update_byte_activity` samples display buffer + tracks peak; `active_bytes_text` rewritten; `active_bytes_summary` mirrors new visibility rule; constructor takes `byte_activity_retention_secs`), `scripts/capture.py` (`--byte-activity-retention-secs` CLI flag, default 30.0). No changes to `screens.py`, `modals.py`, `bridge.py`, `signals.py`, the anomaly pane (ADR 0011), or any non-byte-pane render.
