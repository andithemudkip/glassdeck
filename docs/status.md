# Status

**Phase:** 1 — CAN logger / capture inventory.

**Last touched:** 2026-07-09 — wifi-bridge bench-verified on the bike (M1–M6 + M7a end-to-end, F7-powered, key-on idle). Two firmware bugs found + fixed in the session; the RX-loop-must-live-on-core-1 lesson is promoted to a finding. See [[2026-07-09-wifi-bridge-first-on-bike]].

## Blocked on

Nothing — pick from Next actions.

## In progress

- **Firmware.** `can-logger` v1 shipped, listen-only @ 500 kbps. `wifi-bridge` M1–M6 + M7a shipped + bench-verified on the bike; RX pinned to core 1 for WiFi-coexistence, see [[wifi-vs-can-core-partitioning]]. Shared `firmware/lib/{twai,slcan,status_led}/` used by both targets. Iteration: OTA reflash via `POST /ota`; live capture via `websocat -n ws://192.168.4.1/stream | scripts/capture.py --stdin`.
- **Capture tooling.** `scripts/capture.py` end-to-end; `scripts/inventory_ids.py` derives per-ID counts/periods. Operator's guide at [`docs/guides/capturing.md`](guides/capturing.md).
- **Decoding coverage.** 22 / 88 payload bytes carry a primary signal, 9 are D7 hash, 3 always-zero, 2 redundant mirrors, 52 undecoded. See [`docs/signals/coverage.md`](signals/coverage.md) for the current map.

## Next actions

Ordered by expected value; pick one.

1. **First ride capture with wifi-bridge.** Throttle sweeps + wheel-speed signals under motion — closes the wifi-bridge validation loop and unblocks items 5–6 below. Prep: enclosure (bare perfboard right now); residual bench items (phone-side OPFS export, `/mark`, 60 s ring-overflow) in [[2026-07-09-wifi-bridge-first-on-bike]] follow-ups.
2. **Phase E of [[2026-06-18-engine-on-stationary-inputs]]** — five RPM setpoints in neutral (~2000/2500/3500/4500/5500), 12 s each. Discriminates:
   - [[signal-warmup-index]] throttle-derived vs RPM-derived vs load-derived (currently `contradicted_by`);
   - [[byte-121-twin-int16]] semantic quantity (ignition advance vs fuel trim);
   - [[signal-12d-d1-bit0]] RPM-keyed vs vehicle-speed-keyed threshold.
3. **Targeted bike-side capture** on the three bytes the corpus sweep narrowed to one moving byte each: `12A` D1, `12E` D6, `5A0` D4. Plus `129` D0 bits 0/2 and `121` channels A/B at fixed RPM with slow throttle excursion. See [[2026-06-30-unknown-byte-corpus-sweep]] for the shortlist.
4. **[[2026-06-24-fuel-level-walkdown]]** — queued to falsify the off-bus assumption in [[project-fuel-on-can]]. Fuel *consumption* on CAN is already closed ([[fuel-consumption-absent-from-broadcasts]]); this is about level only.
5. **Rear wheel-speed LSB** — currently best-fit 0.05633 km/h with a ~10 % gap from 1/16. Resolves via authoritative KTM 390 gearing/rolling-circumference or an OEM-speedo cross-check during a real motion capture.
6. **ABS-lamp threshold value** — needs engine-on motion capture crossing ~6 km/h. Also verifies the provisional engine-running precondition on [[bike/dash-warning-lights]].
7. **`541` D1** — flagged as a candidate derived-coolant byte but only one moving session so far. Needs replication under a cold→warm walk.

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
