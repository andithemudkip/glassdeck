---
area: can
status: provisional
established_by:
  - 2026-06-22-wheel-spin-paddock-stand
references:
  - ktm-can-decoder
---

# Rear wheel speed — `12D` bytes D2 and D6

Rear wheel rotation on the 2020 Husqvarna Svartpilen 401 is broadcast in arbitration ID **`0x12D`** at two byte positions: **D2** and **D6**. Both bytes are STATIC `0x00` when the rear wheel is stationary, and ramp up together with smooth mechanical-decay envelopes when the wheel is spun.

```
rear_wheel_moving = (data[2] != 0) or (data[6] != 0)
```

Promoted from a paddock-stand hand-spin session: 8 hard-push trials produced peak D2 values of 0x42–0x4B and peak D6 values of 0x65–0x75, with envelopes lasting 1.0–2.2 s per push. 6 gentle-push trials produced peak D2 values of 0x1D–0x2D with much shorter envelopes (~0–0.5 s). Across all 1058 motion frames in the session, D2 = 0 ⇔ D6 = 0, and the bytes ramp/decay together with no observed dropouts.

**Unit scaling and the exact relationship between D2 and D6 are open** — see § Open below. This finding is `provisional`: the **decode location** (`12D` D2 + D6 = rear wheel speed) is well-supported, the **encoding** is not.

## Why two bytes for one wheel?

`12D` D2 and D6 ramp together but with a **speed-dependent ratio**: at peak speeds (Phase B hard pushes), D6/D2 ≈ 1.53× consistently across 7 pushes. At decay tail values (e.g. D2=29 → D6=34), the ratio drops to ~1.17×. A constant ratio would imply the two bytes are linear scalings of the same quantity; a varying ratio implies they are different quantities that happen to be co-moving.

Three working hypotheses:

1. **D2 is filtered/averaged, D6 is raw.** During the fast acceleration of a hand-push, the filtered estimate (D2) lags the raw count (D6), so D6 leads at peak. During the slow decay, the filter catches up.
2. **Different scaling laws** — e.g. D2 linear in wheel-RPM with no offset, D6 linear with an additive bias term. Possible if the two bytes serve different consumers (ABS controller wants one, dashboard wants another).
3. **D6 is the raw tone-ring count per CAN cycle (10 ms period), D2 is an ABS-derived speed estimate.** Tone-ring count is integer-precise at high speeds and noisy at very low speeds; an ABS estimate may filter the noise but introduce lag.

This experiment can't disambiguate. A steady-state spin (motor-driven, not hand-driven) would hold the wheel at a fixed speed for several seconds and let us read both bytes at a stable operating point — that would settle it.

## Why the OEM speedometer reads 0 during a rear-only spin

The dashboard speedometer stays at 0 km/h throughout a rear-only paddock-stand spin, even when these `12D` bytes are showing large values. Consistent reading:

- `12D` D2 + D6 are **rear-wheel-only** signals (only the rear was spinning; both bytes responded).
- The OEM speedo reads its value from a **different byte sourced from the front wheel**, which was stationary throughout, so the speedo correctly reads 0.
- The front-wheel-speed byte location is **not yet identified**. A future engine-off front-stand spin or a real motion capture (bike rolled in neutral with both wheels turning) will resolve it.

This split — speedo reads front, body-controller reads rear or OR-gates both — is consistent with the auto-headlight observation from the same session: spinning the rear wheel briskly trips the low beam even though the dash speedo never moves. Body controller is reading the rear sensor for its "vehicle moving" logic.

## Cross-walk vs KTM

The ktm-can decoder ([reference](../../references/ktm-can-decoder.md)) places wheel speeds at `12B` on the 2020 KTM 690 Enduro R, broadcast at 10 ms:

```
KTM 12B   D0..D1  front wheel  (big-endian uint16, raw — no km/h scaling)
          D2..D3  rear wheel   (big-endian uint16, raw)
          D4      unknown
          D5..D7  tilt + lean  (two 12-bit signed values sharing D6)
```

KTM test vector (from `ktm-can/tests/test_decoder.py::test_12B`): frame `12B 00 00 02 16 00 02 8F FD` → rear_wheel = 534 (= `0x0216`), front_wheel = 0, tilt = 40, lean = -3. **The decoder emits raw uint16; KTM does not document a km/h conversion factor.**

### How `12D` on Husqvarna lines up byte-for-byte

| Byte | KTM `12B` role         | Husqvarna `12D` (observed)                     |
|------|------------------------|------------------------------------------------|
| D0   | front wheel high byte  | STATIC `0x00` (front not spun this session)    |
| D1   | front wheel low byte   | STATIC `0x00`                                  |
| D2   | rear wheel high byte   | **Varies with rear motion** (this finding)     |
| D3   | rear wheel low byte    | STATIC `0x00` even during all 836 Phase B motion frames |
| D4   | unknown                | STATIC `0x00`                                  |
| D5   | tilt high byte (8 bits)| STATIC `0x00`                                  |
| D6   | tilt low / lean high   | **Varies with rear motion** (Husq-specific repurpose) |
| D7   | lean low byte          | Universal D7 6-cycle byte ([[byte-d7-cycle-hash]]) — not data |

So **D2 sits exactly where KTM puts the rear-wheel uint16 high byte**, and the byte that varies on Husqvarna matches that role. The strong implication for the still-unknown front-wheel byte is:

> **Prediction: `12D` D0..D1 carries front wheel speed** in the same big-endian uint16 encoding KTM uses for rear. Testable on a front-only spin or any real motion capture — both bytes should ramp together with front motion only.

### Why D3 may stay at zero

KTM's test frame has D2 = `0x02`, D3 = `0x16` (full uint16 = 534) — clearly using the LSB at low speeds. Husqvarna's D3 stays at `0x00` across all 836 motion frames in this capture (hand-spin speeds, peak D2 = `0x4B`). Three working interpretations:

1. **Husqvarna uses single-byte resolution at D2.** The KTM uint16 encoding doesn't transfer — Husqvarna's simpler ABS module quantises wheel speed to single-byte precision and leaves D3 as padding.
2. **D3 activates above a speed/quality threshold** that hand-spin never reaches. Hand-spin is bursty and slow; the actual rolling-bike use case may exercise D3.
3. **The encoding is something other than KTM's uint16** — e.g. D2 is tone-ring teeth per CAN cycle, integer-valued, no LSB needed.

Resolves on a road capture where D2 reaches its likely upper range. If D3 stays 0 even at realistic riding speeds, interpretation (1) is confirmed and the rear-wheel resolution is the same as the byte's resolution — much coarser than KTM.

### D6 — Husqvarna-specific repurpose

KTM uses D5..D7 for lean/tilt (12-bit signed integers sharing D6). The 2020 Svartpilen 401 has no lean angle sensor — its ABS module is simpler than the KTM 690's — so D5..D7 are free to repurpose. Husqvarna uses:

- **D5**: STATIC `0x00` (unused / padding).
- **D6**: A wheel-motion-derived quantity, varies with rear-wheel spin in this capture, ratio D6/D2 ~1.53× at peak and ~1.17× at decay tail.
- **D7**: The universal cross-ID 6-cycle byte ([[byte-d7-cycle-hash]]), unrelated to wheel speed.

So D6 is a genuine new signal not present in KTM's mapping — the lean/tilt slot has been replaced with a wheel-derived value. See the "Why two bytes for one wheel?" section above for hypotheses on what D6 actually encodes.

### Patterns and confidence

- This is the third ID-level relocation in the Husqvarna ↔ KTM cross-walk: kill switch (KTM `120` D3 bit 4 → Husq `541` D2 bit 4), wheel speed (KTM `12B` → Husq `12D`). The relocated IDs all sit in the same broadcast-period cohort as the KTM original (10 ms in this case), suggesting the Bosch ECU's broadcast scheduler structure is preserved but ID numbers are platform-specific.
- **Byte positions D0..D3 appear preserved** (front pair + rear pair). **Byte positions D4..D7 differ** (Husqvarna repurposes D5..D7 from KTM's lean/tilt to "padding + extra wheel signal + universal checksum"). This is a cleaner pattern than the earlier "`540` shifts one byte earlier" observation — `12D` doesn't shift, it just truncates the KTM layout and adds a new signal.

## Evidence

- [`docs/experiments/2026-06-22-wheel-spin-paddock-stand.md`](../../experiments/2026-06-22-wheel-spin-paddock-stand.md) — Result section (per-push table, peak values, envelope statistics).
- [`logs/2026-06-22-wheel-spin-paddock-stand/`](../../../logs/2026-06-22-wheel-spin-paddock-stand/) — raw capture, 77 694 frames.
- [`scripts/wheel_spin_scan.py`](../../../scripts/wheel_spin_scan.py) — per-push analysis script.

## Open

- **Byte-to-km/h scaling.** No real-speed reference in this capture, and KTM's decoder emits raw uint16 with no km/h factor either — so the cross-walk doesn't unlock the units. Resolves on a road or roll-the-bike capture with the OEM speedo visible. Promote from `provisional` to `confirmed` once a calibration trace exists.
- **D6 vs D2 — what's actually different.** Three working hypotheses above; need a steady-state spin or a long road capture to discriminate.
- **Front wheel speed.** Location predicted by the KTM cross-walk to be `12D` D0..D1 as big-endian uint16 (KTM puts it there on `12B`). Both bytes are STATIC `0x00` in this rear-only capture, consistent with the prediction. Resolves on a front-only spin (Phase C of [[2026-06-22-wheel-spin-paddock-stand]], deferred for lack of a front stand) or any real motion capture.
- **Auto-headlight as a derived signal.** No separate "headlight on" bit appears in the always-on broadcast (full-bit scan returned only D2 bit 6, which is just the high bit of the speed byte). Hypothesis: the body controller drives the headlight directly from this byte (or an internal "vehicle moving" line) with no CAN intermediate. Threshold appears to be near `12D` D2 ≥ 0x40, but unconfirmed — needs a session with synchronised `b` (headlight transition) marks. See experiment Follow-ups.
- **What happens above hand-spin speeds.** Phase B peak D2 was 0x4B (75); we have no idea what the byte does at riding speeds (0x80? 0xFF? overflow? wraparound?). Open until a road capture.

See also: [[always-on-broadcast-ids]], [[ktm-can-decoder]], [[signal-side-stand]] (for the `540` shift pattern, contrast with this `12B`→`12D` ID move).
