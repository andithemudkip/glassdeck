---
area: can
status: confirmed
established_by:
  - 2026-06-23-shift-lever-vs-clutch
  - 2026-06-19-gear-cycle-clutch
references:
  - ktm-can-decoder
---

# Clutch lever — `129` D0 bit 3

Clutch lever state on the 2020 Husqvarna Svartpilen 401 is broadcast in arbitration ID **`0x129`**, byte **D0**, **bit 3** (mask `0x08`).

```
clutch_pulled = bool((data[0] >> 3) & 0x01)
```

| Bit value | Meaning |
|-----------|---------|
| `0`       | clutch released (lever at rest) |
| `1`       | clutch pulled (lever displaced) |

Sustained — the bit holds as long as the lever stays pulled, releases when the rider lets go. Broadcast at the regular `129` cadence (10 ms), so transitions are visible within one frame.

## Lever-switch threshold (this physical bike)

The clutch-lever switch on this bike is mechanically finicky and only trips when the lever is **pulled upward past a threshold** (well past the start of travel). Shallow / partial pulls — particularly the gentle "blip" pumps that work fine for testing throttle or other inputs — may not actuate the switch at all and produce no bit-3 movement.

This explains the [Phase A clutch-only null result](../../experiments/2026-06-18-gear-cycle-clutch.md) (5 clutch pumps, engine off, neutral — bit 3 never set across 4 463 `129` frames): those pumps were physically below the switch threshold. Future clutch captures need full-travel pulls past the click point.

When designing experiments that depend on a clutch edge, prefer full-pull-hold-release reps over rapid pumps.

## Why this is clutch, not "shift-lever displaced"

Previously this bit was attributed to a shift-lever-displaced sensor ([[signal-shift-failed]] history) based on its set-window pattern in the Phase B gear-cycle capture (bit set continuously for 17.8 s in run 1, 5.7 s in run 2 — interpreted then as "rider holding the gear lever displaced"). [2026-06-23-shift-lever-vs-clutch](../../experiments/2026-06-23-shift-lever-vs-clutch.md) disambiguates cleanly:

| Stimulus (in neutral, engine off) | Bit 3 fires? |
|---|:---:|
| Clutch pulled (full travel), 4 reps | **YES** (4/4 — set for 2.4–4.1 s blocks matching holds) |
| Shift lever pressed, no shift, 3 reps | **NO** (0/3 — bit 3 stayed clear) |

The Phase B "sustained displacement" windows were the rider holding the clutch in during shift attempts, not the shift lever.

## Cross-walk vs KTM

The ktm-can decoder ([reference](../../references/ktm-can-decoder.md)) does not place clutch on the bus on the KTM 690 Enduro R. This is a Husqvarna 401-specific broadcast (or a KTM 390 platform broadcast the 690 lacks). No KTM mapping to validate against; today's two-condition disambiguation is the primary evidence.

## Evidence

- [`docs/experiments/2026-06-23-shift-lever-vs-clutch.md`](../../experiments/2026-06-23-shift-lever-vs-clutch.md) — disambiguation session, neutral, engine off, clutch-only and shifter-only events separately marked. 4 clutch holds: bit 3 set for ~2.4–4.1 s each, matching hold durations; 3 shift-lever events: bit 3 stayed clear. Polarity, sustained character, and "not shift lever" all established in one session.
- [`docs/experiments/2026-06-18-gear-cycle-clutch.md`](../../experiments/2026-06-18-gear-cycle-clutch.md) — Phase B clutch-held windows during gear cycle (re-interpreted post 2026-06-23). Run 1 17.8 s and run 2 5.7 s bit-3 holds match the rider's clutch holds across shift attempts, not shift-lever displacement.
- [`logs/2026-06-23-shift-lever-vs-clutch/`](../../../logs/2026-06-23-shift-lever-vs-clutch/) — raw capture for the disambiguation session.

## Open

- **Polarity at the switch level.** Today's evidence is "lever pulled = bit set." Whether the switch is open-when-rest / closed-when-pulled vs the inverse on the wiring side doesn't matter for decode but matters for fault diagnosis (broken sensor wire vs broken sensor return both read 0; broken supply vs always-pulled wire both read 1).
- **Does the bit ever stick or latch?** Not observed in 4 reps of full release. Multi-hour sessions or post-stall conditions could surface a latch behaviour that short sessions miss.
- **Did Phase B's 17.8 s and 5.7 s hold lengths match the rider's actual clutch holds during the failed-shift attempts?** Worth a frame-by-frame re-alignment of Phase B against the event marks under the clutch interpretation — if the times don't match the rider's reconstructed clutch-in periods, something else is going on.

See also: [[signal-shift-failed]], [[signal-gear-position]], [[always-on-broadcast-ids]].
