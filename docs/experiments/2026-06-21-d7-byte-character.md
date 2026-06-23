---
date: 2026-06-21
status: success
phase: 1
related:
  findings:
    - can/byte-d7-cycle-hash
    - can/always-on-broadcast-ids
  references:
    - ktm-can-decoder
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

# D7 byte character — reproduce the checksum algorithm, or distinguish counter from checksum on `12D`

## Hypothesis

[[byte-d7-cycle-hash]] observed that D7 on 9 of 11 always-on broadcast IDs behaves like a derived byte: its cardinality scales with the rest of the payload's cardinality, IDs with static D0..D6 cycle through exactly 6 D7 values, and IDs with active payloads explore 100+ values. The leading hypothesis is "D7 is a deterministic function of D0..D6 emitted by the ECU's broadcast scheduler" — but the specific algorithm has not been reproduced.

Two related claims will be tested simultaneously:

1. **A single algorithm fits all 9 IDs.** A CRC-8 variant, a J1939-style additive checksum, or an XOR fold is computed by the ECU over D0..D6 and placed at D7. The same algorithm (possibly with a per-ID seed or per-ID XOR constant) explains every frame on every capture. If this holds, the algorithm is reproducible from data alone.

2. **`12D` D7's six values are *not* this algorithm — they're a mod-7 sequence counter.** [[byte-d7-cycle-hash]] flagged `12D` as the outlier: bytes 0–6 are STATIC `0x00`, D7 is LOW-CARD(7) (one more value than the "6 unique values" pattern). A checksum over an all-zero payload returns one value, not seven. A mod-7 sequence counter increments once per broadcast, modulo 7, independently of payload. The two are trivially distinguishable by time-series.

These two questions sit naturally together: if (1) holds and `12D` doesn't fit, that strengthens (2); if (1) fails but `12D` *is* a clean counter, the "D7 is structural" hypothesis splits into two distinct phenomena rather than one.

## Setup

Desk-only. Corpus = every capture taken so far, to maximise polynomial-fit surface area:

- `logs/2026-06-17-key-on-cold-boot/`
- `logs/2026-06-17-engine-idle-run-{1,2,3}/`
- `logs/2026-06-19-throttle-sweep-engine-off/` — most-active `120` and `541` payloads; the discriminative capture
- `logs/2026-06-19-kill-switch-toggle/`
- `logs/2026-06-19-side-stand-toggle/`
- `logs/2026-06-19-gear-cycle-clutch-A-clutch-only/`
- `logs/2026-06-19-gear-cycle-clutch-B-gear-cycle/`

Out of scope: the bench-dryrun and the yank test (yank test recorded 0 frames per its `session.md`).

New script: `scripts/d7_algorithm.py`. Iterates polynomial × seed × reflection × init-XOR space, scores each candidate against the corpus, emits the best-scoring few per ID, plus a joint best-fit assuming a single polynomial across all 9 IDs.

Tooling note: the search space is small enough to brute-force on a laptop. ~50 CRC-8 polynomials × 256 seeds × {reflect-in, reflect-out, both, neither} × 256 final-XOR = ~13 M candidate parameterisations per ID per pass. For each parameterisation we test against ~10 K frames; that's ~10¹¹ byte-ops total which is uncomfortable but tractable. Reasonable shortcut: fix reflection & final-XOR at the most common automotive values (no reflect, final-XOR = 0x00 or 0xFF) on the first pass and only widen if nothing fits.

## Procedure

### Part A — single-polynomial fit on the 9 checksum-candidate IDs

The 9 IDs from `byte-d7-cycle-hash`: `120`, `121`, `129`, `12A`, `12D`, `12E`, `541`, `5A0`, `5B0`. (`540` and `450` are excluded from the original hypothesis because their payloads were too static to surface a D7 pattern; they get a separate pass below.)

1. Build a frame corpus: for each of these 9 IDs, collect every observed (D0..D6, D7) tuple from all capture logs. Deduplicate exact tuples — what matters is coverage of distinct payloads, not frame count.
2. Candidate polynomial list (start narrow):
   - **CRC-8 standard variants**: SAE-J1850 (0x1D), CRC-8/AUTOSAR (0x2F), CRC-8/SMBUS (0x07), CRC-8/MAXIM (0x31), CRC-8/CDMA2000 (0x9B), CRC-8/DARC (0x39), CRC-8/I-CODE (0x1D, init=0xFD).
   - **Simple XOR fold**: D7 = D0 ⊕ D1 ⊕ ... ⊕ D6 (optionally with a per-ID constant).
   - **J1939-style additive**: D7 = (sum(D0..D6) + ID_lo) mod 256, with and without final-XOR.
3. For each candidate, scan the seed (init value) space 0x00..0xFF — flat, with the same seed across all 9 IDs first ("one global parameterisation").
4. **Pass criterion (strict)**: predicted D7 matches observed D7 in ≥99 % of frames on **every one of the 9 IDs simultaneously**. If any candidate hits this bar, the algorithm is identified.
5. **Pass criterion (relaxed)**: ≥99 % on at least 7 of the 9 IDs with the same polynomial but a **per-ID** seed. The seed is then per-ID configuration; the algorithm itself is shared.
6. If neither bar is hit on the narrow list, widen: add reflect-in / reflect-out variants and a final-XOR sweep. If still nothing fits, the hypothesis fails and we record what was tried.

### Part B — `12D` D7 character

`12D`'s D7 distribution (LOW-CARD(7)) gets a dedicated time-series test independent of Part A:

1. From any single capture (use `2026-06-17-engine-idle-run-1` — long, steady), extract `12D` frames in chronological order over a 5-second window (~500 frames at 10 ms period).
2. Plot D7 vs frame index (text scatter is fine — 500 points fit in a terminal). Visual inspection distinguishes counter (sawtooth or staircase) from checksum (flat, since D0..D6 is static, except where the static value briefly drifts).
3. Quantitative test for mod-7 counter: compute `(D7[i+1] - D7[i]) mod 7`. If ≥95 % of pairs equal `1`, it is a mod-7 counter incrementing each frame.
4. Quantitative test for mod-N counter with N ≠ 7: try N ∈ {2, 3, 5, 6, 7, 8, 14, 16}. The pattern "7 unique values" could be coincidence over a finite window of a wider counter.
5. Cross-check: does the winning polynomial from Part A predict `12D` D7 correctly? If yes, `12D` is not the outlier the original hypothesis claimed — its 7 unique values just happen to be what a checksum over its nearly-static payload produces. If no, `12D` D7 is genuinely a different mechanism.

### Part C — `540` and `450` D7

The original hypothesis explicitly says "says nothing about `540` and `450`." With the wider corpus (especially the kill-switch and side-stand captures, where `540` D0..D6 moves more than at idle), there is now enough D7 variation to apply Part A's polynomial fit to these two IDs too. Run the winning polynomial (or the best near-misses) against them and record fit %.

## Expected outcomes

- **One algorithm fits 9 IDs at >99 %.** [[byte-d7-cycle-hash]] promotes to `confirmed` *with the algorithm specified* (polynomial + seed + reflection params). Phase 5 active-TX is materially unblocked: any frame the dashboard synthesises can be checksummed correctly before transmit. `byte-d7-cycle-hash` rewrites to specify the algorithm; the "Open" section largely closes.
- **Per-ID seed, shared polynomial fits ≥7 IDs.** Same promotion, with a small per-ID config table.
- **No fit on the narrow list, but a fit on the widened search.** Same promotion outcome; the experiment doc records the search depth needed (useful when future ECU variants are encountered).
- **No fit at all.** [[byte-d7-cycle-hash]] demotes to `provisional` and records what was tried. Reconsider whether D7 might be partly checksum / partly counter, partly module-state, or a manufacturer-proprietary obfuscated function. Active-TX work for Phase 5 picks up a known unknown.
- **`12D` D7 is a mod-7 counter.** Carve-out in `byte-d7-cycle-hash`: 9 IDs are checksums, `12D` is a sequence counter. Provisional new finding `signal-12d-heartbeat-counter.md` (or similar).
- **`12D` D7 obeys the same algorithm.** The original hypothesis was over-stated; `12D` is not exceptional; the "7 unique values" was a checksum-output-space artefact. Update `byte-d7-cycle-hash` to remove the carve-out.

## Result

Run with `python scripts/d7_algorithm.py`. The experiment expanded mid-execution as Part B's findings reshaped the search; the result is reported across seven labelled parts.

### Part A — single-polynomial fit on 9 IDs

Corpus after deduplication by `(D0..D6, D7)` per ID: `120`:3151, `121`:308, `129`:31, `12A`:13, `12D`:7, `12E`:13, `541`:4783, `5A0`:13, `5B0`:8. Total 8327 distinct (payload, checksum) pairs across the 9 candidate IDs.

- **A.1 — global parameterisation.** Best CRC-8 variant: **CRC-8/ROHC** at 89/8327 = 1.1 % aggregate. Top six all sit between 0.7 % and 1.1 %; per-ID hits are in single digits everywhere. XOR fold and J1939 sum perform worse (≤0.8 %).
- **A.2 — per-ID seed search.** Searching `init` ∈ 0..255 per-ID for each top polynomial does not move the needle. Best per-ID-seed: CRC-8/ROHC at 110/8327 = 1.3 %.
- **A.3 — CAN ID low byte prepended/appended (AUTOSAR E2E Profile 5 style).** Worse than no-ID at 0.6 % aggregate.

**Original hypothesis refuted as stated.** D7 is not a CRC-8 (or J1939 sum, or XOR fold) over D0..D6 alone, with or without an ID byte, with or without per-ID seeds. The 1.1 % hit rate is consistent with random coincidence at 1/256.

### Part B — `12D` D7 character

10 s window of idle-run-1, `12D` frames = 1000. **D0..D6 is constant `00 00 00 00 00 00 00` for all 1000 frames.** Yet D7 cycles through six distinct values in a strict repeating sequence:

```
0x35 → 0x5F → 0x6A → 0x8B → 0xBE → 0xD4 → 0x35 → 0x5F → 0x6A → 0x8B → 0xBE → 0xD4 → …
```

- **A checksum over D0..D6 alone would produce one value, not six.** Refutes the "CRC over D0..D6" hypothesis fundamentally.
- **A mod-N sequence counter would produce monotonic increments.** Mod-2 fit at 66.7 % (the 2-toggle pattern of the cycle); higher N all sit at 30 – 50 %. None is a counter.

D7 is computed from D0..D6 *plus* a hidden state that itself cycles with period 6.

### Part C — `540` and `450`

In the 5 s idle-run-1 window: `540` D7 was static `0x00` (single distinct payload `00 11 00 00 00 01 48`); `450` D7 was also static `0x00`. The original `byte-d7-cycle-hash` explicitly excluded these two on payload-sparsity grounds; the wider corpus did not surface them either. Both IDs need a capture with more payload movement to test D7 structure.

### Part D — 6-cycle is universal

Per-ID 5 s windows from idle-run-1, restricted to each ID's dominant payload to isolate the cycle:

| ID    | distinct D7s | period | cycle (in order observed)                                  |
|-------|-------------:|-------:|------------------------------------------------------------|
| `129` |       6      |   6    | `0xBA, 0xD0, 0x31, 0x5B, 0x6E, 0x8F`                       |
| `12A` |       6      |   6    | `0xB6, 0xDC, 0x3D, 0x57, 0x62, 0x83`                       |
| `12D` |       6      |   6    | `0x35, 0x5F, 0x6A, 0x8B, 0xBE, 0xD4`                       |
| `12E` |       6      |   6    | `0x71, 0x90, 0xA5, 0xCF, 0x2E, 0x44`                       |
| `541` |       6      |   6    | `0x4A, 0x7F, 0x9E, 0xAB, 0xC1, 0x20`                       |
| `5A0` |       6      |   6    | `0xB0, 0xDA, 0x3B, 0x51, 0x64, 0x85`                       |
| `5B0` |       6      |   6    | `0xD5, 0x34, 0x5E, 0x6B, 0x8A, 0xBF`                       |
| `121` |       6      |  n/a   | `0x3D, 0x57, 0x62, 0x83, 0xB6, 0xDC` (dominant payload only) |
| `120` |       4      |  n/a   | window too noisy — 154 distinct payloads in 250 frames     |

Eight of nine D7-checksum-candidate IDs show a clean period-6 cycle on a constant payload. `120` would too if the window were chosen with a constant throttle value (deferred to a follow-up; the throttle sweep does this naturally but in a different shape).

### Part F — universal cycle XOR per-ID constant

Every ID's 6-value cycle, sorted, equals `12D`'s reference cycle sorted, XOR a single per-ID constant:

| ID    | offset vs `12D` | sorted cycle                                       |
|-------|---------------:|-----------------------------------------------------|
| `12D` |     0x00       | `0x35, 0x5F, 0x6A, 0x8B, 0xBE, 0xD4`               |
| `5B0` |     0x01       | `0x34, 0x5E, 0x6B, 0x8A, 0xBF, 0xD5`               |
| `129` |     0x04       | `0x31, 0x5B, 0x6E, 0x8F, 0xBA, 0xD0`               |
| `12A` |     0x08       | `0x3D, 0x57, 0x62, 0x83, 0xB6, 0xDC`               |
| `121` |     0x08       | `0x3D, 0x57, 0x62, 0x83, 0xB6, 0xDC`               |
| `5A0` |     0x0E       | `0x3B, 0x51, 0x64, 0x85, 0xB0, 0xDA`               |
| `541` |     0x15       | `0x20, 0x4A, 0x7F, 0x9E, 0xAB, 0xC1`               |
| `12E` |     0x1B       | `0x2E, 0x44, 0x71, 0x90, 0xA5, 0xCF`               |

**The cycle base is universal across IDs.** Per-ID variation reduces to an 8-bit XOR offset.

`121` and `12A` share offset `0x08` — could be coincidence (≈13 % birthday-paradox probability across 9 IDs and 256 offsets, so one collision is plausible) or could indicate the offset depends on the dominant payload rather than purely the ID. Worth a future check on `121`'s non-dominant payloads.

The reference cycle's pairwise-XOR closure is `{0x35, 0x5F, 0x6A, 0x8B, 0xBE, 0xD4, 0xE1}` — exactly the 7 nonzero values in the XOR-vector space spanned by `{a=0x35, b=0x6A, c=0xE1}`. The cycle visits 6 of those 7 vertices, skipping `0xE1` (one of the basis vectors). This is the structure of a 3-bit Gray code over the {a, b, c} basis with one position omitted — strong evidence that D7 is generated by a small linear feedback over a 3-bit state register, not a generic CRC-8 over arbitrary bytes.

### Parts E and G — exhaustive CRC-8 search

- **Part E.** Standard-variant CRC-8 (15 named variants) × init 0..255 × counter byte at any of 9 positions, with D0..D6 = 0, searching for the parameterisation that emits exactly `{0x35, 0x5F, 0x6A, 0x8B, 0xBE, 0xD4}` for counter ∈ 0..5. **No match.**
- **Part G.** Exhaustive: every polynomial 0x01..0xFF × init 0..255 × every reflection setting × every counter placement. **No match.**

The algorithm is **not** a standard CRC-8 over (counter, D0..D6). It has at least one additional hidden input — a DataID, a per-ID seed/secret, an internal LFSR state, or something the bus does not directly expose.

### Part H — `120` cycle close-out

Pulled `120` from the cold-boot engine-off window (174 s key-on-no-engine, D0..D6 = `00 00 00 00 00 00 00` throughout). 1501 frames in a 30 s sub-window. D7 cycles through `{0x35, 0x5F, 0x6A, 0x8B, 0xBE, 0xD4}` with period 6 — **identical to `12D`'s reference cycle**. Per-ID offset = `0x00`. Closes the 9th row in the universal-cycle table.

Two of nine IDs now share offset `0x00`: `12D` and `120`. Plus the earlier `121`/`12A` pair at `0x08`. Two collisions in 9 IDs × 256 offsets = ~1% Poisson probability — unlikely but possible. Briefly motivates a "no per-ID secret" hypothesis: maybe the offset is just `f(D0..D6)` and the matching reduces to "both IDs happened to have all-zero payloads in their cycle windows."

### Part I — `f(D0..D6)` as a payload-only function: search

Tested every standard CRC-8 variant against the observation set `{(ID's dominant payload, observed offset)}` for all 9 IDs.

- **I.1** — 15 named CRC-8 variants. Best: CRC-8/DARC at **3/9 matches**. The 3 are `120`, `129`, `12D` — and `120`/`12D` are trivial because both have all-zero payloads and CRC of all-zero is 0 for any init=0 variant. So really 1/9 non-trivial.
- **I.2** — exhaustive over all 255 polynomials × 256 inits × every reflection setting. **No 9/9 fit. No 8/9 fit either.** Best: 3/9.

The payload-only CRC-8 hypothesis is refuted. Whatever `f` is, it is not a CRC-8 over D0..D6 alone.

### Part J — extended payload search and direct table-constraint solve

- **J.1** — same CRC-8 search with **reversed byte order** (right-to-left processing). Same 3/9 best.
- **J.2** — exhaustive reversed-order over all polynomials. **No 9/9 fit.**
- **J.3** — direct table-constraint solve. Four of the IDs have exactly one non-zero byte in their dominant payload:

  | ID    | byte position | byte value | observed offset |
  |-------|--------------:|-----------:|----------------:|
  | `12E` |   6           |  `0xC0`    |    `0x1B`       |
  | `5A0` |   4           |  `0x04`    |    `0x0E`       |
  | `129` |   3           |  `0x01`    |    `0x04`       |
  | `5B0` |   0           |  `0x10`    |    `0x01`       |

  These give exact constraints on a CRC-8 table T: `T¹[0xC0] = 0x1B`, `T³[0x04] = 0x0E`, `T⁴[0x01] = 0x04`, `T⁷[0x10] = 0x01` (forward order, init=0). Search across all 255 polynomials, both reflection settings, both byte orders: **no polynomial satisfies even 3 of 4 constraints.**

This is the cleanest refutation of "`f` is a CRC-8 over D0..D6" we can produce. The function compressing payload into byte 7 is fundamentally not a CRC-8 on D0..D6 alone — it either uses a hidden per-ID input, or it is not a CRC at all (Pearson hash, custom permutation table, etc.).

## Interpretation

D7's algorithmic structure is much richer and more constrained than `byte-d7-cycle-hash` originally claimed:

1. **D7 is not a CRC over D0..D6 alone.** Refuted at every standard-variant level and at the per-ID seed level. The aggregate hit rate of 1.1 % is random-coincidence noise.

2. **D7 has a per-frame counter input that cycles modulo 6.** Confirmed by Part B (1000 frames of constant payload → 6 cycle values, strict period 6) and Part D (universal across all 8 testable IDs).

3. **Per-ID variation is a single 8-bit XOR offset to a universal reference cycle.** Confirmed by Part F. This dramatically simplifies the model: instead of "9 unrelated checksum functions," it's "one function plus 9 offsets."

4. **The reference cycle has linear (Gray-code-like) structure** over a 3-bit XOR basis `{0x35, 0x6A, 0xE1}`, suggesting a small LFSR or table generator — not an 8-bit CRC.

5. **The exact algorithm has a hidden input.** Parts E and G eliminate every standard CRC-8 over (counter, D0..D6) as the source. The remaining candidates are: (a) CRC-like over (DataID_16bit, counter, payload) where DataID is per-ID and pre-shared — AUTOSAR E2E Profile 5 lookalike; (b) a manufacturer-proprietary table generator that we can't infer from D7 alone; (c) an LFSR over a per-ID seed that produces the 6-cycle.

For Phase 5 active TX, the implications are mixed:

- **Replay-style TX is feasible.** If the dashboard wants to send a frame with a payload it has already observed on the bus, it can pin D7 by listening to the cycle: any of the 6 observed values is valid at the matching counter position. Steady-state cycle lock-in takes ≤60 ms (six 10 ms frames).
- **Novel-payload TX is blocked.** Without the algorithm, the dashboard cannot synthesise a valid D7 for a payload the ECU hasn't broadcast itself. Phase 5 active features (mode toggle, trip reset, etc.) probably need either reverse-engineering the algorithm in detail or relying on payloads we can observe the ECU emit.

The "6 unique values on static-payload IDs" + "100+ on active-payload IDs" observation from the original `byte-d7-cycle-hash` is fully explained: 6 = the cycle period; 100+ = (counter × payload_state) combinations, where the payload-derived component compresses into the same 8-bit output space via the same CRC-like function.

## Follow-ups

- [x] Rewrite [`docs/findings/can/byte-d7-cycle-hash.md`](../findings/can/byte-d7-cycle-hash.md) — promote from "observation only" to a fully structural finding: 6-cycle period, universal base, per-ID XOR offsets cataloged, exact algorithm open.
- [x] **`120` cycle close-out** (Part H). All-zero payload in cold-boot engine-off window confirms offset `0x00`. Cataloged.
- [ ] **Counter-phase alignment across IDs.** All 8 captured cycles start at different positions because the captures begin at arbitrary times. A simultaneous-capture analysis (any one capture, all IDs read in lockstep) of `(timestamp mod 60 ms, ID, D7_position)` would tell us whether the per-ID counters share a global phase (one master counter source) or run independently (each module has its own).
- [ ] **Per-payload offset characterisation.** Now with TWO collisions (`120`/`12D` at `0x00` *and* `121`/`12A` at `0x08`), the question sharpens: compute `121`'s offset across each of its 9 distinct payloads. If the offset varies with payload, it's payload-derived. If it stays at `0x08`, it's per-ID. Cheap desk follow-up — but Parts I/J already refuted the simplest payload-only model, so a structural per-payload finding would require a non-CRC hash function.
- [ ] **DataID search.** Try CRC-8/AUTOSAR with a 16-bit DataID prepended, searching DataID ∈ 0..65535 per ID, looking for one that reproduces the cycle. ~16 M configs per ID, tractable but a separate desk session.
- [ ] **Active-TX implications for Phase 5.** A short note in [[byte-d7-cycle-hash]] explaining that until the algorithm is reproduced, only replay-style TX of previously-observed payloads is viable. Mode toggle and trip reset will probably need either external information about the algorithm or a clever observation that the OEM dash's TX cycle is itself observable on the bus (which would let the dashboard replay those bytes verbatim).
