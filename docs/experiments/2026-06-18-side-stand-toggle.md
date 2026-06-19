---
date: 2026-06-18
status: success
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/post-kill-decay-groups
    - can/signal-side-stand
  references:
    - ktm-can-decoder
  experiments:
    - 2026-06-17-payload-diff-idle
  logs:
    - 2026-06-19-side-stand-toggle
---

# Side-stand toggle, engine off — decode `540` D4 bit 0

## Hypothesis

KTM 690 encodes side-stand (kickstand) state at `540` D4 bit 0 with `1` = stand raised, `0` = stand down. At idle our `540` D4 was static `0x00` — consistent with the bike sitting on the side stand. Lifting the stand should flip bit 0 to 1; lowering it should flip it back.

This is the simplest of the engine-off captures (one input axis, two states, no rider coordination beyond moving the stand). It also doubles as a sanity test for the `540` ID more broadly — `540` already carries coolant temperature and probably gear, and is on a slow-decay (likely body-controller) module. The side-stand sensor is one of the bike's safety interlocks, so its broadcast latency matters for confirming the bike's logic.

## Setup

- Bike: 2020 Husqvarna Svartpilen 401, **engine off**, neutral, key on (position 1), kill switch in run.
- **The bike must be physically supported throughout** since the side stand will spend time raised. A second person holding the bike upright is fine; a centre stand or paddock stand is better; do **not** attempt this alone without something holding the bike.
- Adapter / firmware / host as before.

## Procedure

1. Start capture: `python scripts/capture.py --port /dev/cu.usbmodem101 --label side-stand-toggle`.
2. 5 s key-off baseline.
3. Key on, press **space**, settle 30 s with stand down.
4. Toggle the side stand through this sequence, pressing the literal **`j`** key (unmapped; capture.py records it verbatim — chosen to evoke "jiffy stand") at the instant the stand reaches the new position:
   1. Down → up. `j`. Hold 5 s.
   2. Up → down. `j`. Hold 5 s.
   3. Down → up. `j`. Hold 5 s.
   4. Up → down. `j`. Hold 5 s.
   5. Down → up. `j`. Hold 5 s.
   6. Up → down. `j`. Hold 5 s.
5. Stand left **down** at the end (its rest position; do not key off with the stand up).
6. Key off. Wait 2 s. `q`.
7. `session.md` — note any dash reaction (a kickstand icon, an interlock warning), any sense of switch chatter (a flaky microswitch could produce a noisy bit), and whether the bike was on its side stand vs being held.

Three full down-up-down cycles is enough to distinguish a clean level bit from an edge transient and to characterise any debounce.

## Analysis plan

1. **`540` D4 bit 0.** Per-window mode value (six 5-second held windows alternating down/up). Expect strict alternation: 0/1/0/1/0/1 or 1/0/1/0/1/0.
2. **Polarity.** Confirm 1 = up vs the KTM 1 = up. If inverted, note explicitly — adds another data point to "is KTM polarity reliable on Husqvarna" alongside the kill-switch finding.
3. **Latency.** Look at frames in the 200 ms window around each `j` mark. `540` broadcasts at 100 ms — so the bit should flip within at most one broadcast period (~100–200 ms) of the physical toggle.
4. **Chatter / debounce.** Within each "held" window, check for any short-lived bit flips (debounce events from a worn microswitch). Note if present.
5. **Other bits in `540` D4.** D4 was STATIC `0x00` at idle. Any other bit moving with the stand is a secondary finding.
6. **Bus-wide bit scan** as in the other engine-off experiments — any bit anywhere that alternates with the toggle pattern is worth flagging, even though `540` D4 is the only KTM-hypothesised target.

## Expected outcomes

- **Clean toggle at `540` D4 bit 0, polarity = KTM** → [`docs/findings/can/signal-side-stand.md`](../findings/can/signal-side-stand.md) at `confirmed`.
- **Clean toggle, polarity inverted** → same finding, note the polarity flip. Combined with kill-switch result (if also inverted), the Husqvarna pattern is "KTM bit positions hold but polarity may flip" — a useful general rule for future hypotheses.
- **No toggle at `540` D4 bit 0** → search the bus for the actual location. KTM and Husqvarna may differ here.
- **Chatter detected** → log it. The dashboard's interlock logic will need to know whether the bike's broadcast bit is debounced or raw.

## Result

Capture: [`logs/2026-06-19-side-stand-toggle/`](../../logs/2026-06-19-side-stand-toggle/) — 28 943 frames, 11 always-on IDs, 6 `j` event marks. Bike on a paddock stand; kickstand icon on the cluster tracked the stand state visibly; no anomalies.

Analysed with [`scripts/side_stand_scan.py`](../../scripts/side_stand_scan.py), which partitions the capture into the 7 toggle windows (alternating DOWN/UP starting from DOWN), trims 1.2 s after each flick to clear the press-to-flip latency (see below), and scans every (ID, byte, bit) for a bit whose dominant value alternates in lockstep with the windows at ≥ 0.95 per-window purity.

**Exactly one bit matched:** `540` D3 bit 0. Per-window pattern `0,1,0,1,0,1,0`, purities all `1.00`. Polarity: 0 = DOWN, 1 = UP. The dominant D3 byte alternates `0x10` ↔ `0x11`; bit 4 (`0x10`) is unchanged across both states, consistent with the idle-baseline `payload-diff` reading of D3 = STATIC `0x10` on a bike sitting on its side stand (bit 0 = 0 = down).

`540` D4 bit 0 (the KTM hypothesis) read `0` in every frame of every window. **`540` D4 carries no side-stand state on Husqvarna**; D4 stays `0x00` throughout the capture.

### Press-to-flip lag is rider mistiming, not bus latency

The latency probe (first `540` frame after each `j` whose D3 bit 0 differs from the pre-toggle dominant) returned 597 – 986 ms across the six toggles. **This is not a bus property** — the rider keyed `j` at the moment of *intent* to flick the stand, and the foot-/hand-driven travel of the kickstand itself takes that long to complete. The actual sensor-to-bus latency is not measured here and is presumed comparable to the kill switch (within one `540` broadcast period, ~100 ms). The 1.2 s post-toggle head trim in the analysis script is there to clear those stale-state frames before the steady-state purity check — not because the bus is slow.

| toggle | direction       | press-to-flip |
|--------|-----------------|--------------:|
| j[0]   | DOWN → UP       |      986 ms   |
| j[1]   | UP   → DOWN     |      641 ms   |
| j[2]   | DOWN → UP       |      828 ms   |
| j[3]   | UP   → DOWN     |      597 ms   |
| j[4]   | DOWN → UP       |      697 ms   |
| j[5]   | UP   → DOWN     |      612 ms   |

## Interpretation

- KTM 690 → Husqvarna 401 cross-walk: location shifts D4 → D3 (one byte earlier), polarity preserved (1 = up). This is the second "byte-position shifts ±1 within the same ID" delta on `540` — the first was coolant temperature at D5/D6 here vs D6/D7 on KTM ([[signal-coolant-temp]]). `540`'s byte layout is **systematically shifted one byte earlier** versus KTM, at least for these two signals. Worth checking the next time another `540` signal is hypothesised.
- Polarity continues to match KTM. So far on this bike: kill switch (KTM polarity OK, location moved to a different ID), side stand (KTM polarity OK, location moved within the same ID). **No inverted-polarity case has surfaced yet**; the working assumption is now "Husqvarna preserves KTM polarity but may relocate the bit".
- The `540` D3 byte is now ~half characterised: bit 0 = side stand, bit 4 = something else that is static-1 at key-on (engine off) and stayed static-1 across all 7 windows. A future capture varying other engine-off inputs may surface what bit 4 of D3 represents.
- Side-stand state is broadcast steadily on `540` (100 ms period) in both states — no rate change, no dropout. The signal is observable at all times the bus is up, same as the kill switch.

## Follow-ups

- [x] Write [`docs/findings/can/signal-side-stand.md`](../findings/can/signal-side-stand.md) at `confirmed`.
- [x] Update [`docs/references/ktm-can-decoder.md`](../references/ktm-can-decoder.md): side-stand is `540` D3 bit 0 on Husqvarna (KTM has D4 bit 0). Polarity matches.
- [ ] Confirm with engine running — included implicitly in the engine-on stationary batch ([[2026-06-18-engine-on-stationary-inputs]]); the bit should remain at `540` D3 bit 0 and not be re-routed once the engine is up.
- [ ] Sensor-to-bus latency. Not measured here — the press-to-flip figure is dominated by rider mistiming and stand travel time. If we ever need a real number (e.g., to validate dashboard interlock logic against the OEM cluster's response time), the cheapest path is a synthetic ground-truth mark on the stand fed into a free GPIO; until then the working assumption is "within one `540` broadcast period, like the kill switch".
- [ ] Bit 4 of `540` D3 is unidentified. It is static-1 throughout this capture and was static-1 in idle baselines too. Note for the bus-wide bit catalogue.

A finding for side-stand state. Combined with the kill-switch finding, this covers the bike's two basic safety-interlock signals on the bus (still missing: clutch state — deferred to engine-on; gear-position N detection — confirmed via [[signal-gear-position]]).
