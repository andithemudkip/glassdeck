---
date: 2026-07-29
status: planned
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/post-kill-decay-groups
    - can/signal-ride-mode
    - can/bitrate
  references:
    - husqvarna-community-notes
  experiments:
    - 2026-06-21-cold-boot-id-emergence
    - 2026-06-17-key-on-cold-boot
    - 2026-07-24-cluster-fuse-pull
  decisions: []
  logs: []
---

# X10 disconnect — what the cluster contributes to ABS + QS initialisation

## Hypothesis

Disconnecting the OEM cluster (P10) at X10 leaves the bike running but kills ABS
and the quickshifter. This is rider-known behaviour on this platform, and
[[husqvarna-community-notes]] records that another team hit the same wall, solved
it, and did not publish how.

Our CAN corpus says whatever the cluster contributes is **not a distinct message**:
4 cold-boot windows, 0 boot-only IDs, 0 UDS, 0 frames outside the documented 11
([[always-on-broadcast-ids]]). Three mechanisms survive that constraint. This
session is designed to separate them in one sitting.

| # | Hypothesis | Mechanism |
|---|---|---|
| **H1** | **Node-presence timeout** | The cluster publishes one of the 11 IDs. A30/A11 monitor for it; absence raises a comms DTC and they disable ABS + QS by design. |
| **H2** | **Physical presence** | The cluster is electrically load-bearing — most plausibly a 120 Ω bus terminator, secondarily conditioning X10 pin 5 (kill mirror, shared with A11 pin 33). No CAN content involved. |
| **H3** | **Payload handshake** | All 11 IDs continue, but bytes inside them differ when the cluster is absent — the exchange is hiding in payload we've been reading as static. |

H1 is ranked first: it needs no hidden protocol, predicts exactly the observed
symptom (both systems out together), and its fix — keep broadcasting the missing
ID — is trivial to implement and very much worth not disclosing commercially.

H2 is the rider's hypothesis and is the reason for the bench step below. Note
`docs/hardware/can-adapter.md:49` already *assumes* "termination at the ECU/dash
ends of the backbone (2× 120 Ω → 60 Ω)" — stated as fact, never measured, and the
verification checkbox at line 73 is still open. Physics prior is moderate, not
high: at 500 kbps over a ~2 m backbone a reflection round-trip is ~1 % of a bit
time, so a missing terminator often still communicates.

Only three X10 pins touch nets any other module sees — 5 (kill mirror, also A11
pin 33), 9 and 10 (CAN L/H). Every other pin is a dash-only sensor or supply net,
so H2 must run through one of those three.

### Discriminating predictions

| Observation with X10 unplugged | H1 | H2 | H3 |
|---|:--:|:--:|:--:|
| An ID drops out of the inventory | ✅ | — | — |
| `bus_err` / `rx_missed` climb; CRC or partial frames | — | ✅ | — |
| All 11 IDs at normal rate, bus clean, payload bytes differ | — | — | ✅ |
| CANH–CANL resistance rises 60 Ω → 120 Ω (key off) | — | ✅ | — |

Not mutually exclusive — the cluster could both terminate the bus and publish an
ID. The bench step settles H2 independently of the captures.

## Setup

**Rig must be laptop-powered, not bike-powered.** The wifi-bridge boots off F7
with the key, so it cannot see the pre-key-on window — and the boot window is the
entire experiment. Use `firmware/can-logger` over USB (ADR 0001), started before
each key-on, exactly as [[2026-06-17-key-on-cold-boot]] did.

- Bike: 2020 Husqvarna Svartpilen 401. Neutral, side stand down, kill switch RUN.
  **Stationary for the whole session** — with X10 off there is no speedo and no
  warning lamps.
- Engine: key-on / engine-off throughout. Do not start the engine with the
  cluster disconnected. (An engine-on repeat is a follow-up, not this session.)
- Multimeter for the bench step.
- Camera on the dash bezel for the connected windows; on the ABS/QS warning state
  after reconnect.
- **All X10 connect/disconnect operations happen key OFF.** No hot unplugging —
  avoids transients and spurious DTCs that would muddy the ID diff.

Prerequisite tooling change: `scripts/capture.py` currently discards firmware
`# …` status comments (`parse_slcan_line`, capture.py:120), which is where
`bus_err` / `rx_missed` / `rx_overrun` live. As it stands a degraded bus and a
healthy bus produce **identical** capture files, so H2 would be invisible. Patch
to tee those lines into a `bus_status.log` sidecar before running this session.

## Procedure — freeform (no YAML)

Timing isn't load-bearing; condition ordering is. Three captures, each a full
key-off → key-on → steady-state boot.

### Bench step — resistance (key OFF, no capture)

Do this first. It may settle H2 before any capture runs.

1. Key off. Unplug our adapter from the diagnostic connector (its own 120 Ω would
   corrupt every reading — see can-adapter.md:51).
2. Measure resistance CANH–CANL at the diagnostic port (pins 2 and 5). Record.
3. Unplug X10 at the cluster. Measure again. Record.
4. Reconnect X10. Measure again — should return to the step-2 value; if it
   doesn't, stop and investigate the connector seating before continuing.

Reading ~60 Ω → ~120 Ω at step 3 means the cluster is a bus terminator and **H2
is live**. Unchanged (~60 Ω) means the two terminators live at ECU and ABS, the
cluster is not one of them, and H2 collapses to the pin-5 variant only.

### Capture A — baseline, cluster connected

5. Adapter plugged back in. `python scripts/capture.py --port <port> --label x10-baseline`
6. 5 s of silent pre-key-on head, then key on. Space-mark at the key-on instant —
   this is t=0 for every boot-window comparison.
7. Run 90 s. Note dash self-test behaviour and which lamps extinguish.
8. `q` to stop. Key off.

### Capture B — cluster disconnected

9. Key off confirmed. Unplug X10 at the cluster.
10. `python scripts/capture.py --port <port> --label x10-disconnected`
11. Same shape: 5 s head, key on, space-mark, 90 s.
12. Rider notes anything observable that changes — audible relay clicks, ABS pump
    self-test noise at key-on, headlight behaviour. **Do not attempt to verify
    that ABS or QS are disabled**: the dash is unplugged so there are no lamps,
    and the bike is stationary and engine-off so neither system can be exercised.
    The symptom is rider-known and is not what this session measures; the ID diff
    is. See Open questions.
13. `q`. Key off.

### Capture C — reconnect / recovery

14. Key off confirmed. Reconnect X10.
15. `python scripts/capture.py --port <port> --label x10-recovery`
16. Same shape. Watch whether ABS + QS come back on their own at this key-on, or
    whether a fault stays latched and needs the rider's known clear procedure.
17. `q`. Key off.

`session.md` per capture: dash lamp state at key-on and after self-test, whether
ABS/QS were confirmed out (B) and confirmed back (C), any DTC-like dash
behaviour, and the three resistance readings from the bench step.

## Analysis plan

1. **ID inventory diff** — `python scripts/inventory_ids.py` on each of the three
   sessions, anchored to the key-on mark. Per-ID frame count, first-seen offset,
   median period. Any ID at ~0 fps in B and normal in A **and** C is
   cluster-published → **H1**, and names the ID we need to synthesise.
   - Prime suspects are the two unattributed boot waves from
     [[post-kill-decay-groups]]: S-mid (`12A`, `5A0`) and S-late (`541`, `450`).
     The schematic lists only three CAN nodes; F is ECU and S-early is ABS, so
     P10 should be in one of these two by elimination.
   - `450` is the standout: last of all 11 to boot (+424 ms), near-entirely
     static, and the one thing it does carry is ride mode D4 b7 — the function the
     cluster commands ([[signal-ride-mode]]).
2. **Bus health diff** — `bus_status.log` across A/B/C. Any rise in `bus_err` or
   `rx_missed` in B, or partial/malformed lines in `capture.log`, is **H2**.
   Baseline is all-zero on a healthy bus.
3. **Boot-window payload diff** — for every ID surviving in B, align A and B on
   the key-on mark and diff payload bytes over t=0 → +5 s at ~50 ms granularity.
   Any byte that differs consistently between A and B is **H3** and is the
   handshake. Pay particular attention to the always-zero bytes: 42 of 88 read
   clean zero across the corpus, and `byte-encoding-12-in-16` already burned us
   once with a nibble that was zero until the right input fired.
4. **Steady-state payload diff** — same comparison over the 60–90 s window, to
   separate "boot-only exchange" from "continuous heartbeat".
5. **Cross-check C against A.** Recovery should reproduce baseline. If it
   doesn't, something latched, and the difference is itself informative.

## Expected outcomes

- **H1 confirmed (most likely).** One ID — probably `450` — is absent throughout
  B. This resolves the [[signal-ride-mode]] command-direction open for free,
  attributes a boot wave in [[post-kill-decay-groups]], and turns "replace the
  dash" into a bounded TX problem: synthesise that ID with plausible content.
  Unblocks drafting the TX ADR.
- **H2 confirmed.** Bench step shows 60 → 120 Ω and/or `bus_err` climbs in B. The
  fix is a resistor, and the replacement dash needs to reproduce the cluster's
  electrical presence rather than its traffic. Would also mean the community team
  spent months looking for a message that never existed.
- **H3 confirmed.** All 11 IDs present and clean in B, but bytes differ. Hardest
  outcome — points at a payload-level exchange, and the boot-window diff tells us
  where to look next.
- **Nothing differs at all.** Would mean the cluster contributes nothing
  observable at the diagnostic stub, and ABS/QS loss is mediated some other way
  entirely. Forces a re-read of whether the diagnostic port really sees the whole
  segment, despite the schematic showing one net.

## Open questions this session cannot answer

- **Is ABS genuinely disabled, or just undisplayed?** "ABS + QS stop working" is
  rider-known from community report, not something we have verified functionally.
  Two very different failures are consistent with it: the ECU/ABS actually fault
  and disable, or both systems keep working and we simply lose the cluster that
  displays their status. QS in particular may be gated by an enable setting
  stored *in* the dash, which would make its loss a configuration artefact rather
  than a fault.
- Answering it needs an engine-on, moving test with the cluster disconnected —
  substantially riskier than this session and out of scope here. Note it as a
  precondition for any "remove the OEM cluster permanently" decision, since the
  fix differs completely between the two cases.
- This session measures what the cluster *contributes to the bus*, which is the
  input to that decision either way.

## Risks and caveats

- ABS and QS are *expected* to fail in window B. That is the known symptom, not
  an experiment failure. Bike stays stationary throughout, so neither is needed.
- A DTC may latch and survive into C. Rider has a known fault-clear procedure
  (per the planned [[2026-07-24-abs-fault-and-recovery]]); note whether it was
  needed and what worked.
- **Odometer — not a real risk.** Unplugging X10 drops both supply rails, pin 2
  (ignition, F7) and pin 1 (permanent, F2). But the odo cannot be in
  backup-rail-retained RAM: a battery disconnect is routine maintenance and would
  wipe it every time, which no manufacturer ships and odometer-tamper regulation
  effectively forbids. It is in EEPROM/flash. Pin 1's permanent feed is for the
  clock — the thing that *does* reset after a battery disconnect. Photograph the
  reading before window A anyway; it costs nothing and the clock resetting at
  window C is a useful confirmation the cluster fully power-cycled.
- **This experiment does not authorise any TX.** Listen-only throughout, per
  golden rule 1. It produces the evidence a TX ADR would need, nothing more.
- One session cannot distinguish "cluster publishes this ID" from "cluster and
  some hidden fourth node both went quiet". If an ID drops out, the follow-up is
  to confirm the cluster specifically is its source.

## Follow-ups

- Update [[post-kill-decay-groups]] — its "whether the dashboard P10 originates
  any CAN traffic" open item should close either way.
- Update [[always-on-broadcast-ids]] with per-ID module attribution for whatever
  window B resolves.
- Write `docs/findings/hardware/cluster-bus-termination.md` from the bench
  readings regardless of outcome, and close the can-adapter.md:73 checkbox.
- If H1: draft the TX ADR for the identified ID, plus a bench experiment
  synthesising it with the cluster disconnected — the first real
  replacement-dashboard milestone.
- Likely pre-empts [[2026-07-24-cluster-fuse-pull]], which asks the same
  ownership question via F2. Both source docs agree and are consistent: F2 is the
  manual's combination-instrument fuse, and per `docs/hardware/dash-connector.md`
  it feeds X10 pin 1, the permanent memory/clock backup rail — while pin 2, the
  dash's main supply, sits on the F7 rail. So F2 does power the cluster, just not
  the rail that keeps it alive with the key on; pulling it should land that
  experiment's outcome 1 (cluster stays on the bus) rather than depowering it.
  X10 disconnect removes the cluster outright and needs no fuse-topology
  assumption. Retire the fuse pull if this session resolves ownership.
- **Odometer exposure applies to this session too — see Risks.**
