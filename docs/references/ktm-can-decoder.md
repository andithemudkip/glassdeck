# Reference: ktm-can decoder (KTM 690 Enduro R, 2020)

Public Python decoder for the CAN bus of a 2020 KTM 690 Enduro R, by [@mattallty/willglynn etc., upstream credit Dan Plastina](https://advrider.com/f/threads/results-from-hacking-the-ktm-superduke-1290-can-bus.1200087/). Repository (local working copy on this machine): `/Users/andrei/Developer/ktm-can/`.

## Why this matters for our project

The KTM 690 Enduro R uses the same Bosch ECU family as the 2020 Husqvarna Svartpilen 401 / KTM 390 platform. Cross-checked against our [`docs/findings/can/always-on-broadcast-ids.md`](../findings/can/always-on-broadcast-ids.md) capture, **five of the seven IDs the ktm-can decoder targets are present on our bike's diagnostic stub at the same broadcast periods.**

| CAN ID | Period   | Present on Svartpilen 401? | Period match? |
|--------|----------|----------------------------|---------------|
| `120`  | 20 ms    | ✅ Yes                     | ✅ ~19.4 ms   |
| `129`  | 20 ms    | ✅ Yes                     | ✅ ~19.4 ms   |
| `12A`  | 50 ms    | ✅ Yes                     | ✅ ~50.2 ms   |
| `12B`  | 10 ms    | ❌ Not present              | —             |
| `290`  | 10 ms    | ❌ Not present              | —             |
| `450`  | 50 ms    | ✅ Yes                     | ✅ ~49.9 ms   |
| `540`  | 100 ms   | ✅ Yes                     | ✅ ~99.6 ms   |

KTM's `12B` ID itself is **not present** on the Husqvarna bus, but wheel-speed data lives on Husqvarna's `12D` instead (also 10 ms — see [[signal-wheel-speed-rear]]). KTM's `290` (front brake pressure) has no Husqvarna analog identified yet — possibly chassis-electronics that this bike's simpler ABS module doesn't emit on the diagnostic stub.

## Signal mappings — apply, don't trust

The ktm-can decoder is a **hypothesis source**, not a drop-in decoder for the Svartpilen 401. Byte positions can shift between Bosch ECU variants, signal sets differ, and a value that reads as `kill_switch=0` on KTM may be inverted, repositioned, or absent on Husqvarna. Each KTM signal needs **independent verification** against our captures before being promoted to a finding.

### Confirmed-matching signals (verified against our data)

| Signal       | Location (KTM) | Location (Husqvarna 401) | Encoding              | Established by |
|--------------|----------------|--------------------------|-----------------------|----------------|
| Engine RPM   | `120` D0,D1    | **same — `120` D0,D1**   | Big-endian uint16     | [[signal-rpm]] |
| Throttle position | `120` D2  | **same — `120` D2**      | uint8, range 0–254    | [[signal-throttle-position]] |
| Gear position (N, 1) | `129` D0 hi nibble | **same — `129` D0 hi nibble** | `0=N, 1–6=gears` (2–6 unverified) | [[signal-gear-position]] |
| Coolant temp | `540` D6,D7    | **`540` D5,D6 (shifted -1 byte)** | Big-endian uint16, divide by 10 → °C | [[signal-coolant-temp]] |
| Kill switch  | `120` D3 bit 4 | **`541` D2 bit 4 (different ID)** | 1 = run, 0 = stop (polarity matches KTM) | [[signal-kill-switch]] |
| Side stand   | `540` D4 bit 0 | **`540` D3 bit 0 (shifted -1 byte)** | 1 = up, 0 = down (polarity matches KTM) | [[signal-side-stand]] |
| Rear wheel speed | `12B` D2..D3 (uint16 BE) | **`12D` D2 (high byte; D3 static — single-byte resolution)** | Same byte position as KTM's high byte; LSB stays 0 at hand-spin speeds; units TBD | [[signal-wheel-speed-rear]] |
| Rear wheel speed (extra) | (n/a — KTM uses D6 for lean) | **`12D` D6 (Husqvarna-only)** | Husq repurposes D5..D7 from KTM's lean/tilt; D6 is a wheel-derived signal, D7 = universal cycle, D5 = padding | [[signal-wheel-speed-rear]] |

### Hypotheses to test in future per-input captures

Listed in priority order — easiest to test first, all engine-off where possible:

| Signal                       | KTM location           | Test (suggested capture)                                  |
|------------------------------|------------------------|-----------------------------------------------------------|
| **Front wheel speed**        | `12B` D0..D1 (uint16 BE) | **Predicted at `12D` D0..D1** by analogy with rear (D2..D3 match KTM). Test on front-only spin or real motion capture; D0..D1 currently STATIC `0x00` in rear-only data |
| Clutch switch                | `129` D0 bit 3         | Engine-off scan refuted; revalidate engine-on              |
| Throttle open/closed flag    | `12A` D0 bit 1         | Refuted engine-off ([[signal-throttle-position]]); revalidate engine-on |
| Throttle map (actual)        | `120` D4 bit 0         | Cycle ROAD/SUPERMOTO map switch                           |
| Throttle map (requested)     | `12A` D1 bit 6         | Engine-off suppressed; revalidate engine-on               |
| Traction control button      | `450` D2 bit 0         | Press TC button if equipped                               |
| Kickstand error              | `540` D4 bit 7         | Hard to engineer — keep an eye on it                      |
| Key-on / engine-running flag | `540` D4 bit 3         | Already validated indirectly via [[always-on-broadcast-ids]] — confirm bit position |

### Non-matching / inconclusive

- **`540` D0**: KTM has `0x02` always. We see `0x00` always. So *something* is different at the head of the 540 message — could be ECU variant id, model code, or just unused on our bike. Not load-bearing.
- **`540` D1,D2 = RPM (slow update)**: KTM claims `540` carries the same RPM signal as `120`, slower. Our data does not support this — `540` D1,D2 big-endian interpreted as RPM gives idle values of 3500–4400, well above this bike's true idle (~1700 RPM, confirmed via `120` D0,D1). `540` D1 in our data is thermally-correlated but doesn't behave like RPM. **Best read: Husqvarna's `540` does not carry a second RPM copy at D1,D2** — the byte is something else (possibly a thermal correction parameter or idle-stability metric).
- **`12B`, `290`**: not present on our bus.

### Constants that match (and one that doesn't)

- `129` D0 = 0x00 throughout idle (matches "gear=neutral=0", "clutch out=0").
- `540` D3 hi nibble: KTM expects gear here as a redundant copy. Refuted on Husqvarna — D3 lo nibble does not carry gear ([[signal-gear-position]]), and D3 bit 0 carries the side-stand state ([[signal-side-stand]]). The hi nibble is LOW-CARD(4) at engine-on idle; identity unknown.
- `540` D4 = 0x00 throughout idle and across the side-stand toggle capture (matches KTM's "kickstand=down=0" *value*, but Husqvarna doesn't store the kickstand bit here — it's at D3 bit 0 instead; D4 is something else, currently observed as static-zero).

## Notes on style differences

Bosch ECUs for KTM/Husqvarna platforms ~2020 era share the message scheduler (so IDs and periods carry over), but the payload byte assignments are per-variant. The ktm-can author's caveat ("only verified on my 2020 KTM 690 Enduro R") is exactly the right frame: treat their work as a high-quality prior for the search, not as ground truth.

### Patterns observed so far

- **`540` byte layout is shifted one byte earlier on Husqvarna.** Coolant temp (KTM D6,D7 → Husq D5,D6) and side stand (KTM D4 bit 0 → Husq D3 bit 0) both moved by exactly -1. Worth using as a starting hypothesis when probing the next `540` signal.
- **Polarity preservation.** Every Husqvarna signal verified against a KTM hypothesis so far has preserved KTM's polarity (engine RPM, throttle position, gear, coolant temp, kill switch, side stand). No inverted-polarity case has surfaced yet — but the kill-switch case (location moved to a different ID entirely) shows that "polarity preserved" doesn't imply "byte position preserved".
- **ID relocation is common.** Two Husqvarna signals now sit on a different ID than KTM: kill switch (KTM `120` → Husq `541`) and wheel speed (KTM `12B` → Husq `12D`). The receiving period matches in both cases (so the broadcast scheduler still knows the right slot), but the ID number itself changes. Treat the KTM ID as a starting hypothesis, but always scan adjacent IDs in the same period cohort.

## Citation

When promoting a finding established by cross-checking against this reference, cite both the ktm-can source file (e.g. `ktm-can/src/ktm_can/decoder.py @ 0x540`) and the experiment that verified the match against our captures.
