# Status

**Phase:** 2 (decoder) complete → entering 3 (dashboard). Phase 5 groundwork running early — OEM-cluster removal gates the Phase 3 hardware design.

**Last touched:** 2026-08-02 — rider live-view observations scoped two findings and drafted two engine-off experiments: [[2026-08-02-torque-engine-off-gear-dependence]] (the `121` D0:D1 throttle threshold is neutral-only; in gear it pins at −36) and [[2026-08-02-qs-bits-lever-strain-engine-off]] (`121` D6 QS bits hold for 500 ms+ under incomplete *downshift* pressure engine-off, and stay silent on upshifts — against a perfectly symmetric up/down split in the ride corpus).

## Blocked on

Nothing — pick from Next actions.

## In progress

- **Rig is done and not in flux.** `can-logger` + `wifi-bridge` both shipped and on-bike-validated ([[2026-07-22-first-moving-ride]]); capture, analysis and OTA all have `bin/` wrappers. Commands: [`bin/README.md`](../bin/README.md). Operator's guide: [`docs/guides/capturing.md`](guides/capturing.md).
- **Decoding coverage.** Post-2026-07-24: 28 / 88 payload bytes carry a primary signal (was 22 pre-ride), 42 always-zero (was 3), 4 static non-zero, 9 D7 hash, 5 dup mirrors, **0 undecoded** (was 51). See [`docs/signals/coverage.md`](signals/coverage.md). Unknown structure now lives inside `S◐` cells and behind untested inputs on the always-zero cells — no more black-box bytes.
- **Load-axis interpretation open.** `540 D1` and `121 A/B` both respond to real load; whether they're MAP-like, torque-like, or fuel-injection-quantity-derived needs a controlled load capture (paired same-RPM/same-throttle in different gears, or coast-down runs).

## Next actions

Ordered by expected value; pick one.

1. **[[2026-07-29-x10-disconnect-boot-diff]]** — unplug X10 and capture three full boots (connected / disconnected / recovery) to find what the cluster contributes to ABS + QS init. Gates full OEM-dash removal; USB rig, not wifi-bridge (needs the pre-key-on head).
2. **Engine-off garage session, both experiments back-to-back (~40 min, stationary, no ride).** [[2026-08-02-torque-engine-off-gear-dependence]] then [[2026-08-02-qs-bits-lever-strain-engine-off]] — both correct claims currently written into `confirmed`/`provisional` findings, and the second is a stationary on-demand trigger for the QS bits.
3. **GPS-augmented next ride for wheel-speed LSB anchor.** Log phone GPS (1 Hz) alongside CAN on the next ride so we can cross-correlate GPS ground-truth speed with decoded wheel speed at highway speeds — pins the LSBs from ±10 % (rider-dash-observed) to ±0.3 %, promotes both wheel-speed findings from `provisional` back to `confirmed`. No special maneuvers required.
4. **[[2026-07-12-neutral-rpm-sweep]]** (**engine-on**) — five RPM setpoints in neutral (12 s each), matched to [[2026-06-23-engine-driven-rear-spin]], discriminates the throttle-vs-RPM axis for [[signal-fuel-injection-setpoint]] (with the load axis now known-active, this becomes the *cleaner* throttle-only reference to subtract from the load-inclusive rolling data).
5. **Coast-down capture** — planned as [[2026-07-23-coast-down]], freeform (no procedure YAML). Ride, close throttle in various gears, don't touch brake/clutch, let the bike coast. Confirms or refutes the signed-torque interpretation of `121 A/B` and pins the LSB in N·m if bike + rider mass is roughly known. Pairs cleanly with GPS logging from Next Action #3 (same ride).
6. **ABS fault / recovery session** — planned as [[2026-07-24-abs-fault-and-recovery]]. Rider knows how to induce a real ABS fault (disconnect a ground point + key-on) and clear it. Captures: fault state (disambiguates the 5 [[signal-abs-lamp]] bits), ABS-active hard-brake event (may surface an ABS-active bit and downstream substitute for the missing brake-input signal from [[2026-07-10-brakes-stationary]]), fault-clear transition. Secondary check on [[signal-ride-mode]] under fault conditions (via the recovery sequence's mode cycling). Freeform, four phases.
7. **[[2026-07-24-cluster-fuse-pull]]** — F2 is the manual's combination-instrument fuse and feeds X10 pin 1 (permanent backup rail); the dash's *main* supply is pin 2 on the F7 rail, so an F2 pull likely leaves the cluster on the bus and lands its outcome 1. Action #1 tests ownership directly instead.
8. **[[2026-06-24-fuel-level-walkdown]]** — queued to falsify the off-bus assumption in [[project-fuel-on-can]]. Fuel *consumption* on CAN is already closed ([[fuel-consumption-absent-from-broadcasts]]); this is about level only.
9. **Follow-ups from the 2026-07-22 sub-analyses** — the `12A D1 bit 2` extra-transitions in moving-2 (see [[signal-abs-lamp]] Open); the `121 D6` bits 2-7 (0 across the corpus — need a rev-limiter or wheelie-cut scenario to exercise). ~~[[byte-12d-d3-d4-front-mirror]] LSB re-fit~~ closed 2026-07-22 (0.0577 km/h/LSB, promoted to `confirmed`).

## Open questions (from `docs/research.md`)

1. Can the OEM dashboard be completely disconnected?
2. Does the ECU expect messages from the dashboard?
3. How similar is the KTM 390 CAN map to the KTM 690 CAN map?
4. Which signals are already available as broadcasts?
5. How are ROAD/SUPERMOTO commands transmitted?

## Where things live

- Findings — `docs/findings/<area>/` (current-best knowledge, rewritten on contradiction).
- Experiments — `docs/experiments/YYYY-MM-DD-slug.md` (includes failures; never deleted).
- Decisions — `docs/decisions/NNNN-slug.md` (superseded, not deleted).
- Raw captures — `logs/YYYY-MM-DD-<condition>/` (immutable).
- Signals — `docs/signals/` (canonical definitions, coverage map).
- Hardware — `docs/hardware/`.
