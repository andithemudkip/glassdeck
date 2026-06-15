# blalor/ktm-can — KTM CAN decoder reference

Closest existing prior art for the KTM CAN map. Useful as a **starting hypothesis** for what to look for in our captures and how to interpret payloads — *not* as a ground-truth source for the 390 platform.

## Source

- Repo: <https://github.com/blalor/ktm-can>
- Language: Python (CAN decoder library)
- License: **none specified** — treat as "look, don't republish." We can cite IDs and verify against our own captures; we should not vendor their code into this repo.
- Last code change: 2021-02-28 — effectively static. The decoder file is the canonical artifact; no active development.
- Upstream decoding credit: Dan Plastina, original work on a 2017 SuperDuke 1290, documented on the ADVrider forum. blalor extended it for a 2020 KTM 690 Enduro R.
- Forum thread: ["Results from hacking the KTM SuperDuke 1290 CAN bus"](https://advrider.com/f/threads/results-from-hacking-the-ktm-superduke-1290-can-bus.1200087/) on advrider.com — referenced in the repo README as the upstream source of decoding notes.

## What it documents

CAN ID layout for the 2020 KTM 690 Enduro R. All IDs are **11-bit standard** (range `0x120`–`0x540`) and the message structure is the classic 8-byte CAN 2.0A payload. Frame rates are in milliseconds.

| CAN ID | Period | Signals | Notes |
|--------|-------:|---------|-------|
| `0x120` | 20 ms | `rpm` (D0–D1, BE u16), `throttle` 0–255 (D2), `kill_switch` (D3 bit 4), `throttle_map` actual (D4 bit 0) | Fast RPM source. D7 is a 6-step rolling counter. |
| `0x129` | 20 ms | `gear` (D0 high nibble; 0 = N), `clutch_in` (D0 bit 3) | D7 is another rolling counter. |
| `0x12A` | 50 ms | `requested_throttle_map` (D1 bit 6), `throttle_open` flag (D0 bit 1) | Several bytes asserted to be always 0 — good unmapped-byte indicator. |
| `0x12B` | 10 ms | `front_wheel`, `rear_wheel` (D0–D3, two BE u16s), `lean` and `tilt` (12-bit signed, packed into D5–D7) | Highest-rate frame in the set. The lean/tilt layout is the trickiest decode in the file. |
| `0x290` | 10 ms | `front_brake` (D0–D1, BE u16) | D2–D7 asserted always 0. |
| `0x450` | 50 ms | `traction_control_button` (D2 bit 0) | D4 toggles 0x00/0x09 around map requests — likely mirrors `0x12A` mode bit. |
| `0x540` | 100 ms | `rpm` (D1–D2), `gear` (D3 low nibble; 7 = unknown), `kickstand_up` and `kickstand_err` (D4), `coolant_temp` °C (D6–D7 BE u16 / 10) | Slow RPM source — same value as `0x120` but updated 5× slower. Useful cross-check. |

`0x540` D4 also carries a "key on, kill switch on, not running" bit that drops once the engine starts — looks like a useful "is the engine actually running" indicator if it reproduces on the 390.

## What's *not* in there

- ABS / wheel-sensor health bits beyond raw wheel speeds.
- Indicator / blinker state, high-beam, horn — none decoded.
- Dashboard mode button (ROAD ↔ SUPERMOTO) — this is one of our specific open questions and the library has nothing on it.
- Fuel level, fuel consumption, trip / odometer.
- Any TX-side analysis. The library is read-only.
- Bitrate. The library assumes the host adapter is already on the bus at the right rate; it doesn't document it.

## How we use it

1. **Inform first-capture expectations.** When we capture key-on / engine-on traffic, we expect to see most of these IDs (or close variants) if the 390 reuses the 690 message layout. Absence is itself a finding.
2. **Cross-reference, don't assume.** Every claim above is a hypothesis on our 390 until a capture proves it. Confirmed signals get promoted to `docs/findings/can/<id>.md`; mismatches get recorded as experiments.
3. **Methodology source.** The decoder's per-byte comments (which bytes are constant, which are rolling counters, which mask which bit) show how blalor and Plastina isolated each signal. That methodology is reusable even where the IDs aren't.
4. **Test fixtures as sanity material.** `tests/test_decoder.py` contains raw 8-byte payloads paired with expected decoded values. Even though they're from a 690, they're useful for unit-testing any decoder we write against the *structure* of the message.

## Files worth opening when we're decoding

- `src/ktm_can/decoder.py` — single Python file, function-per-ID with rich inline comments. This is the canonical reference.
- `tests/test_decoder.py` — raw byte → decoded value examples.
- `scripts/decode_log.py`, `scripts/viewer_*.py` — rough live-CAN viewers using `python-can`. Worth a look if we end up writing a similar real-time monitor, but our capture path goes via SLCAN to a host script (see [ADR 0004](../decisions/0004-logger-wire-format-slcan.md)) so the architecture differs.

## Caveats

- **690 ≠ 390.** Bike is a different segment, different ECU, different sensor set. IDs may match, may shift, may carry different scaling. Treat every match as a hypothesis to verify.
- **2017–2021 vintage.** Decoding predates our bike's MY2020 by 0–3 model years on the 690 side, and the SuperDuke source work is from 2017. Some bits may have moved between firmware revisions even on the same ID.
- **No claim of completeness.** The README is explicit that the library covers only what blalor needed for their project. Plenty of bytes are marked `unknown`.
