---
area: can
status: confirmed
established_by:
  - 2026-06-24-front-wheel-decay-mark
---

# Encoding pattern: split-width fields in a 16-bit slot

A 16-bit (two-byte) BE slot is shared between **a wider primary signal in the high bits** and **one or more narrow co-located signals in the low bits**. The "extra bits at the bottom" are *not* padding — they carry separate information that's easy to mistake for measurement quantisation.

## Detection vs interpretation

A first pass scan flags the pattern: `(raw_u16 & 0x000F) == 0` across most frames of the slot. Two things to keep in mind:

1. **A clean-modulo result doesn't mean "12-bit value, 4 bits of padding"** — it means the low 4 bits *happened to be zero in the captured conditions*. The bits may carry signals that are only active in different operating modes (engine on vs off, sensor activation gates, etc.). Always cross-check across multiple operating points before concluding the low bits are unused.
2. **Decoder for the wide field must explicitly mask the low bits**, even if they appear zero in your training data:

```python
value = ((data[hi] << 8) | (data[lo] & 0xF0)) / scale
# NOT: value = ((data[hi] << 8) | data[lo]) / scale
```

The naïve uint16 decode breaks the moment the low-nibble signal fires.

## Confirmed instance: front wheel speed `12D` D0:D1

- **Wide field** (bits 15:4 of the BE u16) = front wheel speed, 12-bit value, LSB 1/192 km/h. See [[signal-wheel-speed-front]].
- **Narrow field** (bit 0 of the low byte) = engine-correlated flag, set ~3.5% of frames in engine-on conditions, always clear engine-off. See [[signal-12d-d1-bit0]].
- **Bits 1-3 of the low byte** = still always zero in everything observed; possibly reserved, possibly more signals not yet exercised.

In all engine-off captures, every non-zero raw `(D0 << 8) | D1` value is a multiple of 16 (the speed field on its own). In the engine-on capture, raw = `0x0001` appears 1002 times — speed field zero, flag bit set — confirming the bits are independent.

## Why this matters

- **Don't assume a 16-bit field uses all 16 bits.** A scan that finds the low 4 bits stuck at zero might still be looking at a multiplexed slot whose other field hasn't fired yet.
- **LSB-fitting is much less mysterious when you factor out the field width.** A signal that looks like LSB ≈ 1/190 km/h on raw u16 is much more clearly LSB = 1/12 km/h on the 12-bit extracted value. 1/12 is binary-friendly (= 1/0xC) where 1/190 isn't.
- **Always test across multiple operating regimes** before promoting the "(raw & 0x000F) == 0" observation to a structural claim. Engine-off / engine-on is the cheapest split for any speed-adjacent signal; key-off-to-key-on for any boot-state signal; pre-fault-to-post-fault for any health/diagnostic signal.

## Where to look next

- **Rear wheel speed `12D` D5:D6** — the same kind of scan against [[2026-06-23-engine-driven-rear-spin]] showed the rear *does* set its low nibble (16 202 frames of low-nibble-non-zero) — so rear D5:D6 is genuine 16-bit, with no protected nibble. The front-vs-rear asymmetry within `12D` is real and not just a scan artifact.
- **`121` D0..D3 (twin int16 channels)** — already known to be signed-int16 BE pairs ([[byte-121-twin-int16]]); worth checking whether either channel has a stuck-zero low nibble or whether all 16 bits genuinely move.
- **Any future uint16-decoded signal** — add the modulo-16 check to the decoding scratchpad, *and* check the same against captures from multiple operating regimes before concluding the low bits are unused.

## Evidence

- [[2026-06-24-front-wheel-decay-mark]] — initial discovery of the multiples-of-16 pattern.
- [[2026-06-23-engine-driven-rear-spin]] — surfaced the engine-on bit-0 activity that broke the naïve "12-bit padding" reading.
- [`scripts/front_wheel_decay_mark.py`](../../../scripts/front_wheel_decay_mark.py) — the low-end distribution scan.

See also: [[signal-wheel-speed-front]], [[signal-12d-d1-bit0]], [[signal-wheel-speed-rear]].
