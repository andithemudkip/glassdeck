---
area: can
status: partial
established_by:
  - 2026-06-18-gear-cycle-clutch
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
| 2    | `0x2` *(hypothesised, KTM mapping)* | unverified |
| 3    | `0x3` *(hypothesised)* | unverified |
| 4    | `0x4` *(hypothesised)* | unverified |
| 5    | `0x5` *(hypothesised)* | unverified |
| 6    | `0x6` *(hypothesised)* | unverified |

The N=0 and 1=1 mappings were observed cleanly across all sampled windows of the Phase B gear-cycle capture (purity 100% in the held-N windows; purity ~90% in the 1st-gear window, the remainder explained by 1 s of shift-mechanics settling). Gears 2–6 were not reached: with the engine off on a paddock stand, the gearbox dogs do not align well enough to engage gears above 1st. The KTM-style `gear == integer` encoding is the standing hypothesis for 2–6 and the natural reading given how cleanly 0 and 1 fall out.

The low nibble of `129` D0 stayed `0x0` in every observed *held-gear* window — but follow-up alignment of the Phase B trace ([[signal-shift-lever]]) shows the lo nibble carries **shift-lever sensor** state, not gear state: bit 3 = lever displaced from rest (sustained), bit 1 = shift attempt failed to engage target gear (transient). The dashboard `-` glyph discussed below is most likely sourced from bit 1, not from a separate sensor as previously hypothesised.

## What the dash "-" means

When the bike physically cannot resolve a gear (e.g., a shift-lever push that didn't actually engage a gear), the dash shows `-`. On the CAN bus, `129` D0 **hi** nibble reads `0x0` (neutral) during these "-" episodes — the gear field itself has no transition / unknown sentinel value. But the **lo** nibble does carry a failed-shift flag — see [[signal-shift-lever]] for bit 1's signature, which fires shortly after the failed N→2 attempts in Phase B. The dashboard MVP can almost certainly mirror the OEM `-` by watching `129` D0 bit 1 directly, with no separate sensor required. Needs engine-on confirmation.

## Cross-walk vs KTM

The ktm-can decoder ([reference](../../references/ktm-can-decoder.md)) places gear at **`129` D0 hi nibble** with `0=N, 1–6=gears`, and separately mirrors it at **`540` D3 lo nibble**:

- **`129` D0 hi nibble — location and N/1 encoding match.** Confirmed on Husqvarna.
- **`540` D3 lo nibble — does NOT carry gear on Husqvarna.** Stayed at `0x0` (100% purity) across all five Phase B windows. The KTM redundant-broadcast story does not transfer. Gear is single-source on this bike (or at least: not also on `540`).

The `540` D3 hi nibble was LOW-CARD(4) in the idle baseline but stayed at `0x1` throughout Phase B. Its variation must come from inputs not exercised here (mode toggle? ABS state? coolant-driven warm-up state?) — open to investigate.

## Evidence

- [`docs/experiments/2026-06-18-gear-cycle-clutch.md`](../../experiments/2026-06-18-gear-cycle-clutch.md) — Phase B Result section.
- [`logs/2026-06-19-gear-cycle-clutch-B-gear-cycle/`](../../../logs/2026-06-19-gear-cycle-clutch-B-gear-cycle/) — raw capture.
- [`scripts/gear_scan.py`](../../../scripts/gear_scan.py) — per-window nibble tabulation that surfaced the mapping.

## Open

- **Confirm gears 2–6.** Requires engine running so the input shaft is turning and the dogs align. Bundle into the engine-on stationary experiment, or a brief first-motion test.
- **Confirm there is no transition sentinel.** The current evidence is "didn't see one in our 2nd-engagement attempts," but full 1↔2 shifts under power may surface a brief intermediate value during the shift itself.
- **What drives `540` D3 hi nibble's idle-time cardinality of 4?** Static in Phase B → not gear. Test under mode toggle and warm-up sweeps.
- **Where does the dash get the `-` state from?** Almost certainly a shift-lever-position input on a separate bus. Out of scope for the dashboard MVP unless we decide we need to mirror it exactly.

See also: [[always-on-broadcast-ids]], [[ktm-can-decoder]].
