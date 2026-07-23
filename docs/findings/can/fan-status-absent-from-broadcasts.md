---
area: can
status: confirmed
established_by:
  - 2026-07-22-first-moving-ride
---

# Cooling-fan status — absent from the always-on broadcast set

The cooling fan's on/off state is **not visible in any bit of the 88-byte always-on broadcast payload** on the 2020 Husqvarna Svartpilen 401. Across `logs/2026-07-22-first-moving-ride/moving-5.log`, where the rider observed three fan-state transitions at known coolant temperatures, no bit in any of the 11 always-on IDs shows a matching transition pattern within ±5 s of any fan event, in either polarity.

## Evidence

The rider observed three fan transitions during moving-5:

- **t + 27.2 s**: fan ON → OFF as coolant crossed 90 °C going down (event #1).
- **t + 75.5 s**: fan OFF → ON as coolant crossed 95 °C going up (event #2).
- **t + 116.3 s**: fan ON → OFF as coolant crossed 90 °C going down (event #3).

Coolant crossing timestamps are derived directly from the decoded 540 D5:D6 trace ([[signal-coolant-temp]]), so they carry the same precision as the coolant channel itself (0.1 °C, ~100 ms broadcast period).

`scripts/first_moving_ride_fan_hunt.py` bit-slices every payload byte across all 11 IDs (11 × 8 × 8 = 704 bits) and reports each bit's transition count and timestamps. Distribution:

| Transitions in the capture | Bits |
|---:|---:|
| 0 | 524 (74 %) — dead across the whole capture |
| 1 – 6 | 11 (candidates for a fan-cycle bit) |
| 8 | 5 — engine-on counter high bits |
| 400+ | ~ 40 — counters, D7 hashes, coolant / speed low bits |

The 11 candidate bits with 1–6 transitions in the whole capture, and their actual transition timestamps (t+s from capture start), listed in full:

| Bit | first | Transitions (t+s → new value) |
|-----|-------|-------------------------------|
| `120 D2 b5` | 0 | 76.4 → 1, 78.4 → 0 |
| `129 D0 b4` | 0 | 68.3 → 1, 90.2 → 0 |
| `540 D1 b4` | 0 | 70.2 → 1, 73.2 → 0, 74.2 → 1, 78.2 → 0, 79.2 → 1, 82.2 → 0 |
| `540 D1 b5` | 0 | 78.2 → 1, 79.2 → 0 |
| `540 D3 b0` | 0 | 55.3 → 1 (side-stand DOWN → UP mid-ride, [[signal-side-stand]]) |
| `540 D6 b5` | 1 | 9.0 → 0, 33.2 → 1, 48.1 → 0, 62.9 → 1, 97.0 → 0 (coolant temp low bits) |
| `540 D6 b6` | 0 | 33.2 → 1, 48.1 → 0 (coolant temp bit) |
| `540 D6 b7` | 1 | 33.2 → 0, 48.1 → 1 (coolant temp bit) |
| `541 D4 b5` | 1 | 4.24 → 0, 36.24 → 1, 68.24 → 0, 100.23 → 1 (engine-on counter b5, 32 s period) |
| `541 D4 b6` | 0 | 4.24 → 1, 68.24 → 0 (engine-on counter b6, 64 s period) |
| `541 D4 b7` | 0 | 68.24 → 1 (⚠ conflicts with [[signal-engine-on-counter]] "bit 7 reserved") |

None matches the fan sequence [27, 75, 116] s, in either "bit HIGH = fan ON" or "bit LOW = fan ON" polarity, within a 5 s tolerance. Bits that flipped at other moments have plausible explanations (coolant LSBs at 540 D6 low bits; engine-on counter periodicities at 541 D4 bits 5/6; a side-stand toggle at 540 D3 b0). Even relaxing the tolerance to ±15 s does not surface a match.

## Interpretation

The ECU knows the fan state (it drives the relay), but does not publish it on the always-on set. Options for what a firmware consumer could do:

- **Infer from coolant crossing 90 / 95 °C.** [[signal-coolant-temp]] is a clean 0.1 °C signal, so a client can reproduce the thermostat hysteresis in software without needing a broadcast. Cheapest option.
- **Query via UDS.** Not verifiable from passive listening, and this project has documented [[always-on-broadcast-ids]] as closed with no UDS traffic observed — moot until an active-request path is opened.
- **Tap the fan relay directly.** Physical wire on the dash-replacement side, similar to the fuel-level sender ([[fuel-level-sender]] hardware note in [[project-fuel-on-can]]). Costs a wire but is authoritative.

Anomalous observation — `541 D4 bit 7` transitioned once at t+68.24 s (0 → 1) in moving-5, which contradicts the current [[signal-engine-on-counter]] finding that "bit 7 reserved (never toggled)". Probably means the counter reached 128 for the first time in a session we watched; needs a separate look. Not related to fan status, but flagged so we don't lose it. See Follow-ups.

## Analogous findings

- [[fuel-consumption-absent-from-broadcasts]] — same shape: physical signal exists but not on the passive bus.
- [[battery-voltage-absent-from-always-on-broadcasts]] — same shape for battery voltage.
- [[project-fuel-on-can]] (memory) — fuel level also not on CAN; hardware-tap solution.

Building a broader pattern: several "the ECU knows this" signals aren't broadcast passively on this bike, forcing the dashboard replacement to either infer them, tap wires, or (eventually) send UDS requests.

## Open

- **Fan control via UDS.** Untestable until we have an active-request path. Deferred behind [[always-on-broadcast-ids]] until Phase 4+.
- **KTM 690 cross-check.** Unknown whether the 690 platform broadcasts fan status; would be a useful data point for the general "which convenience signals does Bosch publish across model years" question.
- **`541 D4 bit 7` transition** at t+68.24 s in moving-5 conflicts with the "bit 7 reserved" claim in [[signal-engine-on-counter]]. Cheapest check: run the counter across a full 128 s window in a moving capture and see whether bit 7 sets exactly at count 128 (as a native uint8 rollover would). If yes, D4 is actually a full uint8 counter and [[signal-engine-on-counter]] needs updating to bit_length 8.

## Evidence

- [[2026-07-22-first-moving-ride]] moving-5 — 122.6 s window with 3 rider-observed fan transitions and simultaneous coolant trace covering the 90–95 °C band twice.
- [`scripts/first_moving_ride_fan_hunt.py`](../../../scripts/first_moving_ride_fan_hunt.py) — the bit-slicing hunt across all 704 payload bits.

See also: [[signal-coolant-temp]], [[fuel-consumption-absent-from-broadcasts]], [[battery-voltage-absent-from-always-on-broadcasts]], [[always-on-broadcast-ids]], [[signal-engine-on-counter]].
