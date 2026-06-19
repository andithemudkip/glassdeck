---
date: 2026-06-18
status: planned
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/post-kill-decay-groups
  references:
    - ktm-can-decoder
  experiments:
    - 2026-06-17-payload-diff-idle
  logs: []
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

## Follow-ups

- A finding for side-stand state. Combined with the kill-switch finding, this completes the bike's basic safety-interlock surface on the bus.
- If polarity matches KTM here but is inverted on the kill switch (or vice versa), update [`docs/references/ktm-can-decoder.md`](../references/ktm-can-decoder.md) with the per-signal polarity status — Husqvarna polarity is signal-specific, not module-wide.
