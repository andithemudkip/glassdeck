# Status

**Phase:** 1 — CAN logger / capture inventory.

**Last touched:** 2026-07-22 — first on-bike moving ride (freeform, 5 chunks, 386k frames). **Milestone: zero `?` bytes remain on the always-on payload** — every byte across all 88 cells now has a classification (28 primary signal, 9 hash, 3 mirror, 4 static non-zero, 44 always-zero). New findings: [[signal-abs-lamp]] (5 bits after historical cross-check demoted `12A D1 b2`; see [[signal-12a-d1-bit2]] for that separate signal), [[fan-status-absent-from-broadcasts]], [[signal-quickshifter]] (shift-cut on `121 D6` bits 0-1; can't distinguish QS from clutched on this bike due to shoddy clutch sensor), [[signal-541-d3-time-bin]], [[fuel-consumption-derivation-from-torque]] (torque-based fuel model, supersedes the old `RPM × throttle` plan; overrun correctly gives 0 fuel — a real efficiency win of 15.6 % of ride distance), [[signal-12a-d1-bit2]] (semantics-open sibling of the ABS-lamp cluster). Rewrites: [[signal-wheel-speed-front]] (LSB 1/10, still 12-bit), [[signal-12d-d1-bit0]] (4-bit rear-speed band, not a flag), [[signal-engine-on-counter]] (full uint8, not 7-bit). Retractions: [[signal-warmup-index]] and [[byte-121-twin-int16]] paddock-stand "not load-derived" — real riding shows both are load-responsive; 121 A/B leading-candidate signed engine torque. See [[2026-07-22-first-moving-ride]].

## Blocked on

Nothing — pick from Next actions.

## In progress

- **Firmware.** `can-logger` v1 shipped, listen-only @ 500 kbps. `wifi-bridge` M1–M6 + M7a shipped + on-bike-validated by [[2026-07-22-first-moving-ride]]; RX pinned to core 1 for WiFi-coexistence, see [[wifi-vs-can-core-partitioning]]. Shared `firmware/lib/{twai,slcan,status_led}/` used by both targets. Iteration: OTA reflash via `POST /ota`; live capture via `websocat -n ws://192.168.4.1/stream | scripts/capture.py --stdin`.
- **Capture tooling.** `scripts/capture.py` end-to-end; `scripts/inventory_ids.py` derives per-ID counts/periods. Operator's guide at [`docs/guides/capturing.md`](guides/capturing.md).
- **Decoding coverage.** Post-2026-07-22: 28 / 88 payload bytes carry a primary signal (was 22 pre-ride), 44 always-zero (was 3), 4 static non-zero, 9 D7 hash, 3 dup mirrors, **0 undecoded** (was 51). See [`docs/signals/coverage.md`](signals/coverage.md). Unknown structure now lives inside `S◐` cells and behind untested inputs on the always-zero cells — no more black-box bytes.
- **Load-axis interpretation open.** `540 D1` and `121 A/B` both respond to real load; whether they're MAP-like, torque-like, or fuel-injection-quantity-derived needs a controlled load capture (paired same-RPM/same-throttle in different gears, or coast-down runs).

## Next actions

Ordered by expected value; pick one.

1. **GPS-augmented next ride for wheel-speed LSB anchor.** Log phone GPS (1 Hz) alongside CAN on the next ride so we can cross-correlate GPS ground-truth speed with decoded wheel speed at highway speeds — pins the LSBs from ±10 % (rider-dash-observed) to ±0.3 %, promotes both wheel-speed findings from `provisional` back to `confirmed`. No special maneuvers required.
2. **Run the stationary-inputs pair** — both `status: planned`, split from the old bundled experiment (see the superseded 2026-06-18 file for context).
   - [[2026-07-12-dash-inputs]] (key-on, **engine-off**) — Phase A (ROAD/SUPERMOTO toggle) surfaces the ABS mode broadcast; Phase B (trip reset) tests whether it hits the bus at all; Phase C decodes MODE/SET short-presses.
   - [[2026-07-12-neutral-rpm-sweep]] (**engine-on**) — five RPM setpoints in neutral (12 s each), matched to [[2026-06-23-engine-driven-rear-spin]], discriminates the throttle-vs-RPM axis for [[signal-warmup-index]] (with the load axis now known-active, this becomes the *cleaner* throttle-only reference to subtract from the load-inclusive rolling data).
3. **Coast-down capture** — planned as [[2026-07-23-coast-down]], freeform (no procedure YAML). Ride, close throttle in various gears, don't touch brake/clutch, let the bike coast. Confirms or refutes the signed-torque interpretation of `121 A/B` and pins the LSB in N·m if bike + rider mass is roughly known. Pairs cleanly with GPS logging from Next Action #1 (same ride).
4. **ABS fault / mode / recovery session** — planned as [[2026-07-24-abs-fault-and-recovery]]. Rider knows how to induce a real ABS fault (disconnect a ground point + key-on) and clear it (ABS-mode toggle + hard brake to trigger ABS). One session captures: fault state (disambiguates the 5 [[signal-abs-lamp]] bits), ROAD/SUPERMOTO mode toggle (closes [[2026-07-12-dash-inputs]] Phase A open), ABS-active hard-brake event (may surface an ABS-active bit and downstream substitute for the missing brake-input signal from [[2026-07-10-brakes-stationary]]), fault-clear transition. Freeform, four phases.
4. **[[2026-06-24-fuel-level-walkdown]]** — queued to falsify the off-bus assumption in [[project-fuel-on-can]]. Fuel *consumption* on CAN is already closed ([[fuel-consumption-absent-from-broadcasts]]); this is about level only.
5. **Follow-ups from the 2026-07-22 sub-analyses** — the `12A D1 bit 2` extra-transitions in moving-2 (see [[signal-abs-lamp]] Open); the `121 D6` bits 2-7 (0 across the corpus — need a rev-limiter or wheelie-cut scenario to exercise). ~~[[byte-12d-d3-d4-front-mirror]] LSB re-fit~~ closed 2026-07-22 (0.0577 km/h/LSB, promoted to `confirmed`).

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
