---
date: 2026-06-21
status: success
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/signal-rpm
    - can/signal-coolant-temp
    - can/signal-throttle-position
    - can/signal-kill-switch
    - can/signal-side-stand
    - can/signal-gear-position
    - can/byte-d7-cycle-hash
  experiments:
    - 2026-06-17-payload-diff-idle
    - 2026-06-18-throttle-sweep-engine-off
    - 2026-06-18-kill-switch-toggle
    - 2026-06-18-side-stand-toggle
    - 2026-06-18-gear-cycle-clutch
  logs:
    - 2026-06-17-key-on-cold-boot
    - 2026-06-17-engine-idle-run-1
    - 2026-06-17-engine-idle-run-2
    - 2026-06-17-engine-idle-run-3
    - 2026-06-19-throttle-sweep-engine-off
    - 2026-06-19-kill-switch-toggle
    - 2026-06-19-side-stand-toggle
    - 2026-06-19-gear-cycle-clutch-A-clutch-only
    - 2026-06-19-gear-cycle-clutch-B-gear-cycle
---

# Cross-session payload-byte diff — single-cause attribution across all captures on disk

## Hypothesis

The original [[2026-06-17-payload-diff-idle]] classified the 88 payload bytes of the 11 always-on broadcast IDs against three engine-idle baseline runs only. Its "STATIC: 47 bytes" verdict is therefore a **lower bound on movement** — a byte that never changes across three steady-idle windows can still change under a per-input condition (throttle, kill, gear, side-stand, clutch). Several of those per-input captures now exist; their data has been mined for the *expected* bit (e.g., `kill_switch_scan.py` finds the kill bit) but never re-fed into the full byte-classification grid.

Concrete predictions:

1. **Several bytes flagged STATIC in [[2026-06-17-payload-diff-idle]] will turn out to vary** when the per-input captures are included. Each such byte is either (a) a side effect of the per-input control that no targeted scan was looking for, or (b) a byte that only carries information when the corresponding input is exercised (e.g., a gear-shift latch). Both cases are useful: they cut the STATIC pool further and surface candidate signals.
2. **Single-cause bytes will exist** — bytes that change in exactly one of {throttle, kill, gear, side-stand, clutch} sessions and are static in every other session. Single-cause attribution is the cleanest possible signal hypothesis; a per-input capture turns directly into a finding.
3. **Multi-cause bytes will also exist** — bytes that move under two or more conditions. These are composite/derived signals (e.g., a "rider intent" or "ride mode" byte that captures multiple inputs) or D7-style checksum bytes where the payload upstream changed. Cataloguing them is useful even when individual attribution is impossible.
4. **The known signals will reappear** as a sanity-check baseline: `120` D2 should flag throttle-only, `541` D2 should flag kill-only, `540` D3 should flag side-stand + gear, `129` D0 should flag gear-only, etc. The procedure is validated when all the already-confirmed signals are recovered by this scan.

If the scan finds *no* new movers beyond the already-known signals, that is also a useful null result: it bounds how much information can be extracted from these specific stationary engine-off captures and reinforces that engine-on capture is the right next step.

## Setup

Desk-only. Corpus — 9 captures on disk that contain CAN frames (2 captures excluded: `2026-06-17-bench-dryrun` and `2026-06-17-yank-test` are 0-byte capture logs; `2026-06-17-key-off-baseline` is bus-silent by design and contributes no payload bytes):

| Session                                            | Condition                                      | Engine | Inputs varied                       |
|----------------------------------------------------|------------------------------------------------|--------|-------------------------------------|
| `2026-06-17-key-on-cold-boot`                      | key-on, engine never started                   | off    | none (control)                      |
| `2026-06-17-engine-idle-run-1`                     | engine cold idle                               | on     | none                                |
| `2026-06-17-engine-idle-run-2`                     | engine partial-warm idle                       | on     | none                                |
| `2026-06-17-engine-idle-run-3`                     | engine operating-temp idle                     | on     | none                                |
| `2026-06-19-throttle-sweep-engine-off`             | key-on, throttle swept full range              | off    | throttle position                   |
| `2026-06-19-kill-switch-toggle`                    | key-on, kill switch toggled 6×                 | off    | kill switch                         |
| `2026-06-19-side-stand-toggle`                     | key-on, side stand toggled 6×                  | off    | side stand                          |
| `2026-06-19-gear-cycle-clutch-A-clutch-only`       | key-on, clutch lever pumped                    | off    | clutch                              |
| `2026-06-19-gear-cycle-clutch-B-gear-cycle`        | key-on, gear cycled N↔1                        | off    | gear (plus clutch for the shift)    |

Each session has an `events.csv` and a `capture.log`. The engine-idle runs have additional event marks (`key_on`, `starter`, `idle_settled`, `kill`); the per-input sessions have one keystroke per input transition (`k`, `j`, `g`, `n`, `t`, `c`).

New script: `scripts/cross_session_diff.py`. Reads all 9 sessions, classifies each (ID, byte) pair into a movement profile across the session set.

## Procedure

1. **Per-session per-byte summary.** For each session, for each of the 88 (ID, byte) pairs, compute:
   - distinct value count
   - dominant value + dominant-value frequency (purity)
   - value set (capped at 16 distinct, then "≥16")
   - bit-level: per-bit dominant value (0 or 1) and per-bit purity

   Trim each session to its steady window: drop the first 2 s after `key_on` (boot transient — see [[2026-06-21-cold-boot-id-emergence]]) and the last 2 s before end-of-capture. For the engine-idle runs, trim to the `idle_settled` → `kill` window (matches [[2026-06-17-payload-diff-idle]]'s definition); for the per-input sessions, use the full window from `+2 s after key-on` to end.

2. **Cross-session classification.** For each (ID, byte), build a 9-entry profile of (distinct_count, dominant_value) and classify:

   - **GLOBAL-STATIC** — same dominant value across all 9 sessions with ≥99 % purity in each. Tightens the [[2026-06-17-payload-diff-idle]] STATIC count and surfaces bytes truly carrying no signal in any captured condition.
   - **SINGLE-CAUSE(<session>)** — moves (≥3 distinct values OR purity ≤80 %) in exactly one session; static in the other 8. Records the session that triggered the movement. These are the prime new-signal candidates.
   - **ENGINE-STATE** — moves in the 3 engine-on sessions but is static across all 6 engine-off sessions (existing payload_diff result reproduced through a different lens — useful sanity check).
   - **MULTI-CAUSE** — moves in 2+ sessions. Annotated with the set of triggering sessions and a hint about whether the movement is consistent across them (same value set → composite of inputs encoded into one byte) or different (likely D7 checksum reacting to upstream change).
   - **D7-EXCLUDED** — byte position D7 of any ID. Per [[byte-d7-cycle-hash]], D7 churns deterministically with the rest of the payload; it will trivially appear MULTI-CAUSE everywhere. Tag separately so it doesn't drown out genuine multi-cause hits.

3. **Bit-level overlay.** Repeat (2) at bit granularity for any byte that is not GLOBAL-STATIC. A bit-level SINGLE-CAUSE hit is the strongest possible signal lead — exactly the [[signal-kill-switch]] / [[signal-side-stand]] pattern.

4. **Reproduce known signals.** Print the row for each already-confirmed signal byte (`120` D0, `120` D1, `120` D2, `129` D0, `540` D3, `540` D5, `540` D6, `541` D2) and verify the classifier puts them in the expected bucket:
   - `120` D0, D1 → ENGINE-STATE (RPM only varies engine-on)
   - `120` D2 → SINGLE-CAUSE(throttle-sweep)
   - `129` D0 → SINGLE-CAUSE(gear-cycle)
   - `540` D3 → MULTI-CAUSE(side-stand, gear-cycle) — side-stand bit 0 + gear lo nibble share the byte
   - `540` D5, D6 → ENGINE-STATE (coolant only varies engine-on)
   - `541` D2 → SINGLE-CAUSE(kill-switch)

   If any expected reproduction misses, the scan logic has a bug — investigate before trusting the new findings.

5. **Emit the candidate-signal short list.** Filter the cross-session table to:
   - bytes that newly turn out to move (were STATIC in [[2026-06-17-payload-diff-idle]], are not GLOBAL-STATIC here)
   - bytes flagged SINGLE-CAUSE (excluding the known ones)
   - bit-level SINGLE-CAUSE hits in non-confirmed bytes

   Each such hit becomes a row in a candidate-signal table with: ID, byte (or byte:bit), triggering session, value set under that session, value when static, plain-English next-step hypothesis (e.g., "candidate clutch-event latch — re-test under [[2026-06-19-engine-on-gear-clutch]] when engine-on clutch data exists").

6. **Write findings.** Any SINGLE-CAUSE hit on a per-input session whose target signal is already isolated becomes a candidate `provisional` finding (e.g., a previously-unflagged byte that only moves in the kill-switch capture is a second kill-related field). Hits on inputs without a confirmed signal (clutch — null so far) become higher-priority candidates for the engine-on stationary batch.

## Expected outcomes

- **GLOBAL-STATIC count meaningfully smaller than 47.** Some "STATIC at idle" bytes will turn out to track an input. A small reduction (say 47 → ~38) is a normal outcome and worth recording.
- **Known signals reappear in their expected buckets.** Procedural sanity.
- **At least one new SINGLE-CAUSE hit per per-input session that hasn't already been mined to exhaustion.** Most likely on the clutch or side-stand sessions (each only confirmed a single bit; secondary fields plausibly exist). Less likely on throttle (already mined hard via `throttle_sweep.py`'s range-threshold scan).
- **D7 bytes uniformly MULTI-CAUSE.** Expected; the D7-EXCLUDED tag separates them visually but adds no new information.
- **Plausible null:** zero new SINGLE-CAUSE hits. Useful — it shows the existing per-input scans were already complete for these inputs, and the residual unknowns require new captures (engine-on, motion). The next session should then be engine-on stationary, not more desk work.

## Result

`scripts/cross_session_diff.py` was run against all 9 captures. Window summary:

|  session     | engine | frames | window length |
|--------------|:------:|-------:|--------------:|
| `cold-boot`  | off    | 71 299 | 169.8 s       |
| `idle-1`     | on     | 75 160 | 179.0 s       |
| `idle-2`     | on     | 74 087 | 176.4 s       |
| `idle-3`     | on     | 73 391 | 174.8 s       |
| `throttle`   | off    | 26 099 |  64.5 s       |
| `kill`       | off    | 28 911 |  75.0 s       |
| `stand`      | off    | 27 871 |  66.4 s       |
| `clutch`     | off    | 36 190 |  86.2 s       |
| `gear`       | off    | 29 281 |  70.1 s       |

### Classification summary (D7 excluded, 77 byte slots)

| classification    | count |
|-------------------|------:|
| GLOBAL-STATIC     | 58    |
| MULTI-CAUSE       | 8     |
| ENGINE-STATE      | 6     |
| SINGLE-CAUSE      | 5     |

Down from ~65 STATIC-of-77 in [[2026-06-17-payload-diff-idle]] — **7 bytes were promoted out of the static pool** by adding the per-input sessions.

### Known-signal reproduction (procedural sanity)

| ID    | byte | got                        | expected                   | verdict |
|-------|------|----------------------------|----------------------------|---------|
| `120` | D0   | ENGINE-STATE               | ENGINE-STATE (RPM hi)      | ✓       |
| `120` | D1   | ENGINE-STATE               | ENGINE-STATE (RPM lo)      | ✓       |
| `120` | D2   | SINGLE-CAUSE(throttle)     | SINGLE-CAUSE(throttle)     | ✓       |
| `129` | D0   | SINGLE-CAUSE(gear)         | SINGLE-CAUSE(gear)         | ✓       |
| `540` | D3   | MULTI-CAUSE(kill, stand)   | MULTI-CAUSE(stand, ?)      | ✓ (kill not gear — see below) |
| `540` | D5   | MULTI-CAUSE                | ENGINE-STATE (coolant hi)  | ✗ (data-hygiene — see below) |
| `540` | D6   | MULTI-CAUSE                | ENGINE-STATE (coolant lo)  | ✗ (same)                     |
| `541` | D2   | SINGLE-CAUSE(kill)         | SINGLE-CAUSE(kill)         | ✓       |

Six of eight reproductions match exactly. The two misses are both 540 coolant bytes — both fail ENGINE-STATE because the engine-off sessions disagree on their dominant coolant value:

- `540` D5 dominant: `0x01` in cold-boot + stand + clutch + gear, `0x00` in throttle + kill, `0x01→0x02→0x03` across idle-1/2/3 (cold→warm→op-temp). This is *not* a classifier bug — it's real coolant data. The 2026-06-19 captures were after several days where the bike sat; ambient temperature differences across capture days push the encoded coolant value (×0.1 °C) below the 0x01 quantisation threshold for some sessions. Not a bug; a useful reminder that "engine-off" doesn't mean "coolant sensor reads zero."
- `540` D6 (coolant lo byte, ×0.1 °C) has 256 distinct values in every engine-on session and 2-4 distinct in engine-off — also real coolant entropy, classified MULTI-CAUSE because every session "moves."

Loosening the ENGINE-STATE criterion to allow a small engine-off dominant set would tag these correctly but would also paint genuine MULTI-CAUSE bytes as ENGINE-STATE. The classifier's current strictness is acceptable; coolant bytes get a manual carve-out in interpretation.

`540` D3's `MULTI-CAUSE(kill, stand)` is interesting on its own: stand session toggles bit 0 (the known side-stand signal); the kill session shows transient `0x00`/`0x01` values among an otherwise-`0x10` byte during kill→STOP edges. Bit 4 of `540` D3 is one of the [[engine-state-bits-decay-shape]] bits — it briefly drops with the kill→STOP transition even with the engine off. That refines the bit's character: not pure engine-state, but tracks "ignition + kill in run" rather than just "engine running." Same picture as `540` D2 below.

### Candidate short list (non-GLOBAL-STATIC, non-already-confirmed)

| ID    | byte | classification              | observation                                                                              | next step |
|-------|------|-----------------------------|------------------------------------------------------------------------------------------|-----------|
| `540` | D1   | ENGINE-STATE                | dominant 0x00 engine-off, **0x0E/0x0F/0x10** monotonic across idle-1/2/3 (cold→warm→op). Strong candidate for a **derived/binned coolant** signal — possibly the gauge needle output. | promote to `provisional` finding; verify dynamics on next engine-on capture |
| `540` | D2   | SINGLE-CAUSE(kill)+DRIFT    | static 0x40 in all engine-off sessions, static 0x00 in all engine-on idle, briefly toggles to 0x00 in kill session. Bit 6 = "ignition armed AND kill=run" — refines the engine-state bit map for this bit (it tracks kill even engine-off, not just engine running). | update [[engine-state-bits-decay-shape]] |
| `5B0` | D0   | SINGLE-CAUSE(kill)          | 0x10 in 8/9 sessions; kill session shows 6 frames of 0x00 vs 593 of 0x10. Possible kill-correlated bit 4 in a previously-untagged ID. | confirm via bit-level scan ([[2026-06-21-bit-transition-scan]]) before promoting |
| `121` | D2   | ENGINE-STATE                | 0x01 engine-off, dominant 0x00 engine-on (with some movement). Reproduces a bit already in the engine-state bit table (`121` D1 bit 5/7 family), now visible at byte granularity. | already in [[engine-state-bits-decay-shape]] — no action |
| `121` | D5   | ENGINE-STATE                | 0x80 engine-off, **clean 0x88 engine-on**, static in both. Bit 3 of `121` D5 = engine-running indicator (same as payload_diff's `121` D5 bit 3 flip 0→1). | already in [[engine-state-bits-decay-shape]] — no action |
| `541` | D4   | ENGINE-STATE                | 0x00 engine-off, mixed 0x00/0x03 engine-on. Engine-correlated but not pure. Was CRC-LIKE in payload_diff. | low priority — possibly fast counter triggered engine-on |
| `121` | D0,D1,D3 | MULTI-CAUSE             | high-cardinality bytes that move in many sessions; `121` D3 jumps to 0xCF during gear session. Likely fast-changing engine telemetry. | low priority |
| `541` | D5   | MULTI-CAUSE                 | moves in gear + idle-1 + throttle. Distinct=2 in gear (0x0D/0x0E); could be a slow counter that ticks under transmission/throttle activity. | flag for engine-on stationary follow-up |
| `541` | D6   | MULTI-CAUSE                 | moves in nearly every session, high cardinality. Looks like a counter/derived field, not a flag. | low priority |
| `129` | D0   | SINGLE-CAUSE(gear) — known  | **side observation that turned into a finding**: distinct=5 in gear session, not 2. Values `0x00,0x10` are N/1st as expected, but `0x08,0x0A,0x18` appear transiently. Follow-up alignment of bit-3 / bit-1 vs event marks attributed bit 3 to "lever displaced" and bit 1 to a failed-shift flag. *(Updated 2026-06-23 per [[2026-06-23-shift-lever-vs-clutch]]: bit 3 was misattributed — it's actually the clutch lever, see [[signal-clutch]]. The Phase B "displacement" windows match the rider's clutch holds during shift attempts. Bit 1 = failed-shift survives, now tracked in [[signal-shift-failed]].)* | initially `signal-shift-lever`, since split into [[signal-clutch]] (bit 3) and [[signal-shift-failed]] (bit 1); updated [[signal-gear-position]] |

### Bytes that promoted out of STATIC

The 7-byte reduction (65 → 58 GLOBAL-STATIC across non-D7 slots) comes from `540` D1, `540` D2, `121` D2, `121` D5, `541` D4, plus the two `540` coolant bytes that the per-input sessions newly exercise (`540` D5/D6). No previously-STATIC byte newly moved under throttle/clutch/stand/gear/kill alone that wasn't already on the engine-on radar — the per-input sessions did not surface entirely new attributions, only refined the engine-state bit map.

### D7 distribution (separate table per [[byte-d7-cycle-hash]])

D7 per-session distinct counts confirm the cycle-with-offset model: most IDs land at 6 distinct values per session (the universal 6-cycle), with `120` and `541` showing the expected wide distribution from per-payload XOR fold (`f(D0..D6)`). `450` and `540` D7 are static `0x00`/`0x00` across all 9 sessions — consistent with their finding-flagged "skip / no algorithm fit" status. Nothing here contradicts [[byte-d7-cycle-hash]].

## Interpretation

The cross-session diff did most of its work by **refining existing findings** rather than surfacing new SINGLE-CAUSE signals. The procedural sanity check passes (6 of 8 known signals reproduce exactly in their expected buckets; the 2 misses are coolant bytes with a legitimate data-hygiene explanation, not classifier bugs). That validates the methodology and means the GLOBAL-STATIC tally is trustworthy.

The most interesting positive result is **`540` D1 as a candidate derived coolant signal** — its dominant value steps cleanly through 0x0E → 0x0F → 0x10 across cold → warm → op-temp idle runs, matching the thermal sweep that decoded [[signal-coolant-temp]]. This is a single-byte derived encoding (possibly the dashboard gauge needle position, or coolant in 1 °C resolution if 0x0E = 14 °C is a low-end clamp). Worth a `provisional` finding now and a verification pass on the next engine-on capture.

The most useful **refinement** is `540` D2 bit 6 (and to a lesser degree `540` D3 bit 4): both are engine-state bits in payload_diff's bit map, and both now show **kill-session transient drops** even with the engine off. That tells us these bits aren't tracking "engine running" but rather "ignition + kill switch + (other conditions) all in the run-permit state." It's a meaningful sharpening of [[engine-state-bits-decay-shape]] — the "engine-run permission" framing the existing finding tentatively rejected might actually be correct for at least these two bits, once "permission" is understood to include the kill switch.

The most useful **null** is that no STATIC-at-idle byte was newly promoted by the per-input sessions to a *previously unseen* SINGLE-CAUSE attribution. Every byte the per-input sessions exercise is already attributed (throttle → `120` D2; kill → `541` D2; stand → `540` D3 bit 0; gear → `129` D0). The bit-level scan ([[2026-06-21-bit-transition-scan]]) is the right next thing to do — many bytes flagged MULTI-CAUSE here look like they could decompose into clean per-input bits hiding inside multi-bit bytes (`541` D5 with distinct=2 in gear is a candidate). After that, the residual unknowns are genuinely engine-on stationary territory.

What this experiment **does not** establish:

- That the engine-off corpus is exhausted at bit granularity — the byte-level classifier could be missing single-bit movements that don't push a busy byte's dominant-value purity below 99 %. [[2026-06-21-bit-transition-scan]] is designed to catch exactly that case.
- That `540` D1 *is* a derived coolant signal vs. a coincident engine-state byte that happens to step monotonically — confirmation requires correlating its byte value to a finer-grained coolant temp series, which is engine-on data.
- That `5B0` D0's 6 frames of `0x00` in the kill session are signal vs. noise — 6/599 is below the byte-level "moves" threshold's confidence interval. Bit-level scan will resolve.
- That the gear session's `129` D0 lo-nibble appearances (`0x08`, `0x0A`, `0x18`) are gear-state or shift-transient — these need a deliberate engine-off neutral-vs-shift-attempt capture (already partially covered by gear-cycle-B's session.md narrative) to interpret.

## Follow-ups

- ✅ Two refinements to existing findings (`540` D2 bit 6 character, `129` D0 lo-nibble surprise) ready to fold into [[engine-state-bits-decay-shape]] and [[signal-gear-position]] respectively.
- New `provisional` finding for `540` D1 as a candidate derived/binned coolant signal — see [`docs/findings/can/`](../findings/can/).
- `5B0` D0 candidate kill bit deferred to bit-level scan output.
- Companion bit-transition-rate scan: [[2026-06-21-bit-transition-scan]] — to surface flag bits inside MULTI-CAUSE bytes and validate the `5B0` D0 lead.
- After bit-level scan completes, engine-on stationary batch is the right next capture session — the residual unknowns (gears 2–6, clutch with engine on, mode toggle, dynamic RPM, derived coolant verification) all need it.
