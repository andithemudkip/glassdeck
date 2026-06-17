---
area: can
status: confirmed
established_by:
  - 2026-06-17-payload-diff-idle
references:
  - ktm-can-decoder
---

# Engine RPM — `120` bytes D0,D1 (big-endian uint16)

Engine RPM on the 2020 Husqvarna Svartpilen 401 is broadcast in arbitration ID **`0x120`**, bytes D0 (high) and D1 (low), as a 16-bit big-endian unsigned integer. The value is the RPM directly — no scale factor, no offset.

```
rpm = (data[0] << 8) | data[1]
```

Update rate: 20 ms (the broadcast period of `120` — see [[always-on-broadcast-ids]]).

## Verified ranges

From the three engine-idle captures of [`2026-06-17-engine-idle-baseline-x3`](../../experiments/2026-06-17-engine-idle-baseline-x3.md), decoded with the formula above:

| Run | Engine state | RPM median | RPM range observed |
|-----|--------------|-----------:|--------------------|
| 1   | key-on, engine off | 0      | 0 only             |
| 1   | engine idle (cold) | 1705   | 1345 – 2098        |
| 2   | engine idle (partial warm) | 1698 | 1419 – 1945    |
| 3   | engine idle (operating temp) | 1702 | 1446 – 1936  |

Engine-off reads as exact 0, including during the 30 s pre-start window with the key in run position. Idle RPM is closed-loop-controlled at ~1700 RPM and is independent of coolant temperature in the observed range (~48 °C cold idle → ~85 °C operating idle).

Peak-to-peak idle jitter is ~600–750 RPM around the mean, which is normal for a single-cylinder engine at idle.

## Encoding cross-check

This is the same byte position and same encoding the ktm-can decoder uses for the 2020 KTM 690 Enduro R ([reference](../../references/ktm-can-decoder.md)). The `120` message head appears to be portable across Bosch ECU variants on the KTM/Husqvarna 2020-era platform — at least for the RPM field.

## Cranking-window behaviour

During the starter-on / engine-catching window (1 – 5 s across the three runs), the RPM value briefly takes intermediate values between 0 and idle. A dedicated cranking-window analysis hasn't been done; the present finding only asserts the *encoding*, not what the RPM signal looks like during the start transient.

## Open

- **Maximum range.** Verified only up to ~2100 RPM (idle peaks). The full 16-bit range allows up to 65 535 RPM, far above the engine's redline (~10 500 RPM for this bike). A revving capture would confirm the value scales linearly up to redline and doesn't switch encoding above some threshold.
- **`540` may also carry RPM** per the KTM decoder (D1,D2 at 100 ms). Our `540` D1,D2 does not match — values are 3–4× idle RPM if interpreted as big-endian uint16. Either the encoding differs, or `540` doesn't carry a redundant RPM on Husqvarna. Either way, `120` is the authoritative source.

## Evidence

- [`docs/experiments/2026-06-17-payload-diff-idle.md`](../../experiments/2026-06-17-payload-diff-idle.md) — Result section, "Hypothesis: `120` D0,D1 = engine RPM" subsection.
- Re-derive with `scripts/payload_diff.py` (classifier output flags `120[0]` as ENGINE-STATE + IDLE-RPM-CAND) plus the inline verification script in the experiment file.

See also: [[always-on-broadcast-ids]], [[signal-coolant-temp]], [[bitrate]].
