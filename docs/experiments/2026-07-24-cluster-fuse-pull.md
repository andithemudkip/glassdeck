---
date: 2026-07-24
status: planned
phase: 1
related:
  findings:
    - can/signal-ride-mode
    - can/byte-d7-cycle-hash
    - can/always-on-broadcast-ids
  references:
    - svartpilen-401-repair-manual
  experiments:
    - 2026-07-24-abs-mode-toggle
  decisions: []
  logs: []
---

# Fuse 2 pull — cluster CAN ownership test

## Hypothesis

Pulling fuse 2 (dedicated "combination instrument" per the 401 repair manual) removes power from the cluster. If the cluster's CAN transceiver is fed from fuse 2, that removes the cluster from the bus. Watching which of `12A` / `450` disappears in the fuse-out window resolves [[signal-ride-mode]]'s command-direction open — specifically whether either mirror bit is cluster-published.

Four possible outcomes, ranked most-to-least likely:

1. **Fuse 2 is display-only** — cluster stays on CAN, both `12A` and `450` continue broadcasting. Informative-null: fuse 2 doesn't feed the CAN transceiver on this bike (or the cluster has a redundant power feed from fuse 7). We learn nothing about ownership, but we learn that fuse 2 isn't a viable ownership probe. Next step becomes ABS-module-connector disconnect or TX probe.
2. **`450` disappears, `12A` continues** — cluster publishes `450`; ABS ECU (or ECU) publishes `12A` as its own state broadcast, mirroring what it reads from `450`. Confirms the "cluster commands, ABS mirrors" model. TX probe target = `450`.
3. **`12A` disappears, `450` continues** — cluster publishes `12A`. Surprising given [[signal-abs-lamp]] treats `12A` as ABS-family, but possible if cluster also publishes some ABS-related state. Would force a re-read of the abs-lamp finding.
4. **Both disappear** — cluster publishes both mirrors (weird — they'd have no reason to be two separate broadcasts from one module). Or fuse 2 takes down more than the cluster (repair-manual error / undocumented shared feed).

Bonus: whichever bike-side IDs disappear (regardless of the two mirrors) tell us which arbitration IDs the cluster publishes generally. Useful for future ownership questions.

## Setup

- Bike: 2020 Husqvarna Svartpilen 401. **Key ON, engine OFF**, kill switch RUN, neutral, side stand down. Rider off the bike (seat unweighted) — no menu work needed since dash will be dark for most of the session.
- Wifi-bridge is bike-powered via fuse 7 (per [[project-wifi-bridge-ota]] and repair manual — diagnostics connector is on fuse 7, not fuse 2). Fuse 2 pull does *not* affect our capture rig.
- Passenger + rider seats need to come off to reach the fuse box (per repair manual). Do that before starting capture.
- Camera / phone video pointed at the dash through the session — captures the visual behavior at fuse-pull (cluster goes dark) and at fuse-reinsert (cluster reboots, self-test, warning-lamp state). Useful narration for `session.md` and cross-check against any post-experiment DTCs.

**Risks and considerations:**

- Cluster is a display + button module — no motors, no solenoids, no inductive loads. Hot fuse pull is electrically safe. Comparable in risk to the ground-disconnect ABS fault procedure the rider already uses.
- Dash goes dark on fuse pull. Speedometer, warning lamps, mode indicator all off. **Bike must remain stationary** for the fuse-out window — no way to see speed or fault state.
- **The ABS ECU (or ECU) may trigger a "cluster communication lost" DTC** during the fuse-out window if the cluster normally broadcasts a heartbeat message. Clearing this may require a normal key-cycle or the rider's known fault-clear procedure. Note in `session.md` whether any warning lamps stay lit after fuse reinsertion.
- If the cluster stays alive after fuse pull (outcome 1), we've done a benign experiment with no side effects.

## Procedure — freeform (no YAML)

Single fuse pull with clear before / during / after windows. No timed steps — pace based on the dash's visual behavior.

1. Key OFF. Remove passenger seat + rider seat. Verify fuse 2 is the 10 A "combination instrument" fuse (per repair manual — position 2 in the main fuse box under the seat, next to fuses 1 [not assigned] and 3 [power relay]). Have spare 10 A on hand if the pull-out damages the fuse (unlikely with a fuse puller).
2. Wifi-bridge boots when key is next turned on — no capture prep needed beyond having `bin/capture-wifi-bridge` ready.
3. Turn key ON. Start capture: `bin/capture-wifi-bridge cluster-fuse-pull`. Let ABS self-test complete (~4 s of dash startup animation), then 60 s of clean baseline while everything is healthy. Mark: "baseline (cluster healthy)".
4. Pull fuse 2. Cue on the operator screen (or a mental countdown) so the mark lands at the pull moment. Mark: "fuse 2 out".
5. Sit stationary for 60 s. Watch the dash: does it go dark instantly, partially dim, or stay lit? Note in session.md.
6. Reinsert fuse 2. Mark: "fuse 2 back in". Watch the dash come back — does it re-do the self-test, or resume mid-state? Any warning lamps that weren't on before?
7. 30 s of post-recovery data.
8. Key OFF. End capture.

`session.md` — log the fuse pull-out timestamp visually confirmed (dash-goes-dark moment) if it differs from the operator mark; describe the dash behavior at pull and at reinsert; note any lingering warning lamps; describe any DTC-like dash indicators (flashing patterns, fault codes if visible).

## Analysis plan

Simple ID-presence diff across the three windows.

1. **`bin/analyze` or equivalent inventory across three windows** (baseline / fuse-out / recovery):
   - For each of the 11 always-on IDs, count frames per window and derive per-window fps.
   - Any ID whose fps drops from ~20 (or its normal period) to ~0 in the fuse-out window is cluster-published.
2. **Specific check on `12A` and `450`**: same diff, but with emphasis. Report:
   - `12A`: fps baseline → fuse-out → recovery
   - `450`: fps baseline → fuse-out → recovery
   Both intact = neither is cluster-published (outcome 1). One disappears = it's cluster-published (outcome 2 or 3). Both disappear = both are cluster (outcome 4).
3. **Bit-level check on the mode bits during fuse-out** (only if their carrier IDs continue): does `12A` D2 b1 stay at its baseline value (0 = ROAD), or does the surviving module change its published state when it loses its counterpart's broadcast? If it holds, the surviving module has independent state; if it goes to a default or off, the surviving module was mirroring the other.
4. **Bonus ID inventory**: which OTHER IDs disappear in the fuse-out window? Any always-on ID that vanishes when the cluster loses power is cluster-published — this may attribute other mystery IDs (`541`? `5B0`?) for free.
5. **Frame rate anomalies on surviving IDs**: if any surviving ID's rate drops significantly during fuse-out, that suggests the cluster was contributing something to that ID's broadcast (unlikely on CAN, but worth noting).

## Expected outcomes

- **Most likely (outcome 1)**: fuse 2 is display-only, both `12A` and `450` continue at normal rate. Cluster's CAN participation is fed from fuse 7 (shared with ABS + diag connector). Test tells us "fuse 2 is not the right pull target"; next step is ABS-module-connector disconnect or TX probe.
- **Second most likely (outcome 2)**: `450` disappears. Confirms `450` = cluster-published, resolves [[signal-ride-mode]] command direction, TX probe unlocked with `450` as the target.
- **Less likely (outcome 3 or 4)**: `12A` disappears alone, or both disappear. Would force revisions to `signal-abs-lamp` (which currently treats `12A` as ABS-family) and/or the fuse topology in the repair manual.

## Follow-ups

- **On outcome 1**: draft the ABS-module-connector-disconnect experiment as the next passive ownership probe. Riskier physically (finding the connector, potential water ingress if it's in an exposed location) but electrically definitive.
- **On outcome 2**: [[signal-ride-mode]] Open section can be updated to remove the "cluster vs ECU-family" ambiguity. Draft the TX probe experiment with `450` as the spoof target and the ADR authorizing that specific message.
- **On outcome 3**: rewrite the [[signal-abs-lamp]] "5 bits, one signal?" open question — if `12A` is cluster-published, the ABS-lamp bits on `12A` are the cluster's re-broadcast of what it reads from the ABS ECU (probably on `12E`, which stays alive).
- **Regardless of outcome**: any additional IDs identified as cluster-published (bonus from step 4) get noted in [[always-on-broadcast-ids]] as attributed to the cluster.
- **DTC follow-up**: if the fuse-out triggered any persistent warning lamps, note the clear procedure that worked. Adds to [[husqvarna-community-notes]] if unusual.
