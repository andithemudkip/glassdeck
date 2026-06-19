---
date: 2026-06-18
status: success
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/post-kill-decay-groups
    - can/signal-kill-switch
  references:
    - ktm-can-decoder
  experiments:
    - 2026-06-17-payload-diff-idle
  logs:
    - 2026-06-19-kill-switch-toggle
---

# Kill-switch toggle, engine-off — resolve `120` D3 bit 4 polarity vs KTM

## Hypothesis

KTM 690 Enduro R encodes the run/stop kill-switch state at `120` D3 bit 4 with `1` = run, `0` = stop ([`docs/references/ktm-can-decoder.md`](../references/ktm-can-decoder.md)). On this bike, every idle-baseline capture had the kill switch in the run position and `120` D3 reads `0x00` (bit 4 = 0) — the literal opposite of KTM's polarity. Three explanations are possible:

1. **Inverted polarity.** Same byte/bit, opposite sense (0 = run on Husqvarna). Toggling to stop should flip bit 4 from 0 → 1.
2. **Different location on Husqvarna.** Bit 4 is something else entirely; the kill-switch state lives at another (ID, byte, bit).
3. **Latency/edge-only.** The bit isn't broadcast steadily but only at edges. Toggling should produce a transient.

Only one of these can be true. A capture with several clean toggles resolves the question.

This is the most important per-input capture to do first: until we know whether KTM's `120` polarity holds on Husqvarna, every other KTM hypothesis on this bike is suspect by association.

## Setup

- Bike: 2020 Husqvarna Svartpilen 401, side stand down, neutral, **engine off** throughout (do not press starter).
- Key on (position 1) for the whole capture.
- Adapter / wiring / firmware: same as the idle-baseline-x3 runs.
- Host: `scripts/capture.py` with label `kill-switch-toggle`.

## Procedure

1. Key off, plug the adapter in.
2. Start capture: `python scripts/capture.py --port /dev/cu.usbmodem101 --label kill-switch-toggle`.
3. Wait 5 s key-off (bench-blank baseline).
4. Turn key to position 1. Press **space** at the moment of key-on.
5. Wait 30 s for the dash self-test to complete and the bus to reach steady key-on-engine-off state. **Do not press the starter at any point.** Kill switch starts in the **run** position.
6. Toggle the kill switch through this sequence, ~5 s between each press (so the steady-state value is sampled cleanly between transitions), pressing **`k`** at the instant of each flick:
   - run → stop  (`k` at flick)
   - wait 5 s
   - stop → run  (`k`)
   - wait 5 s
   - run → stop  (`k`)
   - wait 5 s
   - stop → run  (`k`)
   - wait 5 s
   - run → stop  (`k`)
   - wait 5 s
   - stop → run  (`k`)
7. Wait a final 10 s in run position.
8. Key off. Wait 2 s. `q` to stop the capture.
9. Fill in `session.md` immediately — note any anomalies (warning light pattern change, dash flicker, neutral lamp behaviour) at any of the flicks.

Six toggles gives three full run→stop→run cycles, enough to distinguish a steadily-broadcast level signal from an edge-only transient and enough to rule out a coincidental flip.

## Analysis plan

Run a window-aware payload diff (extend `scripts/payload_diff.py` or write a small one-off) over the 11 always-on IDs, partitioning frames into the seven event windows (key-on→toggle1, toggle1→toggle2, …, toggle6→key-off):

1. **Primary check:** does `120` D3 bit 4 flip its dominant value between consecutive windows in alternation with the kill-switch state? Tabulate per-window bit value.
2. **Polarity:** which value (0 or 1) corresponds to run vs stop. Compare to KTM.
3. **Other bits in `120` D3:** any other bit that alternates with the toggle pattern. The byte was static `0x00` at idle, but with engine off and kill switch toggling we may see other state surface.
4. **Bus-wide bit scan:** any bit at any (ID, byte, bit) that alternates with the toggle. If `120` D3 bit 4 doesn't move, somewhere else might.
5. **Slow-decay group sanity:** since the kill switch in the run-vs-stop sense (engine off) is conceptually different from "kill while running" (which we already characterised in [`findings/can/post-kill-decay-groups.md`](../findings/can/post-kill-decay-groups.md)), confirm that all 11 IDs continue broadcasting throughout the capture — no module should power down from a switch flick alone with key still on.

## Expected outcomes

- **Bit toggles cleanly at `120` D3 bit 4** with polarity 0 = run, 1 = stop → write [`docs/findings/can/signal-kill-switch.md`](../findings/can/signal-kill-switch.md) at `confirmed`, note inverted polarity vs KTM as a Husqvarna ECU quirk.
- **Bit toggles cleanly at `120` D3 bit 4** with polarity 1 = run, 0 = stop → the engine-off idle-baseline captures had bit 4 = 0 but kill was supposedly in run; means the baseline session.md is wrong about kill-switch position, or we misread the schematic. Investigate before writing a finding.
- **Bit toggles cleanly at some other (ID, byte, bit)** → write the finding there, note KTM disagreement explicitly in [`docs/references/ktm-can-decoder.md`](../references/ktm-can-decoder.md).
- **No bit toggles cleanly** with the switch → either the kill signal is encoded across more than one bit, or it's an edge-only transient not picked up by window-statistics. Look at frame-by-frame diffs in a 200 ms window around each `k` mark.

## Result

Capture: [`logs/2026-06-19-kill-switch-toggle/`](../../logs/2026-06-19-kill-switch-toggle/) — 30 289 frames, 11 always-on IDs, 6 `k` event marks.

Analysed with [`scripts/kill_switch_scan.py`](../../scripts/kill_switch_scan.py), which partitions the capture into the 7 toggle windows (alternating RUN/STOP starting from RUN), trims 300 ms after each flick for debounce / propagation, and scans every (ID, byte, bit) for a bit whose dominant value alternates in lockstep with the windows at ≥ 0.95 per-window purity.

**Exactly one bit matched:** `541` D2 bit 4. Per-window pattern `1,0,1,0,1,0,1`, purities all ≥ 0.99. Polarity: 1 = RUN, 0 = STOP.

`120` D3 bit 4 (the KTM hypothesis) read `0` in every frame of every window — engine-off RUN included. **`120` D3 carries no kill-switch state on Husqvarna.**

Side-observation: with key on and the kill switch in STOP, every ID in the Fast post-kill-decay group ([[post-kill-decay-groups]]) dropped to ~5 – 6 % of its RUN broadcast rate. The Slow group's rates were unchanged. Details in [`docs/findings/can/signal-kill-switch.md`](../findings/can/signal-kill-switch.md) under "Side-finding: Fast-group throttling at kill = STOP".

## Interpretation

- The KTM 690 → Husqvarna 401 mapping breaks at `120` for kill-switch state. **Polarity is preserved** (1 = run); **location is not**. The mechanism is plausibly that `120`'s source module isn't broadcasting reliably while the kill switch is in STOP, so the platform moved (or always kept) the kill-switch signal on `541` instead — which is in the Slow group and stays up across both states.
- This is the first concrete cross-platform location delta within the always-on broadcast set (the coolant-temp ±1 byte was a delta within the same ID; this is a different ID entirely).
- Outcome #1 from the Hypothesis section is partially right (polarity is opposite of what idle-baseline suggested for `120` D3) but the more interesting answer was outcome #3-shaped: the bit lives elsewhere.

## Follow-ups

- [x] Write [`docs/findings/can/signal-kill-switch.md`](../findings/can/signal-kill-switch.md) at `confirmed`.
- [x] Update [`docs/references/ktm-can-decoder.md`](../references/ktm-can-decoder.md) with the Husqvarna delta: kill-switch is `541` D2 bit 4, not `120` D3 bit 4. Polarity matches.
- [x] Fold the Fast-group-vs-kill-state observation into [`docs/findings/can/post-kill-decay-groups.md`](../findings/can/post-kill-decay-groups.md). On re-analysis the "throttled rate" reading was wrong: every Fast-group frame in every STOP window of this capture landed in the first second after the toggle, with seconds 1–5 flat zero. It's the same post-kill decay tail as the engine-on case, not a different steady-state. The finding now reads: kill = STOP triggers the Fast-group decay regardless of engine state.
- [ ] Engine-on kill press (kills a running engine) is a separate path from engine-off kill toggling. Worth a single brief capture to confirm `541` D2 bit 4 still carries the signal in that case.
- The window-aware bit-scan template generalises directly to the other engine-off captures (throttle sweep, gear shift, clutch, side stand). `kill_switch_scan.py` can be reused with different event labels.
- This capture's first 25 s (key-on settle, kill in RUN, no inputs) is a clean engine-off-only baseline if a future analysis wants one separate from the idle baseline.
