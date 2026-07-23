---
date: 2026-06-30
status: success
phase: 2
related:
  findings:
    - always-on-broadcast-ids
    - byte-d7-cycle-hash
    - signal-engine-torque
    - byte-encoding-12-in-16
    - engine-state-bits-decay-shape
    - signal-12d-d1-bit0
  decisions: []
  logs:
    - 2026-06-17-key-on-cold-boot
    - 2026-06-17-engine-idle-run-1
    - 2026-06-17-engine-idle-run-2
    - 2026-06-17-engine-idle-run-3
    - 2026-06-19-gear-cycle-clutch-A-clutch-only
    - 2026-06-19-gear-cycle-clutch-B-gear-cycle
    - 2026-06-19-kill-switch-toggle
    - 2026-06-19-side-stand-toggle
    - 2026-06-19-throttle-sweep-engine-off
    - 2026-06-22-wheel-spin-paddock-stand
    - 2026-06-23-engine-driven-rear-spin
    - 2026-06-23-shift-lever-vs-clutch
    - 2026-06-24-front-wheel-decay-mark
    - 2026-06-24-front-wheel-hand-spin
---

# Unknown-byte reconnaissance — desk-only sweep across the captured corpus

Profile every undecoded byte and bit on the 11 always-on broadcast IDs across the 14 sessions already on disk. Goal is not to attribute new signals directly — it's to rank the 53 `?` bytes (and the uncharted bits inside the 21 `S◐` bytes) from [`docs/signals/coverage.md`](../signals/coverage.md) into buckets that tell us which deserve next-capture rider input and which should be deprioritised.

## Hypothesis

For each currently-undecoded byte, the corpus will sort it into one of four buckets:

1. **Globally static** — single value across every frame of every session. Either reserved or a slot that only fires under conditions we have never captured (e.g. ABS event, fault state, indicator stalk). High prior for several bytes on `12A`, `12E`, `5A0`, and the entire `450` payload.
2. **Active but already attributable** — moves only when a known signal moves, with correlation near ±1.0 to RPM / throttle / coolant / wheel-speed / engine-on counter. These are silent mirrors / derivations of signals we already have; they don't unlock new information but they do close the byte.
3. **Active and not explained by known signals** — moves across the corpus but doesn't track any decoded quantity. These are the **highest-value targets**: each one is a candidate signal we can chase with a focused correlation pass or a single next-capture experiment.
4. **Engine-state-bit-shaped** — bit-level: stable in one mode (off / on / kill), flips once at the boundary, never wiggles within. Adds to the bit set already catalogued by [[engine-state-bits-decay-shape]].

A secondary hypothesis: bucket-3 entries will cluster on a small number of IDs. `12A` (50 ms, Slow group, untouched), `12E` (20 ms, Slow-early, untouched), and `5A0` (100 ms, Slow-mid, untouched) are the strongest candidates given they currently carry zero attributions but broadcast continuously through every captured condition.

## Setup

Desk-only. No new captures. Inputs:

- All 14 captures listed in `related.logs` — covers cold boot, key-on engine-off, idle (cold / warm / hot), gear cycle, clutch, kill toggle, side-stand toggle, throttle sweep engine-off, paddock-stand wheel spin engine-off, engine-driven rear spin (RPM B1..B5), shift-lever vs clutch, front-wheel hand-spin engine-off, front-wheel decay + high-beam toggle.
- Per-session `events.csv` marks for windowing (engine-on / engine-off / setpoint / kill / input-toggle).
- Coverage matrix [`docs/signals/coverage.md`](../signals/coverage.md) as the byte-level "what's already explained" mask.
- Reference signals decoded by `scripts/decode_live.py` (or equivalent): `rpm`, `throttle_position`, `coolant_temp`, `wheel_speed_front`, `wheel_speed_rear`, `engine_on_counter`, `kill_switch`, `side_stand`, `gear_position`.

New script: `scripts/unknown_byte_sweep.py`. Outputs derived CSVs alongside each session (`unknown_byte_sweep.csv`) and a single top-level summary `scripts/out/unknown_byte_sweep_summary.csv` joining across sessions.

D7 is excluded on the 9 IDs where the cycle-hash model is closed ([[byte-d7-cycle-hash]]); D7 on `540` and `450` *is* included so we can re-test whether it stays at `0x00` now that the corpus is larger than when the original D7 finding was written.

## Procedure

1. **Build the unknown mask.** From `coverage.md`, materialise the list of `?` bytes (53) and, for each `S◐` byte, the list of bits not yet attributed. Persist as `scripts/coverage_mask.yaml` so this sweep and future ones share one source of truth.

2. **Per-session per-byte aggregation.** For each `(session, ID, byte)` in the unknown mask:
   - distinct value count
   - value histogram (top 5 + tail count)
   - mean, std, min, max
   - per-bit toggle count and dominant value
   - first-seen and last-seen timestamps relative to session start and to the engine-on / engine-off windows

3. **Cross-corpus rollup.** For each `(ID, byte)`:
   - union of distinct values across all 14 sessions → if `|union| == 1`, mark **GLOBAL-STATIC**
   - per-session per-bit toggle count: a bit is **STATIC-PURE** if every session has zero toggles, **STATE-BIT-SHAPED** if toggle count is ≤ 2 per session but the dominant value differs between engine-off and engine-on sessions, **ACTIVE** otherwise
   - engine-off vs engine-on Δ across the multi-session corpus (mirroring the battery-voltage scan's framing), with KNOWN-signal cells annotated so the human reader can sanity-check the top of the list

4. **Correlation pass against known signals.** For every byte marked **ACTIVE** in step 3, compute Pearson r against:
   - `rpm` (engine-on windows only)
   - `throttle_position` (engine-on; also against the throttle-sweep engine-off session as a separate channel)
   - `coolant_temp` (idle-x3 only — the three runs span cold/warm/hot)
   - `wheel_speed_front` and `wheel_speed_rear` (engine-driven rear-spin + front-wheel hand-spin)
   - `engine_on_counter` (engine-on windows; modular unwrap before correlating)
   - `RPM × throttle` (load proxy — see [[signal-engine-torque]] open questions)
   - Time-since-engine-on (engine-on windows) — to surface monotonic state.

   A byte with `|r| ≥ 0.9` to any known channel is **EXPLAINED-BY**. Lower r values are kept verbatim — manual review is cheaper than an arbitrary threshold for the borderline cases.

5. **Per-byte bucketing.** Tag each unknown byte as one of: `GLOBAL-STATIC`, `EXPLAINED-BY:<signal>`, `STATE-BIT-SHAPED`, `UNEXPLAINED-ACTIVE`, `INSUFFICIENT-DATA`. The last bucket is for bytes that change in only one session — too narrow to discriminate without another capture.

6. **Three targeted sub-checks** opened by the sweep, run in the same pass:
   - **121 channel A/B** ([D0:D1, D2:D3] BE int16): correlate decoded int16 values against `rpm`, `throttle_position`, `RPM × throttle`, and engine-on-but-fixed-RPM windows from rear-spin Phase A (load-only). Records whether the rear-spin idle-with-drivetrain-load case moves either channel.
   - **541 D6 vs throttle**: revisit the weak `r ≈ +0.26` flagged in [[signal-throttle-position]] using the full corpus, including the engine-on throttle behavior from rear-spin (the original finding ran engine-off only).
   - **540 D7 and 450 D7**: confirm or break the "always 0x00" claim across all 14 sessions. If either ever deviates, it's a new signal lead.

7. **Output.** Two human-facing tables in this experiment doc post-run:
   - **Per-ID byte status** with bucket + supporting numbers (replaces the next manual update of `coverage.md`'s matrix).
   - **Shortlist** — the `UNEXPLAINED-ACTIVE` bytes sorted by activity, each with a one-line "what to test next" (correlation candidate or rider input to exercise).

## Result

Coverage mask built from `signals.yaml` + the additions table fixes 25 of 88 bytes as fully explained, leaves 7 partially-explained, and 56 fully-unknown. The sweep classified all 65 non-mask-fully-covered bytes across the 14-session corpus:

| Bucket               | Count |
|----------------------|------:|
| GLOBAL-STATIC        |    46 |
| EXPLAINED-BY         |     1 |
| STATE-BIT-SHAPED     |     0 |
| UNEXPLAINED-ACTIVE   |    14 |
| INSUFFICIENT-DATA    |     2 |

Per-ID byte status after the sweep:

```
legend: 0=GLOBAL-STATIC  E=EXPLAINED-BY  ?=UNEXPLAINED-ACTIVE  .=INSUFFICIENT-DATA  X=fully-in-mask
ID     D0  D1  D2  D3  D4  D5  D6  D7
120    X   X   X   X   0   0   0   X
121    ?   ?   ?   ?   0   ?   0   X
129    ?   0   0   0   0   0   0   X
12A    0   ?   0   0   0   0   0   X
12D    X   X   X   X   E   X   X   X
12E    0   0   0   0   0   0   ?   X
450    0   0   0   0   0   0   0   X
540    0   X   ?   ?   0   X   X   X
541    0   .   ?   0   X   ?   ?   X
5A0    0   0   0   0   ?   0   0   X
5B0    .   0   0   0   0   0   0   X
```

Notable bucket assignments:

- **`12D` D4 → EXPLAINED-BY `wheel_front`** at r = +0.9985 in `2026-06-24-front-wheel-decay-mark` and r = +0.9978 in `2026-06-24-front-wheel-hand-spin`. Two independent captures, both engine-off, both near-perfect correlation. `12D` D4 is a front-wheel-speed-derived broadcast — distinct byte position from the known `12D` D0:D1 12-bit field, so this is a *new* speed channel (probably the same value at a different scale, similar to how `12D` D2 is the coarse rear-speed mirror).
- **`541` D6 → UNEXPLAINED-ACTIVE, moves in 14/14 sessions** — the most active byte in the corpus. Already informally noted as the "key-on ramp counter" in side-comments on `scripts/battery_voltage_scan.py`; this sweep elevates it to a first-class target. Not strongly correlated with any decoded reference (best r = +0.504 vs `wheel_front`).
- **`12A` D1 → UNEXPLAINED-ACTIVE, moves in 13/14 sessions** but only 2 distinct values in the corpus union — a single-bit-shaped flag on a 50 ms-period ID that nothing in `signals.yaml` explains. Strong candidate for a per-input correlation walk.
- **`121` D0–D3** all UNEXPLAINED-ACTIVE — confirms the twin int16 finding ([[signal-engine-torque]]) is the right frame, and the channels themselves remain semantically open. Best r values are `D1` and `D0` ≈ +0.80 vs throttle (from the throttle-sweep session — both channels' low bytes move with throttle even engine-off; D0 movement is the sign-extension from D1 dipping negative).
- **Three "untouched" IDs each have exactly one moving byte**: `12A` D1, `12E` D6, `5A0` D4. Every other byte on each of these IDs is GLOBAL-STATIC. Tightens the bike-side experiment plan: chase one byte per ID instead of all eight.

Sub-check results:

- **`121` channel A/B int16 vs RPM / throttle / load.** Engine-off the channels sit at sharply different "bias" values (μA ≈ 166, μB ≈ 463 across nearly every session, with `gear-B` and `throttle` showing μA dropping into the 117-119 range — the only engine-off sessions where channel A moves materially). Engine-on the channels wobble near 0 (μA ≈ +0.4 to +1.3, μB ≈ +0.3 to +1.3). On `idle-1/2/3` the channels correlate moderately *negatively* with RPM (r_A ≈ -0.5 to -0.7, r_B ≈ -0.7 to -0.8) — i.e. as engine moves off idle the channels move closer to 0. On `rear-spin/on` (RPM sweep), r_A and r_B vs RPM only reach +0.31-0.33 and vs throttle +0.48-0.56 — *not* the strong load-correlated signature MAP would produce. The "lambda short-term trim" hypothesis fits the engine-on signature (closed-loop wobble at idle, larger excursions in open loop) but the engine-off bias values argue against it. Verdict: still open, but the desk-only data narrows the search away from MAP and toward fuel/ignition correction terms.
- **`541` D6 vs throttle.** Revisit of the weak r ≈ +0.26 flagged in [[signal-throttle-position]]'s open-questions list. Re-tested against the full corpus: the throttle-sweep engine-off session gives r = +0.403 — modest, *not* a throttle-derived signal. D6 is dominated by the key-on ramp counter pattern; the throttle session correlation is incidental. Open question can be closed.
- **`540` D7 and `450` D7 always-0x00 reconfirmation.** Across all 14 sessions: `540` D7 = 18,809 frames, 0 non-zero; `450` D7 = 38,507 frames, 0 non-zero. Both **CONFIRMED 0x00**. The "two D7 exceptions to the cycle hash" claim from [[byte-d7-cycle-hash]] survives the larger corpus.

Outputs:

- `scripts/coverage_mask.yaml` — auto-generated explanation map (derived from `signals.yaml` + script-internal `MASK_ADDITIONS`).
- `scripts/out/unknown_byte_sweep_per_byte.csv` — per (ID, byte) bucket + supporting stats.
- `scripts/out/unknown_byte_sweep_corr.csv` — every (ID, byte) × reference signal correlation that passed the std + bucket-count filters.
- `scripts/out/unknown_byte_sweep_per_bit.csv` — STATE-BIT-SHAPED bits (empty this run — no new ones beyond the already-attributed five).

## Interpretation

- **`12D` D4 is a real, decode-able signal.** Two engine-off sessions independently land r ≥ 0.998 against decoded front wheel speed. Next: write a finding once the encoding (offset / scale / wrap behaviour) is characterised — this needs a script-level look at the byte values vs decoded wheel_front, not another capture.
- **The three untouched IDs collapse from 21 unknown bytes to 3 unknown bytes.** Six of the seven bytes on each of `12A`, `12E`, `5A0` are GLOBAL-STATIC across every condition we've exercised. Future bike-side experiments don't need to "decode 12A" — they need to decode `12A` D1, `12E` D6, `5A0` D4. That's a 7× narrower target list than the coverage matrix suggested.
- **GLOBAL-STATIC ≠ reserved.** Forty-six bytes read a single value across 14 sessions and ~800k frames. Some are genuinely reserved (the D7 exceptions, the bits-1-3 reserved zeros). Others are latent — likely waiting on inputs we haven't exercised (ABS active, indicator stalk, indicator stalk + brake, fault states, fuel low, mode button, ambient sensor delta). The list of GLOBAL-STATIC bytes is now a *checklist* for the next bike-side session: each novel input should be specifically watched against it.
- **The `121` twin int16 channels are not MAP and not load-driven.** Best engine-on r vs RPM × throttle is ≈ +0.31. The original [[signal-engine-torque]] write-up already ruled out drivetrain load via the rear-spin Phase A test; the corpus-wide correlation pass corroborates that ruling on a much broader basis. The remaining candidates are lambda short-term trim, ignition advance correction, or a fuel-table correction term — all of which would respond to fine RPM/throttle excursions rather than coarse setpoints. Discriminating among them requires a slow throttle-sweep at fixed RPM in a future engine-on capture.
- **Limitations the sweep can't bypass.** 100 ms bucket aggregation will blur fast transients (anything < 100 ms — including, plausibly, parts of the `121` int16 channels' engine-on wobble). For bytes that move only during input edges (e.g. a one-frame flag on an indicator press), the correlation pass will under-detect. The cardinality + per-session-moves stats catch these but the r-based bucketing doesn't.

## Follow-ups

- **Finding (write):** `12D` D4 — front-wheel-speed-derived broadcast, encoding TBD by a small follow-up script that plots `12D` D4 vs decoded `wheel_speed_front` across both engine-off sessions and fits scale/offset/wrap. Update `coverage.md` and `signals.yaml` once the encoding is locked.
- **Finding (write):** `541` D6 — key-on ramp counter promoted from informal side-note in `scripts/battery_voltage_scan.py` to a documented behaviour. Cheap to characterise from the existing 14 sessions: the script-level look at value-vs-time-since-key-on across all engine-off windows.
- **Open question closed:** `541` D6 ≠ throttle-derived (r ≤ +0.40 in the only session that moves throttle). Update [[signal-throttle-position]]'s open-questions section.
- **Open question reconfirmed:** `byte-d7-cycle-hash` exceptions (`540` D7, `450` D7) hold across the full 14-session corpus.
- **Coverage matrix update.** `docs/signals/coverage.md` per-ID byte map should pick up: `12D` D4 → `EXPLAINED-BY:wheel_front`; `12A`, `12E`, `5A0` bytes (other than the one moving byte) → confirmed GLOBAL-STATIC after 14 sessions.
- **Next bike-side session — narrowed plan.** The novel-input list (ABS active, indicator stalk, horn, headlight high/low, brake-lever pressure, near-empty-fuel idle, fault-trigger) gets watched specifically against:
  - The three single-moving-byte IDs: `12A` D1, `12E` D6, `5A0` D4.
  - The two `121` int16 channels for slow-throttle / fixed-RPM excursions (lambda / ignition-correction hypothesis discriminator).
  - `129` D0 bits 0 and 2 (the two unattributed bits in the gear / clutch / shift byte).
  - `541` D5 (moves in 6/14, no current attribution).
  - The full GLOBAL-STATIC checklist for any byte that suddenly flips — a single flipping byte under a novel input attributes itself.
- **Decision unblocked or forced.** None outright. Soft pressure on a hypothetical "should the dashboard pipe the `121` twin int16 channels through to the live view even without semantic attribution?" — leaning yes, since the rear-spin engine-on signature suggests they're informative about ECU state even if we don't yet know what they represent. Not an ADR yet.

## Follow-ups

- **Coverage matrix update.** Per-ID byte status from step 5 is the new ground truth — `docs/signals/coverage.md` gets a refresh.
- **Per-bucket findings, only where the conclusion is durable.** A *new* `GLOBAL-STATIC` claim across 14 sessions is finding-worthy ("byte X observed static across full corpus"); an `UNEXPLAINED-ACTIVE` byte is not — it stays in this experiment until a hypothesis is tested.
- **Next-capture experiment scoping.** The shortlist drives the rider-input plan for the next session: pair each high-priority unknown byte with the input most likely to move it. Specifically:
  - Untouched-ID bytes (`12A`, `12E`, `5A0`): test ABS-active condition (gentle parking-lot brake-grab on wet surface), indicator stalk, horn, headlight high/low, brake-lever pressure sweep, and a fuel-tank-near-empty engine-on run.
  - `450` payload: still won't have moved — flag for a UDS-sniff session, since this ID may only update on diagnostic request.
- **`121` channel A/B**: if the sub-check correlates one channel with `RPM × throttle` and the other with something else, write a finding promoting the encoding's interpretation. Otherwise, lock in a single bike-side experiment that varies load at fixed RPM/throttle (paddock-stand 1st-gear at multiple steady-state RPM with brake load).
- **Decision unblocked or forced**: none yet — this is reconnaissance. The bike-side follow-up may force an ADR on whether the dashboard MVP ignores the `121` channels (treat as "interesting but unattributed") or pipes them through.
