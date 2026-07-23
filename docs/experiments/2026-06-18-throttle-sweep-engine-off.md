---
date: 2026-06-18
status: confirmed
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/post-kill-decay-groups
    - can/signal-throttle-position
    - can/byte-d7-cycle-hash
  references:
    - ktm-can-decoder
  experiments:
    - 2026-06-17-payload-diff-idle
  logs:
    - 2026-06-19-throttle-sweep-engine-off
---

# Throttle sweep, engine off — decode `120` D2 and surrounding throttle flags

## Hypothesis

Three KTM hypotheses converge on the throttle input:

1. **`120` D2 = throttle position, 0–255** (full scale across the grip travel). The byte read static `0x00` across the idle baseline because the throttle was always closed. A slow sweep should produce a clean monotone in this byte.
2. **`12A` D0 bit 1 = throttle-open flag** (1 = open, 0 = closed). The byte read static `0x10` at idle (bit 4 set, bit 1 clear) — consistent with the throttle being closed. Cracking the throttle should flip bit 1 to 1; releasing should flip it back. Hysteresis is plausible — the flag may engage at a finite grip angle, not the first 1/256.
3. **`12A` D1 bit 6 = requested map / ride-by-wire state.** `12A` D1 was LOW-CARD(2) at idle, value flipping between two states. KTM ties bit 6 to map selection. With the engine off and the throttle moving, bit 6 may not change — or it may, if the ECU re-evaluates the requested map whenever pedal position changes. Either outcome is informative.

Doing the sweep **engine off** isolates the throttle-position channel from RPM and torque feedback. With the engine off, `120` D0,D1 (RPM) is `0x0000` — so any byte that moves with the throttle in this capture is throttle-related, not RPM-driven. Engine-on confirmation comes later in [2026-07-12-neutral-rpm-sweep](2026-07-12-neutral-rpm-sweep.md).

## Setup

- Bike: 2020 Husqvarna Svartpilen 401, side stand down, neutral, **engine off** throughout.
- Key on (position 1). Kill switch in run position (does not affect bus with engine off).
- The throttle is ride-by-wire on this bike — there is no mechanical linkage from grip to throttle plate. The ECU samples the grip-position sensor and broadcasts it regardless of whether the engine is running, so this capture is meaningful even with no combustion happening.
- Adapter / firmware / host as per kill-switch capture above.

## Procedure

1. Key off, plug adapter.
2. Start capture: `python scripts/capture.py --port /dev/cu.usbmodem101 --label throttle-sweep-engine-off`.
3. Wait 5 s key-off baseline.
4. Key on. Press **space** at key-on. Wait 30 s for dash self-test and steady key-on-engine-off state.
5. Sweep sequence. **Rule:** press **`t`** once at the start of each phase below, then execute that phase as one continuous motion. The throttle trace itself marks the internal boundaries (ramp vs. hold vs. ramp), so you don't need wall-clock marks for them.
   1. `t`, then **slow sweep:** open 0 → WOT over ~6 s, hold ~3 s at WOT, close WOT → 0 over ~6 s, hold ~3 s closed. One smooth, continuous motion.
   2. `t`, then **step response:** snap to WOT in <0.5 s, hold ~3 s, snap to 0 in <0.5 s, hold ~3 s closed.
   3. `t`, then **reproducibility ramp:** repeat the slow sweep from phase 1 (open, hold, close, hold).

   Total: 3 `t` presses.
6. Key off. Wait 2 s. `q` to stop.
7. `session.md` — note any dash-side reaction (any indicator lighting, EOBD light flicker, throttle-position dot on the dash if present), and any sense of throttle stop/dead-band at either end.

Slow ramps are the prize — they make `120` D2 sweep through every value cleanly, so any nonlinearity (compression near WOT, dead-band near 0, scale factor) is visible. Fast blips test latency / step-response and may surface filter-derivative bytes if the ECU broadcasts a derivative.

## Analysis plan

1. **`120` D2 sweep check.** Plot D2 value over time during the slow ramps. Expect a smooth ramp 0 → ~255 → 0. Note:
   - actual min / max values (is full scale really 0–255, or 0–200 like some KTM dyno maps?),
   - dead-band at zero (first N counts may be flat as the sensor crosses a sentinel),
   - any inflection or knee (could indicate a non-linear map between grip angle and broadcast value).
2. **Map `120` D2 to grip percentage.** Since the rider drove a roughly linear sweep, the broadcast curve should be roughly linear too. Significant non-linearity in the broadcast is a mapping/encoding finding.
3. **`12A` D0 bit 1 flag.** Plot bit 1 against `120` D2 value. Find the threshold where bit 1 = 1. Hysteresis check: does the on-threshold equal the off-threshold, or is there a band?
4. **`12A` D1 bit 6.** Tabulate value over the whole capture. Did it move? If so, is the motion correlated with throttle position, or independent (a periodic toggle / housekeeping)?
5. **Bus-wide diff.** Any other byte that moves with throttle position. Candidates already flagged at idle as UNKNOWN or LOW-CARD: `121` D7 (UNKNOWN), `541` D6 (UNKNOWN), `12D` D7 (LOW-CARD(7)). Check whether their value distribution correlates with the sweep.
6. **Engine-off invariants.** Sanity: `120` D0,D1 should remain `0x0000` throughout. Coolant temp at `540` D5,D6 should sit at ambient. Anything moving in those bytes is a flag-on-the-experiment, not a finding.

## Expected outcomes

- **`120` D2 sweeps cleanly with the grip** → promote to [`docs/findings/can/signal-throttle-position.md`](../findings/can/signal-throttle-position.md) as `confirmed`. Record encoding (linear, scale, any dead-band) and the engine-off baseline value at closed.
- **`12A` D0 bit 1 toggles with the throttle** at some threshold → promote to a flag finding alongside.
- **`12A` D1 bit 6 does not move** → KTM map-bit hypothesis is unconfirmed by this experiment but not refuted (engine off may suppress it). Re-test engine-on.
- **Some unexpected byte moves with throttle** → log it; may be a torque-demand or pedal-rate byte not present in the KTM decoder.

## Follow-ups

- Engine-on throttle blip (in [2026-07-12-neutral-rpm-sweep](2026-07-12-neutral-rpm-sweep.md), Phase D) to confirm the engine-off decoding holds engine-on; `12A` D1 bit 6 is re-probed there and (via the mode toggle in [2026-07-12-dash-inputs](2026-07-12-dash-inputs.md), Phase A).
- If `120` D2 encoding is non-linear, that's a `docs/findings/can/` entry on its own — important for the dashboard's throttle gauge.

## Result (2026-06-19)

Capture: [`logs/2026-06-19-throttle-sweep-engine-off/`](../../logs/2026-06-19-throttle-sweep-engine-off/) — 26 838 frames over ~76 s, three throttle-blip event marks separating phase 1 (slow sweep), phase 2 (step response), phase 3 (reproducibility ramp). One `l` keypress at 12:10:45 is a misclick, ignored (recorded in `session.md`).

Analysis re-derivable with `python scripts/throttle_sweep.py`.

### Hypothesis 1 — `120` D2 = throttle position (0–255)

**Confirmed**, with a refinement: full scale is **254, not 255**. D2 swept cleanly through 166 distinct values 0..254 across the slow sweep, monotonically with the rider's grip motion. Closed throttle broadcasts exact `0x00`, wide open broadcasts `0xFE`. Promoted to [[signal-throttle-position]].

### Hypothesis 2 — `12A` D0 bit 1 = throttle-open flag

**Refuted.** Zero transitions across the entire 53 s capture (53 s including all three phases), despite the throttle traversing its full range nine times (open-hold-close-hold-snap-hold-snap-hold-open-close-… etc). Whatever this bit encodes, it is not "throttle off the stop". The KTM hypothesis at this bit position does not transfer to Husqvarna.

### Hypothesis 3 — `12A` D1 bit 6 = requested map / RBW state

**Unconfirmed (as predicted).** Bit is 0 across all 994 `12A` frames in the capture, all three phases. The hypothesis predicted this might happen with the engine off (the ECU may not re-evaluate map state when not running); re-test in [2026-07-12-dash-inputs](2026-07-12-dash-inputs.md) (Phase A mode toggle) and [2026-07-12-neutral-rpm-sweep](2026-07-12-neutral-rpm-sweep.md) (Phase D blips).

### Bonus hypothesis that surfaced mid-analysis: `120` D7 = APP2 (dual-sensor pedal)

**Refuted.** D7 ranged 32–223 with 186 unique values across the same window where D2 swept 0–254, which superficially looked like a candidate second throttle channel (ride-by-wire systems normally have two grip-position sensors for safety). But frame-by-frame Pearson correlation of D7 vs D2 across all 3 183 `120` frames gives r = **−0.012**, and D7's mean stays pinned at ~125–132 across every D2 bin from 0 to 254. The throttle channel does not co-broadcast at this connector; either APP2 lives only on the ECU's internal bus, or it isn't broadcast at all on the diagnostic stub.

### Engine-off invariant

`120` D0,D1 (RPM, see [[signal-rpm]]) read exact `0x00 0x00` across all 3 183 `120` frames. RPM channel is fully decoupled from throttle in the broadcast layer.

### Side finding — D7 looks like a checksum

The bus-wide range scan surfaced a striking pattern: D7 across 9 of the 11 always-on IDs has a value-set cardinality that scales with how much the rest of the payload moves. Mostly-static IDs (`129`, `12A`, `12D`, `12E`, `5A0`, `5B0`) all show exactly **6 unique D7 values**; active-payload IDs (`120`, `541`, `121`) show 12–186. Consistent with a checksum or hash over D0..D6, ruling out a free-running counter. Promoted as an observation with the CRC interpretation as the leading hypothesis: [[byte-d7-cycle-hash]].

### Weak lead — `541` D6

Pearson r = +0.26 vs `120` D2 (zero-order hold on D2). Could be coincidental drift over the capture window, or a heavily filtered throttle-derived signal. Range only 20 counts — too weak to promote, not weak enough to discard. Re-test with a longer / multi-direction sweep before making a call.
