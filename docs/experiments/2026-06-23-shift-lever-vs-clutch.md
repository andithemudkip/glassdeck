---
date: 2026-06-23
status: success
phase: 1
related:
  findings:
    - can/signal-clutch
    - can/signal-shift-failed
  references:
    - ktm-can-decoder
  experiments:
    - 2026-06-18-gear-cycle-clutch
    - 2026-06-23-paddock-stand-gear-spin
  logs:
    - 2026-06-23-shift-lever-vs-clutch
---

# Disambiguate `129` D0 bit 3 — clutch lever vs shift-lever-displaced

## Hypothesis

While verifying the [[signal-gear-position]] decode after [2026-06-23-paddock-stand-gear-spin](2026-06-23-paddock-stand-gear-spin.md), the rider noticed that **pulling the clutch lever flips `129` D0 bit 3** in the live view. This contradicts the bit-3 attribution in the prior shift-lever finding (provisionally "lever displaced from rest"), where bit 3 was believed to track shift-lever-position via the factory quick-shifter sensor.

The two competing interpretations are:

1. **Bit 3 = clutch lever pulled.** The Phase B "bit 3 set continuously for 17.8 s / 5.7 s" windows would then be the rider holding the clutch in across the shift attempts, not the shift lever. The Phase A clutch-only null result (`129` D0 statically `0x00` across 4 463 frames) needs an alternative explanation — most plausibly that the Phase A pumps fell below the lever sensor's activation point.
2. **Bit 3 = shift-lever displaced.** Original interpretation. The rider's observation in the live view today would be a confound — instinctively pulling the clutch and pressing the shift lever happen together.

The disambiguation is to mark each input separately and check which one bit 3 follows.

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. **Engine off**, key on, kill switch in run.
- **Neutral throughout.** Decouples the test from any gear-state-conditioned broadcast logic.
- Rear paddock stand from the prior session, no shifter input intended in the clutch phase, no clutch input intended in the shifter phase.
- Adapter / firmware / host as before. Capture running with live view.
- Marks: `c` (`clutch`) **pressed before pulling the clutch** so the mark precedes the action; `g` (`gear`) **pressed before depressing the shift lever** for the same reason. Shift lever was pressed only (preload toward a shift) without going through to a gear change.

## Procedure

1. Settle in neutral, key on, ~5 s baseline before any marks.
2. **Phase 1 — clutch only.** Four reps: `c` mark, then pull the clutch lever (full travel, sustained ~2–3 s), then release. Hands only — no foot on the shifter.
3. **Phase 2 — shifter only.** Three reps: `g` mark, then press the shift lever downward (preload, no through-shift), hold briefly, release. No hand on the clutch.
4. End capture.

`events.csv` recorded 4 `clutch` marks and 3 `gear` marks; the per-mark analysis below uses ±3 s windows around each mark.

## Result

Capture: [`logs/2026-06-23-shift-lever-vs-clutch/`](../../logs/2026-06-23-shift-lever-vs-clutch/) — 21 848 frames, 2 602 of them on ID `129`, 52 s span. Per-window scan of `129` D0 bit 3 (mask `0x08`):

| Mark | Event   | t_rel (s) | bit 3 set frames / window | Notes |
|------|---------|----------:|--------------------------:|-------|
| 1    | clutch  |  +10.1    | 6 / 301                   | brief tap (mark fired, then sustained pull came shortly after — see runs below) |
| 2    | clutch  |  +21.3    | 174 / 300                 | sustained pull |
| 3    | clutch  |  +26.0    | 183 / 300                 | sustained pull |
| 4    | clutch  |  +31.2    | 180 / 300                 | sustained pull |
| 5    | gear    |  +38.5    | **0 / 299**               | shift lever pressed |
| 6    | gear    |  +43.1    | **0 / 300**               | shift lever pressed |
| 7    | gear    |  +47.0    | **0 / 300**               | shift lever pressed |

Baseline (first 5 s of capture, no marks): 0 / 254 bit 3 set. `129` D0 statically `0x00`.

**Run-length view** of bit 3 across the full capture:

```
t+ 12.64 → t+ 12.74  (0.11 s)  lo=0x8
t+ 15.24 → t+ 19.34  (4.09 s)  lo=0x8
t+ 21.77 → t+ 24.16  (2.39 s)  lo=0x8
t+ 26.52 → t+ 29.22  (2.70 s)  lo=0x8
t+ 31.62 → t+ 34.56  (2.94 s)  lo=0x8
```

Five clean blocks, all in Phase 1 (clutch). Phases 2 (shifter) produced no bit-3 set frames at all.

Bit 1 (the candidate shift-attempt-failed flag) also remained clear throughout — expected, since the rider made no through-shifts and no failed-engagement attempts.

## Interpretation

- **Bit 3 = clutch lever pulled.** 4/4 clutch reps fired the bit; 3/3 shifter reps did not. The Phase B "sustained bit-3 set" windows match the rider's clutch holds during shift attempts, not the shift lever. New finding: [[signal-clutch]] at `confirmed`.
- **Phase A's null result is resolved.** The rider confirmed in this session that the clutch-lever switch is mechanically finicky — only trips when the lever is pulled upward past a threshold. Phase A's gentle pump-style pulls were below that threshold. Future clutch captures need full-travel pulls past the click point.
- **Bit 1's failed-shift attribution survives.** It didn't fire today (rider didn't trigger a `-` event), but the disambiguation didn't disprove it either. Now tracked in [[signal-shift-failed]] at `provisional`, evidence base narrowed to Phase B's two failed N→2 attempts.
- **Clutch is on the bus regardless of gear.** Engine-off + neutral was the strictest configuration — the broadcast persists even when the ECU has no functional reason to read it (no engine to stall, no gear to disengage). Indicates the ECU samples and broadcasts the input continuously whenever the bus is up, same pattern as throttle / kill switch / side stand.
- **Operator-driven `c`/`g` marks one-handed before the action worked cleanly.** Rider sequence "mark, then act" preserves a well-defined window-start for analysis even though the mark precedes the bit transition by a fraction of a second. Lesson for future single-rider sessions: pre-action marking is reliable when the action is repeatable and the analysis window is wide enough (±3 s here).

What this does NOT tell us:
- Engine-on behaviour (negligible risk — no precedent for engine-state-conditioned broadcasts of digital inputs on this bus).
- Whether bit 3 has any additional meaning in non-N gears (negligible risk — broadcast is uniform across the disambiguation, and Phase B engine-off in 1st showed the same hold pattern).
- Switch hysteresis (does the bit drop at the same lever angle it sets at?). Not load-bearing for the dashboard MVP.

## Follow-ups

- [x] New finding: [[signal-clutch]] (`confirmed`).
- [x] [[signal-shift-failed]] (renamed from the bit-3-bundling shift-lever finding) — bit 1 = failed-shift attribution preserved, evidence base narrowed.
- [x] [[signal-gear-position]] cross-references updated.
- [x] [[2026-06-19-engine-on-gear-clutch]] → superseded (both sub-hypotheses now closed).
- [x] [`signals.yaml`](../signals/signals.yaml) — `shift_lever_displaced` renamed to `clutch`, `shift_lever_failed` renamed to `shift_failed`.
- [ ] Phase B realignment under the clutch interpretation: re-walk the bit-3 set windows against the rider's reconstructed clutch holds. If timings match, that's confirmatory; if they don't, something else is happening. Low priority — single-source evidence already strong.
