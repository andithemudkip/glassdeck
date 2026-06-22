# 16. Combination Instrument

*(2022 Husqvarna Svartpilen 401 Repair Manual, pages 168–181)*

## 16.1 Combination Instrument

The combination instrument is mounted in front of the handlebar.

Components:

1. Indicator lamps
2. Display
3. Function buttons

---

## 16.2 Activation and Test

### Activation

The combination instrument is activated when the ignition is switched on.

**Note:** Display brightness is controlled automatically by an ambient light sensor.

### Startup Test Sequence

When the ignition is switched on:

* All indicator lamps illuminate briefly (except turn signal indicator).
* Tachometer and gear display segments illuminate sequentially.
* Speedometer counts from 0 to 299 and back.
* Remaining display segments illuminate briefly.
* The **PIONEERING SINCE 1903** logo appears.
* The selected ABS mode is displayed for 4 seconds.
* The display then returns to the last selected mode.

### Notes

* The malfunction indicator lamp remains illuminated while the engine is not running.
* If the lamp illuminates while riding, stop safely and contact an authorized Husqvarna dealer.
* The ABS warning lamp remains illuminated until approximately **6 km/h (4 mph)** is reached.

---

## 16.3 Warnings

All active warnings are displayed on the **Info** screen until cleared.

If multiple warnings exist, the general warning symbol flashes.

### CAN Bus Faults

Possible warnings:

* `CAN FAILURE`
* `CAN ABS FAILURE`
* `CAN EMS FAILURE`

### ABS Failure

Displayed when ABS is no longer active.

### Quick Shifter Failure

Displayed when Easy Shift has a fault.

### ECU Failure

Displayed when the engine control unit reports a malfunction.

### Transport Lock

Displayed when transport mode is active.

### Temporary Transport Lock

Displayed when temporary transport mode is active.

### Kill Switch

Displayed when the emergency stop switch is activated.

### SideStand Down

Displayed when the side stand is lowered.

### Low Oil Pressure

Displayed when engine oil pressure is too low.

### Low Battery

Displayed when:

**Battery Voltage ≤ 10.5 V**

### Coolant Sensor Failure

Displayed when the coolant temperature sensor is faulty.

### High Coolant Temperature

Displayed when:

**Coolant Temperature > 110°C (230°F)**

### Fuel Level Sensor Failure

Displayed when the fuel level sensor is faulty.

### Low Fuel Level

Displayed when fuel reaches reserve level.

---

## 16.4 Indicator Lamps

Indicator lamps provide operating status information.

### Turn Signal Indicator

* Flashes green with turn signals.

### Malfunction Indicator Lamp (MIL)

* Illuminates yellow.
* Indicates an OBD-detected electronics fault.
* Stop safely and contact a Husqvarna dealer.

### Shift Warning Light

* Flashes red at RPM1.
* Illuminates solid red at RPM2.

### Neutral Indicator

* Illuminates green when transmission is in neutral.

### High Beam Indicator

* Illuminates blue when high beam is active.

### ABS Warning Lamp

* Illuminates yellow for ABS status or faults.

---

## 16.5 Shift Warning Light

Located above the display.

The shift warning can be configured in:

* Trip 1
* Trip 2

### During Break-In Period

Until:

**ODO < 1,000 km (621 mi)**

The shift light is always active.

| Condition                        | Behavior                            |
| -------------------------------- | ----------------------------------- |
| Coolant ≤ 35°C (95°F)            | Shift light illuminates at 6500 rpm |
| Coolant > 35°C and ODO > 1000 km | User-configurable RPM1 and RPM2     |

### Definitions

* **RPM1** → light flashes red
* **RPM2** → light illuminates solid red

**Note:** In sixth gear, after first service and with a warm engine, the shift warning light is disabled.

---

## 16.6 Display Layout

Display elements:

1. Tachometer
2. Gear indicator
3. Speed display
4. Fuel level
5. Information area
6. Clock
7. Coolant temperature

### Notes

* Clock must be reset if battery or fuse is disconnected.
* Brightness is controlled automatically.

---

## 16.7 Fuel Level Display

Fuel quantity is shown as bars.

More bars = more fuel.

### Notes

* Low Fuel warning appears at reserve level.
* Display updates with a delay to avoid fluctuations while riding.
* If the sensor signal is lost:

  * No bars are shown.
  * `Fuel Level Sensor Failure` appears.

---

## 16.8 Coolant Temperature Indicator

Coolant temperature is displayed using bars.

More bars = hotter coolant.

### Temperature States

| State           | Display             |
| --------------- | ------------------- |
| Engine cold     | Up to 3 bars        |
| Engine warm     | 4 bars              |
| Engine hot      | 5–8 bars            |
| Engine very hot | All 8 bars flashing |

### Overheat Warning

When all bars illuminate:

`High Coolant Temperature`

appears.

### Notes

If overheating occurs:

* Stop immediately.
* Allow engine to cool.
* Check coolant level.

The ECU may limit maximum engine speed during overheating.

---

## 16.9 Function Buttons

### MODE Button

Cycles through:

* ABS
* Info
* ODO
* Trip 1
* Trip 2

### SET Button

Changes menus within the selected display.

---

## 16.10 ABS Display

Navigate:

`MODE → ABS`

Displays current ABS mode.

### Notes

* ABS mode can only be changed while stationary.

---

## 16.11 Info Display

Navigate:

`MODE → Info`

Shows active warnings.

### Notes

* Only appears if warnings exist.
* Warnings are stored until no longer active.
* Multiple warnings cycle automatically.
* Press **SET** to view the next warning.

---

## 16.12 ODO Display

Navigate:

`MODE → ODO`

Displays total vehicle mileage.

### Notes

* Retained even if battery is disconnected.
* Maximum display: **99,999**
* Press **SET** to cycle ODO menus.

---

## 16.12.1 Fuel Range

Displays estimated remaining range.

### Notes

* Based on average fuel consumption and fuel level.
* Appears after several hundred meters of riding after startup.

---

## 16.12.2 Service

Displays distance remaining until next service.

### Notes

When service distance reaches zero:

`Service Reset`

appears every time the ignition is switched on.

This warning is **not** shown in the Info display.

---

## 16.13 Trip 1

Displays distance since last reset.

### Notes

* Maximum: 9999.9
* Press **SET** to cycle Trip 1 menus.

### Menus

#### Time Trip 1

Displays riding time.

#### Average Speed Trip 1

Displays average speed.

#### Avg F.C. Trip 1

Displays average fuel consumption.

### Reset Trip 1

Hold:

`SET for 3 seconds`

---

## 16.14 Trip 2

Displays distance since last reset.

### Notes

* Maximum: 9999.9

### Menus

#### Time Trip 2

Displays riding time.

#### Average Speed Trip 2

Displays average speed.

#### Avg F.C. Trip 2

Displays average fuel consumption.

### Reset Trip 2

Hold:

`SET for 3 seconds`

---

## 16.15 Adjusting ABS Mode

### Condition

Motorcycle stationary.

### Procedure

1. Navigate to `ABS`.
2. Hold **SET** for 3–5 seconds.

Available modes:

* ROAD
* SUPERMOTO

### Notes

* Do not open the throttle while changing modes.
* If switching fails, previous mode remains active.
* A flashing ABS mode indicates a fault.

### Mode Behavior

#### ROAD

ABS active on:

* Front wheel
* Rear wheel

#### SUPERMOTO

ABS active on:

* Front wheel only

Rear wheel ABS disabled.

---

## 16.16 Setting Units

### Condition

Motorcycle stationary.

### Procedure

1. Navigate to `ODO`.
2. Hold **MODE** for 5 seconds.
3. Use **SET** to select units.
4. Wait approximately 5 seconds to save.

### Available Units

#### Distance

* km
* miles

#### Volume

* l
* USga
* UKga

### Notes

Changing units converts stored values while retaining ODO.

---

## 16.17 Setting the Clock

### Condition

Motorcycle stationary.

### Procedure

1. Navigate to `ODO`.
2. Hold **MODE + SET** for 5 seconds.
3. Set hours using **MODE**.
4. Set minutes using **SET**.
5. Press **MODE + SET** together to save.

### Notes

* 24-hour format.
* Clock resets if battery or fuse is disconnected.

---

## 16.18 Adjusting Shift Speed RPM1

### Conditions

* Motorcycle stationary
* ODO > 1000 km (621 mi)

### Procedure

1. Navigate to `TRIP 1`.
2. Hold **MODE** for 5 seconds.
3. Adjust value:

   * MODE = increase
   * SET = decrease
4. Press **MODE + SET** together to save.

### Notes

* RPM1 = flashing shift light.
* Adjustable in 50 rpm increments.
* Must remain at least 50 rpm below RPM2.

---

## 16.19 Adjusting Shift Speed RPM2

### Conditions

* Motorcycle stationary
* ODO > 1000 km (621 mi)

### Procedure

1. Navigate to `TRIP 2`.
2. Hold **MODE** for 5 seconds.
3. Adjust value:

   * MODE = increase
   * SET = decrease
4. Press **MODE + SET** together to save.

### Notes

* RPM2 = solid shift light.
* Adjustable in 50 rpm increments.
* Must remain at least 50 rpm above RPM1.

---

## 16.20 Resetting Service Interval Display

### Condition

Motorcycle stationary.

### Procedure

1. Navigate to `ODO`.
2. Navigate to `SERVICE`.
3. Hold **SET** for at least 10 seconds.

### Notes

The service interval can only be reset.

It is **not possible** to manually adjust the service distance or service time.
