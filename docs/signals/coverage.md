# CAN coverage

Index of decoded signals and per-ID payload coverage on the 2020 Husqvarna Svartpilen 401 diagnostic-port bus.

- Encoding-authoritative: [`signals.yaml`](signals.yaml).
- Prose-authoritative: [`docs/findings/can/`](../findings/can/).
- This page is the map: what's decoded, what isn't, where the unknowns live.

## Decoded signals

| Signal | ID | Location | Status | Finding |
|---|---|---|---|---|
| rpm | `120` | D0:D1 BE u16, rpm | confirmed | [signal-rpm](../findings/can/signal-rpm.md) |
| throttle_position | `120` | D2 u8, full scale 254 | confirmed | [signal-throttle-position](../findings/can/signal-throttle-position.md) |
| gear_position | `129` | D0 bits 7:4 enum (N, 1–6) | confirmed | [signal-gear-position](../findings/can/signal-gear-position.md) |
| clutch | `129` | D0 bit 3 bool | confirmed | [signal-clutch](../findings/can/signal-clutch.md) |
| shift_failed | `129` | D0 bit 1 bool | provisional | [signal-shift-failed](../findings/can/signal-shift-failed.md) |
| wheel_speed_front | `12D` | D0:D1 bits 15:4, 12-bit BE, 1/12 km/h | confirmed | [signal-wheel-speed-front](../findings/can/signal-wheel-speed-front.md) |
| rear_speed_27kmh_flag | `12D` | D1 bit 0 | provisional | [signal-12d-d1-bit0](../findings/can/signal-12d-d1-bit0.md) |
| wheel_speed_rear | `12D` | D5:D6 BE u16, 1/16 km/h | confirmed | [signal-wheel-speed-rear](../findings/can/signal-wheel-speed-rear.md) |
| warmup_index | `540` | D1 u8 (interpretation under review) | provisional | [signal-warmup-index](../findings/can/signal-warmup-index.md) |
| side_stand | `540` | D3 bit 0 bool | confirmed | [signal-side-stand](../findings/can/signal-side-stand.md) |
| coolant_temp | `540` | D5:D6 BE u16, 0.1 °C | confirmed | [signal-coolant-temp](../findings/can/signal-coolant-temp.md) |
| kill_switch | `541` | D2 bit 4 bool (primary) | confirmed | [signal-kill-switch](../findings/can/signal-kill-switch.md) |
| engine_on_counter | `541` | D4 bits 6:0, 7-bit mod-128, ~1 Hz | confirmed | [signal-engine-on-counter](../findings/can/signal-engine-on-counter.md) |
| engine_off_counter | `541` | D6 u8, 8-bit mod-256, ~1 Hz | confirmed | [signal-engine-off-counter](../findings/can/signal-engine-off-counter.md) |
| kill_switch (redundant mirror) | `121` | D5 bit 2 | confirmed | [signal-kill-switch](../findings/can/signal-kill-switch.md) |
| kill_switch (redundant mirror) | `5B0` | D0 bit 4 | confirmed | [signal-kill-switch](../findings/can/signal-kill-switch.md) |

### Decoded but unattributed (encoding known, physical quantity not)

| Slot | ID | Location | Status | Finding |
|---|---|---|---|---|
| 121 channel A | `121` | D0:D1 BE int16 | encoding confirmed | [byte-121-twin-int16](../findings/can/byte-121-twin-int16.md) |
| 121 channel B | `121` | D2:D3 BE int16 | encoding confirmed | [byte-121-twin-int16](../findings/can/byte-121-twin-int16.md) |
| front-wheel-speed mirror | `12D` | D3:D4 BE u16, 3/64 km/h LSB | encoding confirmed on D4 (D3 unexercised < 12.7 km/h) | [byte-12d-d3-d4-front-mirror](../findings/can/byte-12d-d3-d4-front-mirror.md) |
| engine-state bits (5×) | `121`, `540` | `121` D1.5, D1.7, D5.3; `540` D2.6, D3.4 | flips engine-on / engine-off, attribution open | [engine-state-bits-decay-shape](../findings/can/engine-state-bits-decay-shape.md) |
| D7 checksum | 9 IDs | D7 | confirmed: 6-cycle XOR ⊕ 5-bit GF(2) hash of D0..D6 | [byte-d7-cycle-hash](../findings/can/byte-d7-cycle-hash.md) |

## Per-ID byte coverage

11 always-on broadcast IDs × 8 bytes = **88 bytes** total. The set is closed: [always-on-broadcast-ids](../findings/can/always-on-broadcast-ids.md) confirms no other arbitration ID broadcasts on this bus, and no UDS / 29-bit traffic is observed.

Cell legend:

- **S** — primary signal here, byte fully accounted for
- **S◐** — primary signal occupies some bits; other bits in the same byte still unknown
- **h** — D7 structural hash, not payload ([byte-d7-cycle-hash](../findings/can/byte-d7-cycle-hash.md))
- **0** — always reads `0x00` across every observed condition; no signal extracted (could be reserved or could carry a latent signal we haven't fired — see [byte-encoding-12-in-16](../findings/can/byte-encoding-12-in-16.md))
- **dup** — known redundant copy of a signal carried canonically elsewhere
- **?** — no decoded structure yet

| ID    | period | D0 | D1 | D2 | D3 | D4 | D5 | D6 | D7 |
|-------|-------:|----|----|----|----|----|----|----|----|
| `120` |  20 ms | S rpm hi | S rpm lo | S throttle | 0 | ? | ? | ? | h |
| `121` |  20 ms | S intA hi | S◐ intA lo + es b5,b7 | S intB hi | S intB lo | ? | S◐ kill-dup b2 + es b3 | ? | h |
| `129` |  20 ms | S◐ gear b7:4, clutch b3, shift-failed b1 (b0,b2 ?) | ? | ? | ? | ? | ? | ? | h |
| `12A` |  50 ms | ? | ? | ? | ? | ? | ? | ? | h |
| `12D` |  10 ms | S frontWS hi | S◐ frontWS hi-nib + 27 km/h flag b0 (b1–3 = 0) | dup coarse rear-speed mirror, 1/10 km/h | S◐ frontWS-mirror hi (observed 0, unexercised < 12.7 km/h) | dup frontWS-mirror lo, 3/64 km/h | S rearWS hi | S rearWS lo | h |
| `12E` |  20 ms | ? | ? | ? | ? | ? | ? | ? | h |
| `450` |  50 ms | ? static | ? static | ? static | ? static | ? static | ? static | ? static | 0 |
| `540` | 100 ms | ? | S warmup-index | S◐ es b6 | S◐ side-stand b0 + es b4 (b5–7 = 0) | ? | S coolant hi | S coolant lo | 0 |
| `541` |  20 ms | ? | ? | S◐ kill-switch b4 | ? | S engine-on counter b0–6 (b7 reserved) | ? | S engine-off counter | h |
| `5A0` | 100 ms | ? | ? | ? | ? | ? | ? | ? | h |
| `5B0` | 100 ms | S◐ kill-dup b4 | ? | ? | ? | ? | ? | ? | h |

`es` = engine-state bit (semantics open, see [engine-state-bits-decay-shape](../findings/can/engine-state-bits-decay-shape.md)).

## Quick stats

After the 2026-06-30 corpus sweep:

| Category | Bytes | %  |
|---|---:|---:|
| Carries a primary signal (S or S◐) | 23 | 26 % |
| Structural D7 hash (h)             |  9 | 10 % |
| Always-zero across 14 sessions (0) |  3 |  3 % |
| Redundant mirror of decoded signal (dup) | 2 | 2 % |
| Undecoded (?)                      | 51 | 58 % |

Whole-ID status:

- **All 8 payload bytes (D0..D6) untouched**: `12A`, `12E`, `5A0` — 3 of 11 IDs have no extracted signal at all. The 2026-06-30 sweep narrowed each of these from "8 unknown bytes" to **exactly one moving byte** across the 14-session corpus: `12A` D1, `12E` D6, `5A0` D4. The other 18 bytes between them read a single value in every captured condition.
- **All 7 payload bytes frozen across every captured condition**: `450` — payload has never moved, so we can't say *anything* about it from passive listening. Some rider input we haven't exercised must move it (or it's UDS-only).

## How to read "what's missing"

Bit-counting the unknowns is misleading — a single undecoded byte could carry one byte-wide quantity, or eight independent flags, or any mix. What we can say:

- **The unknowns are bounded above by 51 bytes** (the `?` cells) plus the uncharted bits inside the 23 `S◐` cells, plus whatever lies latent under the 3 always-zero bytes. No new arbitration ID will arrive: 800 679 frames across 14 sessions span every condition exercised and surface zero IDs outside the documented 11. The 2026-06-30 corpus sweep ([[2026-06-30-unknown-byte-corpus-sweep]]) classified the unknowns as **46 GLOBAL-STATIC** (a single value across every captured frame — likely reserved unless a not-yet-exercised input flips them), **13 UNEXPLAINED-ACTIVE** (move across sessions, no known-signal correlation passed |r| ≥ 0.9; 14 originally, one closed by the post-sweep `541` D6 → engine-off counter promotion), and **2 INSUFFICIENT-DATA** (move in only one session).
- **No UDS / diagnostic side-channel.** Signals that only respond to UDS request (likely candidates: fuel level, odometer, fault codes — see [fuel-consumption-absent-from-broadcasts](../findings/can/fuel-consumption-absent-from-broadcasts.md), [battery-voltage-absent-from-always-on-broadcasts](../findings/can/battery-voltage-absent-from-always-on-broadcasts.md)) won't surface in passive captures regardless of how many bytes we work through.
- **Always-zero is not the same as empty.** [byte-encoding-12-in-16](../findings/can/byte-encoding-12-in-16.md) shows a low nibble that read clean-zero engine-off and carried a real signal engine-on. A `0` cell becomes a `?` the first time an untested input flips it.

Priority heuristic for the next probe: pick an undecoded byte on a fast-period ID (10 / 20 ms suggests the byte is meant for fast-changing state) and pair it with a rider input not yet exercised — ABS event, indicator stalk, mode button, brake pressure, ambient-temp swing. `450` payload moving for the first time would also unlock a whole ID at once.
