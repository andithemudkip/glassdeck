---
area: can
status: provisional
established_by:
  - 2026-07-22-first-moving-ride
---

# Shift-in-progress ignition cut + downshift auto-blip — `121` D6 bits 0, 1

The Svartpilen 401 broadcasts two bits on `121 D6` that fire during every real gear shift:

| Bit | Fires on | Meaning |
|-----|----------|---------|
| bit 0 | every up- and downshift | ECU-issued ignition cut for the shift |
| bit 1 | only downshifts | auto-blip (throttle blip to match revs) |

The only observed byte values on `121` D6 are `0x00` (normal), `0x01` (upshift), and `0x03` (downshift). Bits 2-7 have never been observed set across the corpus.

```python
shift_cut_active = bool(data[6] & 0x01)   # ignition cut for shift in progress
downshift_blip   = bool(data[6] & 0x02)   # only set with bit 0 during downshifts
shift_direction  = "downshift" if downshift_blip else "upshift" if shift_cut_active else None
```

## What this bit doesn't tell you: QS vs clutched

An early reading of this bit (before rider feedback) claimed it fired *only* on quickshifter shifts because the [[signal-clutch]] bit stayed 0 during 65 of 66 shift windows. **That inference is wrong** because the clutch-lever switch on this bike is mechanically shoddy and often fails to register even when the rider is genuinely using the clutch — see [[signal-clutch]] "Lever-switch threshold" and [[project-clutch-sensor-unreliable]] (memory). Rider confirmed on 2026-07-22 that they used a mix of QS and clutched shifts during the ride, but only 1 clutched N-engagement (out of ~ 10 expected) triggered the clutch bit.

So the CAN-only picture is:

- `121 D6 bit 0` fires on **every** observed shift, regardless of whether the rider used QS or the clutch.
- `signal-clutch` (`129` D0 bit 3) fires on **some** shifts where the rider actually used the clutch, missing others.
- Without a reliable clutch signal, this data cannot distinguish QS from clutched shifts.

Two possible ECU-side stories fit:

1. **ECU always cuts ignition for any shift** — whether the rider used QS or the clutch, the shift-lever strain sensor triggers ignition cut. Bit 0 = "any shift event". Some sport-bike ECUs work this way.
2. **ECU only cuts for QS, but with a broken clutch input it can't tell** — the strain gauge triggers, the ECU tries to check the clutch sensor to see if it's a clutched shift and skip the cut, but the clutch bit reads 0 (broken sensor), so the ECU treats every shift as QS. Bit 0 = "ECU thinks it's a QS shift", which happens to be all of them on this bike because of the broken sensor.

Both are consistent with the observed 100 % fire rate. A capture with a **repaired or bypassed** clutch sensor — one that reliably reports rider clutch use — would decide between the two stories: does bit 0 skip when the ECU knows the clutch is pulled? Not resolvable on this ride.

## Evidence — timing

Per `scripts/first_moving_ride_qs_bit_probe.py` on 56 real gear-to-gear transitions (excluding 10 N-to/from-1 engagements from stopped):

| Metric | Upshifts | Downshifts |
|--------|---------:|-----------:|
| Onset relative to gear-enum change | median -40 ms (leads by 20-80 ms) | median -22 ms (leads by 0-140 ms) |
| Cut duration | median 60 ms, range 20-141 ms | median 60 ms, range 20-200 ms |

The bit rises 20-140 ms **before** the `129` D0[7:4] gear enum increments (or decrements). Matches the mechanical picture: shift-lever strain sensor triggers → ECU cuts ignition → dogs unload → gear engages (the enum changes) → ignition resumes. Median 60 ms cut is right in the typical Bosch shift window.

Downshift cuts can be longer (max 200 ms observed on a 2 → 1 downshift under moderate load); consistent with the ECU holding the cut through the auto-blip until RPM matches the new ratio.

## Evidence — up vs down partitioning is exact

56 real gear-to-gear transitions, from `scripts/first_moving_ride_qs_bit1.py`:

| Direction | Total | 0x01 (bit 0 only) | 0x03 (bits 0+1) |
|-----------|:-----:|:-----------------:|:---------------:|
| Upshift   |  31   | **31 (100 %)**    | 0                |
| Downshift |  25   | 0                 | **25 (100 %)**   |

No upshift set bit 1, no downshift set bit 0 alone. Bit 1 is a clean "downshift" discriminator — an auto-blip flag that only makes sense on downshifts (matching revs on the way down).

## Out-of-window baseline

- Overall duty of `121` D6 bit 0 across the ride: **0.46 %** (212 frames set across ~ 46 000 `121` frames).
- **100 % of those set frames** fall inside a ±400 ms shift window. Zero out-of-window fires.

Bit 0 is a genuine shift-event flag — not a byproduct of some other varying signal on `121`, and not triggered outside shifts.

## Cross-walk vs KTM

The ktm-can decoder ([reference](../../references/ktm-can-decoder.md)) does not document a quickshifter or shift-cut signal on the 2020 KTM 690 Enduro R — that model doesn't have QS from the factory on the covered years. This is a 401-specific broadcast (or a KTM 390 platform broadcast the 690 lacks).

## What this newly attributes

`121` D6 was previously an all-`?` byte in [`docs/signals/coverage.md`](../../signals/coverage.md). This finding attributes bits 0 and 1. Bits 2-7 of D6 remain uncharted; the byte is otherwise `0x00` across the entire moving corpus.

## Open

- **QS vs clutched discrimination.** Not resolvable from this ride's CAN. Requires either a fixed clutch sensor or a rider-marked capture where every shift's actual mechanism is labelled at capture time. Once resolvable, either (a) the bit is confirmed as "any-shift ignition cut" and this finding stands, or (b) the bit is confirmed as "QS-only" and needs renaming.
- **What lives in `121` D6 bits 2-7.** All observed as 0 across the moving corpus. Candidates: rev-limiter engaged, wheelie-control cut, pit-limiter, over-speed cut. Would need scenarios that trigger those to exercise.
- **What lives in `121` D4.** Latched at `0x04` across the whole moving corpus, with only 10 frames at `0x00` at moving-2 startup. Likely a system-startup indicator, similar to `5A0 D4`.

## Evidence

- [[2026-07-22-first-moving-ride]] moving-1..4 — 66 gear transitions across a real-world ride.
- [`scripts/first_moving_ride_quickshifter.py`](../../../scripts/first_moving_ride_quickshifter.py) — shift enumeration + initial classification (attempted, superseded by the clutch-sensor caveat).
- [`scripts/first_moving_ride_qs_bit_probe.py`](../../../scripts/first_moving_ride_qs_bit_probe.py) — per-shift bit-timing analysis (onset, duration, out-of-window baseline).
- [`scripts/first_moving_ride_qs_bit1.py`](../../../scripts/first_moving_ride_qs_bit1.py) — bit 1 as downshift-blip discriminator.

See also: [[signal-gear-position]], [[signal-clutch]] (with the shoddy-switch note that's load-bearing for the QS-vs-clutched discussion above), [[signal-shift-failed]] (transient flag on failed shifts — separate `129` D0 bit 1, orthogonal to this one), [[byte-121-twin-int16]] (same ID, D0-D3, engine-torque candidate — note that torque channels dip during the ignition cut, providing indirect corroboration that the bit really does gate ignition).
