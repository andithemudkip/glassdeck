---
area: can
status: provisional
established_by:
  - 2026-06-18-gear-cycle-clutch
  - 2026-06-21-cross-session-payload-diff
references:
  - ktm-can-decoder
---

# Shift-lever sensor — `129` D0 lo nibble

The low nibble of `129` D0 carries shift-lever state, distinct from the gear position encoded in the high nibble ([[signal-gear-position]]). Two bits within the nibble are independently meaningful at the level of evidence we have:

| bit | mask | candidate meaning                                     | status |
|-----|-----:|-------------------------------------------------------|--------|
| 3   | `0x08` | **shift lever displaced from rest position** (sustained — strain-gauge / lever-position sensor reading "foot on lever") | provisional |
| 1   | `0x02` | **shift attempt did not engage target gear** (transient — fires shortly after a failed shift)                            | provisional |

These map to the byte values seen on the bus:
- `0x00` — N, lever at rest
- `0x10` — 1st gear, lever at rest
- `0x08` — N, lever displaced
- `0x18` — 1st gear, lever displaced
- `0x0A` — N, lever displaced + failed-shift flag set

## Why "factory quick shifter" sensor, not a QS+ cut request

The bike has a factory quick shifter (per user manual). The quickshifter mechanism needs a lever-position input to time its ignition cut; what we observe on `129` D0 is consistent with the underlying sensor, not the QS cut request itself:

- **Bit 3 holds for multiple seconds.** Run 1 in the [Phase B gear-cycle capture](../../../logs/2026-06-19-gear-cycle-clutch-B-gear-cycle/) had the bit set continuously for 17.8 s; run 2 for 5.7 s. A QS+ ignition-cut pulse is 50–150 ms. The sustained signal matches a sensor reading "lever is currently displaced" rather than a transient cut request.
- **Bit 3 is gear-session-specific.** Zero set frames across the throttle-sweep (3 183), kill-switch-toggle (3 140), side-stand-toggle (3 433), and Phase A clutch-only (4 463) captures. It only ever sets when the rider is actually working the gear lever.
- **Bit 1 specifically fires after failed shifts.** In Phase B the rider attempted N→2 twice (engine-off on a paddock stand, dogs didn't align, dash showed `-`). Bit 1 set briefly ~1.8 s and ~1.4 s after each failed-shift event. It did **not** fire after the successful N→1 transition or the 1→N return.

## Why this might explain the dashboard `-` glyph

[[signal-gear-position]] notes that the OEM cluster shows `-` when a shift attempt doesn't engage a gear, and earlier reasoning attributed that to "a separate shift-lever-position sensor not bridged onto the diagnostic-port CAN stub." `129` D0 bit 1's failed-shift signature is exactly the input the cluster would need to render `-`. It may be that the diagnostic stub *does* carry the signal — it's just one bit inside a byte that byte-level scanning missed (the byte's dominant value stays at `0x00` during Phase B because bit 1 fires only briefly).

This needs an engine-on capture with real shift failures vs successes to confirm. If the bit-1 signature holds, the dashboard MVP can show `-` directly from `129` D0 bit 1 without a separate sensor input.

## Open

- **Engine-on verification.** Push the lever during normal shifts (with engine running, paddock stand, push 1→2→3→2→1). Bit 3 should set whenever the rider's foot is on the lever; bit 1 should remain clear during successful shifts and fire only on attempts that don't engage.
- **Polarity / direction.** Does bit 3 distinguish up vs down displacement, or is it a single "displaced" flag? Half-click upshifts (1→2) vs full-click downshifts (2→1) may resolve this. None of the existing captures had both directions cleanly separated.
- **0x0A duration.** Bit 1's "failed shift" assertion lasted multiple seconds in the Phase B observations — long enough that it might be a latch the cluster clears on the next valid gear change. Worth measuring the assertion lifetime under different recovery sequences (clutch in/out, neutral-find, valid shift).
- **Relation to factory QS cut.** The cut itself is an ignition / fuel-injection action by the ECU, not a CAN message. So we shouldn't expect to see the QS *cut* on the bus, only its sensor inputs.

## Evidence

- [`docs/experiments/2026-06-18-gear-cycle-clutch.md`](../../experiments/2026-06-18-gear-cycle-clutch.md) — Phase B raw observations.
- [`docs/experiments/2026-06-21-cross-session-payload-diff.md`](../../experiments/2026-06-21-cross-session-payload-diff.md) — Phase B distinct-count surprise that triggered the deeper look.
- Conversational alignment trace of bit 3 / bit 1 vs event marks on Phase B (2026-06-21) — sustained vs transient pattern; failed-shift-only signature for bit 1.
- [`logs/2026-06-19-gear-cycle-clutch-B-gear-cycle/`](../../../logs/2026-06-19-gear-cycle-clutch-B-gear-cycle/) — raw capture.

See also: [[signal-gear-position]], [[always-on-broadcast-ids]].
