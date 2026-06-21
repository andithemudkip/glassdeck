---
area: can
status: confirmed
established_by:
  - 2026-06-17-key-on-cold-boot
  - 2026-06-17-engine-idle-baseline-x3
---

# Always-on broadcast IDs

At the diagnostic-port stub of the 2020 Husqvarna Svartpilen 401, **the same 11 arbitration IDs broadcast continuously** from ~250 ms after key-on through engine cranking, steady idle, and into the first few seconds after kill. All are 11-bit standard frames with 8-byte payloads. No 29-bit traffic, no remote frames, no DLC ≠ 8 has been observed.

| Cohort  | IDs                                       | Median period (cross-run range) |
|---------|-------------------------------------------|--------------------------------:|
| 10 ms   | `12D`                                     | 10.58 – 11.01 ms                |
| 20 ms   | `120`, `121`, `129`, `12E`, `541`         | 19.18 – 19.87 ms                |
| 50 ms   | `12A`, `450`                              | 49.80 – 50.67 ms                |
| 100 ms  | `540`, `5A0`, `5B0`                       | 98.75 – 99.85 ms                |

Period ranges are the min/max of per-run medians across three independent power-cycled engine-idle captures and the original cold-boot capture. Cross-power-cycle spread is ≤ 1.2 % of the mean for ten of eleven IDs and 3.99 % for `12D` (the 10 ms cohort, where USB-CDC bunching has more proportional impact on the median). Treat the median as the load-bearing periodicity figure — inter-arrival min/max are dominated by host-side bunching, not bus jitter (see [ADR 0004](../../decisions/0004-logger-wire-format-slcan.md)).

## The ID set does not change with engine state

The same 11 IDs broadcast at key-on engine-off, throughout cranking windows of 1 – 5 s, throughout steady idle, and into the first ~5 s after kill. **No new ID appears when the engine starts running.** Any "the engine is now running" signal at this connector must be encoded inside the **payload bytes** of the existing 11 IDs — not as a new arbitration ID coming online. This frames all of Phase 2: signal-hunting for engine-state, RPM, throttle position, coolant temperature, oil pressure, etc., is a payload-diff problem against a known fixed ID set.

## First signal mappings inside this fixed ID set

The payload-diff experiment ([`2026-06-17-payload-diff-idle`](../../experiments/2026-06-17-payload-diff-idle.md)) has decoded two signals from these 11 IDs:

- **[[signal-rpm]]** — engine RPM at `120` bytes D0,D1 (big-endian uint16).
- **[[signal-coolant-temp]]** — coolant temperature at `540` bytes D5,D6 (big-endian uint16, ÷10 for °C).

Both were confirmed by cross-referencing the [ktm-can decoder](../../references/ktm-can-decoder.md) for the 2020 KTM 690 Enduro R (same Bosch ECU family) and verifying values against our captures (idle RPM ~1700, coolant climbing from ~26 °C cold to 85.5 °C operating temp across the three idle runs). Per-input experiments will add more.

## Post-kill decay + boot order reveal at least four source modules

The 11 IDs do **not** stop broadcasting uniformly after kill, and they do **not** all appear at boot at the same time. The combined analysis — Fast/Slow decay split plus three distinct Slow-group boot waves — puts the bus at ≥4 source modules. See [[post-kill-decay-groups]] for the sub-grouping table.

**The 11 always-on IDs are the complete bus inventory at idle.** Across all 4 cold-boot windows checked ([[2026-06-21-cold-boot-id-emergence]]), zero one-shot or boot-only IDs appeared — no module emits a "hello" frame and goes silent. Any new ID surfaced by a future per-input capture is genuinely input-driven, not an undocumented boot frame.

## Status

**Confirmed.** Three independent engine-idle captures, all eleven IDs present in every steady-idle window, period spread ≤ 4 % per ID across power cycles. Hypothesis 1 of the idle-baseline experiment (stable always-on set across power cycles, consistent periods) was met cleanly. Hypothesis 2 (a distinct engine-start transient ID set) was rejected — even with cranking windows of 1 – 5.2 s, no new ID surfaced.

## Evidence

- [`docs/experiments/2026-06-17-key-on-cold-boot.md`](../../experiments/2026-06-17-key-on-cold-boot.md) — first 11-ID inventory, key-on engine-off only, 72 916 frames over 174 s.
- [`docs/experiments/2026-06-17-engine-idle-baseline-x3.md`](../../experiments/2026-06-17-engine-idle-baseline-x3.md) — three power-cycled engine-on captures (cold / partially warm / operating temperature), ~89 k frames each, ~175 s steady-idle each, same 11 IDs every time, cross-run period spread tabulated.

Re-derive any number above from the captures: `python scripts/inventory_ids.py logs/<session> [--anchor-label "starter button"]`.

## Open

- Engine state encoded in payload bytes — not characterised. First Phase 2 follow-up.
- Module attribution from the post-kill decay split — see [[post-kill-decay-groups]].
- Whether longer-tail post-kill captures (current ones top out at ~7 s of decay) reveal further structure in the slow-decay group.

**Bike state during captures:** engine cold for the cold-boot session and idle Run 1; partially warm for idle Run 2 (~13 min key-off after Run 1); operating temperature (~half coolant gauge) for idle Run 3. Ambient ~30 °C, fuel ~50 % across all sessions. Check engine + ABS lamps lit at key-on, extinguishing per [[dash-warning-lights]].

See also: [[bitrate]], [[dash-warning-lights]], [[post-kill-decay-groups]].
