---
area: can
status: confirmed
established_by:
  - 2026-06-17-engine-idle-baseline-x3
  - 2026-06-17-key-on-cold-boot
  - 2026-06-19-kill-switch-toggle
  - 2026-06-19-throttle-sweep-engine-off
  - 2026-06-19-gear-cycle-clutch-B-gear-cycle
  - 2026-06-30-unknown-byte-corpus-sweep
---

# Engine-off seconds counter — `541` byte D6

`541` byte D6 is a **1 Hz 8-bit modulo-256 counter** that ticks while the engine is off and is held at `0x00` while the engine is running. Natural complement to the engine-on counter at [[signal-engine-on-counter]] on the same byte position one over (D4) — both are 1 Hz, both 8-bit, opposite engine-state gating.

| State | D6 behaviour |
|-------|------|
| Engine OFF (key on, kill RUN) | Ticks +1 per second, wraps `255 → 0 → 1 → ...` |
| Engine OFF (key on, kill STOP) | Ticks identically — gating is on engine-running, not kill-switch position |
| Engine ON | Snaps to `0x00` within one broadcast period of starter press, holds at `0x00` throughout the engine-running window |
| Post-kill (engine just stopped) | Stays at `0x00` through the ≤ 7 s `541` broadcast decay tail observed in [[post-kill-decay-groups]]. Whether it stays at `0` or resumes counting after a longer engine-off interval is not yet captured. |

The bit-width is the full 8 bits (no reserved high bit, unlike D4 which reserves bit 7 — see [[signal-engine-on-counter]]). The wraparound period is exactly 256 s.

## Evidence

### 1 Hz tick rate

All 14 sessions in [[2026-06-30-unknown-byte-corpus-sweep]] show D6 stepping by exactly +5 (median) per 5-second bin during engine-off windows — every session, every bin, no exceptions. Sample from the cold-boot baseline (no kill toggles, no rider input):

| capture-relative t (s) | D6 median | D6 min..max |
|---|---:|---|
|   0 |  18 |  15 .. 20 |
|   5 |  23 |  20 .. 25 |
|  10 |  28 |  25 .. 30 |
|  50 |  68 |  65 .. 70 |
| 100 | 118 | 115 .. 120 |
| 150 | 168 | 165 .. 170 |
| 170 | 187 | 185 .. 188 |

The min..max spread of 5 per bin is exactly what a 1 Hz counter produces under 5-second binning. No drift, no irregular ticks.

### Wraparound at 256

Two sessions caught the rollover:

| Session | Rollover time (rel) | Values bracketing wrap |
|---|---:|---|
| 2026-06-19-gear-cycle-clutch-B-gear-cycle | ~57 s | `… 252, 253, 254, 255, 0, 1, 2 …` |
| 2026-06-19-throttle-sweep-engine-off    | ~62 s | `… 252, 253, 254, 255, 0, 1 …` |

Same byte-wrap signature as a plain mod-256 8-bit counter. No saturation; no skip-zero artifacts.

### Snap-to-zero at engine-on

Idle-baseline run 1 ([[2026-06-17-engine-idle-baseline-x3]]): D6 reads `42` at t = 25 s (5 s before starter press), reaches `45` at the starter mark (t = 30 s), then drops to `0` within the next broadcast period and stays at `0` for the entire 180 s engine-running window. Same shape in idle-2 (`78 → 0`) and idle-3 (`30 → 0`).

### Kill-toggle behaviour confirms gating is on engine-running, not kill-switch position

[[2026-06-19-kill-switch-toggle]] is engine-off throughout, with the kill switch toggled between RUN and STOP. D6 ticks continuously across every kill-switch transition — neither toggle direction interrupts or resets the counter. The state gate is "engine running ≠ true", not "kill switch == RUN".

### Post-kill: stays at 0 within the broadcast decay tail

The idle-x3 captures end ~6 s after kill; D6 reads `0` for every frame of that tail. Consistent with two readings: (a) the counter only resumes after a longer engine-off interval than the `541` broadcast decay (≤ 7 s per [[post-kill-decay-groups]]) lets us see, or (b) it resumes immediately but the 0-value tail happens to coincide with the decay. Disambiguator would be a capture with a deliberate >15 s post-kill engine-off pause before bus silence — out of current corpus.

## Cross-walk

`541` D4 + D6 together form a pair of complementary 1 Hz counters on the same arbitration ID:

| Byte | Counter | Bits | Engine state where it ticks | Wrap |
|---|---|---|---|---|
| D4 | engine-ON seconds  | 7 (b0..b6; b7 reserved) | engine running | 128 s ([[signal-engine-on-counter]]) |
| D6 | engine-OFF seconds | 8 (all bits)            | engine off (key on) | 256 s |

Both reset to `0x00` at the boundary of their gating condition. Both are frozen when the other is active. Same broadcast period (`541` is 20 ms — see [[always-on-broadcast-ids]]).

## What this rules out

- **`541` D6 is not throttle-derived.** [[2026-06-30-unknown-byte-corpus-sweep]] tested r vs throttle across the whole corpus — best was `r = +0.40` in the throttle-sweep engine-off session, dominated by D6's monotonic ramp coinciding with the rider's slow sweep. Below the cycle-hash exclusion threshold. Closes the open question in [[signal-throttle-position]].
- **Not a wheel-speed broadcast.** Best wheel_front correlation = +0.504 (a different session-coincidence artifact).
- **Not battery voltage.** The shape — monotonic ramp engine-off, snap-to-zero engine-on — is the opposite of what an alternator-regulated voltage signal would do. Already noted as side-finding in [[battery-voltage-absent-from-always-on-broadcasts]]'s scan output.

## Status

**Confirmed.** Encoding, gating, wrap behaviour all reproduced across 14 sessions and ~50 000 `541` frames in [[2026-06-30-unknown-byte-corpus-sweep]]. The only remaining open is whether the counter resumes after a longer engine-off interval following a kill (not within current corpus).

## Open

- **Long post-kill behaviour.** Does D6 resume ticking after a >15 s engine-off interval following a kill, or does it require a full key-cycle? Not testable from current captures — `541` goes silent within ~7 s of kill ([[post-kill-decay-groups]]).
- **Semantic interpretation.** The counter exists for *some* ECU purpose — candidates include sleep/standby timer, immobilizer heartbeat, or diagnostic logging. Doesn't affect the dashboard's use of the signal; flagged here for completeness.

## Use for the dashboard

D6 gives the live dashboard a precise "seconds since key-on, while engine off" timeline at no decode cost. Useful for:

- **Cold-start vs hot-restart classification.** If D6 is small (< ~20 s) at engine-start, this is likely a hot restart; if large (> ~60 s) the rider keyed-on and waited (cold-start setup).
- **Wait-time UX cues.** A "you've been keyed-on for N seconds without starting" indicator could nudge battery-conservation behavior — the dashboard knows it without needing its own clock.
- **Hours-meter integration.** Combined with [[signal-engine-on-counter]], the dashboard has a complete second-resolution accounting of every keyed-on minute, partitioned by engine-running vs engine-off.

## Evidence

- [[2026-06-17-engine-idle-baseline-x3]] — 3 engine-on snap-to-zero observations + pre-starter ramp shape.
- [[2026-06-17-key-on-cold-boot]] — 173 s engine-off ramp from D6 = 15 to D6 = 188 (rate exactly 1 Hz).
- [[2026-06-19-kill-switch-toggle]] — confirms kill-switch position doesn't reset or pause D6.
- [[2026-06-19-throttle-sweep-engine-off]] and [[2026-06-19-gear-cycle-clutch-B-gear-cycle]] — both caught the 255 → 0 wraparound.
- [[2026-06-30-unknown-byte-corpus-sweep]] — flagged D6 as the most-active byte on the bus (moves in 14/14 sessions, no correlation with any decoded signal at |r| ≥ 0.9), triggering this characterisation.
- [`scripts/id541_d6_characterise.py`](../../../scripts/id541_d6_characterise.py) — per-session 5-second-bin time-series, rate calculation, wrap detection.

See also: [[signal-engine-on-counter]] (paired counter at D4), [[always-on-broadcast-ids]], [[post-kill-decay-groups]].
