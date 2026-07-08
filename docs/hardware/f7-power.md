# F7 12V power path

The wiring, parts list, and bench-test procedure for powering the adapter from the bike's switched 12V line (F7, diagnostic pin 4) instead of laptop USB.

Authoritative decision: [ADR 0015](../decisions/0015-f7-12v-power-path.md). This doc is the build instructions.

## Why F7

The bike's diagnostic connector pin 4 (F7, grey/pink wire) carries **switched 12V**: hot when the key is on, dead when the key is off. Hardware that lives on F7 powers up and down with the ignition automatically. No second toggle, no battery to charge, no "did I leave it on?" question. For Phase 2+ test rides this is the cleanest source.

Direct 12V into an ESP32-S3 would destroy it (3.3V part, 5V tolerant on a few pins, not 12V tolerant anywhere). Anything that lives on F7 needs:

1. A fuse — protects the bike harness if something downstream shorts.
2. Reverse-polarity protection — protects the adapter if the connector ever gets reversed.
3. Transient absorption — motorcycle 12V can spike on load dump / alternator switching / coil events. A bulk input cap handles brief transients; a dedicated clamp (MOV, TVS, SCR crowbar) handles sustained over-voltage. This build uses **cap-only** absorption — see § Transient protection tradeoff for the rationale and upgrade paths.
4. A 12V → 5V step-down — the actual job.

Each piece is small. The whole chain fits on a 30×40 mm scrap of perfboard.

## Block diagram

```
Bike diagnostic connector                                          ESP32-S3-DevKitC-1
─────────────────────────                                          ──────────────────
                                  ┌──── fuse ────┐
   pin 4  F7  (+12V switched) ───►│   500 mA     │───┐
                                  └──────────────┘   │
                                                     ▼
                                              ┌─────────────┐
                                              │   1N5819    │   (reverse polarity)
                                              │   Schottky  │
                                              └──────┬──────┘
                                                     │
                                            ┌────────┴────────┐
                                            │                 │
                                            ▼                 │
                                      ┌──────────┐            │
                                      │  470 µF  │            │   (bulk cap — absorbs
                                      │   63 V   │            │    fast transients,
                                      │  electro │            │    slows slow ones)
                                      └──────────┘            │
                                            │                 │
                                            ▼                 │
   pin 3  GD  (GND) ───────────────────────GND               12V_in
                                            ▲                 │
                                            │                 ▼
                                            │         ┌───────────────┐
                                            │         │  LM2596       │
                                            │         │  buck module  │   (12V → 5V, pre-set pot)
                                            │         │  (Romanian)   │
                                            │         └───────┬───────┘
                                            │                 │
                                            │                5V_out
                                            │                 │
                                            └────GND──────────┼──► GND (DevKitC-1)
                                                              └──► 5V  (DevKitC-1)
```

CAN bus wiring (CH, CL) is unchanged from [`can-adapter.md`](can-adapter.md). This document covers only the power chain.

## Bill of materials

This build is hand-assembled on perfboard, so the picks below are **through-hole / axial parts** by default. SMD equivalents are noted in parentheses for anyone who'd rather reflow.

| Part | Specifics | Purpose | Approx. cost |
|------|-----------|---------|--------------|
| **LM2596 buck module** | 4–40 V input, 3 A capable. Available at every Romanian hobby shop (Optimus Digital, Cleste, Sigmanortec, Robofun) and AliExpress. Through-hole pins or screw terminals. Two variants exist: **adjustable** (on-board pot — **must be pre-set to 5.00 V with a multimeter before connecting anything downstream**, see § Operational rules) and **fixed 5 V** (no pot — drop-in, no adjust step). Either works; fixed-5V removes the pot-drift-on-vibration failure mode for free. | 12V → 5V step-down | €1–3 |
| **1N5819 Schottky diode** | 40 V, 1 A, DO-41 axial. ~0.4 V drop at 500 mA. (SMD equivalent: SS14 in DO-214AC. Interchangeable hobbyist parts: SB140, MBR140 — same 40 V / 1 A / DO-41 spec.) | Reverse-polarity protection | <$1 |
| **470 µF / 63 V radial electrolytic** | Aluminum electrolytic, polarised, radial leaded. Voltage rating ≥50 V required; 63 V gives comfortable headroom. Capacitance can be 220–1000 µF without consequence; 470 µF is the sweet spot for size vs. energy absorption. **Watch polarity** — the striped lead is negative. | Bulk transient absorption | €0.50 |
| *Upgrade alternatives: MOV / TVS / SCR crowbar* | See § Transient protection tradeoff. | Dedicated clamp (none of these are in the build-now BOM) | — |
| **500 mA inline fuse + holder** | Either glass 5×20 mm fast-blow (must be mounted inside the enclosure — glass is vibration-fragile in free air) or ATO-mini blade. Inline holder with pigtail leads. 0.5 A is the design value; 1 A is an acceptable fallback if 0.5 A is hard to source or nuisance-trips. | Bike-side overcurrent protection | ~$3 |
| **Perfboard / proto PCB** | ~30×40 mm, 0.1″ pitch | Build substrate | <$1 |
| **Hookup wire** | 22 AWG silicone preferred (flexible, vibration-tolerant) | Interconnects | — |
| **Optional: 5.6 V Zener diode (1N4734A)** | 5.6 V, 1 W, DO-41 axial through-hole | Downstream over-voltage clamp on the 5 V rail — protects the ESP if the buck dies in pass-through mode. See § Transient protection tradeoff. | €0.10 |
| **Optional: SPDT slide switch** | 5V / 1A rated, through-hole pins | Future power-source selector (USB vs F7) | ~$2 |
| **Optional: P-channel MOSFET (e.g. IRF9540N in TO-220, or BS250 in TO-92 for low current)** | >25 V Vds, >2 A Id, Vgs(th) fine at 12 V gate drive (logic-level not required — we're not switching from a 3.3 V GPIO) | Alternative reverse-polarity protection (lower drop than 1N5819, more parts to wire) | <$1 |

### Why these picks

- **LM2596 module** is the workhorse pick for hand-built hobby projects: stocked everywhere in Romania, 40 V input ceiling, tolerates the 12 V automotive rail without complaint. The two real cautions — output ripple and the unset output pot — are mitigated by (a) the ESP32-S3-DevKitC-1 having its own AMS1117-3.3 LDO downstream that cleans up the 5 V rail, and (b) the mandatory pre-adjust step (§ Operational rules). **Alternatives**: MP1584 modules are smaller and lower-ripple but cap at 28 V input — less headroom against transients that get past the bulk cap. **Upgrade path**: Pololu D24V10F5 or Recom R-78E5.0-1.0 if either becomes available — tighter input cap, automotive-rated, no pot to adjust. Both are direct drop-in replacements.
- **1N5819 Schottky** over a P-FET: simpler build, no gate-drive needed, ~0.4 V drop at 500 mA = 200 mW of heat which is invisible. P-FET is the right call for a polished product; the Schottky is the right call for a hand-built dev rig.
- **470 µF / 63 V bulk cap as the only transient protection** because every dedicated clamp candidate (MOV, TVS, zener) has Romanian-availability issues. The cap absorbs the energy of brief transients (ignition spikes, connection inrush) and slows the rise time of slower ones (load-dump tails), giving the LM2596's input cap and 40 V ceiling more margin. Doesn't clamp sustained over-voltage — that risk is accepted (see § Transient protection tradeoff). **Upgrade paths**: SCR crowbar (universally sourceable, robust); MOV (S14K14 etc.) or TVS (P6KE15CA) if either turns up locally.
- **500 mA fuse** because the whole rig peaks at ~500 mA at 5 V (~200 mA reflected at 12 V). A 500 mA fuse trips on any genuine fault and tolerates the normal load with margin. Fast-blow is correct here — there's no inrush worth speaking of. **1 A is an acceptable fallback** if 0.5 A is unavailable (RO blade assortments typically start at 2 A) — still trips on a hard short, just gives up protection against slow partial faults. **2 A is the cap** before fault sensitivity gets uncomfortably low for a bike-side install. **Glass vs blade:** glass 5×20 mm in the design is acceptable provided the holder is mounted inside the enclosure; blade (ATO-mini) is preferred for free-air mounts because of vibration tolerance.

## Transient protection tradeoff

**What the bulk-cap-only chain protects against:**

- Reverse polarity (handled by the Schottky).
- Downstream shorts (handled by the fuse).
- Brief over-voltage spikes — ignition transients, alternator-switching noise, connection inrush. The 470 µF cap absorbs the energy; the LM2596's own input cap and 40 V abs-max input handle the residual.

**What it does *not* protect against:**

- **Sustained over-voltage from a failed regulator.** If the bike's voltage regulator dies in the wrong direction, the rail can sit at 30–60 V for seconds-to-minutes. The bulk cap is not a clamp — it'll happily charge to that voltage (within its 63 V rating). Once the rail exceeds the LM2596's 40 V abs-max input, the buck dies, the buck typically fails short, the fuse blows, and the rig is dead. The bike harness is fine; the adapter needs rebuilding.

This risk is accepted because (a) modern EFI bikes have reliable regulators — sustained failures are uncommon, not a "when, not if" scenario, (b) the failure mode is contained: fuse blows, no harness damage, no bike damage, just a dead adapter, and (c) the dedicated-clamp parts that would prevent it (low-V MOV, low-V TVS) are not reliably sourceable in Romanian hobby shops at the time of this build.

**Upgrade paths**, in increasing order of complexity:

1. **Downstream 5.6 V Zener on the 5 V rail.** *Cheap insurance against the residual ESP-kill scenario.* Even with the bulk cap working as designed, there's a ~10 % chance that during a sustained over-voltage event the buck dies in *pass-through* mode (its internal MOSFET shorts and the input voltage appears at the output) before the cap or fuse have a chance to act. If the pass-through voltage exceeds the DevKitC-1's downstream AMS1117 LDO abs-max (~15 V), the ESP dies. A **1N4734A** (5.6 V, 1 W, DO-41 axial) wired cathode-to-5V-pin / anode-to-GND on the DevKitC-1's 5 V rail catches this: normally non-conducting, but if the rail rises above ~5.6 V the Zener conducts heavily, spikes current draw, blows the fuse, rail collapses to 0 V before the LDO sees abs-max. Closes the only meaningful residual failure path for the cost of one part and two solder joints. **Skip if 1N4734A is not locally available — it's insurance, not required.**
2. **MOV / TVS upstream.** Add a clamp across the 12 V rail downstream of the Schottky, before the bulk cap. Recommended parts if they appear locally: S14K14 (or 14D22K, B72214S0140K) for MOV; P6KE15CA or 1.5KE15CA for TVS. Drop-in addition — no other wiring changes. Addresses the over-voltage event further upstream than the Zener does.
3. **5 W zener clamp upstream.** 1N5354B (17 V) or 1N5355B (18 V) in DO-15. Less surge handling than a TVS but better than nothing. Same physical install as the MOV/TVS.
4. **SCR crowbar upstream.** Most robust. When voltage exceeds zener trigger, SCR fires, shorts the rail, fuse blows. All parts universally stocked. Parts list:
   - SCR: 2N5060 (TO-92, ~11 A surge) or MCR100-6 / C106D.
   - Trigger zener: 1N4744A (15 V, 1 W) or 1N4745A (16 V).
   - Gate resistor: 100 Ω from zener cathode to SCR gate.
   - Gate pull-down: 1 kΩ from SCR gate to SCR cathode.
   - Optional 100 nF ceramic from gate to cathode for noise immunity.
   - Crowbar wired across the rail; the existing fuse becomes the sacrificial element when it fires.

The Zener (option 1) and any upstream protection (options 2–4) are complementary, not alternatives — Zener catches what slips past upstream protection (or what fails downstream of it), upstream protection prevents most events from ever reaching the buck.

## Wiring procedure

Assumes the adapter from [`can-adapter.md`](can-adapter.md) is already built (CAN side working over USB).

### Step 1 — pigtail extension

The existing pigtail to the bike connector is 3-wire (CH, CL, GND). Extend it to 4-wire by adding F7 (grey/pink, diagnostic pin 4). Crimp connectors are fine; if soldering to existing wires, heatshrink each joint individually.

### Step 2 — build the power board

On a small piece of perfboard, in order from input to output:

1. **Fuse + holder** in line with the F7 wire, as close to the bike-side connector as physically practical. Mount location depends on fuse type: **blade (ATO-mini)** can sit at the enclosure entry for swap-without-opening; **glass 5×20 mm** must be inside the enclosure to protect it from vibration.
2. **1N5819 Schottky** in series, anode toward F7 (the fused side), cathode toward the rest of the board. Mark the orientation — installing it reversed means the adapter never sees power; installing it reversed *and* applying reverse polarity means it conducts and fries downstream.
3. **470 µF / 63 V electrolytic** across the rail (between the post-Schottky 12V node and GND). **Polarity matters** — the striped side / short lead goes to GND, the long lead / unmarked side goes to +12 V. Reverse polarity on an electrolytic typically fails it short within seconds and may vent loudly.
4. **LM2596 buck**: `VIN` to the post-cap 12V node, `GND` to common ground, `VOUT` to a 5V rail on the board.

### Step 3 — adapter board wiring

- **5V rail → DevKitC-1 `5V` pin.** Not `3V3` (would bypass the on-board LDO and likely damage the board). Not the USB-C connector. The `5V` pin is on the right-hand header — check the silkscreen.
- **GND → DevKitC-1 `GND`.** Single common ground with the bike (pin 3), the buck output, and the transceiver.
- **Transceiver wiring unchanged.** SN65HVD230 still gets 3V3 from the DevKitC-1's 3V3 pin, not from this power board.
- **Optional: 5.6 V Zener (1N4734A) across the DevKitC-1's `5V` pin and `GND`.** Cathode (striped end) to `5V`, anode to `GND`. Solder directly to the DevKitC-1 header pins or to the 5V rail on the power board — either works. Wrong polarity means it conducts continuously at 5 V and immediately blows the fuse the first time the rig is powered — verify the stripe orientation before powering on. See § Transient protection tradeoff for what this protects against.

### Step 4 — pre-power checklist

Before plugging into the bike:

- [ ] Continuity check: F7 wire from bike connector → fuse holder → Schottky anode.
- [ ] Continuity check: Schottky cathode → buck VIN.
- [ ] Continuity check: GND from bike pin 3 → all GND points on the board.
- [ ] Resistance check between F7 (post-fuse) and GND with multimeter on the 20kΩ range: should read in the kΩ (the buck's input impedance), **not** near 0 Ω (short — find it before powering on).
- [ ] Resistance check between 5V out and GND: similar — kΩ, not short.
- [ ] Visual check: Schottky orientation, electrolytic polarity correct (striped lead = GND), optional 5.6 V Zener stripe pointing at `5V` (cathode), no solder bridges around the buck pins.

## Bench-test procedure

Before connecting to the bike. Bench supply or a 12V battery is fine.

### Test 1 — naked buck

Disconnect the DevKitC-1. **If using the adjustable variant, pre-set the output pot to 5.00 V before installing it on the board, per § Operational rules.** (Fixed-5V modules skip this — the check below still applies.) Apply 12 V to the F7 input. Measure:

- **5V_out:** 4.95–5.05 V with no load. If you see 0 V, the buck is dead or installed wrong. If you see 12 V or any voltage above ~5.5 V, the pot wasn't pre-adjusted (or the buck failed short) — **disconnect immediately**, the next step would have killed the ESP32. Re-adjust on the bench before continuing.
- **Current draw from 12 V:** <20 mA (the buck's own quiescent). If you see >100 mA, something downstream of the 5V rail is shorting or the buck is faulty.

### Test 2 — buck + DevKitC-1, no transceiver

Connect 5V_out → DevKitC-1 `5V` pin and GNDs. **USB unplugged from the DevKitC-1.** Apply 12 V.

- DevKitC-1 power LED should light.
- USB-CDC won't come up (no USB cable), but the boot sequence happens on whatever's flashed.
- Current from the 12 V supply: ~80–120 mA (40–50 mA reflected from the ~200 mA the board pulls at 5 V).
- Touch the buck inductor with a finger after 30 s — warm is fine, uncomfortable to hold is a sign you're at the thermal limit or oscillating.

### Test 3 — full rig, listen-only against a bench CAN node

Reconnect the transceiver. If a bench CAN node is available (another ESP, a CAN-capable USB adapter, anything that broadcasts), point the rig at it and verify frames are received the same way the USB-powered rig does.

- Current from 12 V should rise to ~100–150 mA depending on bus activity.
- The transceiver should not get hot.

### Test 4 — transient stress (optional but recommended)

Cycle the 12 V supply on/off 20 times in quick succession. Watch for:

- Any time the rig fails to boot.
- The fuse blowing (would indicate inrush is exceeding 500 mA — switch to a slow-blow if this happens repeatedly with no actual fault).
- Buck output ringing visible on a scope if you have one (transients above 5.5 V mean the buck is undamped, possibly faulty).

### Test 5 — first bike connection

After all bench tests pass:

1. Key off.
2. Plug the pigtail into the bike's diagnostic connector.
3. Key on. The DevKitC-1's power LED should light within ~100 ms.
4. Run a short capture via whatever firmware is flashed (USB-CDC if `can-logger` and a USB cable is still attached for monitoring; or via the WiFi path once [ADR 0016](../decisions/0016-wifi-dev-capture-and-live-view.md) is up).
5. Key off. The DevKitC-1 should power down within ~50 ms of F7 dropping. No lingering activity.

## Operational rules

- **Pre-adjust the buck's output to 5.00 V before connecting the ESP32 (adjustable variant only).** Adjustable LM2596 / MP1584 modules ship with the output pot at an arbitrary position — often 12 V or higher. Procedure: apply 12 V to the buck's input on the bench, measure VOUT with a multimeter, turn the pot (small screwdriver, usually 10+ turns) until the output reads 5.00 V (±50 mV). Then lock the pot with a dab of nail polish, clear epoxy, or hot glue so vibration on the bike can't shift it. **Do this with the ESP32 disconnected.** Plugging an ESP32 into a buck still configured for 12 V output kills it immediately. Fixed-5V modules have no pot and skip this step — still verify VOUT with a multimeter (Test 1) before wiring downstream.
- **USB and F7 are not simultaneous.** The DevKitC-1's USB VBUS feeds the same 5V rail through a protection diode. Connecting both is electrically safe but creates a backfeed path the buck regulates against. **For flashing or USB-CDC dev, unplug F7. For ride captures, unplug USB.** A piece of tape over whichever port isn't in use is the simplest enforcement until a switch is added.
- **The fuse is the only sacrificial element.** If the rig stops powering up after a fault, check the fuse before assuming a deeper problem. Carry a spare in the toolkit.
- **Bike pin 3 (GD) is the only ground reference.** Do not chassis-ground the adapter to the frame or to an unrelated harness ground point — pin 3 is what the ECU references.
- **Watertightness.** This doc does not cover an enclosure. Until the adapter is enclosed, ride captures should be fair-weather only. Stuff a freezer bag around the board if you have to go out in the wet, and call it engineering.

## Open items

- [ ] **First bench-test pass** on the assembled board (Tests 1–4 above) — verify before bike connection.
- [ ] **First bike-on test** (Test 5) — confirms key-on/key-off timing and that nothing on the bike trips when the rig draws ~150 mA from F7.
- [ ] **Enclosure** for the adapter. 3D-printed project box, sized to fit perfboard + DevKitC-1 + transceiver breakout + power board. Out of scope for this doc; track when the first ride is on the calendar.
- [ ] **SPDT power-source switch.** Deferred until the USB/F7 backfeed footgun actually causes a problem.
- [ ] **P-FET reverse-polarity upgrade.** Documented as an option above. Worth doing only if measured thermals on the 1N5819 ever become a concern (they won't, at this current).
- [ ] **Inline cold-boot timing measurement** vs the USB-powered baseline ([`findings/can/always-on-broadcast-ids.md`](../findings/can/always-on-broadcast-ids.md) — 250 ms time-to-first-frame). The expectation is no meaningful difference; verify and add a finding under `docs/findings/hardware/` if anything surprising shows up.
