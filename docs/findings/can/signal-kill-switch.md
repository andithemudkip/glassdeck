---
area: can
status: confirmed
established_by:
  - 2026-06-18-kill-switch-toggle
references:
  - ktm-can-decoder
---

# Kill switch (run/stop) — `541` byte D2 bit 4

Kill-switch state on the 2020 Husqvarna Svartpilen 401 is broadcast in arbitration ID **`0x541`**, byte **D2**, **bit 4** (LSB-numbered, so mask `0x10`):

```
run  = (data[2] & 0x10) != 0
```

| Switch position | D2 bit 4 |
|-----------------|---------:|
| RUN             |        1 |
| STOP            |        0 |

Confirmed across **6 toggles / 7 windows** with per-window purity ≥ 0.99 — every window's bit value was effectively pure, and the dominant value alternated `1,0,1,0,1,0,1` in lockstep with the toggle sequence. `541` broadcasts continuously in both states (no rate change), so this signal is observable at all times the bus is up.

## Cross-walk vs KTM

The ktm-can decoder ([reference](../../references/ktm-can-decoder.md)) places kill-switch state at `120` D3 bit 4 with `1 = run, 0 = stop`. On Husqvarna:

- **Polarity matches** (1 = run, 0 = stop).
- **Location does not.** `120` D3 stays `0x00` in both run and stop (verified across all 7 windows). `120` does not carry the kill-switch state on this bike.

The likely structural reason: `120` is in the Fast post-kill decay group (see [[post-kill-decay-groups]]), and on Husqvarna the Fast-group source module reduces its broadcast rate dramatically when the kill switch is in STOP — it would be a poor carrier for kill-switch state when its source effectively goes quiet on STOP. `541` is in the Slow group and broadcasts steadily across both states, which makes it the natural source.

## Side-finding: Fast group ceases when kill = STOP, even engine-off

When the kill switch goes to STOP (key on, engine off), every Fast-group ID stops broadcasting within ~1 s. Binning each STOP window's Fast-group frames by their offset from the toggle:

| ID  | Group | s 0–1 | s 1–2 | s 2–3 | s 3–4 | s 4–5 |
|-----|-------|------:|------:|------:|------:|------:|
| 120 | Fast  | 12 / 17 / 17 | 0 | 0 | 0 | 0 |
| 540 | Fast  | 2 / 4 / 3    | 0 | 0 | 0 | 0 |
| 541 | Slow (ref.) | 50 / 50 / 50 | 50 / 50 / 50 | 50 / 50 / 50 | 50 / 49 / 50 | 50 / 23 / 50 |

(Three numbers per cell = the three STOP windows of this capture.)

The Fast-group counts are the **same post-kill decay tail** documented in [[post-kill-decay-groups]] for the engine-on case (last frame at 0.18 – 0.31 s after kill). Engine state at the moment of kill doesn't matter: what matters is that the kill switch is in RUN — when it goes to STOP, the Fast-group source module(s) lose CAN broadcasting capability after the same sub-second tail. This generalises the post-kill-decay finding from "after kill while running" to "any time the kill switch goes to STOP".

## Evidence

- [`docs/experiments/2026-06-18-kill-switch-toggle.md`](../../experiments/2026-06-18-kill-switch-toggle.md) — Result section.
- [`logs/2026-06-19-kill-switch-toggle/`](../../../logs/2026-06-19-kill-switch-toggle/) — raw capture.
- [`scripts/kill_switch_scan.py`](../../../scripts/kill_switch_scan.py) — window-aware bit scan that surfaced the hit.

## Open

- Confirm at higher temperatures / with engine running. The signal at `541` D2 bit 4 is asserted at key-on and tracks the physical switch with the engine off; an engine-on STOP press (which kills a running engine) is a different functional path and may or may not use the same bit.
- Other bits of `541` D2: the byte was not exhaustively characterised. Worth a fresh idle-vs-state scan with several inputs varied.

See also: [[always-on-broadcast-ids]], [[post-kill-decay-groups]], [[ktm-can-decoder]].
