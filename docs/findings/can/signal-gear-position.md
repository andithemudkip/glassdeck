---
area: can
status: confirmed
established_by:
  - 2026-06-18-gear-cycle-clutch
  - 2026-06-23-paddock-stand-gear-spin
references:
  - ktm-can-decoder
---

# Gear position — `129` D0 hi nibble

Selected gear on the 2020 Husqvarna Svartpilen 401 is broadcast in arbitration ID **`0x129`**, byte **D0**, **upper nibble** (`(data[0] >> 4) & 0x0F`).

```
gear_nibble = (data[0] >> 4) & 0x0F
```

| Gear | Nibble value | Status |
|------|-------------:|:------|
| N    | `0x0`        | **confirmed** |
| 1    | `0x1`        | **confirmed** |
| 2    | `0x2`        | **confirmed** |
| 3    | `0x3`        | **confirmed** |
| 4    | `0x4`        | **confirmed** |
| 5    | `0x5`        | **confirmed** |
| 6    | `0x6`        | **confirmed** |

N and 1 were established by the Phase B engine-off gear-cycle capture (purity 100% in held-N windows, ~90% in the 1st-gear window). Gears 2–6 were not reached in Phase B because, engine-off on a paddock stand, the gearbox dogs do not align without the input shaft turning. The wheel-spin paddock-stand session ([2026-06-23-paddock-stand-gear-spin](../../experiments/2026-06-23-paddock-stand-gear-spin.md)) worked around this: spinning the rear wheel by hand walked the dogs into alignment for every gear in sequence, and each gear rendered correctly in the live view (which decodes `129` D0 hi nibble directly). Clean linear ramp `0,1,2,3,4,5,6` confirms the KTM mapping for all 7 values.

The low nibble of `129` D0 carries other signals — see [[signal-clutch]] (bit 3) and [[signal-shift-failed]] (bit 1).

## What the dash "-" means

When the bike physically cannot resolve a gear (e.g., a shift-lever push that didn't actually engage a gear), the dash shows `-`. On the CAN bus, `129` D0 **hi** nibble reads `0x0` (neutral) during these "-" episodes — the gear field itself has no transition / unknown sentinel value. But the **lo** nibble does carry a failed-shift flag — see [[signal-shift-failed]] for bit 1's signature, which fires shortly after the failed N→2 attempts in Phase B. The dashboard MVP can almost certainly mirror the OEM `-` by watching `129` D0 bit 1 directly, with no separate sensor required.

## Cross-walk vs KTM

The ktm-can decoder ([reference](../../references/ktm-can-decoder.md)) places gear at **`129` D0 hi nibble** with `0=N, 1–6=gears`, and separately mirrors it at **`540` D3 lo nibble**:

- **`129` D0 hi nibble — location and N/1 encoding match.** Confirmed on Husqvarna.
- **`540` D3 lo nibble — does NOT carry gear on Husqvarna.** Stayed at `0x0` (100% purity) across all five Phase B windows. The KTM redundant-broadcast story does not transfer. Gear is single-source on this bike (or at least: not also on `540`).

The `540` D3 hi nibble was LOW-CARD(4) in the idle baseline but stayed at `0x1` throughout Phase B. Its variation must come from inputs not exercised here (mode toggle? ABS state? coolant-driven warm-up state?) — open to investigate.

## Evidence

- [`docs/experiments/2026-06-18-gear-cycle-clutch.md`](../../experiments/2026-06-18-gear-cycle-clutch.md) — Phase B Result section (N and 1).
- [`docs/experiments/2026-06-23-paddock-stand-gear-spin.md`](../../experiments/2026-06-23-paddock-stand-gear-spin.md) — wheel-spin engagement reached gears 2–6 engine-off (live-view observation, no log).
- [`logs/2026-06-19-gear-cycle-clutch-B-gear-cycle/`](../../../logs/2026-06-19-gear-cycle-clutch-B-gear-cycle/) — raw capture for the N/1 evidence.
- [`scripts/gear_scan.py`](../../../scripts/gear_scan.py) — per-window nibble tabulation that surfaced the original N/1 mapping.

## Open

- **Transition sentinel.** No value other than `0x0–0x6` was observed in any held-gear window, including across the slow hand-driven shifts of the wheel-spin session. A rapid engine-on shift might still surface a sub-frame intermediate value (`0xF` or similar), but the evidence base is now wide enough that "no transition sentinel exists on this bus" is the favoured reading. Demoted in priority — fold in if a future engine-on capture happens to span shifts.
- **What drives `540` D3 hi nibble's idle-time cardinality of 4?** Static in Phase B → not gear. Test under mode toggle and warm-up sweeps.

See also: [[signal-clutch]], [[signal-shift-failed]], [[always-on-broadcast-ids]], [[ktm-can-decoder]].
