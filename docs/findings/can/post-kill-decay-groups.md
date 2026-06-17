---
area: can
status: confirmed
established_by:
  - 2026-06-17-engine-idle-baseline-x3
---

# Post-kill decay groups — at least two source modules

After the kill switch is pressed, the 11 always-on broadcast IDs do not stop transmitting at the same time. They cleanly split into two groups by how quickly their last frame appears after the `kill switch` event:

| Group         | IDs                                  | Last frame after kill (range across 3 runs) |
|---------------|--------------------------------------|--------------------------------------------:|
| **Fast**      | `120`, `121`, `129`, `540`, `5B0`    |                              0.18 – 0.31 s  |
| **Slow**      | `12A`, `12D`, `12E`, `450`, `541`, `5A0` |                          4.69 – 7.06 s  |

The split is exactly 5 vs 6, with the same IDs on each side every run.

This is the first observed evidence that the 11-ID always-on broadcast set originates from **at least two physically distinct modules** — modules that lose CAN-bus broadcasting capability on different timescales when the kill switch breaks the engine-run circuit. A single module would shed all of its IDs together.

## What this is *not* a finding for (yet)

- **Module identification.** "Fast" probably corresponds to a module on the engine-management / charging side of the harness — something whose supply is tied closely to the running engine — and "Slow" probably corresponds to a module on a keep-alive or buffer-capacitor rail (instrument cluster, body controller, ABS module are all candidates). This is hypothesis, not finding. The CAN traffic alone can't tell us which physical module a given ID comes from.
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
