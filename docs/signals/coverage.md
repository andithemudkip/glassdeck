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
| wheel_speed_front | `12D` | D0 + D1 hi-nibble, 12-bit BE, 1/10 km/h | provisional | [signal-wheel-speed-front](../findings/can/signal-wheel-speed-front.md) |
| wheel_speed_front (fine mirror) | `12D` | D3:D4 BE u16, ~0.0577 km/h/LSB (LSB provisional pending GPS/dash anchor) | confirmed | [byte-12d-d3-d4-front-mirror](../findings/can/byte-12d-d3-d4-front-mirror.md) |
| wheel_speed_rear | `12D` | D5:D6 BE u16, ~0.0565 km/h | provisional | [signal-wheel-speed-rear](../findings/can/signal-wheel-speed-rear.md) |
| wheel_speed_rear (coarse mirror) | `12D` | D2 u8, 1/10 km/h (wraps mod-256 above ~25.5 km/h) | confirmed | [signal-wheel-speed-rear](../findings/can/signal-wheel-speed-rear.md) |
| rear_speed_band | `12D` | D1 low nibble (bits 3:0), 4-bit uint, 25 km/h step | provisional | [signal-12d-d1-bit0](../findings/can/signal-12d-d1-bit0.md) |
| fuel_injection_setpoint | `540` | D1 u8 (ECU base fuel-injection setpoint, recomputed at ~1 Hz) | provisional | [signal-fuel-injection-setpoint](../findings/can/signal-fuel-injection-setpoint.md) |
| side_stand | `540` | D3 bit 0 bool | confirmed | [signal-side-stand](../findings/can/signal-side-stand.md) |
| coolant_temp | `540` | D5:D6 BE u16, 0.1 °C | confirmed | [signal-coolant-temp](../findings/can/signal-coolant-temp.md) |
| kill_switch | `541` | D2 bit 4 bool (primary) | confirmed | [signal-kill-switch](../findings/can/signal-kill-switch.md) |
| engine_on_counter | `541` | D4 bits 6:0, 7-bit mod-128, ~1 Hz | confirmed | [signal-engine-on-counter](../findings/can/signal-engine-on-counter.md) |
| engine_off_counter | `541` | D6 u8, 8-bit mod-256, ~1 Hz | confirmed | [signal-engine-off-counter](../findings/can/signal-engine-off-counter.md) |
| kill_switch (redundant mirror) | `121` | D5 bit 2 | confirmed | [signal-kill-switch](../findings/can/signal-kill-switch.md) |
| kill_switch (redundant mirror) | `5B0` | D0 bit 4 | confirmed | [signal-kill-switch](../findings/can/signal-kill-switch.md) |
| abs_lamp | `12A` | D0 b4, D1 b0, D5 b3 (each HIGH=lit) | provisional | [signal-abs-lamp](../findings/can/signal-abs-lamp.md) |
| 12A_d1_b2 (semantics open) | `12A` | D1 bit 2 | provisional | [signal-12a-d1-bit2](../findings/can/signal-12a-d1-bit2.md) |
| abs_lamp (mirror) | `12E` | D6 bits 4, 5 (each LOW=lit) | provisional | [signal-abs-lamp](../findings/can/signal-abs-lamp.md) |
| ride_mode | `12A` | D2 bit 1 bool (0=ROAD, 1=SUPERMOTO; semantic = rear-ABS-enable) | confirmed | [signal-ride-mode](../findings/can/signal-ride-mode.md) |
| ride_mode (mirror) | `450` | D4 bit 7 bool (same polarity, transitions 20-300 ms behind) | confirmed | [signal-ride-mode](../findings/can/signal-ride-mode.md) |
| shift_cut_active | `121` | D6 bit 0 (ECU ignition cut for any shift; QS-vs-clutched ambiguous) | provisional | [signal-quickshifter](../findings/can/signal-quickshifter.md) |
| shift_blip_active | `121` | D6 bit 1 (down-shift auto-blip) | provisional | [signal-quickshifter](../findings/can/signal-quickshifter.md) |
| engine_torque | `121` | D0:D1 signed int16 BE (~0.25 N·m/LSB provisional) | confirmed | [signal-engine-torque](../findings/can/signal-engine-torque.md) |
| engine_torque (redundant mirror) | `121` | D2:D3 signed int16 BE — mirrors D0:D1 within ~1 LSB | confirmed | [signal-engine-torque](../findings/can/signal-engine-torque.md) |

### Decoded but unattributed (encoding known, physical quantity not)

| Slot | ID | Location | Status | Finding |
|---|---|---|---|---|
| engine-state bits (3×) | `121`, `540` | `121` D5.3; `540` D2.6, D3.4 | flips engine-on / engine-off, attribution open | [engine-state-bits-decay-shape](../findings/can/engine-state-bits-decay-shape.md) |
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
| `120` |  20 ms | S rpm hi | S rpm lo | S throttle | 0 | 0 | 0 | 0 | h |
| `121` |  20 ms | S torque hi | S torque lo | dup torque hi (D0:D1 mirror) | dup torque lo (D0:D1 mirror) | ? static (0x04) | S◐ kill-dup b2 + es b3 | S◐ shift-cut b0 + shift-blip b1 | h |
| `129` |  20 ms | S◐ gear b7:4, clutch b3, shift-failed b1 (b0,b2 = 0) | 0 | 0 | ? static (0x01) | 0 | 0 | 0 | h |
| `12A` |  50 ms | S◐ abs-lamp b4 | S◐ abs-lamp b0 + d1-b2 (semantics open) | S◐ ride-mode b1 | 0 | 0 | S◐ abs-lamp b3 | 0 | h |
| `12D` |  10 ms | S frontWS hi | S◐ frontWS hi-nib + rear-speed band lo-nib (b0-3) | dup coarse rear-speed mirror, 1/10 km/h | dup frontWS-mirror hi (u16 BE at ~0.0577 km/h) | dup frontWS-mirror lo | S rearWS hi | S rearWS lo | h |
| `12E` |  20 ms | 0 | 0 | 0 | 0 | 0 | 0 | S◐ abs-lamp mirror b4, b5 | h |
| `450` |  50 ms | 0 | 0 | 0 | 0 | S◐ ride-mode-mirror b7 | 0 | ? static (0x28 constant) | 0 |
| `540` | 100 ms | 0 | S fuel-sp | S◐ es b6 | S◐ side-stand b0 + es b4 (b5–7 = 0) | 0 | S coolant hi | S coolant lo | 0 |
| `541` |  20 ms | 0 | 0 | S◐ kill-switch b4 | S◐ time-bin 0/1/2 | S engine-on counter (full uint8 mod-256) | 0 | S engine-off counter | h |
| `5A0` | 100 ms | 0 | 0 | 0 | 0 | ? static (0x04 latched at engine-start) | 0 | 0 | h |
| `5B0` | 100 ms | S◐ kill-dup b4 (b0-3, b5-7 = 0) | 0 | 0 | 0 | 0 | 0 | 0 | h |

`es` = engine-state bit (semantics open, see [engine-state-bits-decay-shape](../findings/can/engine-state-bits-decay-shape.md)).

**`12D` wheel-speed layout.** Each wheel is broadcast twice on this ID — one fine 16-bit-ish encoding and one coarser encoding per wheel — plus a 4-bit rear-speed band on the low nibble of D1. Which byte position is labelled "canonical" vs "mirror" is historical discovery order, not ECU precedence: front canonical is the coarser 12-bit at 1/10 km/h (D0:D1), front mirror is the finer 16-bit at ~0.0577 km/h/LSB (D3:D4); rear canonical is the finer 16-bit at ~0.0565 km/h/LSB (D5:D6), rear mirror is the coarser 8-bit at 1/10 km/h (D2). Either encoding per wheel is a valid source of truth; downstream code that wants sub-km/h resolution should read the fine copy.

## Quick stats

Recounted from the per-ID table above, post-2026-07-24 (percentages rounded
independently, so they sum to 101):

| Category | Bytes | %  |
|---|---:|---:|
| Carries a primary signal (S or S◐) | 28 | 32 % |
| Structural D7 hash (h)             |  9 | 10 % |
| Always-zero across every observed condition (0) | 42 | 48 % |
| Static non-zero constant           |  4 |  5 % |
| Redundant mirror of decoded signal (dup) | 5 | 6 % |
| Undecoded (?)                      |  0 |  0 % |

Whole-ID status:

- **No ID left with zero attributed bytes.** `12A` and `12E` carry ABS-lamp bits per [[signal-abs-lamp]] (2026-07-22); `12A` also carries ride-mode per [[signal-ride-mode]] (2026-07-24). `5A0` has D4 latched at 0x04, all other bytes now confirmed always-zero across the 15-session corpus — no primary signal, but structure is characterised.
- **`450` was static-frozen until the mode toggle broke it.** Pre-2026-07-24 corpus (15 sessions, all in ROAD) never saw D0-D5 or D7 move; D6 latched at 0x28. The 2026-07-24 mode-toggle session flipped D4 bit 7 as the ride-mode mirror — so D4 no longer static. D0-D3, D5, D7 remain zero and D6 still `0x28`; another rider input may yet exercise them (or it's UDS-only).

## How to read "what's missing"

Bit-counting the unknowns is misleading — a single undecoded byte could carry one byte-wide quantity, or eight independent flags, or any mix. What we can say:

- **Zero undecoded bytes remain — a first.** Down from 51 pre-2026-07-22. Uncharted structure now lives entirely inside the `S◐` cells (bits within partially-decoded bytes) and the 42 always-zero bytes (which could carry latent signals under untested inputs). No new arbitration ID will arrive: 800 679 + 386 271 frames across 15 sessions span every condition exercised and surface zero IDs outside the documented 11.
- **No UDS / diagnostic side-channel.** Signals that only respond to UDS request (likely candidates: fuel level, odometer, fault codes — see [fuel-consumption-absent-from-broadcasts](../findings/can/fuel-consumption-absent-from-broadcasts.md), [battery-voltage-absent-from-always-on-broadcasts](../findings/can/battery-voltage-absent-from-always-on-broadcasts.md)) won't surface in passive captures regardless of how many bytes we work through.
- **Always-zero is not the same as empty.** [byte-encoding-12-in-16](../findings/can/byte-encoding-12-in-16.md) shows a low nibble that read clean-zero engine-off and carried a real signal engine-on. A `0` cell becomes a `?` the first time an untested input flips it.
