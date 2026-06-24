---
area: bike
status: confirmed
established_by:
  - 2026-06-17-key-on-cold-boot
  - 2026-06-22-wheel-spin-paddock-stand
  - 2026-06-24-front-wheel-hand-spin
source: rider observation
---

# Dash warning-light behavior — check engine, ABS, auto-headlight

Three dash lamps have observable, deterministic extinction/activation conditions usable as ground truth when hunting for engine-state, vehicle-speed, and threshold signals on the CAN bus.

| Lamp           | State at key-on (engine off) | Extinction / activation condition                          |
|----------------|------------------------------|-------------------------------------------------------------|
| Check engine   | Lit, held                    | Extinguishes ~1 s after engine starts                       |
| ABS            | Lit, held                    | Extinguishes ~6 km/h **with engine running** (provisional)  |
| Auto-headlight | Off                          | Activates above some speed threshold; **off-bus, rear-wheel-keyed** (no CAN bit) |

Both lamps complete the dash self-test (sweep at key-on) and then settle into the "lit" state until their respective conditions are met. Numbers above are rider observation, not measured — treat as approximate ("about a second", "6 km/h or thereabouts").

## ABS lamp: engine-running precondition (provisional)

The 2026-06-24 front-wheel hand-spin drove the front wheel to ~11 km/h on the dash (the OEM speedometer is front-wheel-sourced — see [[signal-wheel-speed-rear]] § "Why the OEM speedometer reads 0..."), well above the eyeballed ~6 km/h threshold from the original observation. **The ABS warning lamp did not extinguish.** Engine was off throughout.

Working hypothesis: the ABS module runs a self-test that requires the pump motor (and thus engine power / running ECU state) before it will clear the warning, regardless of measured wheel speed. Plausible because production ABS systems on motorcycles commonly behave this way.

Test to confirm: engine-on stationary capture with vehicle speed at zero — lamp should still be lit; then any future engine-on motion above ~6 km/h should extinguish it. The next engine-on session ([[2026-06-18-engine-on-stationary-inputs]]) will inadvertently rule out the trivial case (lamp doesn't extinguish without speed even with engine on).

## Auto-headlight: off-bus, rear-wheel-keyed

Three independent sessions place the trigger source:

- **2026-06-22 rear-only hand-spin** (front static, rear spun): auto-headlight **did** come on during the harder pushes.
- **2026-06-24 front-only hand-spin** (rear static, front spun to ~11 km/h on the dash): auto-headlight **did not** come on at any point.
- **2026-06-22 rescan** of the same capture using decoded rear km/h (`12D` D5:D6 BE / 16, see [[signal-wheel-speed-rear]]) as the threshold key across every bit on the bus: no CAN bit anywhere matches the expected headlight-bit shape (constant across baseline + Phase A gentle pushes, toggles in Phase B hard pushes, returns to baseline as the spin decays). The only matching bits are `12D` D2 bit 6 and `12D` D6 bit 6 — both arithmetic artifacts of the speed bytes themselves crossing `0x40` (≥6.4 km/h on the D2 1/10 km/h scale, ≥4 km/h on the D6 1/16 km/h scale), not a separate signal.

Front-keyed and OR-gated are ruled out by the 2026-06-24 negative. With the bus-wide rescan also negative, **the body controller reads the rear wheel-speed sensor input directly** (or shares the rear-ABS sensor line) and drives the headlight relay locally without broadcasting a derived signal. The replacement dashboard cannot mirror this trigger off CAN — it would either need its own threshold logic on a rear-wheel speed source or to leave the headlight on a hardware-controlled relay.

Analysis: [`scripts/auto_headlight_rescan.py`](../../../scripts/auto_headlight_rescan.py).

## Why this matters for decoding

Any candidate CAN signal claimed to mean "engine running" must:
- Read *engine-stopped* across the entire `2026-06-17-key-on-cold-boot` capture (check-engine lamp is lit the whole time).
- Flip to *engine-running* within ~1 s of the engine actually firing, in a future engine-on capture.

Any candidate CAN signal claimed to mean "vehicle speed" or "ABS active / healthy" must:
- Read *zero / not-yet-active* across the entire `2026-06-17-key-on-cold-boot` capture (ABS lamp lit throughout).
- Flip to *active* somewhere around 6 km/h in a future ride capture.

These constraints will be cited from `docs/findings/can/*` once specific IDs are tied to specific signals (Phase 2 work).

## Open

- Other warning lights (oil pressure, fuel reserve, neutral, beam, turn indicators, immobilizer, etc.) are not documented here yet. Add per-lamp rows as their behavior is observed and rider-confirmed.
- Whether the OEM dash drives these lamps directly from its own bus reads, or whether the ECU sets a "lamp request" bit that the dash mirrors, is not known. Distinguishing the two will affect any future dashboard replacement work — but it's a Phase 2+ question, not relevant here.

See also: [[always-on-broadcast-ids]].
