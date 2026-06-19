---
date: 2026-06-18
status: partial
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/post-kill-decay-groups
    - can/byte-d7-checksum-hypothesis
  references:
    - ktm-can-decoder
  experiments:
    - 2026-06-17-payload-diff-idle
  logs:
    - 2026-06-19-gear-cycle-clutch-A-clutch-only
    - 2026-06-19-gear-cycle-clutch-B-gear-cycle
---

# Gear cycle + clutch, engine off — decode gear position and clutch lever

## Hypothesis

Two related KTM hypotheses, both untestable from the idle baseline because the bike sat in neutral with the clutch out the whole time:

1. **Gear position lives at `129` D0 hi nibble.** KTM 690 encodes gear as a small integer in the upper nibble of D0 (0 = neutral, 1 = first, 2 = second, …, 6 = sixth). At idle our `129` D0 was static `0x00` — consistent with neutral, but indistinguishable from "the byte means nothing" without varying the gear.
2. **Gear position is also broadcast at `540` D3 lo nibble.** KTM's decoder reads gear from `540` D3 as well, suggesting the cluster receives gear info from a second source for redundancy. At idle our `540` D3 was LOW-CARD(4), not the steady `0x00` that pure-redundancy would imply — possibly the lo nibble holds the gear and the hi nibble holds something else (mode? state machine?).
3. **Clutch state lives at `129` D0 bit 3.** KTM ties bit 3 of `129` D0 to clutch lever pulled (1 = pulled, 0 = engaged). At idle our `129` D0 was static `0x00`, clutch was out → bit 3 = 0, consistent. A clutch-only test with no shifting would isolate the bit; combining with a gear cycle lets us see it move under all the conditions a real ride hits.

Doing gear and clutch in the same capture is efficient: every shift requires clutch in → out, so we get many clutch transitions "for free" while also stepping through gears. Two distinct input streams in the same session means careful event marking is essential.

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. **Engine off** throughout. Side stand down, **rear wheel free** is helpful (centre stand or paddock stand) — without rear-wheel rotation, the dog rings cannot always engage and gears 2–6 may refuse to drop in. If a paddock stand isn't available, do this experiment as far as the bike will physically shift (typically into 2nd) and note the limit.
- Key on (position 1), kill switch in run.
- Adapter / firmware / host as before.

The bike is in neutral at the start. The clutch lever is out.

## Procedure

This experiment is executed as **two or three separate capture sessions** to keep the per-session step count manageable. Each session does its own key-off baseline + key-on settle. Use these labels so analysis can stitch them:

- Phase A → `--label gear-cycle-clutch-A-clutch-only`
- Phase B → `--label gear-cycle-clutch-B-gear-cycle`
- Phase C (optional, can be skipped if A was clean) → `--label gear-cycle-clutch-C-clutch-recheck`

Per-session preamble (run at the start of each):

1. Start capture with the appropriate label above.
2. 5 s key-off baseline.
3. Key on, press **space**. 30 s settling.

Per-session postamble (run at the end of each):

- Key off. Wait 2 s. `q`.
- Fill `session.md`. Note which phase this session covers and, for Phase B, which gears were actually reached.

### Phase A — clutch-only baseline (no shifting)

Five clutch pumps with the bike in neutral. The point is to isolate the clutch bit before the gear axis adds noise.

**Mark convention (read carefully — this matters for analysis):** press a key on **every edge**, not once per cycle. For the clutch: press `c` at the moment the lever starts moving inward, then press `c` again at the moment of release. A pump → two `c` marks. Same rule for shifts (`g` / `n` in Phase B) — one press per actual gear engagement event. If you press only once per cycle, half the timing information is gone and the analysis script falls back to detecting transitions from the payload alone.

For each pump, the literal **`c`** key is unmapped — capture.py records it verbatim. Slow pumps, ~2 s in and ~2 s out, ~3 s between pumps.

1. Clutch in (`c`) — hold 2 s — clutch out (`c`).
2. Wait 3 s.
3. Repeat for a total of 5 pumps. Total: 10 `c` marks.

### Phase B — gear cycle

Bike still in neutral, clutch out. For each shift, press **`g`** at the moment of the shift action; press **`n`** when entering neutral. Clutch must be in for shifting — the same `c` mark applies.

1. **Pull clutch in:** `c`. Hold.
2. **Down-shift to 1st:** `g` at the shifter toe-push. (Confirm the green N light extinguishes.) Hold 3 s with clutch still in.
3. **Up-shift to neutral:** lift gently into N (half-step up from 1st). `n` at the shift; N light should illuminate. Hold 3 s.
4. **Up-shift to 2nd:** lift fully past N to 2nd. `g`. Hold 3 s.
5. **Down-shift to neutral:** half-step down. `n`. Hold 3 s.
6. **Up to 3rd:** through N + full step to 3rd. `g`. Hold 3 s.
7. **Down to neutral.** `n`. Hold 3 s.
8. **Up to 4th.** `g`. 3 s.
9. **Down to neutral.** `n`. 3 s.
10. **Up to 5th.** `g`. 3 s.
11. **Down to neutral.** `n`. 3 s.
12. **Up to 6th.** `g`. 3 s.
13. **Down to neutral.** `n`. 3 s.
14. **Release clutch:** `c`.

If the bike refuses to drop into a gear (likely if the rear wheel can't move), do what's possible — 1st and possibly 2nd — and note the limit in `session.md`. Even just 1-N-2-N-1-N gives us three distinct values (neutral, 1, 2) which is enough to validate the gear-byte hypothesis; full 1–6 is a bonus.

### Phase C — second clutch baseline (optional)

If Phase A's clutch bit was clean and unambiguous, this can be skipped. Otherwise, in its own session: one more slow clutch pump in neutral to confirm the clutch bit returns to its rest state cleanly after the gear churn. `c` in, hold 2 s, `c` out.

## Analysis plan

1. **Clutch bit isolation (Phase A only).** Diff per-frame on `129` D0 across Phase A's five pumps. Expect bit 3 to flip 0 → 1 on each clutch-in and 1 → 0 on each clutch-out, in clean alternation with the `c` marks. Any other bit moving in Phase A while everything else is held still is probably also clutch-driven; flag it.
2. **Gear nibble decoding (Phase B).** For each held-gear window between `g` / `n` marks:
   - `129` D0 hi nibble — tabulate mode value per held window. Expect 0 (N), 1, 2, 3, 4, 5, 6 in order.
   - `540` D3 lo nibble — same. Expect identical sequence if it's a redundant gear broadcast.
   - Note any "weird" intermediate value during the shift itself (an "in transition" sentinel like `0xF` or `0x7` would be useful to document).
3. **Cross-check `129` D0 bit 3 vs the clutch in Phase B.** Bit 3 should be 1 during every shift (clutch in) and 0 during the holds (clutch out, between releases — actually we hold clutch in across the whole gear cycle in this procedure, so bit 3 should be 1 throughout Phase B except phases 1's leading + Phase C). Adjust expectations to procedure.
4. **`540` D3 hi nibble.** It was LOW-CARD(4) at idle. Does it move with gear? With clutch? With neither? If neither, log as still-UNKNOWN.
5. **Bus-wide diff** over the 11 always-on IDs across each phase boundary, same approach as the kill-switch experiment — any bit moving in lockstep with gear or clutch is worth a closer look.

## Expected outcomes

- **Clean gear decoding at `129` D0 hi nibble** → [`docs/findings/can/signal-gear-position.md`](../findings/can/signal-gear-position.md) at `confirmed`. Record the encoding 0=N, 1–6=gears.
- **`540` D3 lo nibble agrees with `129` D0** → also note in the same finding as a secondary broadcast.
- **`540` D3 lo nibble disagrees** → drop the redundant-broadcast hypothesis; figure out what it actually means.
- **Clutch bit at `129` D0 bit 3 toggles cleanly** → [`docs/findings/can/signal-clutch.md`](../findings/can/signal-clutch.md) at `confirmed`.
- **Gears 3+ unreachable** → finding is confirmed only for the gears reached; mark the rest as untested-but-hypothesised. Re-run on a paddock stand if any gear hypothesis matters for the dashboard MVP.

## Result — Phase A (2026-06-19)

Log: [`logs/2026-06-19-gear-cycle-clutch-A-clutch-only/`](../../logs/2026-06-19-gear-cycle-clutch-A-clutch-only/). Five clutch pumps, neutral, engine off. Analysis: [`scripts/clutch_scan.py`](../../scripts/clutch_scan.py).

**KTM clutch hypothesis (`129` D0 bit 3) rejected.** `129` D0 is `0x00` for every one of the 2,595 frames in the active window — no bit there can carry the clutch state. Bus-wide scan across all 11 always-on IDs and bytes D0–D6 finds **no bit whose transitions correlate with the five clutch-in events**. The only non-D7 byte with any cardinality during the active window is `541` D6, which increments monotonically from `0x75` to `0xA8` at ~1 count/sec across the full capture — present in the settle window too, unrelated to the lever. D7 churn is consistent with [[byte-d7-checksum-hypothesis]] (same per-second rates settle vs active in every ID).

No new arbitration ID appeared during pumping — the same 11 always-on IDs were present in pre-key, settle, active and post windows. Clutch is not a "new ID on demand" signal at this connector either.

**Interpretation:** clutch lever state is not broadcast at the diagnostic-port stub when the bike is key-on, engine-off, in neutral. Most likely the ECU only publishes clutch state when the engine is running (starter-interlock / RPM-cut logic). Less likely but possible: it's on a separate bus not bridged to this stub, or it's hidden in D7 behind the checksum.

The clutch question is deferred to the engine-on stationary experiment ([`2026-06-18-engine-on-stationary-inputs.md`](2026-06-18-engine-on-stationary-inputs.md)). Phase C of this experiment (second clutch baseline) is moot and should be skipped.

This null result does not affect the gear hypothesis for Phase B — `129` D0 staying at `0x00` is consistent with the gear nibble encoding `N = 0` (we just need gear changes to test it). The cross-check "bit 3 = 1 when clutch in during gear shifts" in the original Phase B analysis plan is no longer expected to hit — adjust expectations accordingly.

**Side-finding to follow up:** `541` D6 monotonic ~1 Hz drift, range `0x75`–`0xA8` over 75 s. Probably a runtime counter or slow-changing sensor (intake temp? battery temp? key-on uptime?). Not relevant to this experiment but worth a hypothesis file once Phase B is done.

## Result — Phase B (2026-06-19)

Log: [`logs/2026-06-19-gear-cycle-clutch-B-gear-cycle/`](../../logs/2026-06-19-gear-cycle-clutch-B-gear-cycle/). Bike on paddock stand, engine off, attempted N → 1 → N → 2 → N → 2. Bike refused to engage 2nd on the paddock stand (dogs don't align cleanly without the input shaft turning); the dash showed `"-"` on both 2nd-engagement attempts. Reached gears: **N and 1 only.** Analysis: [`scripts/gear_scan.py`](../../scripts/gear_scan.py).

**Gear hypothesis (`129` D0 hi nibble) — CONFIRMED for N and 1.** Held-window dominant values: 0x0 in neutral (purity 100%), 0x1 in 1st gear (purity 90%, remainder is shift-mechanics settling within the first ~1 s of the 1st-gear window). See [[signal-gear-position]] for the finding.

**`540` D3 lo nibble (KTM redundant-broadcast hypothesis) — REJECTED.** Static `0x0` across every window. Gear is single-source on Husqvarna; no redundant broadcast on `540`.

**`540` D3 hi nibble — static `0x1` across all 5 windows.** Surprising — it was LOW-CARD(4) in the idle baseline. Its variation must come from inputs not exercised here (mode toggle and warm-up sweeps are the natural next checks).

**No other field moves with gear.** Broad scan over all (ID, byte, nibble) and full bytes found zero candidates with cardinality ≥3 across the 5 windows (D7 excluded as known checksum). The gear info on this bus is concentrated in `129` D0 hi nibble alone.

**The dash `"-"` glyph is computed cluster-side, not present on this bus.** During both "-" windows (W3 and W4), `129` D0 hi nibble read `0x0` (= N), the same as actual neutral. The bike's gearbox-position sensor never registered 2nd; the cluster must derive `"-"` from a separate shift-lever-position input not bridged to the diagnostic-port CAN stub. There is no `0xF`-style transition sentinel value in `129` D0 hi nibble.

**Gears 2–6 remain hypothesised** (`0x2`–`0x6` per the KTM mapping). Engine-on testing required.

## Follow-ups

- **Engine-on rerun for gears 2–6.** Bundle into [`2026-06-18-engine-on-stationary-inputs.md`](2026-06-18-engine-on-stationary-inputs.md) or a brief first-motion capture. With the engine running and the input shaft spinning, all gears should engage and the `0x2`–`0x6` mapping can be validated. Bonus: watch for any transient intermediate value (`0xF`?) during the shift itself.
- **Re-test clutch with engine running** in [`2026-06-18-engine-on-stationary-inputs.md`](2026-06-18-engine-on-stationary-inputs.md). If still not visible engine-on, mark clutch as not-observable-at-this-connector and stop chasing it for the MVP.
- Phase C (second clutch baseline) is skipped — moot given Phase A's null result.
- **What drives `540` D3 hi nibble?** Idle-baseline cardinality of 4, but static in Phase B. Mode toggle + warm-up are the prime candidates.
- Open a small experiment on `541` D6: capture two long key-on-engine-off sessions (one immediately after a cold start, one after warm-soak) and see whether D6 tracks time-since-key-on linearly or saturates with temperature.
