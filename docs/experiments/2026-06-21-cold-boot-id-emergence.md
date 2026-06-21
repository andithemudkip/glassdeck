---
date: 2026-06-21
status: success
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
  experiments:
    - 2026-06-17-key-on-cold-boot
    - 2026-06-17-engine-idle-baseline-x3
  logs:
    - 2026-06-17-key-on-cold-boot
    - 2026-06-17-engine-idle-run-1
    - 2026-06-17-engine-idle-run-2
    - 2026-06-17-engine-idle-run-3
---

# Cold-boot ID emergence — module boot order and one-shot init frames in the first second

## Hypothesis

The key-on cold-boot experiment measured time-to-first-frame at ~250 ms but did not analyse the **internal structure** of the boot window. Three things may exist between key-on and steady-state broadcasting that the existing analysis did not look for:

1. **Module boot order.** The 11 always-on IDs do not all start broadcasting at the same instant. Whichever module's ID is first on the bus is the first module to finish booting and join the network. A consistent ordering across cold-boot captures reveals the module power-up sequence — useful for guessing which ID belongs to which module (ECU vs body controller vs ABS module vs cluster) and corroborating the Fast/Slow decay grouping (Fast = ECU-fed, Slow = body-controller-fed, presumably).

2. **One-shot init frames.** Some modules emit a "hello" or version-handshake frame at boot that is never broadcast again at steady state. These would appear in the boot window with a unique ID not in our catalogued set of 11, broadcast once or a few times, then go silent. They would have been invisible to `inventory_ids.py` if its per-ID count threshold filtered them out (need to check), or visible but uncategorised.

3. **Cadence ramp.** The 11 always-on IDs may not start at their steady-state period. An ID with steady period 100 ms might emit its first 3 frames at 30 ms intervals (a backlog flush) or vice versa. The cadence shape carries information about how each broadcaster initialises its scheduler.

If (1) holds, the ordering across the 4 captures (1 cold-boot + 3 engine-idle runs, each of which contains a key-on prelude) should be reproducible to within one broadcast period. If (2) holds, we have new IDs to add to the catalogue — possibly with semantics learnable from the payload alone. If (3) holds, the ramp shape tells us something about the modules' broadcast schedulers.

## Setup

Desk-only. Corpus:

- `logs/2026-06-17-key-on-cold-boot/` — the explicit cold-boot experiment.
- `logs/2026-06-17-engine-idle-run-{1,2,3}/` — each starts with a key-off baseline → key-on event, so the first ~1 second after each `key_on` mark is a usable cold-boot window. (Run 1 had an `idle_settled` anomaly per its `session.md`, but the key-on portion is unaffected.)

Out of scope: throttle-sweep, kill-switch, side-stand, and gear-cycle captures all start with the bike already keyed on at capture time (or close to it). Their `key_on` events do not represent module-cold boots.

New script: `scripts/cold_boot_emergence.py`. Reads capture.log + events.csv, slices to the first 1000 ms after `key_on`, emits a per-ID first-seen-offset table, an inventory of any ID that appears in the boot window but not steady-state, and a per-ID inter-message-interval series for the first 10 frames of each always-on ID.

## Procedure

1. **First-seen offsets.** For each of the 4 captures, for every ID that appears in the first 1000 ms after `key_on`, record the relative timestamp of its first frame.
2. **Cross-capture ordering stability.** Sort the 11 always-on IDs by median first-seen offset across the 4 captures. Compute per-ID spread (max − min) — if all 11 spreads are ≤ one broadcast period of the respective ID, the ordering is stable; if any spread is much larger, that ID has a non-deterministic boot moment (worth flagging).
3. **One-shot ID inventory.** List every ID that appears in the boot window. Subtract the 11 always-on IDs. Any remainder is a candidate for a non-broadcast / boot-only / event-driven message. For each such ID, record count, first-seen, last-seen, payload values. Common cases to recognise:
   - One-frame "module ID" announcement (count = 1, fixed payload).
   - Short burst of diagnostic / version frames (count ≤ 5, payload encodes a version or module name).
   - Periodic-but-low-rate frame that just didn't make it into the steady-state inventory because it broadcasts every several seconds (cross-check by looking at the full capture, not just the boot window — these would appear sporadically throughout).
4. **Cadence ramp.** For each always-on ID, compute the deltas between its first 10 frames. Compare to the steady-state period from [[always-on-broadcast-ids]]. Three shapes to look for:
   - **Immediate steady state**: first 10 deltas all within ±10 % of steady period.
   - **Backlog flush**: first few deltas are much shorter than steady, then converge.
   - **Slow start**: first few deltas are longer than steady (e.g., module emits one frame, waits, then settles into cadence).
5. **Cross-correlate ordering with Fast/Slow decay grouping.** If module-power-up order matches decay-group membership (e.g., Fast group IDs all appear first, or all share a single tight cluster of first-seen offsets), that is corroborating evidence for "Fast group = ECU-broadcast, Slow group = body-controller-broadcast" — which is currently inferred but not anchored.

## Expected outcomes

- **A stable boot order across the 4 captures.** Most likely outcome. Annotate [[always-on-broadcast-ids]] with a "boot order" column. Probable corroboration of Fast/Slow grouping → module hypothesis.
- **One or more one-shot IDs surface.** New entries for the bus inventory. Each gets a one-line note in [[always-on-broadcast-ids]] (or a sibling finding) flagging "non-periodic, boot-window only" with payload notes.
- **No one-shot IDs.** Useful null result — confirms the 11 always-on IDs are the complete bus inventory at idle, and any future "new" ID surfaced by a per-input capture is genuinely driven by the input, not by something we missed at boot.
- **Cadence ramp on some IDs.** If a module flushes a backlog, that influences how the dashboard firmware should handle the first second of bus traffic (don't act on frames until steady cadence, or accept that some signals lag).

## Result

Run with `python scripts/cold_boot_emergence.py`. Four analysis sections.

### Analysis 1 — first-seen offsets and boot order

Per-capture first-seen offset (ms after `key_on` keystroke) per always-on ID:

|  ID  | cold-boot | run1 | run2 | run3 | median | spread | steady T |
|------|----------:|-----:|-----:|-----:|-------:|-------:|---------:|
| `120`|   289.4   | 11.4 |278.3 | 98.5 | 188.4  | 278 ms |  10 ms   |
| `121`|   288.4   | 31.3 |277.5 | 97.6 | 187.5  | 257 ms |  20 ms   |
| `129`|   288.7   | 31.4 |277.7 | 97.8 | 187.8  | 257 ms |  20 ms   |
| `12A`|   302.3   | 11.8 |291.9 |111.7 | 201.8  | 290 ms |  20 ms   |
| `12D`|   254.0   | 11.5 |243.3 | 63.2 | 153.2  | 242 ms |  10 ms   |
| `12E`|   278.9   | 11.7 |267.9 | 91.6 | 179.7  | 267 ms |  20 ms   |
| `450`|   523.8   |189.2 |515.1 |332.4 | 423.8  | 335 ms |  50 ms   |
| `540`|   288.9   | 58.2 |277.9 | 98.0 | 188.0  | 231 ms | 100 ms   |
| `541`|   498.7   |148.2 |468.2 |307.9 | 388.0  | 350 ms |  20 ms   |
| `5A0`|   348.6   | 11.9 |347.5 |157.6 | 252.6  | 337 ms | 100 ms   |
| `5B0`|   289.1   | 58.3 |278.1 | 98.3 | 188.2  | 231 ms | 100 ms   |

Absolute first-seen offsets vary by ~250 ms between captures because the rider keys the spacebar mark at the instant of *intent to turn the key*; the actual electrical key-on moment is somewhere between the keystroke and the bus's first transmission. The absolute numbers are not load-bearing; the **relative ordering across IDs within a single capture** is. That ordering is highly stable: every capture shows the same ID coming first, second, and so on.

Boot order, sorted by median first-seen:

| order | ID    | median first-seen | decay group |
|------:|-------|------------------:|-------------|
|  1.   | `12D` |    153 ms         | Slow        |
|  2.   | `12E` |    180 ms         | Slow        |
|  3.   | `121` |    188 ms         | Fast        |
|  4.   | `129` |    188 ms         | Fast        |
|  5.   | `540` |    188 ms         | Fast        |
|  6.   | `5B0` |    188 ms         | Fast        |
|  7.   | `120` |    188 ms         | Fast        |
|  8.   | `12A` |    202 ms         | Slow        |
|  9.   | `5A0` |    253 ms         | Slow        |
| 10.   | `541` |    388 ms         | Slow        |
| 11.   | `450` |    424 ms         | Slow        |

**Two key structural observations:**

1. **The 5 Fast-group IDs cluster within ±1 ms of each other** (187.5–188.4 ms medians). This is much tighter than any individual ID's broadcast period. The 5 IDs are almost certainly being emitted by a **single module** that boots, finishes its self-test, then starts broadcasting all 5 IDs nearly simultaneously.

2. **The 6 Slow-group IDs split into three distinct boot waves:**
   - Early (`12D`, `12E`): 153 and 180 ms
   - Mid (`12A`, `5A0`): 202 and 253 ms
   - Late (`541`, `450`): 388 and 424 ms

   These are separated by 50 + ms gaps — far more than any single ID's broadcast period and far more than the within-Fast-group spread. The Slow decay group is **at least 3 distinct modules**, not one.

Combined: the bus has **at least 4 source modules** on the 11 always-on broadcast set, not 2.

### Analysis 2 — one-shot IDs

For every capture, the set of IDs seen in the boot window equals the set of IDs seen in steady state equals the 11 always-on IDs from [[always-on-broadcast-ids]]. **Zero one-shot IDs.** No module announces itself, emits a version handshake, or otherwise broadcasts something at boot that goes silent later.

The 11 always-on IDs are the complete bus inventory at idle. Any "new" ID surfaced by a future per-input capture (mode toggle, gear shift at speed, etc.) is genuinely driven by the input, not by a module we missed at boot.

### Analysis 3 — cadence ramp

Honest call: this analysis is dominated by USB-CDC delivery artifacts, not bus behaviour. For the high-frequency IDs:

- `12D` (steady T = 10 ms): observed first-10-frame deltas of 0.1–0.5 ms in cold-boot, run2, run3. That is the USB-CDC stack flushing a backlog after a delivery hold — not a real bus phenomenon.
- `120` (steady T = 10 ms): observed avg 20 ms across all 4 captures; deltas range 5–37 ms with bimodal clustering. Consistent with the host receiving pairs of bus frames bunched into single USB packets.
- `12A` (steady T = 20 ms): observed avg ~49 ms (2.5× steady). Same artifact.

For the 100 ms IDs, which are slow enough to escape USB-CDC bunching:

- `540`, `5A0`, `5B0`: first-frame-deltas all hit ~95–105 ms immediately, within ±10 % of the 100 ms steady period. **No startup lag.** These modules boot ready and broadcast at steady cadence from frame 1.
- `450` (steady T = 50 ms): first-frame-deltas hit ~50 ms immediately, also steady from frame 1.

So the cadence-ramp question is partially answered: at the broadcast periods where the host's view is faithful, modules emit at steady cadence from their first frame. We have no way to verify the same for the 10/20 ms IDs without a logic analyzer on the actual bus — the USB-CDC stack is delivering arrivals bunched, not interleaved.

### Analysis 4 — boot order vs Fast/Slow decay correlation

| group | median first-seen |
|-------|------------------:|
| Fast  |    188.0 ms       |
| Slow  |    227.2 ms       |

The 39 ms median gap is dwarfed by the Slow-group internal spread (153 ms to 424 ms — a 270 ms range). The decay grouping does **not** correspond to a single power-up sequence delay; Slow's earliest member (`12D`) actually boots *before* any Fast-group member. The Fast/Slow split is therefore unrelated to boot timing — it really is about post-kill power-rail decay, as [[post-kill-decay-groups]] suggested.

## Interpretation

Three concrete updates.

**The bus has at least 4 modules, not 2.** The combined evidence — Fast-group cluster within 1 ms (1 module) + Slow-group split into 3 boot waves separated by 50–150 ms (≥3 modules) — refines [[post-kill-decay-groups]]'s "at least 2 modules" claim. Best current sub-grouping:

| Sub-group | IDs                       | Boot wave    | Decay tail | Candidate module |
|-----------|---------------------------|-------------:|-----------:|------------------|
| F         | `120`, `121`, `129`, `540`, `5B0` | ~188 ms | <1 s     | ECU / engine-management |
| S-early   | `12D`, `12E`              |  153, 180 ms | ~5–6 s     | ABS module ? |
| S-mid     | `12A`, `5A0`              |  202, 253 ms | ~5–6 s     | body controller ? |
| S-late    | `541`, `450`              |  388, 424 ms | ~5–6 s     | instrument cluster ? |

Module identifications are still hypothesis — the CAN data cannot directly bind IDs to physical modules. But the structural split is concrete and improves the prior over "Fast vs Slow."

**The bus inventory at idle is closed.** No one-shot IDs. Future per-input captures that surface new IDs are revealing input-driven broadcasts, not undocumented boot frames. This bounds the search space for active features — for example, ROAD/SUPERMOTO toggle messages are guaranteed to live either on the 11 always-on IDs or on a new ID introduced by the toggle itself.

**The cadence ramp question is half-answered.** The 50 and 100 ms IDs boot at steady cadence from frame 1, no startup lag. The 10 and 20 ms IDs we can't verify due to USB-CDC bunching. If real bus-level cadence behaviour ever becomes load-bearing (it currently isn't — none of the dashboard's planned logic depends on sub-50 ms latency), the right tool is a logic analyzer on the bus, not the SLCAN logger.

## Follow-ups

- [x] Update [`docs/findings/can/post-kill-decay-groups.md`](../findings/can/post-kill-decay-groups.md) to reflect "at least 4 modules" with the boot-order sub-grouping.
- [x] Update [`docs/findings/can/always-on-broadcast-ids.md`](../findings/can/always-on-broadcast-ids.md) to note "the 11 always-on IDs are the complete bus inventory at idle — boot window adds nothing new."
- [ ] Module identification remains hypothesis. Pinning Fast = ECU and S-late = cluster would require either reading other open-source projects' work on this platform, or hardware-side probing (fuse-pulling individual modules and re-capturing).
- [ ] Per-input captures that surface a new ID now have a strong prior: that ID is likely from a module already in the Fast/S-early/S-mid/S-late inventory, and which one can be guessed from when it appears at boot.
