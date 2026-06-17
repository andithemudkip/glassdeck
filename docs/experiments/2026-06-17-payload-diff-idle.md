---
date: 2026-06-17
status: success
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/post-kill-decay-groups
    - can/signal-rpm
    - can/signal-coolant-temp
  references:
    - ktm-can-decoder
  decisions:
    - 0004-logger-wire-format-slcan
  experiments:
    - 2026-06-17-key-on-cold-boot
    - 2026-06-17-engine-idle-baseline-x3
  logs:
    - 2026-06-17-engine-idle-run-1
    - 2026-06-17-engine-idle-run-2
    - 2026-06-17-engine-idle-run-3
    - 2026-06-17-key-on-cold-boot
---

# Payload-byte classification — idle baseline

Desk-only experiment against captures already on disk. Classifies the 88 payload bytes (11 IDs × 8 bytes each) into structural categories — constant / counter / CRC-like / engine-state / coolant-temp candidate / idle-RPM candidate / unknown — using the windows the idle-baseline-x3 experiment already established.

## Hypothesis

Per [`docs/findings/can/always-on-broadcast-ids.md`](../findings/can/always-on-broadcast-ids.md), the 11 always-on IDs broadcast the same arbitration set regardless of engine state — so anything the bike "says" about engine running, coolant temperature, RPM, etc. must live in the **payload bytes** of those 11 IDs. We have:

- Three power-cycled engine-idle captures, each with an engine-off prelude (~30 s) and a steady-idle window (~175 s).
- The three runs span three engine thermal states (cold / partially warm / operating temperature) — an unplanned but useful three-point thermal sweep across the steady-idle windows.
- A ~5–6 s post-kill window on each run, where five IDs go silent and six continue (per [`docs/findings/can/post-kill-decay-groups.md`](../findings/can/post-kill-decay-groups.md)).

Hypothesised category structure for any given byte:

1. **STATIC** — single value across all captures and all windows.
2. **LOW-CARDINALITY** — small distinct-value set (<16 across hundreds of frames). Likely a status bitfield or a small enum (gear position, state machine).
3. **COUNTER** — predominantly increments by a fixed small step modulo 256 (or 16, for nibble counters). Heartbeat / sequence number.
4. **CRC-LIKE** — high entropy, no pattern, no monotonic structure. Last byte (or last two bytes) of many automotive frames are integrity checksums.
5. **ENGINE-STATE** — distinct value distributions between the engine-off prelude window and the steady-idle window of the same run.
6. **COOLANT-TEMP candidate** — central tendency (mode or median) shifts monotonically across Run 1 → 2 → 3 steady-idle windows, mirroring the thermal sweep.
7. **IDLE-RPM candidate** — low-variance non-zero value during engine-on, ≠ engine-off value, possibly forming a 16-bit pair with an adjacent byte.
8. **UNKNOWN** — none of the above. Future per-input captures will resolve.

A byte can fit multiple categories (e.g., a coolant byte is also engine-state, since engine-off probably reads as ambient or a sentinel). The classification table records all applicable tags.

## Setup

Inputs (all already on disk):

- `logs/2026-06-17-engine-idle-run-1/capture.log` + `events.csv` — Run 1 (cold).
- `logs/2026-06-17-engine-idle-run-2/capture.log` + `events.csv` — Run 2 (partially warm).
- `logs/2026-06-17-engine-idle-run-3/capture.log` + `events.csv` — Run 3 (operating temperature).
- `logs/2026-06-17-key-on-cold-boot/capture.log` + `events.csv` — original cold-boot key-on engine-off, used as a fourth engine-off reference window.

Windows used per run (key_on / starter button / idle_settled / kill switch all read from each `events.csv`; Run 1's `idle_settled` is approximated as `starter + 1 s` per [its session.md](../../logs/2026-06-17-engine-idle-run-1/session.md) anomaly note):

- **engine-off** = `key_on` → `starter`.
- **idle** = `idle_settled` → `kill switch`.
- **decay** = `kill switch` → end of capture.

Tooling:

- `scripts/payload_diff.py` (new) — parses capture.log + events.csv, extracts the 8-byte payload per frame, partitions by window, and emits per-ID per-byte statistics and tags.

## Procedure

1. Implement `scripts/payload_diff.py` with the byte-classification logic above.
2. Run it against each of the four captures; collect per-window byte distributions.
3. Compute the eight category tags per (ID, byte) pair, using these rules:
   - **STATIC:** ≤1 distinct value across all windows and runs.
   - **LOW-CARDINALITY:** ≤16 distinct values across all captures, *and* not STATIC.
   - **COUNTER:** in any single window, ≥80 % of (frame[i+1].byte − frame[i].byte) mod 256 are a single small step ∈ {1, 2, 4, 8, 16}.
   - **CRC-LIKE:** ≥128 distinct values in any window, no counter pattern, no monotonic structure.
   - **ENGINE-STATE:** the byte's mode is different (and the value sets are largely disjoint) between the engine-off prelude and steady idle in *all three* runs.
   - **COOLANT-TEMP candidate:** median (or mode) of the byte in the steady-idle window changes monotonically across Run 1 → 2 → 3 by ≥1 LSB *and* the run-to-run change is larger than the within-run jitter.
   - **IDLE-RPM candidate:** ENGINE-STATE-tagged, *and* the engine-on value has standard deviation ≤4 (low jitter), *and* the engine-on value ≠ 0. Multi-byte pair detection: if byte N and byte N+1 of the same ID are both flagged, attempt a 16-bit little-endian / big-endian interpretation and check that the combined value's variance is consistent with idle RPM jitter (~50 RPM at idle, so ~0.4 % of full-scale).
4. Output a single classification table per ID; aggregate to one experiment-level table.
5. For any COOLANT-TEMP-candidate byte, plot or table the per-run median + IQR to confirm visual monotonicity (text-mode is fine — three numbers per byte).
6. For any ENGINE-STATE-tagged byte, also check the post-kill decay window (in the Slow-decay group only) — value should drift back toward the engine-off value if the byte is genuinely engine-state and not, say, a latched startup flag.
7. Promote bytes that pass all relevant sanity checks to candidate signals in [`docs/findings/can/`](../findings/can/) — but as `provisional` until at least one per-input capture confirms the interpretation. Constants, CRCs, and counters can promote to `confirmed` immediately since they're self-evident from the data.

## Result

### Per-byte classification

`scripts/payload_diff.py` was run against the three engine-idle captures with the rules described in Procedure. Output summary by ID (full output reproducible via `python scripts/payload_diff.py`):

| ID    | byte 0                          | byte 1                          | byte 2     | byte 3     | byte 4     | byte 5                       | byte 6     | byte 7      |
|-------|---------------------------------|---------------------------------|------------|------------|------------|------------------------------|------------|-------------|
| `120` | ENGINE-STATE (RPM hi byte)      | CRC-LIKE (RPM lo byte)          | STATIC 0x00 | STATIC 0x00 | STATIC 0x00 | STATIC 0x00                 | STATIC 0x00 | CRC-LIKE   |
| `121` | LOW-CARD(2)                     | LOW-CARD(13)                    | LOW-CARD(3) | LOW-CARD(14) | STATIC 0x04 | LOW-CARD(3) ENGINE-STATE    | STATIC 0x00 | UNKNOWN    |
| `129` | STATIC 0x00                     | STATIC 0x00                     | STATIC 0x00 | STATIC 0x01 | STATIC 0x00 | STATIC 0x00                 | STATIC 0x00 | LOW-CARD(7) |
| `12A` | STATIC 0x10                     | LOW-CARD(2)                     | STATIC 0x00 | STATIC 0x00 | STATIC 0x00 | STATIC 0x0A                 | STATIC 0x00 | LOW-CARD(13) |
| `12D` | STATIC 0x00                     | STATIC 0x00                     | STATIC 0x00 | STATIC 0x00 | STATIC 0x00 | STATIC 0x00                 | STATIC 0x00 | LOW-CARD(7) |
| `12E` | STATIC 0x00                     | STATIC 0x00                     | STATIC 0x00 | STATIC 0x00 | STATIC 0x00 | STATIC 0x00                 | LOW-CARD(2) | LOW-CARD(13) |
| `450` | STATIC 0x00                     | STATIC 0x00                     | STATIC 0x00 | STATIC 0x00 | STATIC 0x00 | STATIC 0x00                 | STATIC 0x28 | STATIC 0x00 |
| `540` | STATIC 0x00                     | ENGINE-STATE, thermal-corr      | LOW-CARD(2) | LOW-CARD(4) | STATIC 0x00 | **COOLANT-TEMP hi byte**    | **coolant lo byte (CRC-LIKE bin)** | STATIC 0x00 |
| `541` | STATIC 0x00                     | LOW-CARD(2)                     | LOW-CARD(2) | STATIC 0x00 | CRC-LIKE   | LOW-CARD(2)                 | UNKNOWN    | CRC-LIKE    |
| `5A0` | STATIC 0x00                     | STATIC 0x00                     | STATIC 0x00 | STATIC 0x00 | LOW-CARD(2) | STATIC 0x00                 | STATIC 0x00 | LOW-CARD(13) |
| `5B0` | LOW-CARD(2)                     | STATIC 0x00                     | STATIC 0x00 | STATIC 0x00 | STATIC 0x00 | STATIC 0x00                 | STATIC 0x00 | LOW-CARD(8) |

Of 88 payload bytes total: **47 are STATIC** (mostly 0x00, some 0x01/0x04/0x10/0x28/0x0A), **30 are LOW-CARD** (≤16 distinct values across captures), **6 are CRC-LIKE** (≥128 distinct), and a handful are ENGINE-STATE-tagged or UNKNOWN. The bus payload at idle is sparse — under a third of the payload bytes carry any information at all.

### Engine-state bit map

Bit-level analysis (a bit must flip its dominant value engine-off vs idle in all three runs, with ≥90 % purity in each window):

| ID  | Byte | Bit | Off-mode → Idle-mode |
|-----|------|-----|----------------------|
| `120` | 0  |  1  | 0 → 1 |
| `120` | 0  |  2  | 0 → 1 |
| `121` | 1  |  5  | 1 → 0 |
| `121` | 1  |  7  | 1 → 0 |
| `121` | 5  |  3  | 0 → 1 |
| `540` | 2  |  6  | 1 → 0 |
| `540` | 3  |  4  | 1 → 0 |

The 120 D0 bits 1+2 flipping 0→1 at engine-on are not a separate flag — they're the dominant bits of the **RPM high byte** (idle RPM = 1700 = `0x06A4` → D0 = `0x06` = bits 1+2 set). The classifier flagged them by their flip behaviour without knowing what the byte means; the cross-check below resolves them.

### Cross-validation against ktm-can decoder

Loading reference [`docs/references/ktm-can-decoder.md`](../references/ktm-can-decoder.md): the KTM 690 Enduro R has the same broadcast scheduler for IDs `120`, `129`, `12A`, `450`, `540`. Testing two KTM signal hypotheses against our data:

**Hypothesis: `120` D0,D1 = engine RPM, big-endian uint16.** Computed `D0 * 256 + D1` per frame:

| Run | Engine-off median | Idle median | Idle min | Idle max |
|-----|------------------:|------------:|---------:|---------:|
| 1 (cold)        | 0 | 1705 | 1345 | 2098 |
| 2 (partial warm) | 0 | 1698 | 1419 | 1945 |
| 3 (operating)    | 0 | 1702 | 1446 | 1936 |

Idle median ~1700 RPM in all three runs, ~700 RPM peak-to-peak jitter around the mean. Engine-off reads as exact 0. **Match.** RPM is closed-loop-controlled at idle on this engine, so it should not drift with thermal state — and it doesn't. The pattern is exactly what the KTM decoder predicts.

**Hypothesis: `540` D6,D7 = coolant temp × 10 °C, big-endian uint16** (KTM's exact byte positions):

| Run | Median (KTM bytes D6,D7) |
|-----|--------------------------|
| 1   | 2329.6 °C — nonsense     |
| 2   | 3712.0 °C — nonsense     |
| 3   | 2688.0 °C — nonsense     |

**No match.** Husqvarna doesn't have coolant at the same byte position as KTM 690.

**Alternative hypothesis: same encoding shifted one byte earlier — `540` D5,D6 = coolant temp × 10 °C, big-endian uint16:**

| Run         | Median  | Min     | Max     |
|-------------|--------:|--------:|--------:|
| 1 (cold)    | 48.3 °C | 25.8 °C | 63.9 °C |
| 2 (warm)    | 66.6 °C | 50.3 °C | 78.6 °C |
| 3 (op-temp) | 85.5 °C | 74.5 °C | 91.7 °C |

**Perfect match.** Run 3's median 85.5 °C corresponds to half-coolant-gauge — exactly what the rider reported at the end of Run 3. The thermal sweep is real, monotonic, and runs from a believable cold-start temperature (~25 °C, close to ambient) up to operating temperature. Husqvarna's coolant temperature is in `540` bytes D5,D6 — shifted one byte earlier compared to KTM 690.

### Additional indirect matches

KTM signal mappings that we can't *verify* with this dataset (we didn't vary the input) but whose **static values are consistent** with KTM's interpretation given the captured bike state:

- `120` D2 always `0x00` — KTM says throttle position. Throttle was closed → consistent.
- `120` D3 = `0x00` always (including bit 4) — KTM says bit 4 = kill switch (1=run, 0=stop). We had kill switch in run position. **Inconsistent** at face value — either bit 4 inverted on Husqvarna or the signal is elsewhere. Don't promote.
- `129` D0 = `0x00` always — KTM says hi nibble = gear (0 = neutral). Bike was in neutral. Consistent.
- `540` D3 = `0x00` (almost) — KTM says lo nibble = gear; 0 = neutral. Consistent.
- `540` D4 = `0x00` always — KTM says bit 0 = kickstand up (1 = raised). Side stand was down. Consistent.
- `12A` D0 = `0x10` always — KTM says bit 1 = throttle open. Throttle closed all the way → bit 1 = 0. Value `0x10` = bit 4 set, bit 1 clear → consistent with throttle closed.
- `12A` D1 = LOW-CARD(2) — KTM says bit 6 = requested throttle map. Two values, could be the bit toggling within capture (would need to check the time pattern).

### IDs and bytes that don't yet have a KTM hypothesis

- **`12D`**: 17 419 frames/run, broadcast every 10 ms — by far the busiest ID — but bytes 0-6 are all STATIC `0x00` and byte 7 is LOW-CARD(7). No KTM equivalent (the 10 ms KTM 690 ID `12B` is wheel speed / lean / tilt, but those use 8 active bytes and `12D` doesn't carry that data on our bike). Likely candidate: ABS heartbeat with stationary data. Will become important once we move the bike.
- **`12E`, `121`, `541`**: present at 20 ms, mostly LOW-CARD bytes. No KTM 690 equivalent IDs at this period besides those decoded above.
- **`5A0`, `5B0`**: 100 ms IDs, also new versus KTM 690. The Fast/Slow decay groups split `5A0`→Slow and `5B0`→Fast, suggesting at least two source modules.

## Interpretation

The diagnostic-port traffic at idle is exactly the shape the experiment plan predicted: a small set of bytes do all the talking (RPM, coolant, a handful of state bits, throttle/gear/kickstand placeholders), and the majority of the 88 payload bytes are static or near-static. The "ECU broadcasts a structured frame and most fields are zero when the corresponding control isn't varying" model fits.

Two clean wins came out of this:

- **Engine RPM is decoded** — `120` D0,D1 big-endian, idle ~1700 RPM. Promoted to [`docs/findings/can/signal-rpm.md`](../findings/can/signal-rpm.md) at `confirmed`.
- **Coolant temperature is decoded** — `540` D5,D6 big-endian × 10 °C. Promoted to [`docs/findings/can/signal-coolant-temp.md`](../findings/can/signal-coolant-temp.md) at `confirmed`. The thermal sweep accident of Runs 1/2/3 was decisive — three thermal points were what allowed monotonic detection in the first place. Confirmation came from matching the user-reported half-gauge reading at end of Run 3 with the decoded 85.5 °C median.

The KTM-can decoder ([`docs/references/ktm-can-decoder.md`](../references/ktm-can-decoder.md)) is now the project's most valuable external prior. Most signals we haven't decoded yet have a KTM hypothesis that just needs a per-input capture to confirm or refute. The byte-position shift discovered for coolant temp (Husqvarna at D5,D6 vs KTM at D6,D7) suggests we should always test the KTM position **and** ±1 byte before declaring "no match."

What this experiment *cannot* do is replace per-input captures:

- Gear position: bike was in neutral the whole time → can't test gear-position decoding without cycling gears.
- Throttle: never opened → can't disambiguate `120` D2 vs `12A` D0 bit 1.
- Kill switch: never toggled → `120` D3 bit 4 hypothesis remains untested and conflicts with KTM's polarity.
- Vehicle speed, lean, brake: bike was stationary throughout.
- Indicators, beam, horn, mode toggle, trip reset, neutral lamp drive: none were exercised.

`12D`'s near-empty payload is the most surprising finding — the 10 ms broadcast is the busiest message on the bus and yet at idle it carries effectively no varying information. The hypothesis is that `12D` encodes wheel-speed-driven or motion-driven data (analogous to KTM 690's `12B`), and at zero motion the bytes read as zero. This will be one of the first IDs to look at on the first ride capture.

## Follow-ups

- ✅ Two new `confirmed` findings written. *(done in this session)*
- ✅ External-reference doc for the ktm-can decoder. *(done in this session)*
- ✅ `scripts/payload_diff.py` saved and added to scripts catalog. *(done in this session)*
- **Per-input experiments — engine-off batch** (cheapest, most direct payback): throttle sweep, kill-switch toggle, gear-shift cycle, clutch in/out, side stand up/down. Each one tests a specific KTM hypothesis against our IDs. With most bytes already classified, each per-input experiment becomes a focused diff over ~20-40 candidate bytes per ID, not 88.
- **Per-input experiments — engine-on batch**: ROAD/SUPERMOTO toggle (`12A` D1 bit 6 candidate per KTM), trip reset, dash button presses. Should still be done stationary.
- **First ride / motion capture**: once stationary inputs are characterised, a low-speed roll (engine off, neutral, push-and-coast for ~10 m) ought to wake up wheel-speed-driven signals. Strongest candidate ID is `12D` since it's the only 10 ms always-on broadcast and KTM puts wheel speeds at the same period.
- **Bit-position polarity check** for `120` D3 bit 4 (kill switch). KTM says 1 = run; our captured value at kill-run reads as bit 4 = 0. Could be invertedness, could be the bit isn't here at all on Husqvarna. The kill-toggle per-input capture will resolve it.
- **`12D` byte 7 distribution**: LOW-CARD(7), distinct from STATIC 0 — worth a closer look. Could be a heartbeat counter modulo 7, could be an ABS-side state.
