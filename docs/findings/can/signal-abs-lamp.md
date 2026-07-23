---
area: can
status: provisional
established_by:
  - 2026-07-22-first-moving-ride
references:
  - dash-warning-lights
---

# ABS warning-lamp / self-test-complete status — `12A` (3 bits) + `12E` D6 (2 bits)

The ABS warning lamp on the OEM dash is driven by a status flag that appears simultaneously at **five** bits across two arbitration IDs on the 2020 Husqvarna Svartpilen 401:

| Location | Polarity |
|----------|----------|
| `12A` D0 bit 4 | HIGH = lamp lit / OFF = extinguished |
| `12A` D1 bit 0 | HIGH = lamp lit / OFF = extinguished |
| `12A` D5 bit 3 | HIGH = lamp lit / OFF = extinguished |
| `12E` D6 bit 4 | LOW = lamp lit / HIGH = extinguished |
| `12E` D6 bit 5 | LOW = lamp lit / HIGH = extinguished |

All five flip **together** — within the two-broadcast-period window of the first frame after front wheel speed crosses ~ 6 km/h with engine running, on a fresh key-on cycle — and none of them flip back until the next key cycle.

```python
abs_lamp_lit = (
    (data_12A[0] >> 4) & 1
    or (data_12A[1] >> 0) & 1
    or (data_12A[5] >> 3) & 1
    or not (data_12E[6] >> 4) & 1
    or not (data_12E[6] >> 5) & 1
)
# All 5 agree, so reading any one works; the multi-bit agreement is the
# consistency check.
```

> **Correction 2026-07-22 (post-cross-check).** An earlier draft of this finding included a sixth bit, `12A D1 bit 2`, based on its co-transition with the other five during moving-1 and moving-2's ABS-extinguish events. Cross-checking against all 15 pre-2026-07-22 sessions (`scripts/abs_lamp_crosscheck.py`) shows D1 b2 has **completely different behaviour** from the other five: it flips independently across almost every historical capture, including [[2026-06-24-front-wheel-hand-spin]] (engine off, front wheel to 11 km/h, ABS lamp did NOT extinguish per [[bike/dash-warning-lights]] — yet D1 b2 dropped 1 → 0 at t+112.9 s in that session). If D1 b2 were the lamp, it wouldn't flip while the lamp was demonstrably still lit. It got swept into this finding because its moving-1 transition happened to coincide with the actual ABS-extinguish event — a classifier false positive that a per-session cross-check catches cleanly. See [[signal-12a-d1-bit2]] for the follow-up (semantics open — probably an ECU-side "module armed" or "ignition state" bit).

## Evidence — two independent key-cycles in one ride

[[2026-07-22-first-moving-ride]] captured two full ABS-extinguish events across five files: moving-1 was a fresh key-on (cold-ish engine), and moving-2 was a second key-on cycle after the rider stopped and re-started the bike (confirmed by the ESP boot-relative timestamps restarting between moving-1 and moving-2). moving-3 / 4 / 5 continued the same key-on cycle as moving-2 without another cycle.

For each of the 6 candidate bits, per capture (from `scripts/first_moving_ride_abs_verify.py`):

| Capture | Boot cycle | First value on 12A bits / 12E D6 bits | Transitions | Interpretation |
|---------|-----------|:-:|:-:|-|
| moving-1 | fresh key-on #1 | 1 / 0 | 1 | ABS lit at start; extinguishes at t+92.9 s (front wheel first crossed 6 km/h at t+92.76 s) |
| moving-2 | fresh key-on #2 | 1 / 0 | 1 | ABS lit at start; extinguishes at first > 6 km/h crossing |
| moving-3 | continuing key-on #2 | 0 / 1 | 0 | Post-extinguish; stays off |
| moving-4 | continuing key-on #2 | 0 / 1 | 0 | Post-extinguish; stays off |
| moving-5 | continuing key-on #2 | 0 / 1 | 0 | Post-extinguish; stays off |

`12A D1 bit 2`'s 3 transitions in moving-2 (vs 1 for the others) was the signal that this bit is a distinct flag — the cross-check on 2026-07-22 later confirmed it's not an ABS-lamp bit at all (see the Correction blockquote above and the [[signal-12a-d1-bit2]] follow-up).

## Confirms the engine-running precondition on `dash-warning-lights`

[[bike/dash-warning-lights]] flagged the ABS extinguish as `provisional` because the 2026-06-24 front-wheel hand-spin drove the OEM dash speedo to ~11 km/h engine-off without extinguishing the lamp. That negative is now consistent with the positive here — engine was running through both moving-1 and moving-2 first-crossings, and the lamp extinguished on both. Promotes the engine-running precondition from provisional to observed on this ride. Still doesn't disprove other gating (e.g. the ABS module needs to have booted its self-test), but is a strong yes on "engine-off wheel-spin ≠ enough".

## Cross-check: which bits survived, and how the cross-check ran

`scripts/abs_lamp_crosscheck.py` scans every one of the 15 pre-2026-07-22 sessions plus the moving corpus for each candidate bit's initial value, transition count, and per-transition timestamps.

**Bits that survive the cross-check (5)** — never flip in any historical stationary / engine-off / engine-idle / rear-only-motion capture; only flip during the moving-1 and moving-2 ABS-extinguish events:

| Bit | Historical behaviour | Interpretation |
|-----|---------------------|----------------|
| `12A D0 b4` | HIGH in every stationary/engine-off session across the 15-session corpus | ABS lamp lit |
| `12A D1 b0` | HIGH in every session | ABS lamp lit |
| `12A D5 b3` | HIGH in every session | ABS lamp lit |
| `12E D6 b4` | LOW in every session | ABS lamp lit (inverted) |
| `12E D6 b5` | LOW in every session | ABS lamp lit (inverted) |

**Bit that was dropped (1)** — `12A D1 b2`. Behaviour across older captures is completely different from the other five:

- Rises 0 → 1 at ~ t+2s in almost every capture (probably an ignition/module-init handshake).
- Drops 1 → 0 at various later times: 63 s in [[2026-06-19-throttle-sweep-engine-off]], 68 s in side-stand toggle, 77 s in kill-switch toggle, 89 s in [[2026-06-19-gear-cycle-clutch]], 112.9 s in [[2026-06-24-front-wheel-hand-spin]] (engine off, front wheel to 11 km/h — ABS lamp did NOT extinguish per [[bike/dash-warning-lights]], yet this bit dropped anyway; direct proof it's not lamp state).
- Brief mid-session dips in engine-idle-runs.
- Its transition near the moving-1 ABS-extinguish event was coincidence: this bit was already fluctuating and happened to be in the "lit" polarity right before the ABS event, then dropped alongside the real lamp bits. Moving-2 caught it with 3 transitions vs 1 for the others — the first hint something was off.

Semantics of D1 b2 remain open. Rough guess: something ignition/module-side (bike-electrical-armed, engine-crank-permission-granted, or an ECU-node status flag) — but that's speculation. Put on the follow-up list at [[signal-12a-d1-bit2]] as a stub.

## Five bits, but is it five signals?

The five surviving bits are unlikely to be five independent flags in the ECU. All flip simultaneously; all agree on "lit vs extinguished" across the 15-session corpus; and the `12A`/`12E` split doesn't obviously map onto a functional decomposition. Simplest reading: this bike broadcasts the ABS self-test / lamp state redundantly, similar to how kill-switch is mirrored across `541 D2 b4`, `121 D5 b2`, `5B0 D0 b4` ([[signal-kill-switch]]). Possibly:

- **`12A` (3 bits at D0.4, D1.0, D5.3)** — an ABS-module status word where three closely-related flags (lamp, ABS-module-healthy, ABS-permission-to-drive?) are all initialised to 1 during startup and cleared together on first-motion self-test-pass.
- **`12E` D6 bits 4-5** — a second broadcast of the same or overlapping information at inverted polarity, on a different broadcasting node.

Not resolvable without a scenario that stresses them apart (ABS fault, dropped wheel-speed sensor, partial self-test failure).

## What this unblocks

- `12A` was an all-`?` byte previously ([[2026-06-30-unknown-byte-corpus-sweep]] shortlisted only D1 as a "moving byte"). This finding attributes bits in `12A` D0, D5 and D1 b0 — three previously-unknown bytes now partially decoded. (D1 b2 belongs to a separate signal, per the cross-check above.)
- `12E` was similarly all-`?` (shortlisted D6 as moving). D6 now has 2 attributed bits.

Rough coverage delta: `12A` and `12E` move from "0 attributed bytes each" to "3 and 1 partially attributed byte", respectively — unchanged by the D1 b2 cross-check demotion, since D1 remains partially attributed (b0 for ABS lamp, b2 for the separate signal that lives there).

## Open

- **Which bit is *the* ABS lamp, if any of the 5.** They agree here but haven't been disambiguated by a scenario where they might differ — an ABS-active event (hard brake to lockup), an ABS fault (drop a wheel-speed sensor), or a partial self-test failure. Dash-verified moving procedure with a mid-ride stop and re-crossing 6 km/h (planned in [[2026-07-22-first-moving-ride]] Follow-ups) would clarify whether the extinguished state is truly latched-until-key-cycle or whether it toggles on subsequent low-speed windows.
- **Exact extinguish threshold.** Both key-cycles here extinguished at the *first* front-wheel > 6 km/h crossing; the front trace only jumped through the threshold once (no fine-grained crossing capture at low speed). The dash-verified moving procedure's walking-pace phase pins this to ± 0.1 km/h.
- **KTM 690 cross-check.** ktm-can-decoder doesn't cover `12A` / `12E` — worth revisiting once we have this bike's mapping settled.
- **`12A D1 b2` semantics.** Deferred to [[signal-12a-d1-bit2]].

## Evidence

- [[2026-07-22-first-moving-ride]] moving-1 and moving-2 — two independent fresh-key-on ABS-extinguish events.
- [`scripts/first_moving_ride_abs.py`](../../../scripts/first_moving_ride_abs.py) — the initial hunt; found 6 candidates transitioning within ± 0.21 s of the first front-wheel 6 km/h rising crossing.
- [`scripts/first_moving_ride_abs_verify.py`](../../../scripts/first_moving_ride_abs_verify.py) — per-capture verification across the 5-file corpus.
- [`scripts/abs_lamp_crosscheck.py`](../../../scripts/abs_lamp_crosscheck.py) — 15-session historical cross-check that demoted `12A D1 b2` from the ABS-lamp bit-set.
- All 15 pre-2026-07-22 sessions in `logs/` — every stationary / engine-off / engine-idle / rear-only-motion capture confirms the 5 surviving bits stayed in "lit" polarity when the lamp was demonstrably lit.

See also: [[bike/dash-warning-lights]], [[signal-wheel-speed-front]], [[signal-kill-switch]] (analogous multi-ID mirror pattern), [[2026-06-30-unknown-byte-corpus-sweep]] (previous state of `12A` / `12E`), [[signal-12a-d1-bit2]] (the sibling signal we peeled off).
