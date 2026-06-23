---
area: can
status: provisional
established_by:
  - 2026-06-18-gear-cycle-clutch
  - 2026-06-21-cross-session-payload-diff
references:
  - ktm-can-decoder
---

# Shift-attempt-failed flag — `129` D0 bit 1

A transient flag at `0x129` D0 **bit 1** (mask `0x02`) fires shortly after a shift attempt that does not engage the target gear — for example, when the rider pushes the shift lever toward 2nd but the dogs don't align and the gearbox stays in N (or some other non-target state).

```
shift_failed = bool((data[0] >> 1) & 0x01)
```

| Bit value | Meaning |
|-----------|---------|
| `0`       | OK / no failed-shift latched |
| `1`       | shift attempt did not engage target gear (transient) |

Transient — observed firing ~1.4 s and ~1.8 s after two failed N→2 attempts in the Phase B gear-cycle capture (engine off, paddock stand, dogs misaligned). Did **not** fire after successful shifts in the same session. Believed to be the input the OEM cluster uses to render the `-` glyph.

## Status note — bit 3 re-attribution

This finding originally bundled bit 3 of the same nibble as a "shift-lever-displaced" sustained sensor. Bit 3 was disambiguated by [2026-06-23-shift-lever-vs-clutch](../../experiments/2026-06-23-shift-lever-vs-clutch.md) and is now confirmed as the clutch lever — see [[signal-clutch]]. The bit 1 = failed-shift attribution survives that disambiguation: it didn't fire today (rider did not attempt a failed shift in the disambiguation session) and remains supported solely by Phase B's two failed N→2 attempts.

Evidence base is therefore narrow — two transient firings in a single capture, no replication. Provisional until a session with deliberate failed-shift events under cleaner conditions reproduces it.

## Why this might explain the dashboard `-` glyph

[[signal-gear-position]] notes that the OEM cluster shows `-` when a shift attempt doesn't engage a gear. `129` D0 bit 1's failed-shift signature is exactly the input the cluster would need to render `-`. Confirming this on the bus closes the dashboard MVP's `-` rendering: read bit 1 directly, no separate sensor required.

## Open

- **Replication is opportunistic, not scheduled.** The bike's gearbox state on 2026-06-23 was happy — every gear engaged cleanly during the wheel-spin sweep, and no `-` events fired in the disambiguation session that immediately followed. Failed shifts have been observed on this bike on multiple past occasions per the rider, but cannot be reliably provoked on demand. Validation path: keep `shift_failed` decoded in the live view on every session; the next time the dash shows `-` during normal use with logging on, the live view will either show `shift_failed = FAILED` at that moment or it won't. A single naturally-occurring co-occurrence (or non-occurrence) is enough evidence to promote or refute.
- **Phase B re-walk under the corrected attribution.** Cheap consistency check: with bit 3 now known to be clutch (not shift lever), re-align bit 1's two Phase B firings against the rider's reconstructed actions in [`docs/experiments/2026-06-18-gear-cycle-clutch.md`](../../experiments/2026-06-18-gear-cycle-clutch.md) Phase B. If the timings still fit "fires ~1.5 s after a rider attempt to engage that didn't take," that's internally consistent. Doesn't add a new event but tests whether the old interpretation survives the new bit-3 understanding.
- **Assertion lifetime.** How long does the bit stay set after the failed attempt? Does it self-clear, or does it clear only on the next successful gear change / clutch release / something else?
- **Polarity.** Could the dash also be using a "no-target-gear-sensed" inverse logic? Probably not — bit 1 = 0 at rest and 1 during failure is the natural reading.
- **Engine-on confirmation.** The two Phase B failures were engine-off paddock-stand misalignments. Real engine-on misshifts (rare in normal riding) may produce a different signature. Not blocking the MVP since the engine-off pattern is what the cluster sees on the paddock stand too.

## Evidence

- [`docs/experiments/2026-06-18-gear-cycle-clutch.md`](../../experiments/2026-06-18-gear-cycle-clutch.md) — Phase B failed N→2 attempts.
- [`docs/experiments/2026-06-21-cross-session-payload-diff.md`](../../experiments/2026-06-21-cross-session-payload-diff.md) — Phase B distinct-count surprise that triggered the deeper look.
- Conversational alignment trace of bit 1 vs event marks on Phase B (2026-06-21).
- [`logs/2026-06-19-gear-cycle-clutch-B-gear-cycle/`](../../../logs/2026-06-19-gear-cycle-clutch-B-gear-cycle/) — raw capture.

See also: [[signal-clutch]], [[signal-gear-position]], [[always-on-broadcast-ids]].
