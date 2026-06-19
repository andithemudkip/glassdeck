---
date: 2026-06-18
status: planned
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/post-kill-decay-groups
  references:
    - ktm-can-decoder
  experiments:
    - 2026-06-17-payload-diff-idle
  logs: []
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

1. Start capture: `python scripts/capture.py --port /dev/cu.usbmodem101 --label gear-cycle-clutch`.
2. 5 s key-off baseline.
3. Key on, press **space**. 30 s settling.

### Phase A — clutch-only baseline (no shifting)

Five clutch pumps with the bike in neutral. The point is to isolate the clutch bit before the gear axis adds noise.

For each pump, press the literal **`c`** key (unmapped — capture.py records it verbatim) at the moment the clutch lever crosses ~half-travel inward; press `c` again on release. Slow pumps, ~2 s in and ~2 s out, ~3 s between pumps.

1. Clutch in (`c`) — hold 2 s — clutch out (`c`).
2. Wait 3 s.
3. Repeat for a total of 5 pumps.

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

### Phase C — second clutch baseline

After all the gear churn, repeat one more slow clutch pump in neutral to confirm the clutch bit returns to its rest state cleanly. `c` in, hold 2 s, `c` out.

15. Key off. Wait 2 s. `q`.
16. Fill `session.md`. Critical: **list which gears were actually reached**. If only N, 1, 2 — say so explicitly.

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

## Follow-ups

- If a paddock stand wasn't used and we couldn't reach all gears: schedule a paddock-stand version of this experiment to close the remaining values.
- If `540` D3 hi nibble moves with neither gear nor clutch, it's a remaining UNKNOWN to chase later. Mode toggle in the engine-on stationary experiment might catch it.
- A clutch-isolated rerun (no shifting, just pumps) would tighten the clutch bit's polarity and threshold characterisation if anything from this combined run is messy.
