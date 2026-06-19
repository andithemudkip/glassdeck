---
area: can
status: confirmed
established_by:
  - 2026-06-18-side-stand-toggle
references:
  - ktm-can-decoder
---

# Side stand (raised/down) — `540` byte D3 bit 0

Side-stand state on the 2020 Husqvarna Svartpilen 401 is broadcast in arbitration ID **`0x540`**, byte **D3**, **bit 0** (LSB-numbered, so mask `0x01`):

```
up   = (data[3] & 0x01) != 0
down = (data[3] & 0x01) == 0
```

| Stand position | D3 bit 0 |
|----------------|---------:|
| UP (raised)    |        1 |
| DOWN           |        0 |

Confirmed across **6 toggles / 7 windows** with per-window purity `1.00` on every window — every steady-state window's bit value was effectively pure, and the dominant value alternated `0,1,0,1,0,1,0` in lockstep with the rider's `j` event marks. `540` broadcasts continuously at ~100 ms in both states (no rate change, no dropout), so this signal is observable at all times the bus is up.

Across all 7 windows of this engine-off capture, `540` D3 took only two values: `0x10` (DOWN) and `0x11` (UP). The hi nibble was stuck at `0x1` and the only varying bit was bit 0 — consistent with [[signal-gear-position]]'s observation that the D3 hi nibble was LOW-CARD(4) in the engine-on idle baselines but stuck at `0x1` for engine-off captures with inputs not exercised. Bit 0 was static 0 across the idle baselines (bike on its side stand), which matches the polarity confirmed here.

## Press-to-flip lag — rider mistiming, not bus latency

Pressing `j` and seeing the bit flip is separated by ~0.6 – 1.0 s in this capture, but this is **rider mistiming**, not a bus property: the rider keyed `j` at the *intent* to flick the stand, and the foot-/hand-driven travel of the kickstand itself takes that long to complete. The actual sensor-to-bus latency is not measured by this experiment and is presumed comparable to the kill switch (≤ one `540` broadcast period, ~100 ms). Treat the dashboard bit as edge-responsive to the physical stand state.

If a precise number is needed later, a synthetic ground-truth mark (e.g., a microswitch or reed on the stand fed into a free GPIO) would isolate sensor-to-bus latency from rider-press-to-stand-completion time.

## Cross-walk vs KTM

The ktm-can decoder ([reference](../../references/ktm-can-decoder.md)) places side-stand state at `540` D4 bit 0 with `1 = up, 0 = down`. On Husqvarna:

- **Polarity matches** (1 = up, 0 = down).
- **Location shifts one byte earlier**: D4 → D3 within the same ID.

This is the second `540` signal where the byte position shifts one earlier vs KTM. The first was coolant temperature ([[signal-coolant-temp]]) at D5/D6 on Husqvarna vs D6/D7 on KTM. Pattern emerging: **`540`'s byte layout is systematically shifted one byte earlier on Husqvarna**, with polarity preserved. Use this as a starting hypothesis when probing future `540` signals.

Combined with the kill-switch finding ([[signal-kill-switch]]), the pattern across all KTM cross-walks tested so far is "polarity preserved, location may move" — no inverted-polarity case has been observed on Husqvarna yet.

## Evidence

- [`docs/experiments/2026-06-18-side-stand-toggle.md`](../../experiments/2026-06-18-side-stand-toggle.md) — Result section.
- [`logs/2026-06-19-side-stand-toggle/`](../../../logs/2026-06-19-side-stand-toggle/) — raw capture, 28 943 frames.
- [`scripts/side_stand_scan.py`](../../../scripts/side_stand_scan.py) — window-aware bit scan that surfaced the hit.

## Open

- Engine-on confirmation. Bit position should be unchanged once the engine is up; verify alongside the other engine-on stationary inputs ([[2026-06-18-engine-on-stationary-inputs]]).
- True sensor-to-bus latency. Not measured here (the press-to-flip figure is dominated by rider mistiming / stand travel time). If ever load-bearing for the dashboard, a synthetic ground-truth mark on the stand would pin it down — otherwise the working assumption is "within one `540` broadcast period, like the kill switch".
- `540` D3 hi nibble is unidentified. Stuck at `0x1` throughout this capture; LOW-CARD(4) at engine-on idle ([[signal-gear-position]]). Worth flagging during the engine-on input batch — likely surfaces with mode toggle, ABS state, or warm-up.

See also: [[always-on-broadcast-ids]], [[signal-kill-switch]], [[signal-coolant-temp]], [[ktm-can-decoder]].
