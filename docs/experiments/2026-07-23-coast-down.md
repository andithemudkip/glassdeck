---
date: 2026-07-23
status: planned
phase: 1
related:
  findings:
    - signal-engine-torque
    - fuel-consumption-derivation-from-torque
    - signal-fuel-injection-setpoint
  decisions: []
  logs: []
---

# Coast-down capture — verify signed-torque interpretation of `121 A/B`

## Hypothesis

If `121 D0:D1` (channel A) really carries signed engine torque, then during a coast-down (throttle closed, in gear, no brake, no clutch — engine spun by the wheels via the drivetrain) two things should be true:

1. **`121_A` should be strongly negative** throughout the coast — engine is producing negative net torque (drivetrain drag) as the wheels drive it against its own internal friction and pumping losses.
2. **At matched RPM in different gears, `121_A` should read the same value** — engine-brake torque is a property of the engine at that RPM, not the gear. This is the discriminator against alternate interpretations like "load-derived" or "throttle-derived with idle offset". Load and gear-ratio effects diverge sharply across gears; engine torque doesn't.

If both hold, we upgrade [[signal-engine-torque]] from `provisional, signed-torque candidate` to `confirmed`. If only (1) holds, `121_A` is signed but not pure engine torque — maybe wheel torque or some cross-mixed quantity. If neither holds, the signed-torque hypothesis is dead and we owe the finding another rewrite.

A cheap secondary outcome: with rider mass + bike mass + rough aero drag known, the coast-down deceleration rate + the RPM trace at each moment gives us engine-brake torque in physical units (N·m). Compare against the raw `121_A` value at that moment to solve for the **LSB in N·m/LSB**. Currently the working estimate is 0.25 N·m/LSB but that was derived circularly from the fuel-consumption model. This measurement is independent.

Also gets checked alongside: [[signal-fuel-injection-setpoint]] `540 D1` behaviour during coast (does it drop toward the coolant-keyed idle baseline as expected, or does it stay elevated?), and the `121 D6` shift-cut bit's out-of-window baseline holds (it shouldn't fire during coast-only).

## Setup

- Bike + rider fully warmed (coolant at operating temp) — cold-start coolant offset on `540 D1` would confound.
- Firmware: `wifi-bridge` latest on `master` (as of 2026-07-22, commit `58a5d95` or newer).
- Capture path: standard phone-side WiFi capture as on 2026-07-22.
- **GPS on the phone if the capture app supports concurrent logging** — this is the wheel-speed LSB anchor from status.md Next Action #1, and it pairs perfectly with coast-down (gives us absolute deceleration for the LSB-in-N·m calculation). If the app doesn't do concurrent GPS, log GPS separately in a second app (Strava, whatever); we'll cross-reference by clock time after the fact.
- Anything you can jot down or remember afterward that helps: rider weight (with gear), any panniers/luggage, tyre pressure if known.

## Procedure — freeform

The core observation you need to produce is: **a stretch of time where you're in a gear, throttle fully closed, not touching brake or clutch, and the bike is decelerating from a decent speed down to a low one.** Repeat that shape in a few different gears.

Rough shape of the ride:

1. Start capture, ride normally until engine is fully warm and you feel comfortable / traffic-clear.
2. Find a flat, straight, empty stretch — flat is important (grade adds an unknown force), empty is safety.
3. Whenever it's safe, close the throttle in whatever gear you happen to be in and just let the bike coast. Don't touch the brake or the clutch. Let RPM/speed drop until it feels awkward (bike getting close to idle-in-gear feeling, or you need to intervene for traffic, or the section ends).
4. Roll on throttle or brake normally to end the coast. Then set up for the next one — maybe upshift or downshift into a different gear once you're back up to speed, and repeat.
5. Spread the coasts across gears — 2nd, 3rd, 4th, 5th all give useful data. Skip 1st (too aggressive) and 6th (engine brake is very weak, coast is dominated by aero drag). Getting each of 2/3/4/5 at least twice is ideal but not necessary.
6. Stop capture whenever you're done or need to head back.

**No fixed setpoints, no timing marks, no rider decisions to make mid-manoeuvre.** The clean coast-downs will be auto-detected from the CAN trace (throttle = 0, RPM > idle, no clutch bit, no brake — wait, we don't have brake on CAN yet, so we rely on the deceleration curve being smooth without brake intervention).

**Number of good coasts needed:** 5-6 across at least 3 different gears gets us a solid answer. More is fine; less is workable if the data is clean.

**Ideal coast length:** ~ 5 seconds is enough. Longer (10-15 s) is better because it lets RPM sweep through a wider range in a single coast, which strengthens the "torque vs RPM curve" fit for that gear. But don't force it if traffic doesn't let you.

**Things that would confound a coast — toss it in analysis, no big deal:**

- Uphill / downhill grade (any noticeable slope). Skip these.
- Strong wind or gusts.
- Rider input mid-coast — brake tap, clutch, throttle blip.
- Cornering — lean angle changes the effective drag.
- Rough surface — chip-seal, gravel, pothole.

Analysis will auto-flag coasts that have irregular deceleration curves; you don't need to be perfect on the road.

## What to note afterward (optional, but helps analysis)

Rider mental notes are enough — nothing to write down in the moment. After the ride, jot down or tell me:

- Roughly how many coast-downs you did.
- Any coasts you specifically remember being wonky (had to brake mid-coast, hit wind, whatever) so we can look at them specifically.
- Your weight in riding gear (rough is fine — ±5 kg doesn't hurt the LSB calc).
- Tyre pressures if you know them (optional).

If the ride is otherwise nothing special — no dash warnings, no new noises, no rider-observed dash weirdness — you don't need to write a full ride summary.

## Result

_To fill after the ride._

Auto-detected coast-downs (throttle=0 AND RPM > 2000 AND monotonic speed drop for ≥ 3 s):

_TBD._

Per-coast analysis and cross-gear comparison of `121_A` at matched RPM:

_TBD._

## Interpretation

_To fill after analysis. Expected patterns and their implications:_

- **`121_A` cleanly negative + agrees across gears at matched RPM** ⇒ signed-torque hypothesis confirmed. [[signal-engine-torque]] promotes to `confirmed`; [[fuel-consumption-derivation-from-torque]] calibration LSB anchored.
- **`121_A` negative but disagrees across gears** ⇒ signal is signed but not pure engine torque. Candidate reinterpretations: wheel torque estimate (would scale with gear ratio) or something else.
- **`121_A` doesn't go strongly negative in coast** ⇒ signed-torque interpretation fails. Back to the drawing board on [[signal-engine-torque]].
- **`540 D1` walks down toward coolant-baseline during coast** ⇒ reinforces "D1 is throttle+load-derived, drops toward idle baseline under no-throttle-no-load" reading. Doesn't confirm any specific interpretation but rules out "D1 is coolant-only".

## Follow-ups

- If the signed-torque interpretation confirms: rewrite [[signal-engine-torque]] as `confirmed`, rename `signal-engine-torque` or similar, add LSB in N·m to `signals.yaml`. Update the fuel model constants in [[fuel-consumption-derivation-from-torque]] and [[project-fuel-consumption-derivation]] memory.
- If GPS was captured concurrently: independently pin the wheel-speed LSBs from status.md Next Action #1. Two experiments closed in one ride.
- If the coast surfaces any anomalous behaviour on other bytes (moving-byte candidates that fire only under overrun, e.g. `121 D6` bits 2-7 which are 0 in normal operation), note them here and open a follow-up.
