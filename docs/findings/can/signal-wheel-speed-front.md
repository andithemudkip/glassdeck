---
area: can
status: confirmed
established_by:
  - 2026-06-24-front-wheel-hand-spin
  - 2026-06-24-front-wheel-decay-mark
references:
  - ktm-can-decoder
---

# Front wheel speed — `12D` D0 + D1 high nibble (12-bit BE)

Front wheel speed on the 2020 Husqvarna Svartpilen 401 is broadcast in arbitration ID **`0x12D`** as a 12-bit big-endian value occupying **D0 (all 8 bits) + D1 high nibble (bits 4-7)**. The low nibble of D1 (bits 0-3) carries *other* signals — see [[signal-12d-d1-bit0]] for the engine-correlated flag in bit 0.

| Field | Encoding | Scale | Behaviour |
|------:|----------|-------|-----------|
| **D0 + D1 high nibble** | 12-bit BE (D0 = high 8 bits, D1[4:7] = low 4 bits) | **exactly 1/192 km/h per raw-u16 LSB** = 1/12 km/h per effective transmitted step | Primary signal. `0` at rest. ECU snaps to `0` below ~2.33 km/h (does not transmit intermediate low values). |

```python
# Correct: mask off the low nibble first
front_wheel_kmh = ((data[0] << 8) | (data[1] & 0xF0)) / 192.0
# Equivalent (extract the 12-bit value, then scale)
front_wheel_kmh = ((data[0] << 4) | (data[1] >> 4)) / 12.0
```

**Do NOT decode as a plain `(D0 << 8) | D1` uint16** — that's correct only when D1's low nibble is zero, which is true engine-off but not always engine-on (see [[signal-12d-d1-bit0]]).

Same arbitration ID as the rear wheel ([[signal-wheel-speed-rear]]), different bytes, **different LSB family** — rear is 1/16 km/h, front is 1/192 km/h. See § "Front and rear use different LSBs (intentional)" below. A *third* wheel-speed encoding lives at D3:D4 on the same ID as a redundant 16-bit BE mirror at 3/64 km/h LSB — see [[byte-12d-d3-d4-front-mirror]].

## Evidence

### Encoding pattern: speed value is 12 bits at the top of the slot

Across all 47 573 frames of [[2026-06-24-front-wheel-hand-spin]] and all 56 000+ frames of [[2026-06-24-front-wheel-decay-mark]] (engine-off in both), **every non-zero raw value of `(D0 << 8) | D1` is a multiple of 16**. The low 4 bits of D1 never set in engine-off conditions. Observed broadcast values span the set `{448, 464, 480, 496, 512, 528, 544, 560, 576, 592, 608, …}` — strictly 16 apart.

In the engine-driven session ([[2026-06-23-engine-driven-rear-spin]]) the low 4 bits **do** flip — specifically D1 bit 0 is set occasionally — but never combined with a non-zero D0:D1 high portion (the front wheel was stationary on the paddock stand the whole time). The high-12-bit field stays at 0 in that capture; the bit-0 flag is the *only* low-nibble activity. So:

- **Wheel speed** uses bits 15:4 of the BE u16. 12-bit value, LSB 1/192 km/h on the raw u16 (equivalently 1/12 km/h on the 12-bit extracted value).
- **Low nibble** (bits 3:0) is **not padding** — it's a separate field. See [[signal-12d-d1-bit0]] for the one bit currently known to carry information.

See [[byte-encoding-12-in-16]] for the broader detection-pattern note.

### LSB calibration against the OEM speedo

Per-push peak raw (BE uint16) on D0:D1 vs the rider-reported dash km/h peak across two sessions, decoded at LSB = 1/192 km/h:

| Session, Push | Dash km/h | Raw u16 peak | raw/192 | Match? |
|---------------|----------:|-------------:|--------:|--------|
| 06-24 hand-spin A | 3 | 608 | 3.17 | ✓ rounds to 3 |
| 06-24 hand-spin A | 3 | 608 | 3.17 | ✓ |
| 06-24 hand-spin A | 3 | 640 | 3.33 | ✓ |
| 06-24 hand-spin A | 4 | 752 | 3.92 | ✓ rounds to 4 |
| 06-24 hand-spin B | 7 | 1344 | **7.00** | ✓ exact |
| 06-24 hand-spin B | 9 | 1712 | 8.92 | ✓ rounds to 9 |
| 06-24 hand-spin B | 10 | 1840 | 9.58 | ✓ rounds to 10 |
| 06-24 hand-spin B | 11 | 1856 | 9.67 | ✗ rounds to 10, not 11 |
| 06-24 hand-spin C | 5 | 896 | 4.67 | ✓ rounds to 5 |

8/9 pushes match within ±0.5 km/h (the dash's quantisation step). The remaining outlier — dash "11" with raw 1856 — is not explainable by any single LSB: the constraints "raw 1344 → dash 7" and "raw 1856 → dash 11" don't overlap on any LSB value, because raw 1856 / 1344 = 1.38 but dash 11 / 7 = 1.57. The rider [explicitly noted](../experiments/2026-06-24-front-wheel-hand-spin.md) that per-push attribution of dash peaks was approximate at the time of recall, so the most likely explanation is that the dash actually peaked at 10 on this push and 11 belonged to a different push whose peak raw was not the absolute-maximum frame sampled. Documented as a known residual.

### ECU low-end broadcast cutoff at raw 448

[[2026-06-24-front-wheel-decay-mark]] captured the decay tail of 5 hand-spin pushes. **Every single push** has its last non-zero raw value equal to exactly **448 = 0x01C0** before the byte snaps to `0x0000` for the rest of the decay. The ECU stops broadcasting non-zero values below `448 / 192 = 2.333 km/h`.

Per-push last-non-zero raw before the b-mark:

| Push | Last raw | Time before b-mark |
|-----:|---------:|-------------------:|
| 1 | 448 | 486 ms |
| 2 | 448 | 456 ms |
| 3 | 448 | 425 ms |
| 4 | 448 | 446 ms |
| 5 | 448 | 217 ms |

The 200-500 ms gap between the bus going quiet and the rider's `b` press is consistent with reaction time *plus* the dash's own display-update latency (the rider was pressing `b` when the *dash* flipped to 0, which lags the bus going to zero by however long the dash holds its previous reading).

### Dash quantisation rule corroborates 1/192

In the decay-mark session, the rider observed **dash briefly displays "2" km/h, never "1"**, before flipping to 0. With LSB 1/192 and ECU floor at raw 448:

- The lowest non-zero ECU broadcast is raw 448 = 2.333 km/h.
- Round-to-nearest dash would display "2" for true ∈ [1.5, 2.5), "1" for true ∈ [0.5, 1.5), "0" otherwise.
- The ECU never broadcasts low enough to register dash "1" (would need true < 1.5, ECU floor is 2.33).
- The ECU does broadcast at 2.333 km/h (raw 448) and 2.417 km/h (raw 464), both within dash-2 band.
- Above 2.5 km/h the dash flips to "3", which takes about 30-50 ms of decay at typical observed rates — matching the rider's "briefest moment" observation.

The dash thus uses **round-to-nearest with an additional rule of suppressing display below ~1.5 km/h**, and the ECU's broadcast floor cuts off most of the dash-2 band, leaving only a brief flash.

## Why front and rear use different LSBs (intentional, not noise)

Rear D5:D6 is `1/16 km/h per LSB` (uint16, full 16-bit resolution). Front D0:D1 is `1/192 km/h per LSB` (12-bit value in 16-bit slot, low 4 bits padded).

| | Rear D5:D6 | Front D0:D1 |
|---|-----------|--------------|
| LSB | 1/16 km/h | 1/192 km/h |
| Effective resolution | 16-bit (full uint16) | 12-bit (high 12 bits of u16) |
| Coarse mirror? | yes — D2 at 1/10 km/h | none |
| Has a low-end ECU cutoff? | not observed (idle in 1st gear sits at raw 162 = 10.1 km/h) | yes, snaps to 0 below raw 448 |

Both are calibrated km/h values, but with different resolutions and conventions — likely because they're consumed by different ECU subsystems (front by the ABS module which wants finer-grained data for slip detection; rear by the engine ECU which is happy with 1/16 km/h for gear/ignition logic). The pulse-per-time hypothesis (front byte being a raw counter rather than km/h) is **disproven** by the clean LSB fit at 1/192 km/h and the binary-friendly 12-bit-in-16-bit encoding.

## Cross-walk vs KTM

KTM's ktm-can decoder ([reference](../../references/ktm-can-decoder.md)) places front wheel speed at `12B` D0:D1 BE uint16 on the 2020 KTM 690 Enduro R. On the Svartpilen 401:

- **ID relocated** `12B` → `12D` (same 10 ms period). Consistent with the rear-channel pattern.
- **Byte position preserved exactly** — front wheel at D0:D1, BE uint16. The 12-bit-in-16-bit packing is likely a Bosch-wide convention; KTM may use the same.
- **LSB scale not assumed** without confirming against KTM data — Bosch ECU variants vary even when byte positions are preserved (coolant temp scale matches across variants; front-wheel LSB might or might not).

## Evidence

- [[2026-06-24-front-wheel-hand-spin]] — established the byte location and gave a noisy LSB best-fit ~1/190.
- [[2026-06-24-front-wheel-decay-mark]] — pinned LSB at 1/192 via the 12-bit encoding observation, the ECU floor at raw 448, and the dash 0/2/3 quantisation rule. Promoted finding to `confirmed`.
- [`scripts/front_wheel_hand_spin.py`](../../../scripts/front_wheel_hand_spin.py) — per-push analysis (sessions 1 and 2).
- [`scripts/front_wheel_decay_mark.py`](../../../scripts/front_wheel_decay_mark.py) — decay-tail analysis, low-end distribution, dash quantisation cross-check.

## Open

- **Origin of the dash-11 outlier** in session 1, push 8. Most likely a recall artifact; no LSB family explains it cleanly. Closed-or-irrelevant for practical decoding — the LSB is pinned at 1/192 with strong corroboration from three independent angles.
- **What lives in the low 4 bits of D1.** Bit 0 carries an engine-correlated flag ([[signal-12d-d1-bit0]], `provisional`). Bits 1-3 still always `0` in everything observed.
- **Does the rear also use 12-bit-in-16-bit packing?** Rear D5:D6 sweep on [[2026-06-23-engine-driven-rear-spin]] needs a quick check — if rear is full 16-bit, the front 12-bit packing is a deliberate per-channel choice; if rear is also 12-bit, then 1/16 km/h × 16 = 1 km/h per step on the rear (would mean the rear's effective resolution is 1 km/h, contradicting the 0.05633 best-fit). Cheap follow-up: scan the rear capture for raw values modulo 16.

See also: [[signal-wheel-speed-rear]], [[byte-encoding-12-in-16]], [[always-on-broadcast-ids]], [[ktm-can-decoder]], [[dash-warning-lights]].
