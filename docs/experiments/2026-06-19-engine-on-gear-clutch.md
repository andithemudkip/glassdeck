---
date: 2026-06-19
status: superseded
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/signal-gear-position
    - can/signal-clutch
    - can/byte-d7-cycle-hash
  references:
    - ktm-can-decoder
  experiments:
    - 2026-06-18-gear-cycle-clutch
    - 2026-06-23-paddock-stand-gear-spin
    - 2026-06-23-shift-lever-vs-clutch
  logs: []
---

# Engine-on gear cycle + clutch revalidation — close gears 2–6 and re-test clutch with engine running

> **Superseded 2026-06-23 — never ran.** Both sub-hypotheses closed engine-off via two unrelated sessions:
>
> - Gears 2–6 confirmed by [2026-06-23-paddock-stand-gear-spin](2026-06-23-paddock-stand-gear-spin.md): spinning the rear wheel by hand on a paddock stand walked the gearbox dogs into alignment for every gear, no engine needed. See [[signal-gear-position]] (now `confirmed`).
> - Clutch found at `129` D0 bit 3 by [2026-06-23-shift-lever-vs-clutch](2026-06-23-shift-lever-vs-clutch.md): the original Phase A clutch-only null result was a switch-threshold issue (shallow pumps below the lever sensor's activation point), not a "clutch is not on the bus" finding. See [[signal-clutch]] (`confirmed`) and the bit 3 re-attribution note on [[signal-shift-failed]].
>
> The transient sentinel hunt is the only sub-hypothesis left and is now low priority — across the wide engine-off shift evidence we now have, no value outside `0x0–0x6` appeared in `129` D0 hi nibble. Fold into a future engine-on capture opportunistically rather than running a dedicated session.
>
> Plan preserved below for reference.

---

## Hypothesis

Two open questions from [`2026-06-18-gear-cycle-clutch`](2026-06-18-gear-cycle-clutch.md), both of which require the engine running to resolve.

1. **Gear nibble `0x0`–`0x6` mapping holds for gears 2–6.** Phase B confirmed N=`0x0` and 1=`0x1` at `129` D0 hi nibble. The KTM mapping suggests 2=`0x2`, 3=`0x3`, …, 6=`0x6` — parsimonious and the natural reading. We couldn't test it engine-off because the gearbox dogs don't align without the input shaft turning. With the engine running and the clutch in, all gears should engage cleanly on a paddock stand. **This is the highest-confidence sub-hypothesis** — a clean ramp of nibble values `0,1,0,2,0,3,0,4,0,5,0,6,0` aligned to the shift marks confirms it.

2. **A transient sentinel may appear during the shift itself.** When the dogs are mid-disengage / mid-engage, the gear-position sensor may briefly report something other than the prior or next gear value. KTM ECUs sometimes use `0xF` for "in transition / unknown." Engine-off in Phase B we never saw any value other than `0x0` (N) and `0x1` (1st), even during the failed 2nd attempts. With clean engine-on shifts producing rapid 1→2, 2→3 etc. transitions, we have a better chance of catching a sub-frame intermediate value.

3. **Clutch state is broadcast when the engine is running.** Phase A's null result was the cleanest evidence yet that clutch is absent at the diagnostic stub with engine off. The most parsimonious explanation: the ECU only publishes clutch state when it has a functional reason to do so (starter interlock active, fuel cut on shift, engine-running idle stabilisation). With engine running, **the bytes that were static at engine-off may light up**. Pump the clutch with engine idling and re-scan. Specifically:
   - Re-test the KTM hypothesis at `129` D0 bit 3 — `129` D0 was forced to `0x0` engine-off, but engine-on it carries gear (so the hi nibble will be non-zero in non-N gears), and the lo nibble was never tested under conditions that would force it to move.
   - Broad scan over all (ID, byte, bit) — Phase A only saw `541` D6 cardinality move (monotonic counter); engine-on, many more bytes will be active and the clutch bit (if any) could be anywhere.

A side-finding to keep an eye on: the `541` D6 monotonic counter from Phase A. With engine running, does it speed up, slow down, reset, or stay at the same ~1 Hz drift? Cheap to observe and informs whether D6 is wall-clock-since-key-on, runtime-with-engine, or temperature-related.

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. **Engine running, idling**, in neutral at start, **kill switch in RUN**.
- **Bike on a paddock stand with the rear wheel free.** This is non-negotiable for this experiment — without it, gear 2+ cannot be engaged even with the engine running.
- Engine at operating temperature before starting the capture (idle for 5–10 min, or after a short warm-up ride). Stable idle removes a confound and reduces fuelling-driven RPM noise that could mask clutch-related bit movement.
- Rider stands beside the bike to operate clutch + shifter. Stay alert: paddock stand + running engine + spinning rear wheel = risk to fingers, cables, loose clothing.
- Adapter / firmware / host as before.

## Procedure

Run as **two separate captures** (same precedent as Phase A/B of the engine-off experiment — easier to focus, easier to interpret per-session). Use these labels:

- Clutch → `--label engine-on-clutch`
- Gear sweep → `--label engine-on-gear-sweep`

Per-session preamble:

1. Start capture.
2. 5 s key-off baseline.
3. Key on, **space**. 30 s settling.
4. Press starter (**`s`**). Let engine catch. **`e`** when idle is stable. Hold 30 s of clean idle.

Per-session postamble:

- Kill switch (**`k`**). Let everything decay. Key off when silent. Wait 2 s. `q`.
- Fill `session.md` — gears actually reached, anything weird at the bike, ambient temp.

### Session 1 — clutch pumps, engine on, neutral

Five clutch pumps with the bike in neutral, engine idling.

**Mark on every edge:** `c` at the start of the pull-in, `c` again on release. Five pumps → 10 `c` marks.

5. Pump 1: `c` — hold 2 s — `c`. Wait 3 s.
6. Pump 2: `c` — hold 2 s — `c`. Wait 3 s.
7. Pump 3: `c` — hold 2 s — `c`. Wait 3 s.
8. Pump 4: `c` — hold 2 s — `c`. Wait 3 s.
9. Pump 5 (slow one): `c` — **hold 10 s** — `c`. Wait 5 s.

The longer fifth hold is insurance against a slow-publishing clutch signal that 2 s pumps could miss between broadcast periods. If anything moves only on the long pump, we'll see it as an outlier vs the first four.

### Session 2 — gear sweep, engine on, paddock stand

The full N → 1 → N → 2 → N → 3 → N → 4 → N → 5 → N → 6 → N sequence. Clutch in for every shift action.

**Mark convention:**
- `c` on clutch in, `c` on clutch out — every edge.
- `g` at the moment of each non-neutral gear shift action.
- `n` when landing in neutral.

10. Settle in N. 5 s of pure-idle data with clutch out.
11. `c` (clutch in). Hold.
12. Down-shift to 1st. `g`. Hold 4 s (clutch in).
13. Up half-step to N. `n`. Hold 4 s.
14. Up to 2nd. `g`. Hold 4 s.
15. Down to N. `n`. Hold 4 s.
16. Up to 3rd. `g`. Hold 4 s.
17. Down to N. `n`. Hold 4 s.
18. Up to 4th. `g`. Hold 4 s.
19. Down to N. `n`. Hold 4 s.
20. Up to 5th. `g`. Hold 4 s.
21. Down to N. `n`. Hold 4 s.
22. Up to 6th. `g`. Hold 4 s.
23. Down to N. `n`. Hold 4 s.
24. `c` (clutch out). 5 s of pure-idle data.

If a gear refuses to engage, mark it: `g` to indicate the attempt, then immediately `n` and skip onward. Note in `session.md` which gear was skipped and why.

## Analysis plan

1. **Re-run `gear_scan.py` against Session 2.** Expect per-window dominant nibble values `0x0` (N windows) and `0x1`–`0x6` (held gear windows). Validate the KTM mapping for 2–6 and update [[signal-gear-position]] to `confirmed`. Tighten `--purity` if the shift transients are short.
2. **Transient sentinel hunt.** Frame-by-frame inspection of `129` D0 hi nibble in a ±200 ms window around each `g`/`n` mark. Look for any value other than the prior gear, the next gear, or `0x0`. If `0xF` (or `0x7`, etc.) appears in every shift window for at least one frame, that's the transition sentinel — document it.
3. **Re-run `clutch_scan.py` against Session 1.** Engine-on means many bytes that were static at engine-off will be active. The signal-to-noise is worse, but `541` D6 (monotonic from Phase A) will be the dominant decoy. Use `--exclude-d7`; consider also masking `541` D6 explicitly in the broad scan if it dominates the ranking. Specifically check `129` D0 bit 3 (KTM hypothesis) again — if engine-on it tracks the clutch, we've found it.
4. **Compare the long pump (step 9) vs the short pumps.** If a bit only moves during the 10 s hold, that's a slow-publishing clutch signal — different from the short-pump-invisible case.
5. **`541` D6 side observation.** Tabulate the byte-value timeline across both sessions and compare against Phase A's ~1 Hz drift. Faster engine-on? Same rate? Resets at engine start?

## Expected outcomes

- **Gears 2–6 nibble values match KTM mapping (`0x2`–`0x6`)** → [[signal-gear-position]] promoted from `partial` to `confirmed`. Add table rows.
- **A transition sentinel value surfaces** → add a row to the gear finding noting "during-shift = `0x<x>`".
- **A clutch bit lights up engine-on** → new finding `signal-clutch.md` at `confirmed`. Polarity, ID, byte, bit recorded.
- **Clutch is still not visible engine-on** → finalise clutch as not-broadcast-on-this-bus. Park the question; we'll wire a discrete clutch sensor on the dashboard side if we need it for the MVP.
- **`541` D6 behaviour informs its identity** — runtime, engine-runtime, or sensor.

## Follow-ups

- If gears 2–6 confirm and the sentinel is documented, [[signal-gear-position]] is `confirmed`. This closes the gear question for the dashboard MVP.
- If clutch is still invisible engine-on, open a brief ADR in `docs/decisions/` noting that the dashboard project will treat clutch as a hardware input (separate sensor), not a bus signal, and stop hunting for it on this stub.
- If `541` D6 turns out to be runtime / temperature / something interesting, promote it to its own finding.
- The engine-on stationary input work has since been split into [[2026-07-12-dash-inputs]] and [[2026-07-12-neutral-rpm-sweep]] — either is independent of this file and can run in any order.
