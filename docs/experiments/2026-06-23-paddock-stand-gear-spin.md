---
date: 2026-06-23
status: success
phase: 1
related:
  findings:
    - can/signal-gear-position
  references:
    - ktm-can-decoder
  experiments:
    - 2026-06-18-gear-cycle-clutch
    - 2026-06-19-engine-on-gear-clutch
  logs: []
---

# Paddock-stand wheel-spin gear engagement — close gears 2–6 engine-off

## Hypothesis

[[signal-gear-position]] confirms N (`0x0`) and 1 (`0x1`) at `129` D0 hi nibble; gears 2–6 are hypothesised to follow the KTM mapping `0x2`–`0x6`. The blocker on Phase B engine-off was that the gearbox dogs don't align without the input shaft turning, so 2nd never engaged.

**Hypothesis:** spinning the rear wheel by hand on a paddock stand should turn the gearbox input shaft enough to walk the dogs into alignment, letting us engage each gear in turn without starting the engine. If it works, the live view should show a clean `N → 1 → 2 → 3 → 4 → 5 → 6` ramp in the gear-position decode, confirming the KTM mapping for all 7 values.

This collapses the engine-on gear-sweep session ([[2026-06-19-engine-on-gear-clutch]]) into a 10-minute engine-off bench test.

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. **Engine off**, key on (position 1), kill switch in run.
- Rear paddock stand, rear wheel free.
- Adapter / firmware / host as before. **Live view running** — gear decode visible in real time.
- No log captured for this session (live-view-only observation).

## Procedure

1. Start in neutral. Confirm live view shows gear `N`.
2. Pull clutch. Press shift lever down (toward 1st). Spin the rear wheel by hand and continue light pressure on the lever until the dogs engage — gear nibble flips to `1` on the live view.
3. Half-click up to neutral. Confirm live view shows `N`.
4. Spin + shift up to 2nd. Confirm live view shows `2`.
5. Repeat for 3rd, 4th, 5th, 6th — spin the wheel while applying lever pressure each time until engagement.
6. Each gear may take several seconds of patient spinning before the dogs walk in; higher gears were not visibly harder than lower ones.

## Result

**All 7 gears engaged successfully and rendered correctly in the live view.**

- N → 1 → 2 → 3: confirmed first, with deliberate observation between each shift. Live view ticked from `N` to `1` to `2` to `3` with no other values appearing.
- 4 → 5 → 6: confirmed in a follow-up walk-up. Same pattern — clean transitions, no surprise values.

No `-` glyph (failed-shift state) was triggered in this session.

No capture log was running — the live view's decoder is the finding under test, so live-view observation IS the test. The decoder itself is unchanged from prior captures where the underlying frames were inspected directly.

## Interpretation

- **Gears 2–6 follow the KTM mapping `0x2`–`0x6`.** Combined with prior evidence for N/1 from Phase B, all 7 values are now confirmed on this bike. [[signal-gear-position]] promoted from `partial` to `confirmed`.
- **Engine-off wheel-spinning is a viable substitute for engine-on gear engagement** on a paddock stand. Useful technique for future gear-related captures without the safety overhead and warm-up cost of a running engine. Slow shifts only — not suitable for transient-state hunts that need rapid shifts under power.
- **The engine-on gear-sweep session is unnecessary.** [[2026-06-19-engine-on-gear-clutch]] is superseded.

What this test does NOT tell us:
- Whether there is a transient sentinel value during rapid 1↔2↔3 power-shifts. Hand-shifts are too slow to surface a sub-frame intermediate. But across the wide evidence base (Phase B and this session), nothing outside `0x0–0x6` ever appeared in `129` D0 hi nibble — the favoured reading is now "no transition sentinel exists on this bus."
- Whether `129` D0 hi nibble holds the same encoding under engine-running fueling and shift conditions. Highly likely (decoder is pure bit-field extraction) but unverified.

## Follow-ups

- [x] [[signal-gear-position]] → `confirmed`, gear table updated to include 2–6.
- [x] [[2026-06-19-engine-on-gear-clutch]] → superseded.
- [ ] If a future engine-on capture (e.g. [[2026-06-23-engine-driven-rear-spin]]) happens to span shifts under power, opportunistically check `129` D0 hi nibble for sub-frame intermediate values. Don't run a dedicated session.
