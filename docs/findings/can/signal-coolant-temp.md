---
area: can
status: confirmed
established_by:
  - 2026-06-17-payload-diff-idle
references:
  - ktm-can-decoder
---

# Engine coolant temperature — `540` bytes D5,D6 (big-endian uint16, divide by 10)

Engine coolant temperature on the 2020 Husqvarna Svartpilen 401 is broadcast in arbitration ID **`0x540`**, bytes D5 (high) and D6 (low), as a 16-bit big-endian unsigned integer in units of **0.1 °C**.

```
coolant_temp_celsius = ((data[5] << 8) | data[6]) / 10.0
```

Update rate: 100 ms (the broadcast period of `540` — see [[always-on-broadcast-ids]]).

## Verified ranges

From the thermal sweep across the three engine-idle captures of [`2026-06-17-engine-idle-baseline-x3`](../../experiments/2026-06-17-engine-idle-baseline-x3.md):

| Run | Engine thermal state at session | Median (°C) | Min – max (°C) |
|-----|---------------------------------|------------:|---------------:|
| 1   | Cold start (engine not run today before this) | 48.3 | 25.8 – 63.9 |
| 2   | Partial warm (Run 1 + ~13 min key-off cool)   | 66.6 | 50.3 – 78.6 |
| 3   | Operating temperature (~half coolant gauge)   | 85.5 | 74.5 – 91.7 |

Run 3's median 85.5 °C corresponds to the rider-reported half-gauge reading at the end of capture. Run 1 starts at ~26 °C (close to ambient ~30 °C) and climbs to ~64 °C as the engine warms during the 175 s idle window. Run 3 starts at ~74 °C and reaches ~92 °C by the end — consistent with continued thermal soak at idle.

## Byte position differs from KTM 690

The ktm-can decoder ([reference](../../references/ktm-can-decoder.md)) puts coolant temp at `540` bytes D6,D7 on the 2020 KTM 690 Enduro R. **Husqvarna 401 has the same encoding but shifted one byte earlier — D5,D6 instead of D6,D7.** This is an important lesson for the rest of the decoding work: byte positions are not portable between Bosch ECU variants even when the IDs and broadcast periods are. Test `±1` byte from the KTM position before declaring "no match" on any future signal hypothesis.

`540` byte D7 reads as static `0x00` on our bike — the byte that holds the coolant low byte on KTM 690 is unused here.

## Encoding scale

Verified by triangulating the rider-reported gauge reading at end of Run 3 (visually "half gauge", which on this bike's gauge corresponds to ~80-90 °C operating temperature) against the decoded value (85.5 °C). The 0.1 °C resolution implied by the divide-by-10 scaling is also consistent with what `540` D5,D6 produce — the range 25.8 °C – 91.7 °C in operation is plausibly real coolant readings, not raw ADC counts or some other quantity.

The value reads as ~25-26 °C in the cold-start window. With ambient ~30 °C and the engine fully cold (no run prior to this session), this is consistent — coolant temp tracks block temperature, which equilibrates slightly below ambient air temp when the engine has been off for many hours and ambient is high enough.

## Open

- **High-temperature behaviour.** Verified only up to ~92 °C. A capture during sustained higher load (longer idle, fan-cycle trigger, hot ambient day) would confirm encoding stays linear above 100 °C and through cooling-fan engagement.
- **Cold-cold behaviour.** Coldest observed value is 25.8 °C. A genuine overnight cold start would extend the verified low end (this matters because some coolant encodings have a different offset below ambient).
- **Sensor identity.** This is presumably the coolant temperature sensor in the cylinder head / thermostat housing, not intake air temp or oil temp. Not verified — could theoretically be a different temperature sensor that happens to track coolant closely. Confirming would require either a long-soak post-ride capture (oil cools differently from coolant) or scoping the actual sensor.

## Evidence

- [`docs/experiments/2026-06-17-payload-diff-idle.md`](../../experiments/2026-06-17-payload-diff-idle.md) — Result section, "Alternative hypothesis: `540` D5,D6 = coolant ×10" subsection.
- Re-derive: `scripts/payload_diff.py` flags `540[5]` as COOLANT-TEMP-CAND with per-run medians [1, 2, 3]; the full multi-byte value comes from the inline verification at the end of the experiment file.

See also: [[always-on-broadcast-ids]], [[signal-rpm]], [[post-kill-decay-groups]] (the `540` ID is in the Slow decay group — coolant temperature continues broadcasting for several seconds after kill, consistent with the source module remaining powered briefly).
