---
date: 2026-07-10
status: partial
phase: 2
related:
  findings:
    - docs/findings/can/signal-engine-torque.md
    - docs/findings/can/signal-wheel-speed-front.md
    - docs/findings/can/signal-wheel-speed-rear.md
    - docs/findings/can/signal-engine-off-counter.md
    - docs/findings/can/battery-voltage-absent-from-always-on-broadcasts.md
  decisions: []
  logs:
    - logs/2026-07-10-brakes-stationary/
---

# Front / rear brake pressure hunt (stationary, engine off)

## Hypothesis

Front-brake and rear-brake inputs surface on the always-on broadcast set as either analog pressure values (BE int16 or u16) or on/off switch bits. Most likely landing zones:

1. **`121` D0:D1 or D2:D3** — twin BE int16 channels (encoding confirmed in [[signal-engine-torque]], semantic unknown). 20 ms period is right for a brake-related signal.
2. **`450`** — currently frozen; if any live rider input moves it, we unlock the whole ID (per `docs/signals/coverage.md` priority heuristic).
3. **A byte on `12D`** — 10 ms wheel-speed ID; ABS logic often collocates brake input with wheel data.
4. **A byte on `540` / `541`** — plausible slow-decay ABS/ECU state carrier.

Null hypothesis (worth stating explicitly): brake pressure lives on a chassis-electronics bus that never reaches the diagnostic stub — per [[ktm-can-decoder]] observing that KTM's `0x290` front-brake ID has no Husqvarna analog identified yet.

## Setup

- **Bike state:** key ON, kill RUN, engine **OFF**, neutral, side stand down, stationary on both wheels. Engine off to keep the noise floor minimal — brake pressure sensors, if present, run off ignition, not engine.
- **Rider position:** standing next to bike, right hand on front lever, right foot on rear pedal. No throttle work, no wheel motion.
- **Hardware:** wifi-bridge over WebSocket (`bin/experiment-wifi-bridge`). First real test of the WiFi procedure runner (ADR 0018 flow + procedure normalizer).
- **Firmware:** wifi-bridge (whatever HEAD is at capture time; recorded in session.md).
- **Duration:** ~6 min including settles.

## Procedure

Auto-marked step-by-step by `docs/experiments/2026-07-10-brakes-stationary.procedure.yaml`. Marks fire at STEP START — the moment the rider is cued to begin the action. The bus broadcast, if any, follows within ~10–20 ms of the press edge, so step start is the right correlation reference.

Phases:
- **A — Front pulses (×6).** Two gentle (~30 % lever travel), two medium (~60 %), two hard (firm stop). ~4 s per pulse (1.5 s press + 2.5 s settle).
- **B — Front sustained.** One 12 s medium-pressure hold. Distinguishes a pulse-only signal from a level signal.
- **C — Rear pulses (×6).** Same pattern via foot pedal.
- **D — Rear sustained.** 12 s medium hold.
- **E — Both together (×3).** Pulse both levers/pedal simultaneously, then one 8 s combined hold. Catches ID-level co-activity (a byte that only moves when *either* brake is on will show up in A/C too, but a byte tied to combined-brake logic — if any — needs Phase E).
- Framing null windows: 20 s pre-Phase-A baseline (nothing pressed), 8 s inter-phase settles.

Ctrl-N / Ctrl-E (live-view hypothesis + expect-shape lenses) available during Phase A as a real-time gut-check on candidate bytes.

## Result

Session captured cleanly via `bin/experiment-wifi-bridge` — 101,752 frames across 11 always-on IDs over 251 s, 21 auto-marks matching the procedure exactly (see `logs/2026-07-10-brakes-stationary/`). Clock offset +1,783,696,824.72 s applied, so `capture.log` frames and `events.csv` marks share one host wall-clock base.

**No brake-attributable movement on any of the 11 always-on IDs.** Byte-level (`scripts/brake_scan.py`) and bit-level (`scripts/brake_bit_scan.py`) window analyses find:

- `121` D0:D1 and D2:D3 twin int16 channels — completely flat across BASE, FA (front pulses), FB (front hold), RC (rear pulses), RD (rear hold), BE (both). Rules out the strongest candidate.
- `450` — 5020 frames but payload never left its idle value; brake input did not unlock it.
- `12D` bytes — D0–D6 flat; D7 is the known cycle hash.
- `540` / `541` — only movement is on the already-decoded engine-off counter (`541` D6, 1 Hz) and cycle hash D7. No other bit changed brake-selectively.

**One anomaly: `541` D5 latched 01 → 02** exactly once at t=+55.76 s post-key-on (t=+7.56 s past front pulse 1, but 2.55 s **before** front pulse 3 during the settle between pulses 2 and 3), then stayed at 02 for the remaining 190 s. This is **not brake-attributable** — the flip timing does not correspond to any press edge, and it matches the "scattered engine-off key-on ramp" characterization for `541` D5 in [[battery-voltage-absent-from-always-on-broadcasts]]. Treated as background counter noise for this hunt.

## Interpretation

Front and rear brake input is **not visible on the always-on broadcast set** of this bike's diagnostic-connector CAN segment, at least in a stationary engine-off state. This is consistent with the null hypothesis from the plan and with the observation in [[ktm-can-decoder]] that KTM 690's `0x290` (front brake pressure) has no Husqvarna analog identified.

Confidence bounds: this rules out only *always-on, stationary, engine-off* visibility. Three plausible reasons brake data could still exist on this bus but not surface here:

1. **Engine-on gating.** ABS ECU may hold brake broadcasts until the engine is running (comparable to how `signal-warmup-index` and `signal-engine-on-counter` are engine-on gated).
2. **Motion gating.** Brake info may only broadcast when wheel speed > 0 (an ABS decisioning necessity — no braking-relevant state at rest).
3. **Off-bus entirely.** Simplified 2020 401 ABS module may keep brake pressure/switch on a chassis-only bus not exposed at the diagnostic stub.

Cannot yet distinguish (1) or (2) from (3) — needs a follow-up capture.

**Wifi-bridge procedure pipeline works.** First real-bike run of `bin/experiment-wifi-bridge` produced a clean session: procedure YAML drove 21 auto-marks at exact 5 s cadence, no keystroke spam from the SLCAN pipe (post-FD-swap fix), timestamp normalization aligned frames with marks with no downstream analyzer changes.

## Follow-ups

- **Motion gating** is the only remaining plausible gate. Piggy-back onto the first-ride motion capture (status next-action #1): a walking-pace phase with 3–4 hard front-brake pulses. Covers gate (2) at ~zero session cost.
- **Skip an engine-on stationary re-run.** Engine-on gating (gate 1) has no plausible mechanism for a body/chassis input like brake — every other engine-on-only signal in the corpus (`warmup_index`, `engine_on_counter`, `121` twin int16, engine-state bits) is engine-management, not chassis. A negative result there would be uninformative; not worth its own session.
- **If the motion phase also comes up empty** → promote to `docs/findings/can/brake-input-absent-from-broadcasts.md`, sibling to `fuel-consumption-absent-from-broadcasts` and `battery-voltage-absent-from-always-on-broadcasts`. Implies the brake-light switch state — which the wiring harness must expose to the dash — is either analog-only or on a chassis bus we can't see. Given [[docs/hardware/dash-connector.md]] has no brake input pins on X10, the replacement dash likely doesn't need brake state at all (OEM dash never displayed it).
- **Positive `541` D5 finding**: a control experiment (key-on + 4 min hands-off, no brake) would pin down whether `541` D5 flips at a fixed time-since-key-on or is genuinely stochastic. Cheap add-on to any future engine-off session.

## Ancillary output

- `scripts/brake_scan.py` — byte-level window scan; distinct-value counts per (ID, byte) in BASE / FA / FB / RC / RD / BE. Kept for reuse in the engine-on and rolling follow-ups.
- `scripts/brake_bit_scan.py` — bit-level companion, per-window transition counts.
