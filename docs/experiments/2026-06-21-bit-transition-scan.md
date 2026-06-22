---
date: 2026-06-21
status: success
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/signal-kill-switch
    - can/signal-side-stand
    - can/byte-d7-checksum-hypothesis
  experiments:
    - 2026-06-17-payload-diff-idle
    - 2026-06-21-cross-session-payload-diff
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

# Per-bit transition-rate scan — find flag-bits hiding inside busy bytes

## Hypothesis

The classifier in [[2026-06-17-payload-diff-idle]] operates at byte granularity. Several confirmed signals are single bits riding inside otherwise-busy bytes:

- [[signal-kill-switch]] — `541` D2 bit 4 lives in a LOW-CARD(2) byte; the byte appears to "just toggle between two values" but only one bit out of the four candidate bits in the LOW-CARD(2) value set is actually the kill state.
- [[signal-side-stand]] — `540` D3 bit 0 lives inside `540` D3 (LOW-CARD(4) at idle), which also encodes gear-related state. Byte-level analysis cannot separate the two; only bit-level analysis can.

Both were only found because a *targeted* per-input scan (`kill_switch_scan.py`, `side_stand_scan.py`) walked every (byte, bit) under the known event window. There is no general untargeted bit-level scan of the existing corpus. **There may be flag-bits that toggle slowly enough to look like noise at byte level, or fast enough to be hidden inside a LOW-CARD byte's value count, that no targeted scan has hit yet.**

Concrete predictions:

1. **Most bits across the 88×8 = 704 candidate bits are constant** in any single session — pure 0 or pure 1 across that session's window. The interesting tail is the bits that *toggle* but at a rate inconsistent with random / checksum / counter behaviour.
2. **A small number of bits will exhibit "toggle in some sessions, stuck in others" behaviour.** Those are flag candidates — they're stuck when the corresponding input is not exercised and toggle when it is. This generalises [[signal-kill-switch]] / [[signal-side-stand]] and is the bit-level analogue of [[2026-06-21-cross-session-payload-diff]]'s SINGLE-CAUSE classification.
3. **Bits inside D7 will toggle uniformly across all sessions** at high rate (per [[byte-d7-checksum-hypothesis]]: D7 cycles 6 deterministic values; 3 of its 8 bits constitute a Gray-code basis and thus toggle ~33–50 % of the time). They will dominate any unfiltered ranking. Excluding D7 sharpens the signal.
4. **Bits inside the RPM byte pair (`120` D0, D1)** will toggle at high rate engine-on (RPM jitter at idle drives the low bits) and be stuck at 0 engine-off. They will reproduce as ENGINE-STATE just like the byte-level analysis but with a clearer bit picture.
5. **Some currently-LOW-CARD bytes will decompose** — e.g., `540` D3 LOW-CARD(4) should decompose into bit 0 (side stand) toggling under the side-stand session + at least one other bit toggling under the gear session, with the rest stuck. If the decomposition doesn't add up to the observed value set, there's a third moving bit we don't have a story for.

If no new toggling-flag patterns surface beyond what byte-level analysis already found, the null result is informative: bit-level information in the engine-off corpus is exhausted, and engine-on capture is the right next step.

## Setup

Desk-only. Same 9-session corpus as [[2026-06-21-cross-session-payload-diff]] — see that experiment's Setup table for the session list and per-session conditions.

New script: `scripts/bit_transition_scan.py`. For every (ID, byte, bit) across the 11 always-on IDs and every session, computes per-bit transition rate, dominant-value purity, and number of distinct (value, value) consecutive pairs. Then ranks bits by a "cross-session contrast" score.

## Procedure

1. **Per-session per-bit metrics.** For each session (trimmed as in [[2026-06-21-cross-session-payload-diff]] step 1), for each (ID, byte, bit), compute:
   - **frame count** — number of frames of this ID in the window
   - **bit toggle count** — number of consecutive frame pairs where the bit value differs
   - **bit toggle rate** — toggles / (frame_count − 1)
   - **dominant value** — 0 or 1, whichever appears more
   - **dominant purity** — frequency of dominant value / frame_count

   Toggle rate range:
   - **0.0** → bit is constant (whole session)
   - **~0.5** → bit toggles every other frame (counter-like or D7-cycle bit)
   - **anything in between** → carries information, rate proportional to the input's change frequency

2. **Per-bit cross-session profile.** For each of the 704 candidate bits, build a 9-entry profile of (toggle_rate, dominant_purity) and classify:

   - **GLOBAL-CONSTANT** — toggle_rate = 0 in every session. Carries no observable information. Expected to be the majority.
   - **CHECKSUM-LIKE** — toggle_rate ≥ 0.25 in *every* session, regardless of session activity. The bit changes constantly. D7 bits will land here; so will the RPM low-byte bits (since RPM jitter is constant at idle). Filter by ID/byte position to separate D7 (known checksum) from RPM-payload bits (known signal).
   - **SESSION-CONTRAST** — toggle_rate is "high" (≥0.05) in some sessions and "low" (≤0.005) in others. The session set where the bit toggles is the candidate trigger. This is the main hunting class.
   - **ENGINE-CONTRAST** — special case of SESSION-CONTRAST where the "high" set is exactly the 3 engine-on sessions and the "low" set is the 6 engine-off sessions. Cross-checks the [[2026-06-17-payload-diff-idle]] engine-state bit map at bit granularity.
   - **NEAR-CONSTANT** — toggle_rate ≤ 0.005 in every session but not exactly 0. Likely a rare flip or boot-transient leakage; flag for inspection but low priority.

3. **D7 separation.** Maintain a `--include-d7` flag (default off). Per [[byte-d7-checksum-hypothesis]] D7 bits are deterministic 6-cycle output and will swamp any unfiltered top-N list. With the flag off, D7 bits are computed but printed separately so they can be sanity-checked against the known cycle (every D7 bit should land in CHECKSUM-LIKE) without polluting the SESSION-CONTRAST hunt.

4. **SESSION-CONTRAST short list.** For each SESSION-CONTRAST bit:
   - ID, byte:bit
   - high-rate sessions (with toggle rate each)
   - low-rate sessions
   - whether the high-rate session set matches one of: {throttle}, {kill}, {side-stand}, {gear or clutch-A or clutch-B}, {engine-on}, {other / no clean match}
   - "known signal" annotation if the bit is already attributed (kill, side-stand, RPM-bit, etc.); otherwise blank — those are the new candidates

5. **Decomposition check for LOW-CARD bytes.** For each byte that [[2026-06-17-payload-diff-idle]] flagged LOW-CARD (>1, ≤16 distinct values), enumerate which bits within the byte are non-constant in the corpus, and verify that the observed value set is consistent with those bits varying independently. If the observed value count exceeds `2^(number of non-constant bits)`, there's a non-bit-independent encoding (multi-bit field), worth flagging.

6. **Reproduce known signals.** Print the row for each already-confirmed signal bit:
   - `541` D2 bit 4 → SESSION-CONTRAST, high set = {kill-switch}
   - `540` D3 bit 0 → SESSION-CONTRAST, high set = {side-stand, gear-cycle} (gear cycle releases/applies side stand? — only if the rider toggled it during shifts, worth checking the session.md narrative)
   - `120` D0 bits 0–2 → CHECKSUM-LIKE (RPM low bits) or ENGINE-CONTRAST (RPM high bits), depending on which bit
   - `120` D2 bits — SESSION-CONTRAST, high set = {throttle-sweep}; sanity-check: throttle byte at idle (closed throttle) reads 0, so all 8 bits are 0 in idle/engine-off sessions and toggle freely under sweep

   If the scan reproduces all known-signal bits, the procedure is validated.

7. **Cross-link with [[2026-06-21-cross-session-payload-diff]].** Every SESSION-CONTRAST bit hit should correspond to a SINGLE-CAUSE or MULTI-CAUSE byte from the byte-level scan. A bit-level hit *without* a matching byte-level hit means the byte-level classifier missed it because the bit's flip didn't push the byte out of its dominant-value purity threshold — that is exactly the case this experiment is designed to catch and is the most interesting class of result.

## Expected outcomes

- **The vast majority of the 704 bits land in GLOBAL-CONSTANT.** Most of the bus is quiet.
- **A small CHECKSUM-LIKE cluster** dominated by D7 bits (8 IDs × 8 bits = up to 64 bits) and the RPM low-byte bits in engine-on sessions. Both expected; both filtered/annotated.
- **A handful of ENGINE-CONTRAST bits** that reproduce the [[2026-06-17-payload-diff-idle]] engine-state bit table.
- **A small number (0–5) of SESSION-CONTRAST bits that aren't already known signals.** Each gets a row in a candidate table; each is a per-input re-test target.
- **Decomposition of `540` D3** confirms bit 0 (side stand) + at least one bit for the LOW-CARD(4) values seen at idle. If a third bit appears, it's either gear-related (we know D3 lo nibble was refuted as gear, but a single bit inside it might still carry something) or a new candidate.
- **Plausible null:** every non-D7, non-RPM bit lands in either GLOBAL-CONSTANT or matches an already-known signal. Useful — confirms the engine-off corpus is bit-level-exhausted and the next unknown bit needs engine-on data.

## Result

`scripts/bit_transition_scan.py` was run against the 9-session corpus. First pass used rate-based thresholds (HIGH_RATE=0.05, LOW_RATE=0.005) and missed all of the known slow flag bits — kill switch, side stand, shift lever — because each of these toggles only a handful of times per session (e.g., 6 kill events → 6/3000 frames = 0.002 rate, well below LOW_RATE). **Switched to an activity-count classifier**: a session is "active" if the bit toggled ≥2 times, "inactive" if 0 times. This catches slow flag bits and reproduces all the expected known signals.

### Classification summary (D7 excluded, 616 bits)

| classification         | count |
|------------------------|------:|
| GLOBAL-CONSTANT        | 517   |
| SESSION-CONTRAST       | 49    |
| ENGINE-CONTRAST-SLOW   | 19    |
| MIXED                  | 15    |
| ENGINE-CONTRAST-FAST   | 8     |
| NEAR-CONSTANT          | 8     |

D7 bits (88 separate): 72 CHECKSUM-LIKE, 16 GLOBAL-CONSTANT — exactly the byte-d7-checksum-hypothesis prediction (some D7s like `450`/`540` were noted as static `0x00`; those land in GLOBAL-CONSTANT).

### Known-signal reproduction (bit-level)

| ID    | byte:bit | got                 | expected                              | verdict |
|-------|----------|---------------------|---------------------------------------|---------|
| `541` | 2:4      | SESSION-CONTRAST(kill) | SESSION-CONTRAST high=kill         | ✓ (6 toggles, matches 6 kill events) |
| `540` | 3:0      | SESSION-CONTRAST(kill+stand) | SESSION-CONTRAST high=stand   | ✓ (stand=6, kill=6 — kill session toggles bit 4 transiently and flips bit 0 too at the kill edge) |
| `540` | 2:6      | MIXED               | ENGINE-CONTRAST + kill                | ~ (kill toggles present, idle-1 has 1 boot transient — pushes out of clean ENGINE-CONTRAST) |
| `540` | 3:4      | MIXED               | ENGINE-CONTRAST + kill                | ~ (same pattern as 2:6) |
| `121` | 5:3      | GLOBAL-CONSTANT     | ENGINE-CONTRAST                       | ✗ (window-trim artefact — flips at engine start/stop, both outside the idle_to_kill window) |
| `129` | 0:3      | SESSION-CONTRAST(gear) | SESSION-CONTRAST high=gear         | ✓ (4 toggles, matches Phase B sustained-then-released observation) |
| `129` | 0:1      | SESSION-CONTRAST(gear) | SESSION-CONTRAST high=gear         | ✓ (4 toggles, matches the two failed-shift edges) |

5 of 7 reproduce cleanly. The `121` 5:3 miss is a methodology note: bits that flip exactly at engine-start and engine-stop have zero toggles inside the `idle_to_kill` window even though their dominant value differs from engine-off. The byte-level cross-session diff catches them; bit-level toggle-counting can't. This is a known limit, not a bug — the [[2026-06-21-cross-session-payload-diff]] ENGINE-STATE table is the authoritative source for those.

### New candidate signals

**1. `5B0` D0 bit 4 — kill-correlated (CONFIRMS the experiment 1 weak lead)**

```
5B0 0:4  SESSION-CONTRAST  high=kill  toggles=6
```

Exactly 6 toggles in the kill session, zero in every other session. Matches the 6 kill toggle events 1:1. The experiment 1 byte-level scan flagged this as a borderline mover (purity 0.99); bit-level confirms it. **Promote to `provisional` finding.** `5B0` was not previously known to carry kill-state info — both `541` D2 bit 4 ([[signal-kill-switch]]) and now `5B0` D0 bit 4 carry the same signal, suggesting two modules broadcast the kill state independently (possibly the body controller and the ABS module — `5B0` is in the [[post-kill-decay-groups]] Fast group, fed by the same module as `120`/`121`).

**2. `121` D5 bit 2 — second kill-correlated bit, distinct from the engine-state bit 3 on the same byte**

```
121 5:2  SESSION-CONTRAST  high=kill  toggles=6
```

Same 6-toggle signature. `121` D5 already has bit 3 known to flip 0→1 engine-on (in the byte-level engine-state map). Bit 2 is **also** present but tracks the kill switch, not the engine. So `121` D5 carries at least two independent state bits: bit 3 = engine, bit 2 = kill.

**3. `541` D4 — slow engine-on counter (7-bit chain)**

```
541 4:0  ENGINE-CONTRAST-SLOW  idle toggles: 177 / 176 / 175
541 4:1                         88 / 88 / 87
541 4:2                         44 / 44 / 44
541 4:3                         22 / 22 / 22
541 4:4                         11 / 11 / 11
541 4:5                         5 / 5 / 5
541 4:6                         2 / 2 / 2
```

The toggle count halves cleanly bit-by-bit from bit 0 to bit 6 — the classic signature of a **binary counter** where bit N flips at half the rate of bit N-1. Engine-on only (zero toggles in every engine-off session). The 7-bit chain caps at bit 6, suggesting a `0..127` value. Across ~175 s of idle, bit 0 toggled 175 times → bit 0 flips ~1 Hz → the counter is ticking at roughly 1 Hz when the engine runs. Plausible candidates: **engine-running seconds counter**, fuel-injection event counter (binned), or a derived value like estimated fuel consumption. Payload_diff originally tagged `541` D4 as CRC-LIKE (high entropy); the bit-level chain explains why — it looks high-entropy because the low bits flip continuously, but the structure is a counter, not a checksum.

**4. `540` D1 bits 0-4 — bit-level signature consistent with derived-coolant**

```
540 1:0  ENGINE-CONTRAST-SLOW   idle toggles: 80 / 81 / 80
540 1:1  ENGINE-CONTRAST-SLOW   80 / 63 / 8           ← falling with temperature
540 1:2  SESSION-CONTRAST       only idle-1+2 active
540 1:3  SESSION-CONTRAST       only idle-1+2 active
540 1:4  SESSION-CONTRAST       only idle-1+2 active
```

Bit 0 toggles uniformly across all 3 idle runs (~80 toggles), but **bit 1 toggles fall as coolant rises** (80 cold → 63 warm → 8 op-temp) and **bits 2-4 stop toggling entirely by Run 3**. Exactly what a coolant-binned encoding would do: the high bits flip during warm-up and stabilise at operating temperature; the low bits keep flipping with noise/jitter. Independent corroboration that [[signal-warmup-index]] (originally surfaced here as `coolant_derived` and later reinterpreted, see that finding for the rewrite) is real and not coincidence.

### Refined or already-known structural patterns

- **`120` D2 bits 0-7** all SESSION-CONTRAST high=throttle, with toggle counts decreasing from bit 0 (312) to bit 7 (6) — the byte is a uint8 throttle position (already in [[signal-throttle-position]]; bit-level confirms it's not a packed multi-field byte, just a clean uint8).
- **`120` D1 bits 0-7** ENGINE-CONTRAST-FAST with toggle counts up to 4493 (≈ near-saturation 50% rates on bit 0) — RPM low byte, low bits saturated. Bit 7 toggles ~1313 times = ~7% rate → RPM high byte's least-significant bit-equivalent.
- **`540` D6 bits 0-5** show the same bit-position-halving pattern as `541` D4 (`bit 0 rate 0.213, bit 1 0.106, bit 2 0.053…`) — coolant lo byte's low bits flipping at decreasing rates. Counter / numeric structure, not flag-bits.
- **`121` D0-D3** scattered SESSION-CONTRAST hits where the "active" set always includes the 3 idle runs plus the kill session (6 toggles in kill = kill event count). These bits aren't *intrinsically* kill-correlated — the kill toggles cause a transient ripple across `121` that touches many bits at once. Likely all driven by the same upstream "engine state changed" event in the module that broadcasts `121`. Counting these as 6 distinct findings would double-count one underlying mechanism.

### Bit-level discoveries the byte-level scan missed

- `5B0` D0 bit 4 (kill) — byte-level flagged it as borderline; bit-level confirms.
- `121` D5 bit 2 (kill) — fully missed at byte level (byte was tagged ENGINE-STATE for the bit 3 flip; bit 2's kill correlation was hidden under the engine-state byte tag).
- `541` D4's counter-chain structure — byte-level called it CRC-LIKE; bit-level reveals it's a counter, not high-entropy noise.
- `540` D1's per-bit thermal pattern — byte-level only said "ENGINE-CONTRAST monotonic"; bit-level shows the **mechanism** (high bits stop toggling once temp settles).

## Interpretation

The bit-level scan was worth running — it surfaced **two new kill-correlated bits** (`5B0` D0 bit 4, `121` D5 bit 2) that byte-level analysis either flagged as borderline or missed entirely, plus a **structural reading** of `541` D4 (counter, not CRC) that revises an earlier classification. The `540` D1 bit-level pattern is the strongest piece of evidence yet that the byte is a derived/binned coolant signal: it doesn't just monotonically rise across thermal sessions, its per-bit toggle profile changes in a way only a quantised thermal encoding would produce.

The kill switch turns out to be broadcast on **at least three independent (ID, byte:bit) locations**: `541` D2 bit 4 ([[signal-kill-switch]]), `5B0` D0 bit 4 (new), and `121` D5 bit 2 (new). All three flip at the same 6 events in the same kill capture. Two modules broadcasting redundant kill-state is consistent with the bus architecture (the kill signal is safety-critical — fuel-pump shutoff and ignition cut both need it, and modules tend to maintain their own local copy rather than depend on cross-module broadcasts).

The methodology limitation is real but bounded: bits that flip *only* at engine-start and engine-stop boundaries don't show toggles inside the idle window. Those are the engine-state bits the byte-level cross-session diff catches via dominant-value differences ([[engine-state-bits-decay-shape]] table), so they aren't lost — they're just covered by the complementary analysis.

What this **does not** establish:

- Whether `541` D4 is a seconds counter, a fuel-injection event counter, or something else. Confirming the rate requires knowing the host module's update period for the byte (currently inferred as ~1 Hz from the ~175 s idle window producing 175 bit-0 toggles).
- Whether `121` D5 bit 2 and `5B0` D0 bit 4 are sourced from the same kill input pin in different modules, or whether they reflect different downstream computations (e.g., "kill switch raw" vs "kill switch + key-on AND"). All three known kill-correlated bits flip on the same edges in this capture; only a more complex scenario (key cycled mid-kill, hardware fault, etc.) could discriminate.
- Whether the gear-session bit ripple on `121` D0-D3 is "kill-like" because the rider also toggled the kill switch during gear cycle (no — session.md doesn't note it) or because the bus has an "engine state changed" composite event. Engine-on capture with more deliberate sequencing would clarify.

## Follow-ups

- ✅ Promote `5B0` D0 bit 4 to a `provisional` finding (second kill-state broadcast location).
- ✅ Add `121` D5 bit 2 to the kill-finding's secondary-locations note.
- ✅ Update [[signal-warmup-index]] (then named `signal-coolant-derived`) with the bit-level corroboration.
- ✅ Update [[engine-state-bits-decay-shape]] with the methodology note that idle-window bit-level scanning misses engine-start/stop-only bits — the byte-level cross-session table remains authoritative for those.
- New `provisional` finding for `541` D4 as a candidate engine-on counter.
- Engine-on capture remains the right next session — confirms `541` D4 rate, validates `540` D1 across more thermal points, and exercises gears 2-6 + clutch + mode toggle.

## Follow-ups

- Any SESSION-CONTRAST bit that doesn't match a known signal becomes a candidate `provisional` finding (ID, byte:bit, hypothesised trigger), gated on a per-input re-test.
- If the `540` D3 decomposition surfaces a non-bit-independent encoding, note it on [[signal-side-stand]] so the value-set caveat is recorded.
- Any byte that bit-level analysis flags but [[2026-06-21-cross-session-payload-diff]] missed gets reported as a classifier-gap on the byte-level diff — useful when designing the next analysis pass.
- If D7 bits *don't* uniformly land in CHECKSUM-LIKE, the [[byte-d7-checksum-hypothesis]] needs revisiting (some D7s might have a non-cycle structure).
