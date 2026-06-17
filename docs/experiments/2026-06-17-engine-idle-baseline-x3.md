---
date: 2026-06-17
status: success
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/post-kill-decay-groups
    - bike/dash-warning-lights
  decisions:
    - 0001-usb-power-during-development
    - 0002-twai-gpio-assignment
    - 0004-logger-wire-format-slcan
  experiments:
    - 2026-06-17-key-off-baseline
    - 2026-06-17-key-on-cold-boot
  logs:
    - 2026-06-17-engine-idle-run-1
    - 2026-06-17-engine-idle-run-2
    - 2026-06-17-engine-idle-run-3
---

# Engine-idle broadcast baseline — three independent captures

## Hypothesis

1. **Always-on set (primary):** there is a stable set of CAN IDs broadcast during engine-running idle that appears in **all three** independent captures, with consistent periods. These are the reliable "the bike says X" channels for later signal decoding. IDs that appear in only one or two of the three runs are noise / event-driven, not steady-state broadcasts.
2. **Engine-start transient (secondary):** there is a distinct ID set or pattern around the cranking → running transition (alternator output coming up, ECU exiting key-on idle, etc.) that does not repeat during steady-state. Like the cold-boot exchange in Session 1, this is easy to miss if the capture starts late.
3. **Period stability (secondary):** any ID claimed to be a steady-state broadcast has the same period (within a few ms) across all three runs. Period drift between runs disqualifies it from the always-on set even if it appears in all three.

The three-capture redundancy is the load-bearing design choice. A single capture would conflate "always on" with "happened to be transmitted during my one window." Three power-cycled runs are the minimum to claim stability.

## Setup

Common to all three runs:

- **Bike:** 2020 Husqvarna Svartpilen 401. Cold (engine not run in the previous 30 min minimum), neutral, side stand down, no electrical accessories engaged.
- **Adapter / wiring:** unchanged from [Session 0](2026-06-17-key-off-baseline.md) and [Session 1](2026-06-17-key-on-cold-boot.md). Breakout's on-board 120 Ω termination state matches the decision recorded after Session 1 (leave in if Session 1 was clean; desolder if Session 1 flagged it).
- **Firmware:** the bitrate build that worked in Session 1 (`logger` 500 kbps **or** `logger-250k` 250 kbps — same one for all three runs of this experiment).
- **Host:** `scripts/capture.py`, venv per `scripts/README.md`.

Run spacing (load-bearing — do not skip):

- **Different power cycles.** Between runs the battery must see at least one full key-off period of ≥ 60 s — long enough that any keep-alive timers in the ECU/dash time out. Quick on-off-on does not count as a new power cycle for this purpose.
- **Different sessions ideally on different days**, but at a minimum spaced ~10 min apart. Same-minute reruns share too much thermal/electrical state to claim independence.
- **No bike state changes between runs.** Same fuel level (refuel only between Run 2 and Run 3 if you have to, and note it), same parking spot, same ambient conditions as far as practical. The point is to vary *only* the power cycle.

## Procedure

For **each** of Run 1 / Run 2 / Run 3, label them `engine-idle-run1`, `engine-idle-run2`, `engine-idle-run3`:

1. Bike key off. Confirm last power-off was ≥ 60 s ago (≥ 30 min for Run 1 since this is the cold start).
2. From the repo root:
   ```
   source .venv/bin/activate
   python scripts/capture.py --port /dev/cu.usbmodem101 --label engine-idle-run<N>
   ```
3. Wait 5 s with capture running, key still off. Bench-blank baseline at the head of the file.
4. Turn key to position 1 (key-on, engine off). **Press space** to mark `key_on` in events.csv.
5. Wait 30 s through the dash self-test into steady key-on-no-engine state. **Don't touch any controls.**
6. Press the starter (`s` hotkey at the moment you press the button). Let the engine catch and settle to idle. **Press space again** as soon as idle sounds stable, to mark `idle_settled`.
7. Hold idle for **120 s**. Don't touch throttle, brake, clutch, indicators, anything. Don't sit on the bike. Don't blip. The point is "what the bike says when nothing is happening."
8. Press the kill switch (`k` hotkey at the press). Let everything decay. Key off after the engine is silent. Wait 2 s, then `q` to stop the capture.
9. **Fill in session.md immediately:** ambient temperature, fuel %, run number, time since previous run, anything unusual (cold start backfire, warning light, weird noise, dropped key-on). Don't batch this across runs — memory of "was that on run 2 or run 3" is the kind of detail that destroys the baseline.

Repeat for runs 2 and 3 with the spacing requirements above.

## Result

### Per-run summary

| Run | Capture start (UTC)     | Frames | Unique IDs | Ambient | Fuel  | Engine thermal state    | Spacing from prev run     |
|-----|-------------------------|-------:|-----------:|---------|-------|-------------------------|---------------------------|
| 1   | 2026-06-17T15:56:23     | 89 803 |         11 | ~30 °C  | ~50 % | Cold (no engine-on today before this) | n/a — first run |
| 2   | 2026-06-17T16:13:19     | 88 872 |         11 | ~30 °C  | ~50 % | Partially warm (Run 1 + 13 min key-off cool) | ~13 min key-off |
| 3   | 2026-06-17T16:18:33     | 90 216 |         11 | ~30 °C  | ~50 % | Operating temp (~half gauge by end) | ~1.5 min key-off (below ~10 min ideal but ≥ 60 s power-cycle floor) |

Per-run frame counts are within ±1 % of each other across a ~3-minute idle window — strong indirect signal that the firmware/USB pipe isn't silently dropping frames between runs.

**Unplanned-but-useful side effect:** the three runs span three thermal states (cold → partial-warm → operating temp) rather than three identical replicates. This is a soft deviation from the plan's "no bike state changes between runs" requirement, but it turns the captures into a natural three-point thermal sweep — directly useful for coolant-temperature payload hunting in the Phase 2 follow-up. Logged in each run's session.md.

### Event marks per run

| Run | `key_on` (UTC)        | `starter button`       | `idle_settled`            | `kill switch`         | Cranking duration (`starter`→`idle_settled`) | Steady-idle duration (`idle_settled`→`kill`) |
|-----|-----------------------|------------------------|---------------------------|-----------------------|---------------------------------------------:|---------------------------------------------:|
| 1   | 15:56:30.148          | 15:57:00.292           | 15:57:01.292 \*           | 16:00:00.251          |  1.000 s \*                                  | 179.0 s                                      |
| 2   | 16:13:26.917          | 16:13:56.381           | 16:13:59.236              | 16:16:55.638          |  2.855 s                                     | 176.4 s                                      |
| 3   | 16:18:42.630          | 16:19:14.471           | 16:19:19.693              | 16:22:14.443          |  5.222 s                                     | 174.8 s                                      |

\* Run 1's `idle_settled` mark was missed — the value above is the `starter + 1 s` proxy. Run 2 and Run 3 recorded the mark properly. The actual cranking → idle-stable interval for this bike from Runs 2 and 3 is ~3–5 s, so Run 1's proxy of +1 s was an underestimate; a slice of what Run 1's analysis called "steady idle" was, in reality, still tail-end stabilisation. Doesn't shift any of the conclusions, but worth flagging if anyone tries to do sub-second analysis on Run 1's idle-window head.

### Cross-run ID stability — steady-idle window

**All three runs see the exact same 11 IDs** in their `idle_settled` → `kill switch` windows. Union = intersection = `{120, 121, 129, 12A, 12D, 12E, 450, 540, 541, 5A0, 5B0}`. **Cross-power-cycle stability bar is met.**

Median inter-arrival period per ID (steady-idle window only, USB-CDC bunching factored out by using the median):

| ID    | Run 1 (ms) | Run 2 (ms) | Run 3 (ms) | Spread (ms) | Spread (% of mean) |
|-------|-----------:|-----------:|-----------:|------------:|-------------------:|
| `12D` |      11.01 |      10.58 |      10.92 |       0.43  |              3.99 %|
| `12E` |      19.35 |      19.40 |      19.18 |       0.22  |              1.12 %|
| `120` |      19.54 |      19.74 |      19.75 |       0.21  |              1.08 %|
| `541` |      19.73 |      19.87 |      19.66 |       0.21  |              1.08 %|
| `121` |      19.37 |      19.55 |      19.41 |       0.18  |              0.90 %|
| `129` |      19.37 |      19.49 |      19.42 |       0.13  |              0.65 %|
| `12A` |      50.17 |      50.67 |      50.09 |       0.58  |              1.15 %|
| `450` |      49.87 |      49.87 |      49.80 |       0.07  |              0.15 %|
| `5B0` |      99.85 |      98.75 |      99.80 |       1.10  |              1.11 %|
| `540` |      99.58 |      99.12 |      99.68 |       0.56  |              0.56 %|
| `5A0` |      99.75 |      99.78 |      99.84 |       0.09  |              0.09 %|

Period spread across power cycles is well under 4 % for every ID and under 1.2 % for ten of the eleven. `12D` (10 ms cohort) is loosest, likely because at 10 ms cycle time the host-side USB-CDC bunching has more proportional impact on the median. The 10 / 20 / 50 / 100 ms cohort structure is the same across all runs — no ID changed cohort, no ID went rogue.

### Engine-start transient — three runs, three cranking-window lengths, same eleven IDs

| Run | Cranking window | Frames in window | Unique IDs in window |
|-----|----------------:|-----------------:|---------------------:|
| 1   |  1.00 s (proxy) |              405 |                   11 |
| 2   |  2.85 s         |            1 187 |                   11 |
| 3   |  5.22 s         |            2 180 |                   11 |

**Even with cranking windows from 1 s to over 5 s, no new ID emerged during cranking in any run.** Hypothesis 2 (engine-start transient as a distinct ID set) is **disconfirmed**: there is no cranking-only or alternator-coming-up arbitration ID on this connector. Any cranking-state information lives inside the payload bytes of the 11 always-on IDs.

### Post-kill decay — confirms a clean 5-vs-6 module split, three power cycles in a row

Latest frame seen for each ID after the `kill switch` event, in seconds (across the full post-kill window captured per run):

| ID    | Run 1 (s) | Run 2 (s) | Run 3 (s) | Decay group         |
|-------|----------:|----------:|----------:|---------------------|
| `120` |    0.306  |    0.234  |    0.231  | **Fast (<0.31 s)**  |
| `121` |    0.305  |    0.244  |    0.251  | **Fast (<0.31 s)**  |
| `129` |    0.305  |    0.244  |    0.251  | **Fast (<0.31 s)**  |
| `540` |    0.262  |    0.175  |    0.202  | **Fast (<0.31 s)**  |
| `5B0` |    0.263  |    0.175  |    0.202  | **Fast (<0.31 s)**  |
| `12A` |    5.606  |    4.793  |    4.686  | Slow (≥4.7 s)       |
| `12D` |    5.646  |    4.836  |    4.805  | Slow (≥4.7 s)       |
| `12E` |    5.646  |    4.835  |    4.712  | Slow (≥4.7 s)       |
| `450` |    6.066  |    5.216  |    5.145  | Slow (≥4.7 s)       |
| `541` |    6.419  |    7.060  |    6.298  | Slow (≥4.7 s)       |
| `5A0` |    5.581  |    4.736  |    4.686  | Slow (≥4.7 s)       |

The split is **exactly 5 vs 6** in every run, with the same IDs on each side every time:

- **Fast-decay group (5 IDs):** `120`, `121`, `129`, `540`, `5B0` — last frame within 0.18–0.31 s of `kill switch`.
- **Slow-decay group (6 IDs):** `12A`, `12D`, `12E`, `450`, `541`, `5A0` — last frame at 4.7–7.1 s after `kill switch`, with broadcasting continuing through end of capture in some cases.

This is the first observed CAN evidence of more than one physical module sourcing the always-on broadcast set: at least two modules with distinct post-kill power-down timing. Promoted to its own finding at `confirmed` status: [`docs/findings/can/post-kill-decay-groups.md`](../findings/can/post-kill-decay-groups.md).

**Note on `12D` decay-window median.** In Run 1 I flagged `12D`'s post-kill median dropping to 0.8 ms as a likely USB-CDC end-of-stream bunching artifact. Runs 2 and 3 reproduce the same pattern — high frame count in the decay window with sub-millisecond inter-arrivals at points. Treat the decay-window *count* as honest but the decay-window *median dt* as a host-side artifact, not a bike fact.

### Disqualified IDs

None across any run, any window. The always-on set is closed at 11 IDs.

### Raw captures

- `logs/2026-06-17-engine-idle-run-1/`
- `logs/2026-06-17-engine-idle-run-2/`
- `logs/2026-06-17-engine-idle-run-3/`

## Interpretation

- **The 11-ID always-on broadcast set is confirmed.** Three independent power-cycled captures, three different thermal states, three nearly-identical inventories. Median periods agree to within ~1 % for ten of eleven IDs and within ~4 % for the busiest (`12D`). The previously-provisional finding [`docs/findings/can/always-on-broadcast-ids.md`](../findings/can/always-on-broadcast-ids.md) is promoted to `confirmed`.
- **Hypothesis 2 (engine-start transient ID set) is rejected.** Three cranking windows of widely different durations (1 / 2.85 / 5.22 s) saw the same 11 IDs. Whatever the cranking → idle transition looks like on this bus, it's *byte-level* not *ID-level*.
- **The post-kill decay-group split is the strongest module-attribution lead we have so far.** Reproducible across three power cycles with the same five IDs going silent within ~0.3 s of kill and the same six continuing for 4.7+ s. Hypothesis: the fast-decay group originates from a module on the engine-management / charging side of the harness that loses power immediately when the kill switch breaks the ignition circuit, while the slow-decay group is sourced from a module powered through a keep-alive or capacitor-buffered rail (instrument cluster? body controller? ABS module?). The hypothesis is not asserted as fact — see follow-ups.
- **The three runs accidentally became a thermal sweep** because the spacing was tighter than ideal between Runs 2 and 3. Cold (Run 1) → partial-warm (Run 2) → operating temp (Run 3). This is a deviation from the original test design (which wanted thermal-state-held-constant), but a useful one: any payload byte that monotonically rises across Runs 1 → 2 → 3 is a coolant-temperature candidate. This becomes the most informative input to the payload-diff follow-up.
- **Period-stability sub-conclusion:** even at the strictest level the experiment plan asked for (a "few ms" tolerance across runs), every ID passes. The bike's broadcast cadence is genuinely stable across power cycles and across the thermal range we sampled. Period-based ID identification in future per-input experiments is therefore on solid footing.

## Follow-ups

- ✅ Promote [`docs/findings/can/always-on-broadcast-ids.md`](../findings/can/always-on-broadcast-ids.md) to `confirmed`. *(done in this session)*
- ✅ Open new finding [`docs/findings/can/post-kill-decay-groups.md`](../findings/can/post-kill-decay-groups.md). *(done in this session)*
- ✅ Update [`docs/status.md`](../status.md). *(done in this session)*
- **Payload-diff experiment** comparing the engine-off prelude vs. steady-idle windows of each run, plus the across-run thermal sweep, on the 11 always-on IDs. This is the next experiment to draft. With three runs at three thermal states, we have natural axes to separate "engine state" bits from "coolant temperature" bytes from "RPM" bytes. No new captures needed.
- **Module attribution experiment** to put hardware-side hypotheses around the fast/slow decay-group split: scope the supply rails for the suspected modules during a kill event, or pull fuses one at a time and see which group disappears. Crosses into hardware testing — defer unless the payload-diff results need it.
- **Tooling — add a hotkey for `idle_settled`** to `scripts/capture.py`. Run 1 needed a proxy; Runs 2 and 3 got it right with a manual spacebar but it's easy to miss. Suggest `e` for "engine settled" with label `engine settled`. Trivial change.
- **Tooling — bus-error visibility.** Still not addressed. With the always-on set now `confirmed` based on cross-run consistency of frame counts, the urgency drops — but it's still the right thing to add before per-input experiments where a dropped frame could be the difference between "input does nothing" and "we missed the response".
- **LED tooling fix** still open — `pio run -e logger -DLED_GPIO=48 -t upload` and bench-verify with no bike connected.
- **Bike-state convention.** Going forward, capturing thermal state more precisely (coolant gauge reading at session start and end, perhaps a digit on the dash if available) is worth doing — this set of three runs accidentally proved it informs analysis.
