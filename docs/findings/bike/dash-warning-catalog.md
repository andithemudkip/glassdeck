---
area: bike
status: confirmed
source: 2022 Svartpilen 401 user manual section 16
references:
  - svartpilen-401-dash-user-manual
---

# OEM dash warning + indicator catalog

The full list of things the OEM dash surfaces to the rider, distilled from the user manual. Two purposes:

1. **Requirements list for our replacement dashboard** — every entry here is information the rider currently sees and must continue to see.
2. **Decode roadmap** — each entry maps to either a CAN signal we need to identify, or a derivation from already-decoded signals.

The "decode status" column tracks which it is. "Open" = source signal not yet identified. "Derived" = the dash computes this locally from a signal already decoded elsewhere; our dashboard will do the same.

## Text warnings (Info screen)

These appear on the Info screen (`MODE → Info`) when active. Multiple active warnings cycle automatically.

| Warning | Trigger condition (per manual) | Decode status |
|---|---|---|
| `CAN FAILURE` | CAN bus fault | open |
| `CAN ABS FAILURE` | ABS module CAN comm fault | open |
| `CAN EMS FAILURE` | EMS module CAN comm fault | open |
| `ABS Failure` | ABS no longer active | open |
| `Quick Shifter Failure` | Easy Shift fault | open |
| `ECU Failure` | ECU reports malfunction | open |
| `Transport Lock` | transport mode active | open (likely immobilizer-related) |
| `Temporary Transport Lock` | temporary transport mode active | open |
| `Kill Switch` | kill switch activated | derived — see [[signal-kill-switch]] |
| `SideStand Down` | side stand lowered | derived — see [[signal-side-stand]] |
| `Low Oil Pressure` | engine oil pressure too low | open |
| `Low Battery` | battery voltage **≤ 10.5 V** | open (need battery-voltage signal) |
| `Coolant Sensor Failure` | coolant temperature sensor faulty | open |
| `High Coolant Temperature` | coolant temperature **> 110 °C (230 °F)** | derived — see [[signal-coolant-temp]] |
| `Fuel Level Sensor Failure` | fuel level sensor faulty | open |
| `Low Fuel Level` | fuel at reserve level | open (need fuel-level signal) |

## Indicator lamps

Persistent lamps on the dash bezel, distinct from text warnings on the Info screen.

| Lamp | Color | Trigger condition (per manual) | Decode status |
|---|---|---|---|
| Turn signal | green flashing | turn signals active | open |
| Malfunction (MIL) | yellow | OBD-detected electronics fault; also lit whenever engine is not running | open — see analysis plan in [`2026-06-18-engine-on-stationary-inputs`](../../experiments/2026-06-18-engine-on-stationary-inputs.md) |
| Shift warning | red flashing / solid red | flashing at user-configured RPM1; solid at RPM2. Break-in (ODO < 1000 km): fixed at 6500 rpm. Disabled in 6th gear with warm engine after first service. | derived — see [[signal-rpm]] (need to find RPM1/RPM2 broadcast too if the dash exposes them) |
| Neutral | green | gear in neutral | derived — see [[signal-gear-position]] |
| High beam | blue | high beam active | open |
| ABS warning | yellow | ABS status or faults; stays lit below **~6 km/h** | partial — empirical timing in [[dash-warning-lights]]; need vehicle-speed signal |

## Numeric thresholds the dashboard must implement

Extracted from the rows above for easy reference:

| Quantity | Threshold | Effect |
|---|---|---|
| Battery voltage | ≤ 10.5 V | `Low Battery` warning |
| Coolant temperature | > 110 °C | `High Coolant Temperature` warning |
| Vehicle speed | < ~6 km/h | ABS warning lamp lit |
| Engine RPM (break-in, ODO < 1000 km) | 6500 rpm | shift warning lit |
| Engine RPM (post-break-in) | user-configured RPM1 / RPM2 | shift warning flashing / solid |
| Coolant temperature for break-in shift rule | ≤ 35 °C | shift warning at 6500 rpm regardless of user setting |

## Source caveats

- Manual is for the 2022 model year; our bike is 2020. Easy Shift / Quick Shifter is present across 2018–2024 (per rider) so that row applies. Other warnings have not been individually verified for the 2020 but are expected to match.
- "Transport Lock" / "Temporary Transport Lock" — manual mentions but does not explain. Likely related to the immobilizer / dealer mode subsystem; revisit when that subsystem is touched.

See also: [[dash-warning-lights]], [[signal-kill-switch]], [[signal-side-stand]], [[signal-coolant-temp]], [[signal-gear-position]], [[signal-rpm]].
