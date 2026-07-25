# Status

**Phase:** 1 — CAN logger / capture inventory.

**Last touched:** 2026-07-24 — [[2026-07-24-abs-mode-toggle]] landed [[signal-ride-mode]] at `confirmed`: ROAD/SUPERMOTO is a two-bit mirror at `12A` D2 b1 (primary) and `450` D4 b7 (mirror), 0=ROAD, 1=SUPERMOTO, semantic = rear-ABS-enable. Also breaks `450` out of its previously-static state (see coverage.md). Active-TX probe deferred pending an ADR.

## Blocked on

Nothing — pick from Next actions.

## In progress

- **Firmware.** `can-logger` v1 shipped, listen-only @ 500 kbps. `wifi-bridge` M1–M6 + M7a shipped + on-bike-validated by [[2026-07-22-first-moving-ride]]; RX pinned to core 1 for WiFi-coexistence, see [[wifi-vs-can-core-partitioning]]. Shared `firmware/lib/{twai,slcan,status_led}/` used by both targets. Iteration: OTA reflash via `POST /ota`; live capture via `websocat -n ws://192.168.4.1/stream | scripts/capture.py --stdin`.
- **Capture tooling.** `scripts/capture.py` end-to-end; `scripts/inventory_ids.py` derives per-ID counts/periods. Operator's guide at [`docs/guides/capturing.md`](guides/capturing.md).
- **Decoding coverage.** Post-2026-07-24: 28 / 88 payload bytes carry a primary signal (was 22 pre-ride), 42 always-zero (was 3), 4 static non-zero, 9 D7 hash, 5 dup mirrors, **0 undecoded** (was 51). See [`docs/signals/coverage.md`](signals/coverage.md). Unknown structure now lives inside `S◐` cells and behind untested inputs on the always-zero cells — no more black-box bytes.
- **Load-axis interpretation open.** `540 D1` and `121 A/B` both respond to real load; whether they're MAP-like, torque-like, or fuel-injection-quantity-derived needs a controlled load capture (paired same-RPM/same-throttle in different gears, or coast-down runs).

## Next actions

Ordered by expected value; pick one.

1. **GPS-augmented next ride for wheel-speed LSB anchor.** Log phone GPS (1 Hz) alongside CAN on the next ride so we can cross-correlate GPS ground-truth speed with decoded wheel speed at highway speeds — pins the LSBs from ±10 % (rider-dash-observed) to ±0.3 %, promotes both wheel-speed findings from `provisional` back to `confirmed`. No special maneuvers required.
2. **[[2026-07-12-neutral-rpm-sweep]]** (**engine-on**) — five RPM setpoints in neutral (12 s each), matched to [[2026-06-23-engine-driven-rear-spin]], discriminates the throttle-vs-RPM axis for [[signal-fuel-injection-setpoint]] (with the load axis now known-active, this becomes the *cleaner* throttle-only reference to subtract from the load-inclusive rolling data).
3. **Coast-down capture** — planned as [[2026-07-23-coast-down]], freeform (no procedure YAML). Ride, close throttle in various gears, don't touch brake/clutch, let the bike coast. Confirms or refutes the signed-torque interpretation of `121 A/B` and pins the LSB in N·m if bike + rider mass is roughly known. Pairs cleanly with GPS logging from Next Action #1 (same ride).
4. **ABS fault / recovery session** — planned as [[2026-07-24-abs-fault-and-recovery]]. Rider knows how to induce a real ABS fault (disconnect a ground point + key-on) and clear it. Captures: fault state (disambiguates the 5 [[signal-abs-lamp]] bits), ABS-active hard-brake event (may surface an ABS-active bit and downstream substitute for the missing brake-input signal from [[2026-07-10-brakes-stationary]]), fault-clear transition. Secondary check on [[signal-ride-mode]] under fault conditions (via the recovery sequence's mode cycling). Freeform, four phases.
5. **[[2026-07-24-cluster-fuse-pull]]** — pull fuse 2 (dedicated cluster power) and watch whether `12A` and/or `450` disappear from the bus. Resolves the [[signal-ride-mode]] command-direction open (or tells us fuse 2 is display-only and we need an ABS-module-connector disconnect instead). ~5 min bike session, no YAML, low risk.
6. **[[2026-06-24-fuel-level-walkdown]]** — queued to falsify the off-bus assumption in [[project-fuel-on-can]]. Fuel *consumption* on CAN is already closed ([[fuel-consumption-absent-from-broadcasts]]); this is about level only.
7. **Follow-ups from the 2026-07-22 sub-analyses** — the `12A D1 bit 2` extra-transitions in moving-2 (see [[signal-abs-lamp]] Open); the `121 D6` bits 2-7 (0 across the corpus — need a rev-limiter or wheelie-cut scenario to exercise). ~~[[byte-12d-d3-d4-front-mirror]] LSB re-fit~~ closed 2026-07-22 (0.0577 km/h/LSB, promoted to `confirmed`).

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
