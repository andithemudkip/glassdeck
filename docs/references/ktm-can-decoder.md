# Reference: ktm-can decoder (KTM 690 Enduro R, 2020)

Public Python decoder for the CAN bus of a 2020 KTM 690 Enduro R, by [@mattallty/willglynn etc., upstream credit Dan Plastina](https://advrider.com/f/threads/results-from-hacking-the-ktm-superduke-1290-can-bus.1200087/). Repository (local working copy on this machine): `/Users/andrei/Developer/ktm-can/`.

## Why this matters for our project

The KTM 690 Enduro R uses the same Bosch ECU family as the 2020 Husqvarna Svartpilen 401 / KTM 390 platform. Cross-checked against our [`docs/findings/can/always-on-broadcast-ids.md`](../findings/can/always-on-broadcast-ids.md) capture, **five of the seven IDs the ktm-can decoder targets are present on our bike's diagnostic stub at the same broadcast periods.**

| CAN ID | Period   | Present on Svartpilen 401? | Period match? |
|--------|----------|----------------------------|---------------|
| `120`  | 20 ms    | ✅ Yes                     | ✅ ~19.4 ms   |
| `129`  | 20 ms    | ✅ Yes                     | ✅ ~19.4 ms   |
| `12A`  | 50 ms    | ✅ Yes                     | ✅ ~50.2 ms   |
| `12B`  | 10 ms    | ❌ Not present             | —             |
| `290`  | 10 ms    | ❌ Not present             | —             |
| `450`  | 50 ms    | ✅ Yes                     | ✅ ~49.9 ms   |
| `540`  | 100 ms   | ✅ Yes                     | ✅ ~99.6 ms   |

The two missing IDs (`12B` wheel speeds / lean / tilt, `290` front brake pressure) are likely chassis-electronics IDs that the Husqvarna's simpler ABS module doesn't emit on the diagnostic stub — they may exist on a different bus segment, or simply not be present on this platform.

## Signal mappings — apply, don't trust

The ktm-can decoder is a **hypothesis source**, not a drop-in decoder for the Svartpilen 401. Byte positions can shift between Bosch ECU variants, signal sets differ, and a value that reads as `kill_switch=0` on KTM may be inverted, repositioned, or absent on Husqvarna. Each KTM signal needs **independent verification** against our captures before being promoted to a finding.

### Confirmed-matching signals (verified against our data)

| Signal       | Location (KTM) | Location (Husqvarna 401) | Encoding              | Established by |
|--------------|----------------|--------------------------|-----------------------|----------------|
| Engine RPM   | `120` D0,D1    | **same — `120` D0,D1**   | Big-endian uint16     | [[signal-rpm]] |
| Coolant temp | `540` D6,D7    | **`540` D5,D6 (shifted -1 byte)** | Big-endian uint16, divide by 10 → °C | [[signal-coolant-temp]] |
| Kill switch  | `120` D3 bit 4 | **`541` D2 bit 4 (different ID)** | 1 = run, 0 = stop (polarity matches KTM) | [[signal-kill-switch]] |

### Hypotheses to test in future per-input captures

Listed in priority order — easiest to test first, all engine-off where possible:

| Signal                       | KTM location           | Test (suggested capture)                                  |
|------------------------------|------------------------|-----------------------------------------------------------|
| Throttle position            | `120` D2 (range 0-255) | Engine-off: throttle sweep capture                        |
| Gear position                | `129` D0 hi nibble; `540` D3 lo nibble | Cycle through gears with clutch (engine off OK) |
| Clutch switch                | `129` D0 bit 3         | Engine-off: clutch in/out a few times                     |
| Throttle open/closed flag    | `12A` D0 bit 1         | Same throttle sweep capture                               |
| Throttle map (actual)        | `120` D4 bit 0         | Cycle ROAD/SUPERMOTO map switch                           |
| Throttle map (requested)     | `12A` D1 bit 6         | Same capture as above                                     |
| Traction control button      | `450` D2 bit 0         | Press TC button if equipped                               |
| Kickstand up flag            | `540` D4 bit 0         | Side stand up vs down (engine off)                        |
| Kickstand error              | `540` D4 bit 7         | Hard to engineer — keep an eye on it                      |
| Key-on / engine-running flag | `540` D4 bit 3         | Already validated indirectly via [[always-on-broadcast-ids]] — confirm bit position |

### Non-matching / inconclusive

- **`540` D0**: KTM has `0x02` always. We see `0x00` always. So *something* is different at the head of the 540 message — could be ECU variant id, model code, or just unused on our bike. Not load-bearing.
- **`540` D1,D2 = RPM (slow update)**: KTM claims `540` carries the same RPM signal as `120`, slower. Our data does not support this — `540` D1,D2 big-endian interpreted as RPM gives idle values of 3500–4400, well above this bike's true idle (~1700 RPM, confirmed via `120` D0,D1). `540` D1 in our data is thermally-correlated but doesn't behave like RPM. **Best read: Husqvarna's `540` does not carry a second RPM copy at D1,D2** — the byte is something else (possibly a thermal correction parameter or idle-stability metric).
- **`12B`, `290`**: not present on our bus.

### Constants that match

- `129` D0 = 0x00 throughout idle (matches "gear=neutral=0", "clutch out=0").
- `540` D3 = 0x00 throughout idle (matches "gear=neutral=0").
- `540` D4 = 0x00 throughout idle (matches "kickstand=down=0" per KTM's encoding, *and* the bike was on its side stand during captures).

## Notes on style differences

Bosch ECUs for KTM/Husqvarna platforms ~2020 era share the message scheduler (so IDs and periods carry over), but the payload byte assignments are per-variant. The ktm-can author's caveat ("only verified on my 2020 KTM 690 Enduro R") is exactly the right frame: treat their work as a high-quality prior for the search, not as ground truth.

## Citation

When promoting a finding established by cross-checking against this reference, cite both the ktm-can source file (e.g. `ktm-can/src/ktm_can/decoder.py @ 0x540`) and the experiment that verified the match against our captures.
