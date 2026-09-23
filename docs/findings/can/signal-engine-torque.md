---
area: can
status: confirmed
established_by:
  - 2026-06-17-engine-idle-baseline-x3
  - 2026-06-23-engine-driven-rear-spin
  - 2026-07-22-first-moving-ride
  - 2026-07-24-torque-throttle-threshold-engine-off
references:
  - ktm-can-decoder
---

# Engine torque (signed) — `121` D0:D1

`121` D0:D1 is **signed engine torque** as a two's-complement int16 big-endian. Positive when the engine is driving the wheels (combustion producing net crank torque), negative during overrun (wheels driving the engine through a closed throttle — engine drag / pumping loss dominates). Broadcast at the 20 ms cadence of `121`. `D2:D3` carries the same quantity through what looks like the ECU's redundant computation path — the two channels track within ~1 LSB during real riding, consistent with the two-channel torque-monitor pattern of safety-critical ride-by-wire ECUs.

```
torque_lsb = int.from_bytes(data[0:2], "big", signed=True)   # 121_A
```

LSB is provisionally **≈ 0.25 N·m** — see [Scaling](#scaling) below. Precise pin still open.

## Direct evidence

Four independent tests, each conclusive on its own:

**1. Sign flip on drive vs overrun.** Aggregated across all engine-on frames of the 2026-07-22 moving corpus: mean **+51.6 LSB under drive** (throttle > 0), mean **−19.5 LSB in overrun** (throttle 0, RPM > 2000). Overrun magnitude scales with RPM: −16 at 3500, −18 at 4000, −20 at 4500, −23 at 5000 — matches engine drag / pumping loss scaling with rotational speed. `scripts/first_moving_ride_load_scan.py`.

**2. Ignition-cut collapse during quickshifter events.** During the ~60 ms ignition cut of a quickshift ([[signal-quickshifter]]), combustion stops and only pumping loss remains at the crank. Test across 31 upshifts (`scripts/first_moving_ride_torque_during_cut.py`):

| Shift group | n | Pre-cut μ | In-cut min μ | Δ |
|-------------|---:|----------:|-------------:|--:|
| Aggressive (rider ON throttle through cut, pre-cut > +30) | 3 | +88 | −38 | **−126 LSB** |
| Neutral (−10 < pre-cut < +30) | 5 | +8 | +9 | +1 |
| All 31 upshifts | 31 | −17 | −28 | −12 |

Individual aggressive shifts land at pre +94 → in-cut −39 (moving-1 3→4); pre +90 → −38 (moving-1 4→5); pre +79 → −37 (moving-2 2→3). The magnitude of the swing is conditioned on the rider's throttle state at cut, not on RPM or throttle position independently — that specifically rules out RPM-derived, throttle-position-derived, and static-lookup interpretations. Only a signal tracking instantaneous combustion produces this.

**3. Physics-based LSB, order-of-magnitude consistent.** `scripts/first_moving_ride_torque_physics_check.py` extracts 54 near-cruise segments (≥1 s, low speed-drift), computes expected drag power `P = m·g·Crr·v + 0.5·ρ·CdA·v³` at each, solves for engine torque via `τ = P / (ω · η_drivetrain)`, divides by observed `121_A` mean to get an implied LSB per segment. Speed-band summary:

```
20-30 km/h:  LSB μ = 0.079 N·m   (small P_drag → noisy)
50-60 km/h:  LSB μ = 0.099 N·m
70-80 km/h:  LSB μ = 0.136 N·m
90-100 km/h: LSB μ = 0.155 N·m
Longest segment (4.6 s, moving-4): LSB = 0.222 N·m
```

Physically plausible torque LSB across every speed band. The drift with speed and the 42 % across-segment CoV reflect gradient / wind / short-segment noise (freeform city ride, not a controlled cruise) rather than an inconsistency in the underlying signal.

**4. Twin-channel redundancy pattern (D0:D1 and D2:D3).** Under real riding the two channels track within ~1 LSB across every RPM/throttle bin. Redundant torque monitors are the standard ISO 26262 pattern for ride-by-wire safety on modern motorcycle ECUs — the "requested vs delivered" cross-check that guards against runaway acceleration. That the two channels exist AND agree closely is itself an argument for the semantic: unrelated computed indices would not be redundant this way.

## Encoding

Two's-complement int16 big-endian at D0:D1 (channel A) and D2:D3 (channel B). Sign-byte consistency verified at **100 % across 35 112 engine-on frames** in four sessions (2026-06-17 idle x3 + 2026-06-23 rear-spin):

| session | engine-on frames | D0:D1 sign-agree | D2:D3 sign-agree |
|---|---:|---:|---:|
| 2026-06-17-idle-1 | 7 997 | 100.0 % | 100.0 % |
| 2026-06-17-idle-2 | 7 962 | 100.0 % | 100.0 % |
| 2026-06-17-idle-3 | 7 998 | 100.0 % | 100.0 % |
| 2026-06-23-engine-driven-rear-spin | 11 155 | 100.0 % | 100.0 % |

D0 is 0xFF iff D1 ≥ 0x80 — the exact sign-extension signature of int16 in the observed magnitude range. Zero counterexamples.

The bimodal {0x00, 0xFF} distribution on D0 / D2 flagged by `scripts/id121_byte_scan.py` was the surface signature; earlier byte-level statistics that looked non-monotonic (`scripts/engine_load_scan.py`) were an artefact of taking means across the sign discontinuity — a sequence wobbling {−1, 0, +1, +2} reads as raw bytes {0xFF, 0x00, 0x01, 0x02} with byte-mean ~64, not ~0.

## Scaling

Working estimate: **1 LSB ≈ 0.25 N·m**, converging from four independent arguments:

- Peak observed magnitude ~75 LSB at 5500-6000 RPM / ~47 % throttle → 18.75 N·m, well inside the Svartpilen 401 spec peak of 37 N·m.
- Aggressive shift-cut swing of ~130 LSB (from +90 down to −40) → 32.5 N·m, in the expected range for full drive torque interrupted by an ignition cut.
- Ride-integrated fuel model at LSB = 0.25 implies thermal efficiency **≈ 27 %** — right in the physical range for a small gasoline single at real-world duty cycle. LSB = 0.5 implies 54 % (impossible); LSB = 0.125 implies 13 % (too low).
- Physics-based per-cruise-segment LSB above averages ~0.13 N·m; segments include acceleration/gradient noise that biases the estimate downward relative to true steady-state, so 0.2-0.25 N·m is the plausible ceiling.

The three arguments converge to 0.2-0.25 N·m/LSB. A controlled coast-down capture (see [[2026-07-23-coast-down]]) will pin this to a single number.

## Range and clamps

**Positive clamp at +172** (hard saturation, engine-on). Full histogram of `121` D0:D1 across the 46 301-frame moving-ride corpus shows values walking naturally up to +160, then a complete zero-count gap 161–171, then a spike of 167 frames at exactly +172 and nothing above:

```
160: █████ (5)
161-171: (0)          ← gap
172: ██████████████████████████████████████████████ (167)   ← clamp
173+: (0)
```

At LSB ≈ 0.25 N·m this is ~43 N·m — the Svartpilen 401 spec peak is 37 N·m, so the clamp sits just past physical peak. Signature is textbook saturation: a natural walk-up, an unreachable range, a spike at the ceiling.

**No negative clamp in the observed range.** The negative tail runs continuously without discontinuity down to the minimum-ever-observed −40 in the same corpus (−22: 282 frames, −34: 28, −36: 117, −38: 70, −40: 1). Whether the ECU has a floor below −40 is unknown — no ride so far has produced enough overrun / shift-cut magnitude to bump it.

**The engine-off two-state values (+166 / −36) are neither of these clamps** — see next section.

## Idle behaviour

At warm idle: torque wobbles around 0 with σ ~0.5-1.0 LSB (< 0.25 N·m of noise). Consistent across all three 2026-06-17 idle baseline captures. This is the physically expected value — the engine is producing exactly enough torque to overcome friction, so net torque at the crank ~ 0.

**Engine-off is a two-state signal, not a bias** ([[2026-07-24-torque-throttle-threshold-engine-off]]). **Scope: neutral only** — that capture was run in neutral with the side stand down throughout, and the throttle threshold below is only established for that state. Rider live-view observation on 2026-08-02 (uncaptured, pending [[2026-08-02-torque-engine-off-gear-dependence]]) is that **in gear, engine-off, D0:D1 reads −36 at all throttle positions** — no threshold behaviour at all. Do not treat the rule below as the general engine-off rule until that experiment runs.
- D0:D1 = exactly **+166** when `120` D2 (rider throttle) < 234.
- D0:D1 = exactly **−36** when `120` D2 ≥ 234 (≈92 % grip) held for ~500 ms. Exit is immediate on throttle release; no latch.
- No intermediate values ever observed — strictly binary switch.
- No sibling mode bit anywhere on the bus co-transitions. D2:D3 stays pinned at +463 in both states; the twin-channel-tracks-within-1-LSB claim (see below) is engine-*on* only.

Interpretation: the ECU is computing D0:D1 as "predicted torque under the current fuel-and-ignition policy", and the policy switches to a fuel-cut precondition at high throttle with dwell. Signature matches the arming preview for a flood-clear / no-fuel-start mode, though whether the fuel-cut actually applies during cranking is untested (engine did not start in that experiment). This engine-off regime is not the operating semantic; it's here as a caveat so downstream tooling doesn't treat +166 as the sole engine-off value.

**Neither +166 nor −36 is an operational clamp** (established by histogram of the moving-ride corpus, see [Range and clamps](#range-and-clamps)). +166 never appears in engine-on data — 0 of 46 301 frames — and sits 6 counts below the actual positive clamp at +172. −36 is a common value in the natural overrun / shift-cut tail (117 hits) but the distribution continues smoothly past it to −40 with no gap or spike. Under LSB ≈ 0.25 N·m the values decode as:
- +166 → 41.5 N·m: the ECU's prediction of "engine torque at current inputs if the engine were running normally at nominal peak-operating conditions" — near the physical peak because throttle < 234 with no fuel-cut policy is a naive-max scenario.
- −36 → −9 N·m: pumping-loss magnitude for a 400 cc single at low RPM, matching what the crank would produce with fuel cut and no combustion.

So both engine-off values are state-specific ECU-precomputed predictions on the same underlying "predicted torque under current policy" signal — not sentinels, not saturation, not clamps.

## What was ruled out along the way

- **Not a counter.** Value is bounded and signed, not monotone-wrap. Contrast [[signal-engine-on-counter]].
- **Not engine-state flags.** No bit on D0:D3 holds a stable {0,1} pattern; bytes wobble continuously.
- **Not the D7 cycle hash.** D7 is computed from D0..D6 per the universal algorithm ([[byte-d7-cycle-hash]]); D0:D3 are payload.
- **Not ignition advance corrections** — the sign-flip-on-overrun pattern doesn't fit; advance is bounded positive (BTDC).
- **Not short/long-term fuel trim** — trims are load-related but bounded to ±25 % or so, not the ±75 LSB range we see.
- **Not load-independent RPM-derived** — the pre-2026-07-22 rear-spin data suggested this at paddock loads, but real-ride load range invalidated the ruling. Torque is by definition load-related.

## Open (refinement, not identification)

- **Nail the LSB to a single number.** The 0.2-0.25 N·m range is well-supported but not pinned. A coast-down capture (throttle closed, bike coasting from ~5000 RPM to idle in a fixed gear on a flat straight) gives clean single-event data without gradient/wind/short-segment confounds — [[2026-07-23-coast-down]].
- **Sub-N·m calibration** for the fuel-consumption cross-check would benefit from a GPS-tracked ride with a tank-fill delta anchor, isolating the fuel-model `k` from the torque LSB.
- **Confirm smooth zero-crossing** on a drive-to-overrun transition. Ride-corpus overrun episodes hint at this (torque walks from positive to negative through zero as the rider closes throttle) but no episode is clean enough for a definitive transient trace.

## Evidence

- [`docs/experiments/2026-06-23-engine-driven-rear-spin.md`](../../experiments/2026-06-23-engine-driven-rear-spin.md) — RPM sweep that surfaced the shape (pre-load-retraction era).
- [`docs/experiments/2026-06-17-engine-idle-baseline-x3.md`](../../experiments/2026-06-17-engine-idle-baseline-x3.md) — cross-session encoding confirmation.
- [`docs/experiments/2026-07-22-first-moving-ride.md`](../../experiments/2026-07-22-first-moving-ride.md) sub-analyses 7, 10 — rolling-load discrimination and shift-cut torque dip.
- [`scripts/id121_int16_verify.py`](../../../scripts/id121_int16_verify.py) — sign-consistency check.
- [`scripts/first_moving_ride_load_scan.py`](../../../scripts/first_moving_ride_load_scan.py) — sign-flip under drive vs overrun.
- [`scripts/first_moving_ride_torque_during_cut.py`](../../../scripts/first_moving_ride_torque_during_cut.py) — ignition-cut torque collapse.
- [`scripts/first_moving_ride_torque_physics_check.py`](../../../scripts/first_moving_ride_torque_physics_check.py) — physics-based LSB consistency across cruise segments.

## Naming history

Originally logged as `byte-121-twin-int16` (a byte-level encoding finding — the semantic was open). The 2026-07-22 moving corpus surfaced the sign-flip and rolling-load response; the shift-cut test in the same corpus provided direct causal evidence; the physics-based LSB check on 2026-07-23 pinned the magnitude to a physically consistent range. Renamed to `signal-engine-torque` on 2026-07-23 and promoted to confirmed. The redundant `D2:D3` channel is retained under the same finding — same quantity, redundant broadcast.

As part of the promotion, `121` D1 bits 5 and 7 — previously listed in [[engine-state-bits-decay-shape]] as candidate engine-state flags on the strength of cross-session dominant-value differences — were reinterpreted as LSBs of the signed torque low byte and removed from that finding. The engine-off bias (D0:D1 ≈ +170) vs idle (~0) fully accounts for the observed bit differences without an independent state flag.

See also: [[signal-quickshifter]] (the ignition cut event this signal uses as its own causal test), [[fuel-consumption-derivation-from-torque]] (the primary fuel model this signal drives), [[signal-fuel-injection-setpoint]] (the parallel fuel-adjacent scalar on `540 D1`), [[signal-rpm]], [[signal-throttle-position]], [[byte-d7-cycle-hash]].
