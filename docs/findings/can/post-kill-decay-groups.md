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

## What this is *not* a finding for (yet)

- **Module identification.** "Fast" probably corresponds to a module on the engine-management / charging side of the harness — something whose supply is tied closely to the running engine. "S-early", "S-mid", and "S-late" probably correspond to three different modules on a keep-alive or buffer-capacitor rail — candidates per sub-group include ABS module (S-early?), body controller (S-mid?), and instrument cluster (S-late?), but the assignment is hypothesis, not finding. The CAN traffic alone can't tell us which physical module a given ID comes from.
- **Sub-100 ms behaviour.** The captured decay tails are 6 – 10 s long. We have no direct view of what happens in the first ~50 ms after kill at sub-frame-period granularity — could be a graceful shutdown sequence, could be sudden loss-of-power, indistinguishable from the data we have.

## Why this matters

For per-input experiments to come, **frame-direction inference is easier when you can hypothesise which module sourced an ID.** Examples:
- ABS-warning-light state (extinction at ~6 km/h per [[dash-warning-lights]]) ought to come from the ABS module — *if* ABS is in the Slow group, then any of the Slow IDs is a candidate source; any Fast ID is ruled out.
- Engine RPM ought to come from the ECU — likely Fast group (engine-run circuit).
- Indicator state ought to come from a body-controller-class module — likely Slow group (keep-alive).

These are hypotheses to test, not asserted relationships. The grouping is what's confirmed; the mapping to physical modules isn't.

## Notes on measurement

- `12D` shows post-kill inter-arrivals collapsing to sub-millisecond medians in all three runs. This is host-side USB-CDC end-of-stream bunching as the buffer drains, not a real bus phenomenon. Use the *last-frame timestamp* (column above) as the load-bearing signal, not the in-window inter-arrival statistics.
- All three captures stopped within ~10 s of `kill switch`, then key-off. A longer post-kill capture would tell us how long the Slow group continues — currently we only know "at least ~4.7 s, with some IDs still broadcasting when capture ended."

## Evidence

- [`docs/experiments/2026-06-17-engine-idle-baseline-x3.md`](../../experiments/2026-06-17-engine-idle-baseline-x3.md) — three independent power-cycled captures, decay tables in the Result section. Re-derive with the windowing analysis embedded in that experiment.

## Open

- Confirming the split with longer post-kill capture tails (target: 30 s+ post-kill capture to characterise the Slow group's actual decay timescale).
- Hardware-side experiment: which physical modules are these? Options include scoping module supply rails through a kill event, or fuse-pulling one module at a time and re-capturing.
- Whether the Fast group correlates with engine-data IDs and the Slow group with body / instrument-cluster IDs — testable once any single ID has been mapped to a signal.

See also: [[always-on-broadcast-ids]].
