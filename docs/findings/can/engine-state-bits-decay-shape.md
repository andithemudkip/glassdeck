---
area: can
status: provisional
established_by:
  - 2026-06-17-payload-diff-idle
  - 2026-06-21-engine-state-bit-attribution
---

# Engine-state bits hold through Fast-group decay — they are not fast engine-running indicators

Five payload bits flip dominant value between engine-off and idle in all three baseline runs (purity ≥ 0.90):

| ID    | byte | bit | engine-off mode | idle mode |
|-------|-----:|----:|----------------:|----------:|
| `121` |  1   |  5  | 1               | 0         |
| `121` |  1   |  7  | 1               | 0         |
| `121` |  5   |  3  | 0               | 1         |
| `540` |  2   |  6  | 1               | 0         |
| `540` |  3   |  4  | 1               | 0         |

`120` D0 bits 1 and 2 also flip but are already attributed (dominant bits of the RPM high byte; idle RPM = `0x06A4` → D0 = `0x06`).

**None of these five bits reverts to its engine-off mode in the host ID's post-kill broadcast tail.** Both host IDs are in the [[post-kill-decay-groups]] Fast group; both go silent within ~300 ms of the kill toggle. Throughout that 300 ms tail, every flagged bit holds its idle value at 1.00 purity (12–16 frames per run on `121`, 2–3 frames per run on `540`).

**They also hold engine-off mode rock-solid through 174 s of key-on-engine-off-kill-in-run.** The cold-boot capture ([[2026-06-17-key-on-cold-boot]]) is exactly that condition: key-on, no engine start, no kill toggle, 174 s of bus broadcast. All five bits read engine-off mode at ≥0.99 purity in every third of the hold — no internal timer, no self-test stage, no drift.

## What this means

For dashboard logic, **none of these bits is a usable "engine running" indicator.** They are slower than RPM and never observed to drop while still being broadcast. The right "engine running" source remains [[signal-rpm]] (`120` D0,D1) — it snaps to exactly `0x0000` at the moment of kill, within one 10 ms broadcast period.

## What the data rules out

The bit's value is not determined by anything we can manipulate without actually running the engine:

- **Not "engine-run permission" (key + kill both in run).** In cold-boot, key is on and kill is in run, but the bit reads engine-off mode. So whatever the bit sources, it requires more than just the engine-run circuit being electrically alive.
- **Not a "key-on latch."** A latch set at key-on would already be at idle mode through cold-boot. It isn't.
- **Not "module power-rail status."** The host module is broadcasting normally for the full 174 s with the bit at engine-off mode — the bit is determined by something downstream of the module being powered.

The bit genuinely changes only when the engine **physically runs**. Off → idle on engine start; never observed to revert before the host ID falls silent on the Fast-group tail.

## Residual question: which sensor sources each bit?

The five bits are likely sourced from the engine-management module's sensor reads. Plausible candidates per host ID:

- `121` (Fast group, 20 ms period): a body / engine-side module. Bits D1.5, D1.7, D5.3 may track oil-pressure switch, fuel-pump-good, ignition-coil-fed, crank-sensor-active, or a composite "engine ready" register.
- `540` (Fast group, 100 ms period, also carries [[signal-coolant-temp]] and [[signal-side-stand]]): the engine-management module. Bits D2.6 and D3.4 may track alternator-good, generator-field-OK, or a similar generator-status flag.

Cross-walking to [`references/ktm-can-decoder.md`](../../references/ktm-can-decoder.md) gives no prior hypothesis for any of the five bits — they're outside the bytes/IDs the KTM 690 decoder catalogues. Attribution would require either reading other open-source KTM/Husqvarna projects or scoping the module's input pins directly during an engine cycle.

## Why this is `provisional` rather than `confirmed`

The "holds-idle through Fast-group decay" and "flat through 174 s of key-on-no-engine" behaviour are confirmed by data. What remains `provisional` is *which sensor* each bit reflects. Until we have an external mapping (manufacturer documentation, another project's decoding, or hardware-side probing), the per-bit semantics are unknown.

## Open

- Per-bit sensor attribution. No cheap CAN-only experiment will resolve this — any per-input capture that doesn't actually run the engine cannot move the needle (cold-boot already covers that condition). The remaining options are external: look up KTM 390 ECU pinouts and trace the module's input pins, find another open-source decoder that names these bits, or accept "engine-running indicator, sensor unknown" for dashboard purposes.

## Open

- Run the key-on-no-start capture. Cost: 1 minute on the bike.
- Per-bit semantic attribution. Cross-walk to [`references/ktm-can-decoder.md`](../../references/ktm-can-decoder.md): KTM `121` is not catalogued in the public decoder, so no prior hypothesis exists for any of the three `121` bits. `540` D2 bit 6 and D3 bit 4 are also outside the KTM bytes we have hypotheses for ([[signal-coolant-temp]] D5,D6; [[signal-side-stand]] D3 bit 0). Attribution probably requires reading other open-source KTM/Husqvarna projects or scoping module supply rails directly.

## Evidence

- [`docs/experiments/2026-06-17-payload-diff-idle.md`](../../experiments/2026-06-17-payload-diff-idle.md) — engine-state bit map.
- [`docs/experiments/2026-06-17-key-on-cold-boot.md`](../../experiments/2026-06-17-key-on-cold-boot.md) — 174 s key-on-no-engine corpus reused by the next experiment.
- [`docs/experiments/2026-06-21-engine-state-bit-attribution.md`](../../experiments/2026-06-21-engine-state-bit-attribution.md) — decay-shape analysis + 174 s cold-boot bit-stability check.

See also: [[post-kill-decay-groups]], [[signal-rpm]], [[signal-side-stand]].
