# 0015 — F7-fed 12V power path for the adapter

**Date:** 2026-06-25
**Status:** Accepted
**Supersedes:** [ADR 0001](0001-usb-power-during-development.md)

## Context

ADR 0001 deferred a 12V power path until "the first test ride is actually on the calendar." That moment is here. Phase 2 wants untethered captures: the rider on the bike, no laptop USB-C cable running into a backpack, free to roll. F7 (diagnostic pin 4, switched 12V) is the only practical power source on the bike that turns on with the key and off when the key is removed.

Feeding F7 straight into the ESP32-S3 would destroy it. Motorcycle 12V is also not bench 12V — it's a regulated automotive rail with occasional transients (load dumps, alternator switching, ignition coil kickback on older bikes; less violent on a modern fuel-injected single but still real). Anything connected to it needs a fuse, transient clamping, reverse-polarity protection, and a buck regulator sized for the load.

The load is small. ESP32-S3-DevKitC-1 + SN65HVD230 + future WiFi radio peaks around 400–500 mA at 5V — call it 2.5 W. A 1 A 5V buck has plenty of headroom.

Buck candidates considered:

- **LM2596 hobby module** — adjustable 5 V output via on-board pot, 4–40 V input, 3 A capable. Sold at every Romanian hobby shop and on AliExpress for €1–3. 40 V input ceiling gives the most headroom against any transient that gets past the bulk cap. Caveats: ships with the pot at an arbitrary position so must be pre-adjusted to 5.00 V before connecting downstream; output ripple is higher than the alternatives below but the ESP32-S3-DevKitC-1's on-board AMS1117-3.3 LDO cleans it up.
- **MP1584 hobby module** — adjustable 5 V output, 4.5–28 V input, 3 A capable. Same Romanian availability. Smaller and lower-ripple than LM2596 but the 28 V input ceiling is uncomfortably close to bus transient potentials — less margin against the failure mode this build accepts.
- **Pololu D24V10F5** — 1 A, 5 V, 4.5–36 V input, 90 %+ efficient. Fixed output (no pot to misset), tighter input cap. Not stocked locally in Romania at time of writing.
- **Recom R-78E5.0-1.0** — 1 A, 5 V, 7–28 V input, 7805 pinout. Also not stocked locally.

This ADR picks the **LM2596 module** as the build-now part because it is reliably available locally and the only real risks (pot mis-setting, ripple) are addressed by a one-time bench procedure and the downstream LDO respectively. The Pololu and Recom are kept on file as direct drop-in upgrades if either appears.

For reverse-polarity protection, a P-channel MOSFET in the high side is the textbook automotive choice (sub-100 mV drop at this current). A series Schottky (1N5819 axial through-hole, or SS14 if going SMD) is simpler and drops ~0.4 V — at 500 mA that's 200 mW of waste heat, totally acceptable for this rig. This ADR picks the Schottky for build simplicity; the P-FET alternative is documented in the hardware doc for anyone optimising later.

For transient protection, the textbook automotive answer is a TVS diode or MOV across the rail. After surveying Romanian hobby-shop availability, neither the low-voltage MOV (most stocked parts are 240–470 V mains-grade) nor the appropriate TVS (P6KE15A / SMAJ15A) is reliably sourceable locally. Three alternatives were considered:

- **SCR crowbar** (small SCR + zener trigger + the existing fuse as the sacrificial element) — robust protection, all parts universally stocked. Costs a few extra components and a build step.
- **5 W zener clamp** (1N5354B or similar) — universally stocked, fits the same DO-15 slot as the TVS. ~75 W peak surge handling is significantly less than a TVS; would fry under a real load-dump event.
- **Bulk input capacitor only, no dedicated clamp** — a fat electrolytic across the buck input absorbs fast transients and slows the rise time of slower ones; the LM2596's 40 V input ceiling handles steady-state up to the cap's clamp point. Protects against ignition-style spikes, connection inrush, and brief excursions; does *not* protect against sustained over-voltage from a failed alternator regulator.

This ADR picks the **bulk-cap-only** approach. Rationale: the bike is a 2020 EFI Husqvarna with a healthy regulator — sustained over-voltage events are rare; brief transients are what the cap handles well; and the protection chain (fuse + Schottky + 40 V buck ceiling + bulk cap) is honest about what it does and doesn't cover. If the rig dies to a regulator failure, the failure mode is contained (fuse blows, buck fries, ESP fries — €15 and a rebuild), and that risk is acceptable for a dev rig that gets retired when ADR 0014 ships. The SCR crowbar stays documented in [`f7-power.md`](../hardware/f7-power.md) as the upgrade for anyone wanting belt-and-suspenders.

## Decision

The bike-side power chain, downstream of diagnostic pin 4 (F7):

```
F7 (+12V switched) → 500 mA fuse → 1N5819 Schottky (reverse polarity)
                                 → 470 µF / 63 V bulk cap (absorb transients)
                                 → LM2596 buck module (12V → 5V, pre-set pot)
                                 → ESP32-S3-DevKitC-1 "5V" pin
GND (diagnostic pin 3) ──────────────────────────────────────► common GND
```

- **F7 wiring is now in scope.** The adapter pigtail grows from 3 wires (CH, CL, GND) to 4 (CH, CL, GND, F7).
- **Fuse:** 500 mA fast-blow inline blade fuse (or PTC equivalent) on the F7 wire, as close to the connector as physically practical. Protects the bike harness, not the adapter.
- **Reverse-polarity:** 1N5819 Schottky (DO-41 axial) in series on the F7 line, downstream of the fuse. ~0.4 V drop accepted. SS14 in DO-214AC is the SMD-build equivalent.
- **Transient absorption:** **470 µF / 63 V radial aluminum electrolytic** across the rail downstream of the Schottky, before the buck. Watch polarity — these are polarised; the long lead / unmarked side goes to +12 V, the short lead / striped side goes to GND. The 63 V voltage rating gives generous headroom above the bus's nominal 14.4 V running voltage; the 470 µF capacitance dampens fast transients and slows the rise time of slower over-voltage events enough that the LM2596's input cap and 40 V ceiling can ride them out. **This does not clamp sustained over-voltage.** SCR crowbar, MOV (S14K14), and TVS (P6KE15CA) are documented as upgrade paths in [`f7-power.md`](../hardware/f7-power.md).
- **Buck:** LM2596-based hobby module, with the output pot **pre-set to 5.00 V on the bench** before installation (see [f7-power.md § Operational rules](../hardware/f7-power.md)) and locked with nail polish or hot glue. Output to the DevKitC-1's `5V` pin (the right-hand header pin labelled `5V`, not `3V3` — see [bom.md](../hardware/bom.md)). Pololu D24V10F5 / Recom R-78E5.0-1.0 are direct drop-in upgrades if locally stocked.
- **Power source selection:** USB-C and F7 must not both be connected to the rig at the same time during normal operation. The DevKitC-1's USB VBUS feeds the same 5V rail through a protection diode, so simultaneous connection is electrically safe but creates a backfeed path that the buck regulates against — wasteful and worth avoiding. **Operational rule:** for flashing or USB-CDC dev, unplug F7. For ride captures, unplug USB. A future hardware revision can add a SPDT slide switch on the 5V rail if this becomes a footgun.
- **F7 is not separately sensed for "key-on" detection.** When F7 drops, the rig powers off — that is the key-off signal. Bus activity remains the engine-running proxy as before.
- **Listen-only mode unchanged.** Power-path changes do not touch the firmware's TWAI configuration. Golden no-TX rule is untouched by this ADR.

The full BOM, wiring procedure, and bench-test protocol live in [`docs/hardware/f7-power.md`](../hardware/f7-power.md).

## Consequences

- **Untethered Phase 2+ captures unblocked.** The rig powers up with the key, powers down with the key, no USB cable, no battery to charge.
- **Cold-boot timing shifts slightly.** The buck regulator and DevKitC-1 boot from a 12 V cold start instead of USB VBUS. Empirically expected to be within ~100 ms of the USB cold-boot path; if cold-boot CAN frames near `t=0` are critical for an experiment, validate against a USB cold-boot capture of the same condition. The 250 ms time-to-first-frame from [`findings/can/always-on-broadcast-ids.md`](../findings/can/always-on-broadcast-ids.md) is the bus's own warm-up — that stays the same.
- **Backfeed during dev** is a real operational footgun until a switch is added — see the rule above. Worth a strip of tape over either the USB-C port or the F7 pigtail when the other is in use.
- **Bike-side fuse responsibility documented.** A 500 mA inline fuse on F7 means a short anywhere downstream blows the inline fuse, not whatever fuse the bike puts on F7 from the factory. Recovery is opening the harness and swapping a blade fuse — no dealer visit.
- **Accepted failure mode: sustained over-voltage = rig destroyed.** Without a dedicated transient clamp, a failed bike-side regulator or other sustained event that drives the rail above ~40 V will likely take out the buck (and possibly the ESP). The fuse blows once the buck shorts, containing the damage to the rig itself — the bike harness is protected, but the adapter needs rebuilding. Honest tradeoff for the parts-sourcing reality; the SCR crowbar in [`f7-power.md`](../hardware/f7-power.md) is the documented upgrade if this risk ever materialises or if test rides extend to less-trusted bikes.
- **Optional downstream 5.6 V Zener (1N4734A)** is documented in [`f7-power.md`](../hardware/f7-power.md) as cheap insurance against the ~10 % residual risk of the buck failing in pass-through mode (input voltage appearing at the output) and frying the ESP. One-part, two-solder-joints addition. Not in the build-now BOM — operator includes it if locally sourceable.
- **No CAN-TX path is introduced.** This ADR is power only.
- **Adapter mechanical packaging is now a thing.** A bare breadboard in a backpack pocket is fine for bench, not for a bike. The adapter wants an enclosure (3D-printed or off-the-shelf project box) before the first real ride. Out of scope for this ADR — track separately if it becomes the limiting factor.
- **ADR 0001's "F7 is unwired" note is now historically false.** ADR 0001 stays on file as the prior decision, marked superseded. The wiring diagram in [`docs/hardware/can-adapter.md`](../hardware/can-adapter.md) needs updating to reflect that F7 is now connected.
