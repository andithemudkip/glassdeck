---
area: can
status: provisional
established_by:
  - 2026-06-25-battery-voltage-desk-scan
references: []
---

# Battery voltage is not carried in the 11 always-on broadcast IDs

Under every captured condition to date — key-on engine-off, engine-on idle (coolant 25 → 92 °C), engine-on through a 1700 → 5000 RPM sweep, and an engine-off high-beam load step — **no byte and no adjacent uint16 BE pair on the 11 always-on broadcast IDs ([[always-on-broadcast-ids]]) behaves like battery voltage**.

## What was tested

Per [[2026-06-25-battery-voltage-desk-scan]]: 10 engine-off windows across 8 sessions, 4 engine-on idle windows across 4 sessions (spanning cold/warm/hot coolant), and 5 RPM-swept windows (B1..B5 of the rear-spin sweep). Per-byte and per-uint16-pair means + stds were ranked against three signatures simultaneously:

  1. Engine-OFF → engine-ON step of the right magnitude (≈ +10..+20 LSB at 0.1 V/LSB; ≈ +150 at 0.01 V/LSB BE).
  2. Within-session stability (voltage is quiet at rest and under regulation).
  3. Cross-session and cross-RPM consistency (voltage doesn't drift with coolant or engine speed).

## What the scan actually found

Every byte with `|Δ(on − off)| ≥ 1 LSB` is fully attributable to a documented signal — RPM, throttle, coolant, kill mirrors, warmup index, ignition-armed bit, side-stand mirror, engine-on counter, key-on ramp counter, or the twin int16 fuel/ignition channels at `121` D0..D3 ([[byte-121-twin-int16]]). The largest unattributed Δ is `541 D5` at −6.1 LSB, which is the high byte of the same key-on ramp pattern as `541 D6` (scattered engine-off, exact zero engine-on — wrong shape for voltage).

The uint16 BE pair scan turned up nothing in plausible voltage ranges either. The closest non-known pair, `12A D1:D2`, sits at 1244 / 1280 (≈ 0.36 V step at 0.01 V/LSB) but is driven by a single-LSB drift on D1 that's at the noise floor; D2 is essentially zero throughout.

## Caveats — why this is `provisional`, not `confirmed`

  - **Cranking has not been captured.** All "engine-off" windows are post-key-on / pre-starter or fully-decayed; all "engine-on" windows are warm-idle or beyond. The dip-and-recover transient of a starter event is the regime most likely to flush a voltage signal onto the bus if one exists there.
  - **D7 was excluded** as the cycle hash ([[byte-d7-cycle-hash]]). Confirmed not to carry signal payload anywhere, but worth noting that the scan didn't examine it.
  - **The high-beam load test produced no positive result either**, which strengthens the rejection but isn't ironclad — a ~50 W headlight on a healthy 12 V battery gives a sub-LSB-at-0.1-V/LSB dip in some cases.

## The leading hypothesis is now: the dash self-senses its own supply rail

The OEM dash is powered through the ignition switch from the battery — the 12 V rail is already on its PCB. A resistor divider + ADC tap before the regulator gives battery voltage essentially for free, with no need for a separate sense pin, a dedicated broadcast, or a UDS request. This is the default implementation on automotive instrument clusters and is consistent with what this scan finds: nothing voltage-shaped on the bus, because the OEM never had a reason to put it there.

Wire + ignition-switch contact resistance puts the dash-side reading ~0.1–0.3 V below the battery terminal under typical loads — comfortably inside the `Low Battery ≤ 10.5 V` margin, so the self-sensed value is accurate enough for the warning the rider actually sees.

## Consequences

  - **Replacement-dashboard implications** ([[dashboard-bike-portability]]): our ESP32 dash gets power from the same 12 V on the same connector. We can do the same trick — a divider into an ADC pin — and reproduce the `Low Battery` warning with zero CAN work and ~3 extra components. **No dedicated voltage-on-CAN experiment is needed for the replacement dash to ship this warning.**
  - **The desk-scan negative is now weak evidence against UDS / cranking-broadcast carriage** — not because the scan was bad, but because the prior on those paths is much lower if the OEM has self-sense available on its own PCB. We should still expect voltage to surface incidentally during the captures already queued for other reasons (a starter capture would happen as part of any future engine-on session, and the UDS sniff is queued under [[project-fuel-on-can]]) but neither is worth a dedicated voltage-only experiment.
  - **Open question, lower priority:** if voltage does emerge during a crank or UDS capture later, it would refute this finding and reopen the question of *why* the OEM publishes it. Until then we treat self-sense as the working model.

## How to promote

Promote to `confirmed` when an incidental capture covering either of the two remaining-but-low-prior regimes (cranking; UDS traffic with the OEM dash present) also shows no voltage-shaped byte. The cranking dip in particular should be unmissable if voltage were broadcast: 12.5 → 9 → 14 V within 1 s ≈ 50 LSB swing at 0.1 V/LSB — nothing else on the bus does that.

Demote to `refuted` if either of those captures surfaces a previously-unattributed byte that tracks voltage. In that case the self-sense hypothesis above also has to be re-examined (the OEM might do *both* — self-sense for the warning and broadcast for telematics), and the `2026-06-25` desk scan stays on file as the analysis of why the always-on-only assumption missed it.
