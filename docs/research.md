# Husqvarna Svartpilen 401 (2020) Custom Dashboard Project

## Goal

Replace the OEM dashboard with an open-source dashboard based on off-the-shelf hardware.

Primary motivations:

- Separate left/right indicator icons.
- Better information density.
- Usable controls while riding.
- Remove dependence on the OEM membrane buttons.
- Easier access to useful information (temps, voltage, fuel, etc.).
- Potential Pelorus/Convoy integration in the future.

---

# What We Know

## Bike

- Husqvarna Svartpilen 401
- Model year: 2020
- KTM 390 platform
- CAN-based electrical architecture

## OEM Dashboard Responsibilities

Confirmed:

- Displays vehicle information
- Stores odometer
- Stores service reminder interval
- Allows ROAD/SUPERMOTO ABS mode switching

Probably does NOT handle:

- Immobilizer
- Key authentication
- Bluetooth

Implication:

- Dashboard is likely not required for engine operation.
- Replacement appears feasible.

---

# Existing Projects

## Bad Winners Dashboard

Pros:

- Demonstrates replacement is technically possible.
- Supports OEM functions.

Cons:

- Poor community reputation.
- Closed source.

## ProjectPilen / Reddit Dashboard

Pros:

- Appears well engineered.
- Strong community interest.

Cons:

- Closed source.
- No published CAN definitions.
- No public firmware repository.

---

# Open Source Resources

## KTM CAN Library

https://github.com/blalor/ktm-can

Important:

- Based on a 2020 KTM 690 Enduro R.
- IDs may not match the 390 platform.
- Useful as methodology and protocol reference.

Files worth studying:

- src/ktm_can/*
- tests/*

The tests and source are more useful than the README.

---

# CAN vs OBD

## CAN

Broadcast traffic used by the dashboard.

Examples:

- RPM
- Speed
- Gear
- Fuel level
- Indicators
- ABS state

Primary source of dashboard data.

## OBD PIDs

Diagnostic requests.

Useful for:

- Verifying CAN decoding
- Troubleshooting
- Understanding scaling/units

Not expected to be the primary source of dashboard data.

---

# Signals Likely Available

Based on KTM reverse engineering efforts.

Expected:

- RPM
- Speed
- Gear
- Fuel level
- Coolant temperature
- Battery voltage
- Indicator state
- ABS mode

Possible:

- Clutch switch
- Side stand switch
- Lean angle
- Tilt angle
- Brake pressure
- Ride mode status

Unknown:

- Service reminder reset messages
- Trip reset messages
- ROAD/SUPERMOTO command messages

---

# ROAD / SUPERMOTO Mode

The OEM dashboard can switch between ROAD and SUPERMOTO modes using dashboard buttons.

Implications:

- The dashboard is probably transmitting at least some control messages.
- Mode state is likely observable on CAN.
- Mode switching may eventually be reproducible.

Development approach:

1. Display mode state.
2. Decode mode-change messages.
3. Only then implement mode switching.

Do not transmit CAN messages until OEM behavior is fully understood.

---

# Odometer Strategy

For an open-source project:

Manual odometer entry is acceptable.

Suggested implementation:

- User enters current odometer during setup.
- Dashboard stores mileage locally.
- Distance accumulates from speed data.
- Odometer remains editable behind a confirmation screen.

No need for legal-grade odometer handling.

Main requirement:

- Avoid silent corruption of mileage data.

---

# Hardware Plan

## Phase 0 / Phase 1

Recommended:

- ESP32-S3 DevKit (preferably N16R8)
- CAN transceiver (SN65HVD230 or similar)
- Diagnostic connector adapter

Optional:

- MicroSD logging module

Avoid buying a display until CAN access is confirmed.

## ESP8266

Can be used for initial CAN logging.

Not recommended for the final dashboard.

Reasons:

- Requires MCP2515 CAN controller.
- Less RAM.
- Less processing headroom.
- More wiring complexity.

---

# Development Plan

## Phase 0 — CAN Access

Tasks:

- Verify diagnostic connector pinout.
- Build CAN adapter.
- Confirm visibility of CAN traffic.

## Phase 1 — CAN Logger

First milestone.

Build a logger, not a dashboard.

Capture logs while:

- Idling
- Revving
- Riding
- Shifting gears
- Using indicators
- High beam
- Neutral
- ROAD ↔ SUPERMOTO switching
- Trip reset
- Service reset
- Dashboard button presses

Goals:

- RPM
- Speed
- Gear
- Fuel
- Coolant temp
- Voltage
- Indicators
- ABS state

## Phase 2 — Decoder

Create:

- Signal definitions
- CAN documentation
- Python tooling

This may become the most valuable open-source contribution.

## Phase 3 — Dashboard

Minimum viable dashboard:

- Speed
- RPM
- Gear
- Fuel
- Coolant temp
- Battery voltage
- Separate left/right indicators
- ABS mode display

No menu system initially.

## Phase 4 — Controls

Investigate:

- Existing switchgear
- Additional handlebar buttons
- Long-press interactions

Goal:

- Full operation without touching the dashboard.

## Phase 5 — Active CAN Features

Potential:

- ROAD/SUPERMOTO switching
- Trip reset
- Service reset

Only after OEM messages are fully decoded.

## Phase 6 — Advanced Features

Potential:

- Fuel economy
- Trip computer
- Service reminders
- Lean angle
- GPS heading
- Pelorus integration
- Convoy mode

---

# Key Open Questions

1. Can the OEM dashboard be completely disconnected?
2. Does the ECU expect messages from the dashboard?
3. How similar is the KTM 390 CAN map to the KTM 690 CAN map?
4. Which signals are already available as broadcasts?
5. How are ROAD/SUPERMOTO commands transmitted?

---

# Key Insight

This project is no longer:

"Reverse engineer an entire motorcycle."

It is:

"Adapt an existing KTM CAN reverse-engineering effort to the 390 platform and build a better dashboard."
