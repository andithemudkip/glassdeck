---
area: bike
status: confirmed
established_by:
  - 2026-06-17-key-on-cold-boot
source: rider observation
---

# Dash warning-light behavior — check engine and ABS

Two warning lights on the OEM dash have observable, deterministic extinction conditions that are useful as ground truth when later hunting for engine-state and vehicle-speed signals on the CAN bus.

| Lamp           | State at key-on (engine off) | Extinction condition                              |
|----------------|------------------------------|---------------------------------------------------|
| Check engine   | Lit, held                    | Engine running for ~1 s                           |
| ABS            | Lit, held                    | Vehicle speed exceeds ~6 km/h                     |

Both lamps complete the dash self-test (sweep at key-on) and then settle into the "lit" state until their respective conditions are met. Numbers above are rider observation, not measured — treat as approximate ("about a second", "6 km/h or thereabouts").

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
