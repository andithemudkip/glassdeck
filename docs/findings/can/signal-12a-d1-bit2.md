---
area: can
status: provisional
established_by:
  - 2026-07-22-first-moving-ride
---

# `12A` D1 bit 2 — module-armed / ignition-state candidate (semantics open)

`12A` D1 bit 2 broadcasts a signal that is *not* the ABS lamp state ([[signal-abs-lamp]]) despite briefly co-transitioning with the ABS-lamp bits during the moving-1 event. Its actual behaviour across the full 15-session corpus is distinct enough to warrant a separate finding, but too varied to pin a specific semantic on without a targeted experiment.

```
d1_b2 = (data[1] >> 2) & 1
```

## Observed pattern across every historical session (`scripts/abs_lamp_crosscheck.py`)

| Session | t+0 val | Transitions after t+0 (t+s → new val) | Notes |
|---------|:-------:|---------------------------------------|-------|
| 2026-06-17-key-on-cold-boot | 0 | → 1 @ t+2.0 | init handshake at ~2s |
| 2026-06-17-engine-idle-run-1 | 0 | → 1 @ 2.0, → 0 @ 30.6, → 1 @ 32.7, → 0 @ 215.6 | brief mid-session dip + late drop |
| 2026-06-17-engine-idle-run-2 | 0 | → 1 @ 2.0, → 0 @ 29.6, → 1 @ 31.6, → 0 @ 213.1 | same pattern |
| 2026-06-17-engine-idle-run-3 | 0 | → 1 @ 2.0, → 0 @ 32.5, → 1 @ 34.5, → 0 @ 216.3 | same pattern |
| 2026-06-19-gear-cycle-clutch-A | 0 | → 1 @ 2.0, → 0 @ 89.2 | drop mid-session |
| 2026-06-19-gear-cycle-clutch-B | 0 | → 1 @ 2.0, → 0 @ 71.1 | drop mid-session |
| 2026-06-19-kill-switch-toggle | 0 | → 1 @ 2.0, → 0 @ 77.9 | possibly correlated with kill toggle |
| 2026-06-19-side-stand-toggle | 0 | → 1 @ 2.0, → 0 @ 68.6 | possibly correlated with side-stand |
| 2026-06-19-throttle-sweep-engine-off | 0 | → 1 @ 2.0, → 0 @ 63.5 | drop with no obvious rider action |
| 2026-06-22-wheel-spin-paddock-stand | 0 | → 1 @ 2.0 (stays 1) | short session; drop never reached |
| 2026-06-23-engine-driven-rear-spin | 0 | → 1 @ 2.0, → 0 @ 30.5, → 1 @ 32.5, → 0 @ 287.4 | same brief-dip + late-drop pattern |
| 2026-06-23-shift-lever-vs-clutch | 1 | (no transitions) | capture started post-init |
| 2026-06-24-front-wheel-decay-mark | 0 | → 1 @ 2.0 (stays 1) | short session |
| **2026-06-24-front-wheel-hand-spin** | 0 | → 1 @ 2.0, **→ 0 @ 112.9 (engine off, front wheel spinning to ~11 km/h)** | proof it's NOT ABS lamp — lamp stayed lit in this session per [[bike/dash-warning-lights]] |
| 2026-07-10-brakes-stationary | 1 | (no transitions) | capture started post-init |
| moving-1 (2026-07-22) | 1 | → 0 @ 93.0 | dropped *at the same time as the ABS-lamp bits* — coincidence |
| moving-2 (2026-07-22) | 1 | 3 transitions | this was the flag that first hinted D1 b2 wasn't the ABS lamp |

## What we know

- **Not the ABS lamp.** The 2026-06-24 front-wheel-hand-spin (engine off, front wheel to ~11 km/h) drops D1 b2 to 0 while the physical ABS lamp stays lit. If D1 b2 were the lamp, it wouldn't flip during a lit condition.
- **~t+2 s rise across every capture that starts pre-init** — some kind of ECU/module handshake / bike-electrical-armed / ignition-state-permission that becomes true 2 seconds after key-on. If your capture starts post-init, you see D1 b2 already at 1.
- **Later transitions are session-specific.** Some sessions have brief mid-session dips (idle runs at ~30-32 s in), some have a long-term drop at variable times, some have both.

## Candidate meanings (all speculative)

- **Ignition-armed / start-permission bit.** Would rise when the ignition switch fully powers the ECU (~2 s handshake) and drop when some downstream fault or user-input clears the arm. Would predict the drop correlates with kill-switch STOP, side-stand DOWN, etc. — worth cross-checking with existing kill-switch and side-stand captures.
- **Module heartbeat / self-test cycle.** Brief mid-session dip at ~30 s could be a periodic self-test cycle. Late drop at ~200+ s could be an ECU state timeout.
- **Some safety-interlock derivative.** The kill/side-stand toggle sessions dropped D1 b2 mid-session; if it tracks either input's raw state (before combining), that would fit.

None are testable without a targeted experiment that varies exactly one input at a time and marks the bit trace against the input.

## Discriminating experiments (all cheap, none run)

- **Kill-switch STOP with engine off, watch D1 b2.** If it drops when kill goes STOP, then D1 b2 is kill-derived (a fourth mirror of [[signal-kill-switch]], though at a different polarity than the known three). Cross-check against the existing 2026-06-19-kill-switch-toggle session's events.csv would settle this.
- **Side-stand down with engine off, watch D1 b2.** If it drops when the side-stand goes DOWN, then D1 b2 is side-stand-derived — but [[signal-side-stand]] is already at `540` D3 b0. Would be a redundant mirror at inverted polarity.
- **Long-duration engine-idle capture past 300 s.** If the late drop is a timer, this pins the timeout. If it's random, no timer.

## Why this got sucked into the ABS-lamp finding

The classifier used to identify the ABS-lamp bits ([`scripts/first_moving_ride_abs.py`](../../../scripts/first_moving_ride_abs.py)) matched on: initial value, transition timing near the wheel-speed threshold crossing, and post-crossing value. D1 b2 happened to be in the "matching" state at moving-1 t+0 (1 = "lit" polarity) and dropped near the crossing, so it scored high. What the classifier didn't check — but the historical cross-check does — is whether the bit was in that state *because* of any ABS-lamp reason. It wasn't; it was in that state because of whatever its actual semantic is, which happened to coincide.

## Evidence

- [`scripts/abs_lamp_crosscheck.py`](../../../scripts/abs_lamp_crosscheck.py) — the multi-session dump above.
- Every session in `logs/` from 2026-06-17 onwards.
- [[signal-abs-lamp]] — the finding that peeled this bit off.

See also: [[signal-kill-switch]], [[signal-side-stand]], [[always-on-broadcast-ids]].
