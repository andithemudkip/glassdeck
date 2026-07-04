---
area: can
status: confirmed
established_by:
  - 2026-06-17-engine-idle-baseline-x3
  - 2026-06-18-kill-switch-toggle
  - 2026-06-21-cold-boot-id-emergence
---

# Post-kill decay groups + boot-order sub-grouping — at least four source modules

When the kill switch goes to STOP, the 11 always-on broadcast IDs do not stop transmitting at the same time. They cleanly split into two groups by how quickly their last frame appears after the kill toggle:

| Group         | IDs                                  | Last frame after kill (range)               |
|---------------|--------------------------------------|--------------------------------------------:|
| **Fast**      | `120`, `121`, `129`, `540`, `5B0`    |                              0.18 – ~1.0 s  |
| **Slow**      | `12A`, `12D`, `12E`, `450`, `541`, `5A0` |                          4.69 – 7.06 s  |

The split is exactly 5 vs 6, with the same IDs on each side every run.

This shows the 11-ID always-on broadcast set originates from **at least two physically distinct modules** with different post-kill power-rail decay timescales. But the boot-order analysis ([[2026-06-21-cold-boot-id-emergence]]) refines this further — the Slow group itself splits into three distinct boot waves, so the bus is sourced by **at least four modules**, not two:

| Sub-group | IDs                                | Boot wave (median first-seen) | Decay tail |
|-----------|------------------------------------|------------------------------:|-----------:|
| F         | `120`, `121`, `129`, `540`, `5B0`  |        188 ms (±1 ms)         |   <1 s     |
| S-early   | `12D`, `12E`                       |    153 ms, 180 ms             |   5–6 s    |
| S-mid     | `12A`, `5A0`                       |    202 ms, 253 ms             |   5–6 s    |
| S-late    | `541`, `450`                       |    388 ms, 424 ms             |   5–6 s    |

The 5 Fast-group IDs first-seen offsets cluster within 1 ms of each other across all 4 cold-boot windows — tighter than any single ID's broadcast period. That is the signature of one module broadcasting all 5 IDs after a single boot completion. The three Slow-group sub-waves are separated by 50–150 ms gaps — far wider than any individual ID's period — so they cannot be the same module.

The Fast/Slow decay-tail dichotomy still holds and is unrelated to boot timing: Slow's earliest member (`12D`) boots *before* every Fast-group member, yet still sits on a slow-decay rail. Decay grouping is about the post-kill power supply, boot grouping is about each module's startup sequence.

**Engine state at kill-time doesn't matter.** Both the engine-on case ([`2026-06-17-engine-idle-baseline-x3`](../../experiments/2026-06-17-engine-idle-baseline-x3.md), three runs) and the engine-off case ([`2026-06-18-kill-switch-toggle`](../../experiments/2026-06-18-kill-switch-toggle.md), three STOP windows) show the same grouping and the same Fast-group sub-second tail. What triggers the decay is the kill switch going to STOP, not the engine stopping. (The engine-off tails extend to ~1 s rather than 0.31 s, but every frame in every STOP window of the kill-toggle capture landed in the first second after the toggle — seconds 1–5 were flat zero. Whether the upper tail genuinely runs out to ~1 s engine-off vs. ~0.31 s engine-on, or whether it's bin-edge / sample-size noise, isn't worth a follow-up at this point.)

## Module identification — partial (updated 2026-07-01 from schematic)

The 2026-07-01 review of the repair-manual wiring diagram (pages 30.1–30.9) surfaced only **three** CAN nodes wired on the bus:

- **A11** — Engine Control Unit (Bosch EFI), CAN on K44/X11 pins 36 (Low) + 37 (High).
- **A30** — ABS Control Unit, CAN on QN/16/X30 pins 4 (Low) + 3 (High).
- **P10** — Combination Instrument (dashboard), CAN on LL/12/X10 pins 9 (Low) + 10 (High).

Attribution against the boot-order sub-groups:

| Sub-group | IDs                                | Source module | Basis |
|-----------|------------------------------------|---------------|-------|
| F         | `120`, `121`, `129`, `540`, `5B0`  | **A11 (ECU)** | Contains RPM ([[signal-rpm]]) which is sourced from B37 crank speed sensor → A11 pin (schematic p. 30.5); throttle ([[signal-throttle-position]]) from B80 grip → A11; coolant ([[signal-coolant-temp]]) from B21 → A11 pin 19. |
| S-early   | `12D`, `12E`                       | **A30 (ABS)** | `12D` carries wheel speeds ([[signal-wheel-speed-front]], [[signal-wheel-speed-rear]]) which are sourced from B70/B71 → A30 (schematic p. 30.9). Only A30 has those inputs. |
| S-mid     | `12A`, `5A0`                       | **open**      | No obvious ECU or ABS attribution. Not P10 (dash doesn't have inputs for anything moving on these). |
| S-late    | `541`, `450`                       | **open**      | Same. `541` D2 bit 4 = kill switch ([[signal-kill-switch]]) — which is wired into both A11 pin 33 and P10 pin 5, so either could be the transmitter, but it's redundantly broadcast on multiple IDs so this doesn't decide it. |

**Discrepancy — one or two missing nodes.** Boot analysis says ≥4 modules; the schematic shows only 3 CAN nodes. Two hypotheses:

1. **A hidden CAN node exists,** not present in these 9 wiring-diagram pages. Most likely candidate on a Bosch platform is an **immobilizer / EWA-D** (electronic wheel authentication device) that handles the transponder key — standard on KTM/Husky platform bikes of this generation, but usually documented in a separate chapter of the repair manual (anti-theft / immobilizer). Might explain S-mid or S-late. A quick scan of the manual's remaining chapters for "immobilizer", "EWA", "transponder" would settle it.
2. **The 4-module inference was slightly wrong** and S-mid + S-late are sub-schedulers *within* A11 (or A30) that boot at a slightly later phase than the main scheduler. Modern ECUs commonly run multiple RTOS tasks with different startup sequences. If so, all six Slow IDs come from at most two physical modules.

Between the two, hypothesis (1) is the cleaner reading — the boot-wave gaps of 50–150 ms are wider than task-scheduler jitter usually is, and immobilizer ECUs are near-ubiquitous on modern EFI bikes. Awaits confirmation from another manual chapter or from a hardware probe (pulling suspected-module fuses and seeing which IDs drop off).

## Other things this is *not* a finding for (yet)

- **Sub-100 ms behaviour.** The captured decay tails are 6 – 10 s long. We have no direct view of what happens in the first ~50 ms after kill at sub-frame-period granularity — could be a graceful shutdown sequence, could be sudden loss-of-power, indistinguishable from the data we have.
- **Whether P10 (dash) transmits at all.** The dash is on the CAN bus by wire, but we have no direct evidence in the boot-order analysis that it originates any of the 11 IDs. If S-mid or S-late are actually the dash rather than a hidden module, hypothesis (2) collapses back into (1) with the dash filling the "missing node" slot.

## Why this matters

For per-input experiments to come, **frame-direction inference is easier when you can hypothesise which module sourced an ID.** With the 2026-07-01 attribution above:

- **RPM, throttle, coolant, side-stand, clutch, gear, kill-switch (primary)** — all from A11 (F group), confirmed against sensor→ECU wiring on schematic pp. 30.4/30.5/30.9.
- **Front/rear wheel speed, plus everything else on `12D`/`12E`** — from A30 (S-early), confirmed against wheel-speed-sensor→ABS wiring on p. 30.9.
- **ABS-warning-light state** — expected to be broadcast by A30 (S-early) since the ABS unit is authoritative for its own lamp state.
- **Indicator state** — not on CAN at all, per repair-manual schematic p. 30.7 (dedicated wires to X10 pins 11 / 12; see [`dash-connector.md`](../../hardware/dash-connector.md)).
- **Anything on S-mid or S-late** — unattributed until hypothesis 1 or 2 above is resolved.

## Notes on measurement

- `12D` shows post-kill inter-arrivals collapsing to sub-millisecond medians in all three runs. This is host-side USB-CDC end-of-stream bunching as the buffer drains, not a real bus phenomenon. Use the *last-frame timestamp* (column above) as the load-bearing signal, not the in-window inter-arrival statistics.
- All three captures stopped within ~10 s of `kill switch`, then key-off. A longer post-kill capture would tell us how long the Slow group continues — currently we only know "at least ~4.7 s, with some IDs still broadcasting when capture ended."

## Evidence

- [`docs/experiments/2026-06-17-engine-idle-baseline-x3.md`](../../experiments/2026-06-17-engine-idle-baseline-x3.md) — three independent power-cycled captures, decay tables in the Result section. Re-derive with the windowing analysis embedded in that experiment.

## Open

- Confirming the split with longer post-kill capture tails (target: 30 s+ post-kill capture to characterise the Slow group's actual decay timescale).
- **S-mid + S-late attribution.** Two paths to close: (a) scan the remaining repair-manual chapters for an immobilizer / EWA / anti-theft ECU that also sits on CAN; (b) hardware-side experiment — pull the F21/F22 ABS fuses or the F3 ECU fuse and re-capture, observe which IDs drop out to attribute the survivors to the un-fused modules by elimination.
- Whether the dashboard P10 originates any CAN traffic. If yes, it's a candidate for one of the currently-open sub-groups. If no, we definitely need a fourth physical node to explain the boot waves.

See also: [[always-on-broadcast-ids]].
