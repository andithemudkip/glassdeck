---
area: can
status: confirmed
established_by:
  - 2026-07-24-abs-mode-toggle
references:
  - ktm-can-decoder
  - svartpilen-401-dash-user-manual
  - husqvarna-community-notes
---

# Ride mode (ROAD / SUPERMOTO) — `12A` D2 bit 1, mirrored on `450` D4 bit 7

Ride-mode state on the 2020 Husqvarna Svartpilen 401 is broadcast as a **two-bit mirror** — the same state published on two different arbitration IDs by (presumably) two different modules, both at ~50 ms period:

| Location            | Mask   | Note |
|---------------------|--------|------|
| `12A` D2 bit 1      | `0x02` | Primary. `12A` is in the ABS-lamp family ([[signal-abs-lamp]]), so likely ABS-ECU-broadcast. |
| `450` D4 bit 7      | `0x80` | Mirror. Publisher unknown; likely cluster (see Open). |

Both bits share identical polarity: **0 = ROAD (rear ABS enabled), 1 = SUPERMOTO (rear ABS disabled)**. Semantic is *rear-ABS-enable* per the owner's manual — the toggle changes nothing else (no map, no power, no TC).

Confirmed across **4 toggles / 5 stable windows** with per-window purity `1.00` on both bits, plus corpus cross-check: both bits were universally 0 across all 15 prior sessions (every prior session was in ROAD by rider recall), and this session's SUPERMOTO windows are the first 1 values ever seen. Detailed timing (~3 s hold-to-bit-flip lag, no separate "hold-active" bit, no event-only IDs at transitions) in [[2026-07-24-abs-mode-toggle]] Result. The two mirrors transition within 20–300 ms of each other; precedence is inconsistent across toggles.

## Cross-walk vs KTM

The ktm-can-decoder places ride mode at `12A` D1 bit 6. On the 401 that bit is **flat 0 across the entire mode-toggle capture** — the KTM hint does not carry over. Husqvarna 401 uses `12A` D2 b1 instead.

## Open

- **No separate on-bus command exists.** A four-way scan across all IDs (`scripts/abs_mode_command_scan.py`) found no hold-only ID, no burst-only ID, no rare byte value, no bit elevated across the 3 s hold, and no bit elevated in the ±0.5 s burst around each mark. So the two mirror bits *are* the command signal — or the actual command is off-bus (LIN, K-line, private ABS↔cluster pair, or a direct wire). For TX-probe design this means "spoof the state bit" is the leading approach; no unknown handshake to reverse first.
- **Command direction / which module owns which broadcast.** Listen-only precedence isn't clean enough to prove `450`-leads-`12A` (or the reverse). Two independent lines of passive evidence both point at *different publishers* but neither pins down identity:
  - **Different D7 conventions.** `12A` follows the standard 6-cycle+hash scheme (D7 = cycle[n mod 6] ⊕ f(D0..D6), all 1264 frames verify); `450` D7 = `0x00` across all 1656 frames — the "outside the cycle family" behavior documented in [[byte-d7-cycle-hash]]. Different firmware D7 policies are unusual within a single module.
  - **Emergence gap at key-on.** Across 4 cold-boot / key-on captures (2026-06-17, 2026-06-22, 2026-06-23, 2026-07-10), `450` consistently emerges 46–223 ms *after* `12A`. Different-module init sequences are the natural explanation; same-module firmware would normally bring up all its broadcast tasks together.

  Both point at "different publishers." Neither identifies *which* modules. A speculative third hypothesis — `450` is ECU-published (cluster → ECU via a bus we don't sniff → ECU broadcasts `450` → ABS ECU reads and mirrors on `12A`) — was suggested by the D7 family similarity with `540` (an ECU-domain ID), but the emergence-order data mildly cuts against it (3 of 4 sessions had `450` emerging *after* the ECU family, not with it). Publisher identity is genuinely undetermined from listen-only. A passive fuse-pull or active TX probe is needed to resolve — see [[2026-07-24-abs-mode-toggle]] Follow-ups. Also see the fuse-topology constraint below.
- **Fuse 7 rules out the naive cluster/ABS fuse-pull test.** Per the 401 repair manual, fuse 7 is shared between the ABS control unit, the combination instrument (cluster), *and* the diagnostics connector — pulling it kills our capture rig alongside both suspects. Fuse 2 is dedicated to the combination instrument (10 A), which *might* be a viable pull target if the cluster's CAN transceiver draws from fuse 2 rather than fuse 7 — untested. Otherwise the ownership test needs a direct connector disconnect at the ABS module, or has to wait for the TX-probe experiment.
- **Fault-state behaviour.** [[2026-07-24-abs-fault-and-recovery]] Phase C step 1 cycles mode during ABS-fault conditions — checks whether both bits still alternate cleanly, or whether the ECU rejects/latches/mirror-desyncs.
- **Engine-on confirmation.** This capture was engine-off. Bit locations should be unchanged engine-on; falls out of any future engine-on session that toggles mode.
- **Manual gate: "stationary."** Manual says the toggle requires the bike stationary. Not tested here. If the replacement dashboard commands a mode change, may need to gate on wheel speed = 0 or the ABS ECU will silently reject.

## Evidence

- [`docs/experiments/2026-07-24-abs-mode-toggle.md`](../../experiments/2026-07-24-abs-mode-toggle.md) — Result section.
- [`logs/2026-07-24-abs-mode-toggle-3/`](../../../logs/2026-07-24-abs-mode-toggle-3/) — 33862 frames, 158 s.
- [`scripts/abs_mode_scan.py`](../../../scripts/abs_mode_scan.py) — window-aware bit scan (state-bit discovery).
- [`scripts/abs_mode_command_scan.py`](../../../scripts/abs_mode_command_scan.py) — all-IDs command/burst/hold-bit scan (negative result — no separate on-bus command).

See also: [[signal-abs-lamp]], [[2026-07-24-abs-fault-and-recovery]], [[husqvarna-community-notes]], [[always-on-broadcast-ids]], [[ktm-can-decoder]].
