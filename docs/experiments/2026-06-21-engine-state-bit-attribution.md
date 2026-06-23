---
date: 2026-06-21
status: success
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/post-kill-decay-groups
    - can/signal-rpm
    - can/signal-coolant-temp
    - can/signal-side-stand
  references:
    - ktm-can-decoder
  experiments:
    - 2026-06-17-payload-diff-idle
    - 2026-06-17-engine-idle-baseline-x3
    - 2026-06-18-side-stand-toggle
  logs:
    - 2026-06-17-engine-idle-run-1
    - 2026-06-17-engine-idle-run-2
    - 2026-06-17-engine-idle-run-3
    - 2026-06-17-key-on-cold-boot
---

# Attribute the engine-state bits left over by payload-diff (+ fan-on hunt, `540` D3 second axis)

## Hypothesis

The idle-baseline `payload_diff` flagged seven bits as flipping between engine-off and idle with ≥90 % purity across all three runs. Two were resolved as the dominant bits of the RPM high byte (`120` D0 bits 1+2). The other five remain unattributed:

| ID    | Byte | Bit | Off → Idle |
|-------|-----:|----:|------------|
| `121` |   1  |  5  | 1 → 0      |
| `121` |   1  |  7  | 1 → 0      |
| `121` |   5  |  3  | 0 → 1      |
| `540` |   2  |  6  | 1 → 0      |
| `540` |   3  |  4  | 1 → 0      |

Each bit is one of:

1. **A true data signal** — oil-pressure switch, charge/alternator status, fuel-pump relay, ignition-relay state, generator/regulator status, "engine running" composite.
2. **A power-rail derivative** — the source module loses VBAT or 12V-ACC when the engine stops; the bit reads its disconnected state. These will track the Fast/Slow decay groups identically — bits on Fast-group IDs vanish ~0.5 s post-kill with no graceful transition; bits on Slow-group IDs ride down ~5–6 s with the rest of the payload.
3. **A latched startup flag** — set once at engine-on and only cleared on key-off; never returns to its engine-off value during the post-kill window.

The three categories are distinguishable by post-kill decay shape over the windows we already have. None of the five bits needs a new capture to be attributed — we just haven't looked at the right slice yet.

Two adjacent threads run on the same corpus:

**Fan-on hunt.** Run 3's coolant peaked at 91.7 °C, median 85.5 °C. KTM 390 typically engages the radiator fan around 102–105 °C, so the fan likely *didn't* run in Run 3 — but the late-Run-3 thermal window is still the warmest sustained data we have, and any bit that flips later in Run 3 than in Runs 1+2 is worth surfacing (fan, thermostat-open, secondary cooling, ECU enrichment table change).

**`540` D3 second axis.** Side-stand confirmed `540` D3 bit 0; `payload_diff` saw D3 as LOW-CARD(4), which is 2 bits of variation. Side-stand was DOWN throughout the idle baselines, so the other axis of D3 movement at idle cannot be side-stand — it is engine-correlated. D3 bit 4 is in the engine-state list above. The hypothesis is that D3 bit 0 + bit 4 jointly account for D3's four observed values at idle, with no third moving bit.

## Setup

Desk-only. No bike interaction; no new capture. Inputs (all on disk):

- `logs/2026-06-17-engine-idle-run-{1,2,3}/capture.log` + `events.csv`
- `logs/2026-06-17-key-on-cold-boot/capture.log` + `events.csv` (fourth engine-off reference)

Per-run windows already defined by `events.csv`:
- `engine-off` = `key_on` → `starter`
- `idle` = `idle_settled` → `kill switch`
- `decay` = `kill switch` → end of capture

Sub-windows we'll add inside `decay`:
- `decay-0` = `kill switch` → +500 ms
- `decay-1` = +500 ms → +1 s
- `decay-2` = +1 s → +2 s
- `decay-3` = +2 s → +5 s
- `decay-4` = +5 s → end (only meaningful on Slow-group IDs)

Sub-windows inside Run 3's `idle` for the fan hunt:
- `idle-r3-early` = `idle_settled` → `idle_settled + 60 s`
- `idle-r3-mid`   = `+60 s` → `+120 s`
- `idle-r3-late`  = `+120 s` → `kill switch`

Tooling: new script `scripts/engine_state_attribution.py`. Reuses `payload_diff`'s frame parser and event-window logic.

## Procedure

1. **Build the per-bit decay table.** For each of the five flagged bits, per run, compute the dominant value and purity in every sub-window (`engine-off`, `idle`, `decay-0..4`). Output a table:

   ```
   ID    byte  bit   engine-off  idle   decay-0  decay-1  decay-2  decay-3  decay-4
   121   1     5     1 (1.00)    0 (...)  ...
   ...
   ```

   Classify each bit:
   - **Data signal**: returns to `engine-off` dominant value in `decay-0` or `decay-1` (faster than the bit's host ID's group decay).
   - **Power-rail derivative**: tracks the host ID's group exactly — Fast-group IDs (`540` lives in Fast) vanish by `decay-1`; Slow-group IDs (`121` lives in Slow) glide through `decay-0..3` with the same envelope as the rest of the payload.
   - **Latched startup flag**: holds the `idle` value through every decay window the ID is still broadcasting in.

2. **Cross-walk to KTM hypotheses.** With each bit's decay shape known, look up the host ID + nearby bits in `references/ktm-can-decoder.md` for candidate semantics. The Husqvarna `540`-shifts-one-byte-earlier rule applies — also check the KTM byte at +1.

3. **Fan-on hunt.** For every (ID, byte, bit), compute dominant value + purity in `idle-r3-early`, `idle-r3-mid`, `idle-r3-late`. Surface any bit whose dominant value differs between an early and a late Run 3 window **and** was STATIC across the entirety of Run 1 + Run 2 + the cold-boot capture. Each such bit is a fan / thermal-stage candidate. If none surface, the conclusion is "fan did not engage in Run 3; thermal stage threshold is >91.7 °C on this bike; a hotter capture is required to surface fan state."

4. **`540` D3 nibble inventory.** Tabulate the four LOW-CARD(4) values of `540` D3 observed across all three runs' `engine-off` + `idle` windows. Decompose each into (bit 0, bit 4, other bits). Check the joint distribution against the marginal of (side-stand state × engine-state). If the four values fit `{0x00, 0x01, 0x10, 0x11}` and reduce cleanly to bit 0 + bit 4, the byte is fully accounted for at idle and any future `540` D3 movement is a new signal.

5. **Promotion.** Any bit that lands the **data signal** classification *and* has a KTM-compatible interpretation gets a `provisional` finding written: `docs/findings/can/signal-<slug>.md`. Per-input confirmation comes later — most of these (oil pressure, fuel pump, charge) are not user-toggleable inputs; engine-on alone tests them, and a low-RPM or stalled-engine moment would test alternator.

## Expected outcomes

- **All five bits attributed by decay shape.** Likely outcome: at least two are power-rail derivatives (the bit goes dark with its module) and the rest are data signals with KTM-plausible mappings. Provisional findings written for the data signals.
- **A fan-on bit found.** Less likely given Run 3 didn't quite reach engagement temperature; if not surfaced, the experiment writes a small "fan threshold >91.7 °C" note instead of a finding.
- **`540` D3 fully decomposed.** Confirms or refutes the "bit 0 + bit 4 explain all observed D3 variation at idle" hypothesis. Either result tightens future `540` decoding.

## Result

Run with `python scripts/engine_state_attribution.py`. Full output reproducible.

### Part A — post-kill decay shape

The five flagged bits, decay-window dominant value (purity, frame count), aggregated table:

| bit            | engine-off    | idle          | decay-0 (0-500 ms)              | decay-1+ (>500 ms) |
|----------------|---------------|---------------|---------------------------------|--------------------|
| `121` D1 bit 5 | `1` (1.00)    | `0` (~0.93)   | `0` (1.00, 12–16 frames/run)    | host ID silent     |
| `121` D1 bit 7 | `1` (1.00)    | `0` (~0.93)   | `0` (1.00, 12–16 frames/run)    | host ID silent     |
| `121` D5 bit 3 | `0` (1.00)    | `1` (1.00)    | `1` (1.00, 12–16 frames/run)    | host ID silent     |
| `540` D2 bit 6 | `1` (0.99)    | `0` (~1.00)   | `0` (1.00, 2–3 frames/run)      | host ID silent     |
| `540` D3 bit 4 | `1` (0.99)    | `0` (~1.00)   | `0` (1.00, 2–3 frames/run)      | host ID silent     |

**All five bits stayed at their idle-mode value through the entirety of the host ID's post-kill broadcast tail.** None reverted to engine-off mode while still being broadcast. The classifier returned **holds-idle** for the three `121` bits (≥10-frame threshold met) and **silent** for the two `540` bits (cell counts below threshold but the dominant value in the available frames is also `0` = idle mode).

`121`'s 12–16 frames in 500 ms (period 20 ms, expected ~25) localises its last broadcast to ~250–400 ms post-kill. `540`'s 2–3 frames in 500 ms (period 100 ms, expected 5) localises its last broadcast to ~200–300 ms post-kill. Both are inside the [[post-kill-decay-groups]] Fast-group envelope.

What we can rule out from the decay window alone: **none of these bits is a fast "engine-running" latch** with sub-300 ms response. RPM (`120` D0,D1) snaps to `0x0000` at the moment of kill (confirmed in `payload_diff`); these bits do not.

### Part A.5 — the 174 s cold-boot extension

Added after the initial draft: the [[2026-06-17-key-on-cold-boot]] capture *is* the key-on-no-engine condition I was about to propose as a follow-up. Re-using it as an extended engine-off reference is the right move, and the 174 s hold is 6× longer than the engine-off prelude of the idle baselines.

Per-third bit stability over the 173.8 s key-on-no-engine hold:

| bit            | expected off-mode | third-1 (57.9 s)   | third-2 (57.9 s)   | third-3 (57.9 s)   | verdict           |
|----------------|------------------:|--------------------|--------------------|--------------------|-------------------|
| `121` D1 bit 5 |     `1`           | `1` (1.00, n=2882) | `1` (1.00, n=2896) | `1` (1.00, n=2895) | flat at off-mode  |
| `121` D1 bit 7 |     `1`           | `1` (1.00, n=2882) | `1` (1.00, n=2896) | `1` (1.00, n=2895) | flat at off-mode  |
| `121` D5 bit 3 |     `0`           | `0` (1.00, n=2882) | `0` (1.00, n=2896) | `0` (1.00, n=2895) | flat at off-mode  |
| `540` D2 bit 6 |     `1`           | `1` (0.99, n=577)  | `1` (1.00, n=579)  | `1` (1.00, n=579)  | flat at off-mode  |
| `540` D3 bit 4 |     `1`           | `1` (0.99, n=577)  | `1` (1.00, n=579)  | `1` (1.00, n=579)  | flat at off-mode  |

All five bits hold engine-off mode at ≥0.99 purity through every third. **No internal timer, no self-test stage, no drift.** The host modules are fully alive and broadcasting normally throughout (`121` at 20 ms, `540` at 100 ms cadence). Whatever sets these bits to idle mode requires the engine to *actually be running*, not just key+kill being in the run position.

This rules out three weaker stories I had on the list:

- **Bit tracks "engine-run permission"** (key + kill in run). Would predict idle-mode through cold-boot; doesn't.
- **Bit is a key-on latch.** Would predict idle-mode through cold-boot; doesn't.
- **Bit is just "module is powered."** Module is powered for 174 s with the bit at engine-off mode.

What remains is the much narrower question of **which sensor each bit sources** — oil pressure, alternator output, fuel pump status, crank-sensor presence, generator-good, ignition coil feedback. The CAN data alone cannot distinguish between these candidates without an external mapping (manufacturer pinout, another open-source decoder, or hardware probing).

### Part B — fan-on hunt in Run 3

Null result. Run 3's idle window is 174.8 s. Partitioned into three 58.3 s sub-windows (early / mid / late), no (ID, byte, bit) across the 11 always-on IDs satisfied the criteria (STATIC across Run 1 + Run 2 + cold-boot, then changing dominant value within Run 3 with ≥0.95 purity per sub-window).

This is the expected outcome: Run 3's peak coolant was 91.7 °C, below the KTM 390 platform's typical radiator-fan engagement threshold (~102–105 °C). The fan almost certainly did not run during Run 3, and any thermostat-open or secondary-cooling threshold is also higher than what we reached. The corpus does not contain a hot-enough sample to surface a fan-on bit.

### Part C — `540` D3 decomposition

D3 byte values observed across all three runs' engine-off + idle windows, decomposed into (bit 0, bit 4, rest):

| value  | bit 0 (side stand) | bit 4 (engine-state) | other bits | off frames | idle frames |
|--------|-------------------:|---------------------:|-----------:|-----------:|------------:|
| `0x00` | 0 (down)           | 0                    | 0x00       |     2      |    5291     |
| `0x01` | 1 (up)             | 0                    | 0x00       |     6      |       0     |
| `0x10` | 0 (down)           | 1                    | 0x00       |   900      |      11     |
| `0x11` | 1 (up)             | 1                    | 0x00       |     3      |       0     |

**All four observed D3 values decompose cleanly into bit 0 × bit 4 with zero other bits set.** D3 is fully accounted for at idle by side-stand + engine-state.

The handful of off-window `0x01`/`0x11` frames (9 total out of 911) and the engine-off mode being `0x10` (side stand down, bit 4 = 1) are both consistent with the bike sitting on its side stand during key-on prep, with bit 4 reading `1` whenever the engine is not running. The idle-window stragglers of `0x10` (11 out of 5302 frames) are the same bit 4 = 0 not having 100 % purity that `payload_diff` had already characterised.

## Interpretation

Three concrete updates.

**`540` D3 is the cleanest fully-decomposed byte on the bus so far.** Side-stand (bit 0) + engine-state-derived (bit 4) account for every observed value at idle. Any future capture surfacing a third moving bit in `540` D3 is a new signal — the catalogue for this byte is now exhaustive at idle and on the side stand.

**The five unattributed engine-state bits are not fast "engine-running" indicators.** None reverted to its engine-off mode during the host ID's ~300 ms post-kill broadcast tail. For dashboard logic, the right "engine running" signal is RPM (`120` D0,D1) — it goes to exact zero within one broadcast period of kill, and is already a `confirmed` finding ([[signal-rpm]]). Treating any of these five bits as engine-running would introduce ~300 ms+ false-positive latency on every kill event.

**The fan-on bit is not in the current corpus.** Run 3 didn't reach engagement temperature; no other capture got close to it. Surfacing fan state will require a deliberately hot capture (sustained idle to 100 °C+, or a stop-and-go traffic capture). Not a blocker; not worth a dedicated session until other higher-payoff captures are exhausted.

**The decay-shape "three stories" framing was the wrong slice.** I initially proposed a separate "key-on, wait 30 s, key-off" follow-up capture to distinguish power-rail-derivative from key-on-latch from slow-decay-sensor — but that condition is already on disk as the 174 s cold-boot capture, and once I ran it (Part A.5), the framing dissolved. The cold-boot data rules out "engine-run-permission" and "key-on-latch" cleanly, and what remains is not three stories about *how the bit decays* but a single question of *which sensor sources the bit*. CAN-only experiments can't resolve that — only external mapping or hardware probing can.

## Follow-ups

- [x] Write a `provisional` finding [`docs/findings/can/engine-state-bits-decay-shape.md`](../findings/can/engine-state-bits-decay-shape.md) describing the holds-idle pattern and the dashboard implication.
- [x] Update [`docs/findings/can/signal-side-stand.md`](../findings/can/signal-side-stand.md) "Bit 4 of D3" note to reflect the now-confirmed full decomposition: `540` D3 = (bit 0 = side stand) | (bit 4 = engine-state, unattributed) | (all other bits = 0 at idle).
- ~~New candidate engine-off capture: **key-on, wait 30 s, key-off, end**~~ — withdrawn. The 174 s cold-boot capture is already exactly this condition. Part A.5 reuses it; nothing more is gained by a fresh shorter version of the same recipe.
- [ ] **Fan-on capture** deferred. Lowest priority of the open inputs — requires sustained 100 °C+ at idle (would need a hot day, no airflow, several minutes), and the same signal will surface incidentally on the first real-traffic ride capture.
- [ ] No changes needed to [[post-kill-decay-groups]] or [[byte-d7-cycle-hash]] — the decay timing observed here corroborates the existing Fast-group envelope rather than refining it, and D7 was out of scope for this experiment.
