---
date: 2026-07-24
status: success
phase: 2
related:
  findings:
    - can/signal-engine-torque
    - can/signal-throttle-position
  logs:
    - 2026-07-24-torque-throttle-engine-off-3
---

# `121` D0:D1 throttle-conditional jump, key-on / engine-off

## Hypothesis

With ignition on and engine not running, `121` D0:D1 (signed engine torque per [[signal-engine-torque]]) sits at ~+166 as the finding predicts, **but jumps discontinuously to ~−36 at throttle raw = 234** (≈ 92 % grip) and back to +166 at 233. Live-view spot-check on 2026-07-24 shows a single-count sharp threshold, not a proportional response.

The candidate explanation is a **flood-clear / throttle-body service arming state**: KTM/Husqvarna ECUs (and most modern EFI) latch a "no-fuel start" mode when the rider holds WOT during key-on / cranking, so a flooded engine can be cleared. The torque channel would then report the ECU's precomputed "torque the engine would produce right now" for a no-fuel state — which explains the destination value being in the same negative-pumping-loss band (−20 to −30 at 3500–5000 RPM per the torque finding) the engine produces during real overrun.

Competing hypotheses to rule out:
1. **Simple throttle-driven scalar** — some engine-off calibration output that's linear in throttle. Refuted a priori by the sharp 233→234 step, but confirm quantitatively.
2. **Any-throttle-motion mode change** — mode arms on grip movement rather than on a threshold. Refuted if pausing at 200 leaves +166 unchanged for seconds.
3. **Throttle raw wrap / encoding artifact** — 234 is a specific value in the throttle byte, not a threshold in a derived quantity. Refuted if the transition threshold varies across sweeps.
4. **Only-during-arming-window** vs **persistent while key-on** — flood-clear conventionally disarms once the engine cranks and rises above some RPM; here the engine never starts, so the window question is: does the mode toggle *back* off if throttle drops below 234 within the same key-on session, or does it latch?

Whichever wins, the immediate consequence is that `signal-engine-torque.md`'s "stable positive bias engine-off" claim needs a caveat and the ~+166 → −36 flip is either a **mode bit that also lives on the bus** (`121` D2:D3, D4:D6, or a sibling ID) or is only reflected through the torque channel.

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. Side stand down, neutral, kill switch in run. **Engine off throughout**, key on.
- Capture path: wifi-bridge → `scripts/capture.py`. Procedure starts key-on (per project convention).
- Nothing plugged in that mechanically holds the throttle. Rider drives the grip by hand.

## Procedure

The rider can't reliably resolve single throttle counts by hand — but the bus can. `120` D2 broadcasts every 20 ms, so a hand-driven ramp of ~10 s across full travel already samples nearly every raw value on the way through. The procedure leans on that: slow, smooth sweeps rather than metronomic per-count nudges.

1. Start capture: `python scripts/capture.py --port <port> --label torque-throttle-threshold-engine-off`.
2. Wait 10 s key-on-engine-off baseline. Confirm `121` D0:D1 = +166 in live view.
3. `t`, then **slow-sweep pair:** grip 0 → WOT over ~10 s, hold WOT ~3 s, WOT → 0 over ~10 s, hold closed ~3 s. One smooth continuous motion. Repeat this whole pair **three times back-to-back**, so we get three independent up-crossings and three down-crossings of the threshold.
4. `t`, then **latch probe:** snap to WOT in <0.5 s, hold ~5 s, snap closed, hold **10 s** at 0. Watch live view: does `121` D0:D1 return to +166 the moment throttle drops below the threshold, or does it stay at −36?
5. `t`, then **step response:** snap 0 → WOT, hold 2 s, snap 0, hold 2 s. Two repeats. Captures entry/exit latency at the transition.
6. Key off. `q` to stop capture.

Total: 3 `t` presses. The throttle trace itself resolves per-count timing — no per-count marks needed.

## Analysis plan

1. **Threshold verification and hysteresis.** From `120` D2 and `121` D0:D1 co-plotted, extract every up-crossing and down-crossing of `121` D0:D1 through 0 in the slow-sweep phase (three of each). For each crossing, read the concurrent `120` D2 value. Expected: up-crossings all at D2 = 234, down-crossings at some value ≤ 234. Consistent-value across the three sweep pairs argues for a hard threshold; variance ≥ 2 counts argues for something rate- or dwell-conditioned. Any width between up-threshold and down-threshold is the hysteresis band. Zero-width → non-hysteretic gate.
2. **`121` D2:D3 twin-channel response.** The torque finding says D2:D3 tracks D0:D1 within ~1 LSB during real riding. Does D2:D3 also step at the same throttle raw, or does D0:D1 alone respond? If only D0:D1 jumps, the twin-channel semantic breaks in the engine-off regime and needs rewording in [[signal-engine-torque]].
3. **`121` D4:D6 mode-bit hunt.** Across the transition frames, diff `121` D4, D5, D6 pre-flip vs post-flip. Any bit that co-transitions on the same frame as D0:D1 stepping is a candidate mode flag exposed on the bus.
4. **Bus-wide diff at the transition.** For each always-on ID, extract the last frame before and first frame after each D0:D1 flip. Any byte that consistently changes across those transitions is a mode-bit candidate. Prime suspects: `12A`, `12D`, `540`, `541`.
5. **Latency.** Time from `120` D2 first showing 234 (or the up-threshold) to `121` D0:D1 first showing the negative value. At 20 ms broadcast period, expect ≤1 frame if the mode is instantaneous; more if there's ECU debounce.
6. **Latch.** Compare the phase-4 hold-at-0-after-WOT window to the phase-2 initial baseline. If `121` D0:D1 = +166 in the phase-7 window, the mode dis-arms on throttle release. If it stays at −36, the mode latches until key-cycle — that's the flood-clear semantic (arm-and-stay-armed-until-start).

## Expected outcomes

- **Threshold pins to exactly 234 in both directions, no hysteresis, no bus-wide mode-bit siblings, disarms on release** → the mode signal *is* the torque channel; the ECU is computing "engine torque at current inputs assuming no fuel" and 234 is just its throttle-raw cutoff for switching the fuel-cut assumption. Amend [[signal-engine-torque]] with the engine-off throttle-conditional case and move on.
- **Threshold hysteretic and/or latches until key-cycle, mode-bit sibling found** → confirm flood-clear semantic on this ECU. Promote to `docs/findings/can/signal-flood-clear-mode.md` (name TBD), with the sibling bit as the primary state signal and the torque-channel dip as a derived symptom. Consequences for the dashboard: this bit is worth exposing during startup, and its arming behavior is a diagnostic-mode signature we can reuse elsewhere.
- **Threshold varies across sweeps** (e.g. flips at 234 on the way up but 231 on the way down, or at different values on repeat sweeps) → not a simple throttle-raw threshold. Widen the search to derived quantities (throttle rate, dwell time above X) before drawing conclusions.

## Follow-ups

- Update `signal-engine-torque.md` § "Idle behaviour" — the "stable positive bias engine-off" statement isn't wrong but is incomplete; add the throttle-conditional case with a link back here.
- If a mode bit is found: cross-check whether it also appears during engine cranking (not covered by this capture — engine stays off). Would need a separate crank-with-WOT experiment, which has combustion-safety considerations worth thinking about first.
- If the sibling-bit hunt finds an unexpected byte moving: check whether it also moves engine-on, to distinguish "flood-clear mode indicator" from "generic engine-off diagnostic flag".

## Result (2026-07-24)

Capture: [`logs/2026-07-24-torque-throttle-engine-off-3/`](../../logs/2026-07-24-torque-throttle-engine-off-3/) — 31 172 frames over ~113 s (11 unique IDs), three phase marks at 17418.11 / 17500.14 / 17520.77. Re-derivable with `python scripts/torque_throttle_threshold.py`.

**All four hypotheses landed as "simple threshold on the torque channel with entry debounce"** — no sibling mode bit, no latch, no graded response.

### Threshold and hysteresis — hard threshold at `120` D2 = **234**, ~500 ms entry debounce, no exit debounce

Histogram of `121` D0:D1 by throttle raw across the whole capture (n=1 095 frames near the threshold):

| throttle D2 | n | frames at +166 | frames at −36 | intermediate |
|------------:|--:|--------------:|-------------:|-------------:|
| 220-233 | 108 | 104 | 4 | **0** |
| 234 (exactly) | 9 | 4 | 5 | **0** |
| 235-254 | 987 | 12 | 975 | **0** |

D0:D1 takes exactly two values, +166 or −36 — never anything in between. The threshold is `120` D2 ≥ 234 (≈92 % grip). The 4 samples ≤ 233 that read −36 and the 12 samples ≥ 235 that read +166 are all captured within the ~500 ms entry-debounce window as the rider crossed the threshold. That window is the only source of variance in the "throttle at flip" reading — the three phase-1 up-crossings landed at 233 / 233 / 241, mean 235.7 ± 4.6, and the three down-crossings at 230 / 234 / 238, mean 234.0 ± 4.0 — the mean-of-means sits at 234 as the underlying threshold.

### Entry debounce — ~500 ms; exit — immediate

Per crossing (`120` D2 first ≥ 234 → `121` D0:D1 first < 0):

| up-crossing | Δ (throttle-crosses-234 → torque-flips) |
|-------------|--:|
| 1 | 456.7 ms |
| 2 | 495.9 ms |
| 3 | 496.9 ms |

Convergence to ~500 ms is tight enough that this is a real ECU debounce, not sampling noise (at 20 ms broadcast cadence each Δ has 40 ms of quantization tolerance). Exit path is the opposite — the phase-2 recovery from throttle=254 back to 0 (t=5 → t=6 s from mark 2) collapsed D0:D1 from −36 to +166 within the 1-s bin. Fine-grained inspection shows the D0:D1 flip lands in the same 20 ms broadcast as `120` D2 dropping below 234, i.e. ≤ 1 frame of exit latency.

### No latch

Phase 2 was designed to distinguish "mode dis-arms on release" vs "mode latches until key-cycle". After the ~5 s WOT hold, throttle returned to 0 and D0:D1 recovered to +166 within 1 s and stayed there for the full 10-s observation window (bins t=6…t=20 in the analysis output). The mode is dynamic, keyed on current throttle-with-dwell, not a latched state.

### No sibling mode bit anywhere on the bus

`121` D4:D6 bytes on the flip frames — pre and post XOR is `00 00 00` for every up-crossing. Bus-wide diff last-pre / first-post across all 11 broadcast IDs:

| ID | changed bytes | notes |
|----|---------------|-------|
| `120` | D2, D7 | D2 = throttle itself moving; D7 = per-frame CRC per [[byte-d7-cycle-hash]] |
| `121` | D0, D1, D7 | D0/D1 = the flip itself; D7 = CRC |
| every other ID | D7 only | CRC churn — no payload change |

The mode signal *is* `121` D0:D1. Nothing else on the bus co-transitions. There is no separate mode flag we can decode from any other ID or byte during this state.

### `121` D2:D3 — engine-off twin-channel claim is wrong

D2:D3 stays pinned at **exactly +463** across the entire capture, in both the +166 and the −36 state of D0:D1. The current finding's claim that the two channels track within ~1 LSB holds only for the engine-*on* real-riding regime; the "stable positive bias engine-off" line is more nuanced than described. See finding update.

## Interpretation

The pattern — throttle ≥ 92 % with ~500 ms dwell, immediate release-response, no latch, no separate mode flag — is consistent with the ECU continuously computing `121` D0:D1 as "predicted engine torque under the current fuel-and-ignition policy", where the policy switches to a **fuel-cut / flood-clear precondition** at high throttle with dwell. The signature matches KTM/Husqvarna EFI flood-clear arming in every published description (WOT held during key-on = "clear a wet engine on next start") except one: real flood-clear typically latches until the engine either starts or key is cycled. Here it dis-arms freely — either this specific ECU doesn't latch until cranking begins (arming is *predictive* while stationary, *committed* on starter engagement), or the observed signal is a state-preview and the true latch lives inside cranking logic we can't probe without actually starting the engine.

Either way, the practical takeaway for the current finding: the "stable engine-off bias" narrative in `signal-engine-torque.md` needs a caveat, and D0:D1 in the engine-off regime is a **two-state** signal, not a bias.

**Not resolved by this capture:**
- Whether the fuel-cut is actually applied to cranking (not tested; engine stayed off).
- Whether the debounce time (~500 ms) is fixed or scales with something else (e.g. temperature, elapsed key-on time). One capture can't distinguish.
- Whether other engine-off modes exist that this experiment didn't trigger (e.g. throttle-body service test, throttle limp mode, learn cycles).
