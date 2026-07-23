---
date: 2026-07-22
status: success
phase: 1
related:
  findings:
    - signal-wheel-speed-front
    - signal-wheel-speed-rear
    - signal-12d-d1-bit0
    - signal-abs-lamp
    - fan-status-absent-from-broadcasts
    - dash-warning-lights
  decisions: []
  logs:
    - 2026-07-22-first-moving-ride
---

# First on-bike moving capture (wifi-bridge, freeform ride)

## Hypothesis

Not a scripted procedure — this is the freeform "first ride" from `docs/status.md` Next Action #1. Aimed to (a) validate the `wifi-bridge` firmware under real ride conditions, and (b) provide the first motion-carrying corpus so we can attack the wheel-speed calibration (status #5), ABS-lamp threshold (status #6), coolant walk-up on `541` D1 (status #7), and the moving-byte shortlist (`12A` D1, `12E` D6, `5A0` D4 from [[2026-06-30-unknown-byte-corpus-sweep]]) all from a single evidence bundle.

## Setup

- **Bike:** 2020 Husqvarna Svartpilen 401, ambient ~22 °C, cold-ish engine at moving-1 start, warm through moving-5.
- **Hardware:** ESP32-S3-DevKitC-1 + SN65HVD230 tap on the OBD/diagnostic port, bike-powered.
- **Firmware:** `wifi-bridge` @ 58a5d95, listen-only @ 500 kbps.
- **Capture path:** WebSocket → rider's phone (iOS) → local file per session → post-ride export to `logs/`.
- **Rider role:** ride the bike, mentally note anything the OEM dash showed, don't press capture-side buttons mid-ride.

## Procedure

Rider mounted the bike with the ESP powered from the bike, opened the wifi-bridge capture UI on their phone, and started `moving-1` before pulling away cold. That capture died mid-ride when the phone screen slept and iOS backgrounded the WebSocket — moving-1 has two GAP markers and lost ~40k frames. Rider then manually started/stopped each of `moving-2` through `moving-5` on the phone to work around the sleep issue, so those four are chunked but each internally clean.

Rider observed the OEM dash throughout and reported three calibration data-points post-ride (see [[../../logs/2026-07-22-first-moving-ride/session.md]] for the full transcription):

- Steady ~60 km/h on the dash coincided with our decoded rear reading ~66 km/h and front reading ~45 km/h.
- Peak dash reading in moving-3 was 101 km/h.
- Cooling fan cycled at 90 °C (off) → 95 °C (on) → 90 °C (off) during moving-5, starting with the fan already on.

## Result

Raw captures: [`logs/2026-07-22-first-moving-ride/`](../../logs/2026-07-22-first-moving-ride/). 386 271 frames across 5 files; all 11 always-on IDs present in every file; no new arbitration IDs.

### Sub-analysis 1 — wheel-speed LSB re-calibration (via `scripts/first_moving_ride.py`)

**Two headline findings, each affecting an existing `confirmed` finding:**

**(a) Front encoding is uint16 BE, NOT 12-bit-in-16-bit.** [[signal-wheel-speed-front]] was pinned as a 12-bit-in-16-bit encoding on the argument that "every non-zero raw value of `(D0 << 8) | D1` is a multiple of 16" across the engine-off hand-spin corpus. Under real motion, the raw front u16 low nibble is non-zero on the majority of moving frames:

| File | Low nibble non-zero (front) | Moving frames |
|------|----------------------------:|--------------:|
| moving-1 | 75.2 % | 22 427 |
| moving-2 | 89.2 % |  9 657 |
| moving-3 | 72.8 % | 15 244 |
| moving-4 | 82.7 % | 14 912 |
| moving-5 |  0.0 % |  2 271 (bike was mostly ≤ ~15 km/h) |

Combined across the four higher-speed files, front raw u16 low nibble carries information roughly 80 % of moving frames — that's not padding, that's the low 4 bits of a genuine 16-bit encoding. The 12-bit finding was an artifact of the engine-off floor (raw values snapped to 0 below 448, so we never saw motion in the low bits) plus the hand-spin data topping out at ~11 km/h. **The 1/192 km/h LSB is also therefore not the correct scale.**

**(b) Rear/front decoded ratio is a constant 0.762 across the entire 30–120 km/h speed range.** Binned by decoded rear speed, using current LSBs (front 1/192, rear 1/16):

| Rear bin (km/h) | n | front μ | rear μ | front / rear |
|-----------------|---:|--------:|-------:|-------------:|
| 20–30 | 4207 | 19.28 | 24.69 | **0.781** |
| 30–40 | 2620 | 26.97 | 34.94 | **0.772** |
| 40–50 | 3391 | 35.29 | 45.98 | **0.767** |
| 50–60 | 6624 | 42.81 | 55.93 | **0.765** |
| 60–70 | 12 678 | 49.92 | 65.32 | **0.764** |
| 70–80 | 6196 | 56.89 | 74.51 | **0.764** |
| 80–90 | 4679 | 64.49 | 84.53 | **0.763** |
| 90–100 | 7871 | 72.57 | 95.20 | **0.762** |
| 100–110 | 3760 | 78.57 | 103.06 | **0.762** |
| 110–120 | 197 | 84.38 | 110.70 | **0.762** |

Below ~20 km/h the ratio drifts (0.928 in the 0–10 bin, 0.805 in the 10–20 bin) — dominated by the front's raw-448 ECU floor and small-denominator noise. Above 20 km/h the ratio is flat within ± 0.02 across an order of magnitude of speed change. Both decoders are linear speed encodings; one channel is scaled ~22 % differently from the other. The likely truth is that both need adjustment (front more than rear).

**(c) Rider calibration point A — dash 60 km/h ⇔ decoded rear ~66, decoded front ~45.**

- If dash reads truth, rear LSB should be scaled by 60/66 = 0.9091 → new LSB ≈ 0.05682 km/h/LSB (= 1/17.6). This matches within 0.9 % the engine-driven best-fit of 0.05633 (= 1/17.75) from [[2026-06-23-engine-driven-rear-spin]] — corroboration that the earlier best-fit was closer to truth than the 1/16 nominal we'd been using.
- Front LSB implied at ~ 1/144 to 1/162 km/h depending on how rear is anchored.

**(d) Rider calibration point B — dash peak 101 km/h in moving-3 ⇔ decoded rear peak 111.75, decoded front peak 85.19.**

- If dash reads truth at peak: rear LSB ≈ 0.05649 km/h/LSB (= 1/17.70). Consistent with the engine-driven best-fit and calibration point (c).
- Front LSB at peak: ≈ 0.00618 km/h/LSB (= 1/162).

Cross-checking (c) and (d) against the empirical front/rear ratio of 0.762 (bike moving > 20 km/h, no slip → both wheels should decode to the same km/h if both LSBs are correct):

- Anchoring rear LSB to engine-driven best-fit 0.05633 → implies front LSB = 0.05633 / (raw ratio) = **~ 1/162** (front raw / rear raw = 9.144, so front_LSB = rear_LSB / 9.144 = 0.006159).
- Anchoring rear LSB to nominal 1/16 (0.0625) → implies front LSB = **~ 1/146**.

Best-fit new LSBs converging from all three constraints:

| Channel | Old LSB | New LSB (best est.) | Ratio | Rewrite |
|---------|--------:|---------------------:|------:|---------|
| Rear D5:D6 | 1/16 = 0.0625 | ~ 0.0563 (= 1/17.75) | 0.90× | closes the "Exact LSB" open in [[signal-wheel-speed-rear]] |
| Front D0:D1 | 1/192 = 0.00521 | ~ 0.0062 (= 1/162) | 1.19× **and** encoding = uint16 not 12-bit-in-16-bit | rewrites [[signal-wheel-speed-front]] |

## Interpretation

The clean linearity of the front/rear ratio across the whole ride is stronger evidence than any single calibration point: it says both channels are honest linear encodings of a shared physical quantity (the ~= true road speed), and that the previous LSBs were derived from incomplete corpora — rear from a gearing-uncertain engine-driven test, front from an engine-off, sub-11 km/h hand-spin.

The 12-bit-in-16-bit finding on front was structurally suspicious: only the engine-off floor made the low nibble look empty. In hindsight, the [[byte-encoding-12-in-16]] argument was too clever — the byte was just a normal uint16 that we happened to only see at coarse increments because the ECU floor cut off values below raw 448, above which the ECU emits every raw value (including odd ones and non-16-multiples). This ride surfaces those.

Both new LSBs are proposed, not `confirmed`. The dash is a UNECE R39-compliant OEM speedo — it may over-read by up to 10 % + 4 km/h — so anchoring to dash truth introduces ±10 % uncertainty. What's tight is the front/rear *relative* scaling; the absolute anchor is what needs one more experiment (a dash-verified steady-state hold at multiple speeds, or a GPS cross-check) to pin.

## Follow-ups

Sub-analysis 1 (wheel-speed LSBs) — done. All finding rewrites and yaml updates committed:
- [[signal-wheel-speed-front]] rewritten: uint16 BE at ~ 1/162 km/h/LSB (was 12-bit-in-16-bit at 1/192; old was engine-off-corpus artifact). Status → `provisional`.
- [[signal-wheel-speed-rear]] LSB updated: ~ 0.0565 km/h/LSB (was 1/16). Status → `provisional`.
- [[signal-12d-d1-bit0]] → `under-review`. Rear-27 km/h flag observation cannot be trusted under front-active motion until re-eval.
- [[byte-12d-d3-d4-front-mirror]] → LSB re-fit needed against corrected canonical.
- `docs/signals/{signals.yaml, coverage.md}` updated.

Sub-analysis 2 (fan-status hunt in moving-5) — done. **Result: fan status not broadcast on the always-on set.** New finding [[fan-status-absent-from-broadcasts]]. 704 payload bits scanned; the 11 quiet-enough candidates (1–6 transitions in the whole capture) fail to match the [27, 75, 116] s fan-event sequence in either polarity at ±5 s tolerance. Analogous to [[fuel-consumption-absent-from-broadcasts]] and [[battery-voltage-absent-from-always-on-broadcasts]]. Firmware inference from coolant crossings is the cheap consumer-side workaround. Anomaly surfaced en passant: `541 D4 bit 7` transitioned once at t+68.24 s, contradicting the "bit 7 reserved" claim in [[signal-engine-on-counter]] — likely a natural uint8 rollover at count 128; noted in the fan finding's Open, not touched here.

Sub-analysis 3 (`541 D1` coolant walk-up) — done. **Result: `541 D1 = 0x00` across every one of the 5 captures**, spanning coolant walkup 26.3 → 87 °C in moving-1, throttle-active riding across all of moving-2..4, and fan-cycling 89–95.7 °C in moving-5. The prior informal "candidate coolant-derived byte" hypothesis (status.md item 7 pre-cleanup) is refuted. `541 D1` is a fifth always-zero byte, promoted from `?` to `0` in [`docs/signals/coverage.md`](../signals/coverage.md); quick-stats updated (`always-zero: 3 → 4`, `undecoded: 51 → 50`). Corpus is now 15 sessions strong on this byte with no motion, so it's likely reserved / UDS-only rather than an untested-input candidate. Script: [`scripts/first_moving_ride_541d1.py`](../../scripts/first_moving_ride_541d1.py).

Sub-analysis 4 (ABS-lamp threshold) — done. **Result: ABS lamp attributed to 6 bits across `12A` and `12E`**, all flipping synchronously when the front wheel first crosses ~6 km/h with engine running, on each fresh key-on cycle. Verified across two independent key-on cycles (moving-1 fresh key, and moving-2 after the rider re-cycled the bike between chunks — inferred from the ESP boot-timestamp restart). New finding [[signal-abs-lamp]]; `docs/signals/{coverage.md, signals.yaml}` updated; [[bike/dash-warning-lights]] promoted from provisional to confirmed on the engine-running precondition. Coverage delta: `12A` and `12E` move from "0 attributed bytes" to "3 and 1 partially attributed" respectively — `5A0` is now the only ID with no extracted signal. Scripts: [`scripts/first_moving_ride_abs.py`](../../scripts/first_moving_ride_abs.py), [`scripts/first_moving_ride_abs_verify.py`](../../scripts/first_moving_ride_abs_verify.py).

Sub-analysis 5 ([[signal-12d-d1-bit0]] re-eval) — done, with a cascading correction to sub-analysis 1. **Result: D1 low nibble is a 4-bit rear-wheel-speed *band* field (= floor(rear_kmh / 25)), not a single flag; and the correct front encoding is 12-bit BE at LSB 1/10 km/h (not the "full uint16 at 1/162" my morning rewrite claimed).**

The rear-speed bin analysis (`scripts/first_moving_ride_12d_d1_bit0.py`) surfaced a puzzling periodic pattern in P(D1 bit 0 = 1) — clean 1.0 for rear 25-50 km/h, clean 0.0 for 50-75, clean 1.0 for 75-100 km/h, clean 0.0 for 100+. Not a threshold flag, not a random speed LSB. The raw-value probe (`scripts/first_moving_ride_12d_d1_probe.py`) showed D1 low nibble = 0 below 25 km/h, 1 in 25-50, 2 in 50-75, 3 in 75-100, 4 in 100+ — a 4-bit integer counting the 25 km/h band. Bit 0 alone tracks the LSB of this integer. Reconciles cleanly with [[2026-06-23-engine-driven-rear-spin]]'s "flag at ~27 km/h" observation: the front wheel was stationary throughout, so the high 12 bits of D0:D1 stayed at 0 and only the low nibble carried info — bit 0 flipped as rear crossed the band-0/band-1 boundary (25 km/h, with 2 km/h of gearing-estimate slop → "27").

Cascading consequence: the "full uint16" front-wheel encoding I posited in sub-analysis 1 was wrong. The low nibble IS heavily active under motion (72-89 %), but not because the encoding is a linear uint16 — it's the separate band field flipping through 0→1→2→3→4 as the bike accelerates. The original 12-bit-in-16-bit structure holds; only the LSB was wrong (was 1/12; correct value is 1/10).

Updated artefacts:
- [[signal-wheel-speed-front]] rewritten AGAIN with a "History of this finding" section documenting the three-iteration convergence. Structure: D0 + D1 high nibble, 12-bit BE. LSB: 1/10 km/h on the extract (~ 1/160 on raw u16). Cross-check: decoded_front / decoded_rear ≈ 1.01 across the whole speed range with the corrected LSBs — the ratio finally lands where it should.
- [[signal-12d-d1-bit0]] rewritten to describe the 4-bit rear-speed band field, superseding the flag interpretation. Also renamed conceptually — the file slug stays, but the signal is now `rear_speed_band` in `signals.yaml`.
- `signals.yaml`: wheel_speed_front back to `bit_length: 12, bit_offset: 4, scale: 0.1`. Added a new `rear_speed_band` entry.
- `coverage.md` updated.
- Lesson embedded in the front finding for future me: **"low nibble active" ≠ "encoding is full uint16" — a low nibble can be a separate speed-derived field with structure.**

Sub-analysis 6 (moving-byte shortlist `5A0` D4) — done. `5A0` D4 is essentially latched at `0x04` across the entire moving corpus, with only 10 frames (~ 1 s) at 0x00 at the very start of moving-2 (fresh key-on). Consistent with a system-startup indicator that latches 0 → 4 once at engine-start and stays. Doesn't warrant a dedicated finding on its own — noting in this experiment log and updating the corpus-sweep shortlist ([[2026-06-30-unknown-byte-corpus-sweep]]) is enough. `12A` D1 and `12E` D6 (the other two moving-byte shortlist items) are already partially attributed via [[signal-abs-lamp]].

Sub-analysis 8 (shift-cut detection, originally "quickshifter detection") — done. **New finding [[signal-quickshifter]]:** two shift-in-progress bits on `121 D6`. Bit 0 = "ECU ignition cut for shift" (fires on 100 % of real up- and downshifts), bit 1 = "auto-blip active" (fires only on downshifts). Byte values observed: 0x00 (normal, 99.5 % of frames), 0x01 (upshift cut), 0x03 (downshift cut+blip). Timing: bit rises ~40 ms before the gear-enum steps and holds median 60 ms (matches Bosch shift-cut window). Zero out-of-window fires. `121` moves from 3 attributed bytes to 4. **Correction from initial reading:** an early version of the finding claimed the rider used QS for 65/66 shifts based on clutch bit being 0. Rider clarified on 2026-07-22 that a mix of QS and clutched shifts was used; the unreliable clutch-lever switch on this bike (see [[signal-clutch]] / [[project-clutch-sensor-unreliable]] memory) simply doesn't fire on most clutched shifts. So `121 D6 bit 0` fires on **every** observed shift regardless of mechanism, and the CAN alone cannot distinguish QS from clutched here. Scripts: [`scripts/first_moving_ride_quickshifter.py`](../../scripts/first_moving_ride_quickshifter.py), [`scripts/first_moving_ride_qs_bit_probe.py`](../../scripts/first_moving_ride_qs_bit_probe.py), [`scripts/first_moving_ride_qs_bit1.py`](../../scripts/first_moving_ride_qs_bit1.py).

Sub-analysis 9 (`541 D4 bit 7` reserved-bit verification) — done, resolved as **counter width was mis-classified**. The moving-1 capture crossed `D4 = 128` at t+108.7 s (the "anomaly" flagged by the fan hunt) and moving-3 starts at `D4 = 143`; both are natural progressions of a full uint8 counter. Peak observed value = 255 with rollover to 0. Updated [[signal-engine-on-counter]] from `bit_length: 7 / modulo 128` to `bit_length: 8 / modulo 256`. Every pre-2026-07-22 engine-on session was shorter than 128 s from engine-start, which is why bit 7 never toggled and was mis-classified as reserved.

Sub-analysis 10 (gear-ratio validation) — sanity check on [[signal-gear-position]]. Per-gear steady-cruise RPM / rear-km/h ratio (95th percentile per gear) walks cleanly through the six gears (183 → 130 → 100 → 80 → 67 → 59), matching the KTM 390 platform's published transmission progression (1st through 6th total ratio spread ≈ 3.1×; observed 183 / 59 = 3.10 ✓). Enum unchanged. Analysis: [`scripts/first_moving_ride_gear_ratios.py`](../../scripts/first_moving_ride_gear_ratios.py).

Sub-analysis 11 (whole-corpus scan of remaining `?` bytes on `12A`, `12E`, `450`, `5A0`, `121 D4`) — done, big **coverage-classification cleanup**. Under 100k+-frames of real riding (cold start, high-speed cruise, decel, gear shifts, warmup, fan cycling):

| ID | Previously classified as | Now observed |
|---|---|---|
| `12A` D2, D3, D4, D6 | ? | all 0x00 across 18205 frames each |
| `12E` D0-D5 | ? | all 0x00 across 46115 frames each |
| `450` D0-D5 | ? static (unknown value) | all 0x00 across 18277 frames |
| `450` D6 | ? static | latched at 0x28 (40) |
| `5A0` D0-D3, D5, D6 | ? | all 0x00 across 9067 frames each |
| `121 D4` | ? | latched at 0x04 (only 10 exception frames at moving-2 startup) |

Coverage-classification delta: 12 previously-`?` bytes are now confirmed `0` (always-zero), 2 more (450 D6, 121 D4) are static non-zero constants. `docs/signals/coverage.md` per-ID table + quick stats updated accordingly. Post-cleanup: primary bytes = 27, always-zero = 26, static-nonzero = 2, hash = 9, mirror = 2, undecoded = 22 (was 51 pre-ride).

Sub-analysis 12 (coolant walk-up scan across all bytes on moving-1) — done, **no new coolant-derived byte identified**. moving-1's 26 → 85 °C walk was cross-correlated against every payload byte (`scripts/first_moving_ride_coolant_scan.py`). Top r-vs-coolant candidates are all the ABS-lamp bits (r ≈ ±0.82) — a time-coincidence artefact from the ABS lamp extinguishing once early in moving-1, coinciding with the coolant being still low. Below those, everything correlates with RPM/speed instead of coolant. `540 D1` (warmup index) shows the expected coolant correlation but at modest r=+0.33 because of confounding throttle response. Confirms `540 D1` is the only coolant-derived byte on the always-on set.

Sub-analysis 15 (`12D D3:D4` mirror LSB refit) — done. Old fit was 3/64 = 0.046875 km/h/LSB against pre-2026-07-22 (wrong) canonical decode. New fit against corrected canonical (12-bit at 1/10 km/h) across 92 827 frames spanning 0-102 km/h: **slope 0.0577 km/h/LSB, intercept +0.22 km/h, Pearson r = 0.99997, RMS residual 0.245 km/h**. Old 3/64 slope gives 26× worse residual. D3 is now exercised (walks 0..6, previously all-zero), confirming the multi-byte 16-bit BE structure. [[byte-12d-d3-d4-front-mirror]] promoted from `provisional` to `confirmed` on encoding, with the LSB now anchored to the corrected canonical. Coverage table updated. Script: [`scripts/first_moving_ride_d3d4_refit.py`](../../scripts/first_moving_ride_d3d4_refit.py).

Sub-analysis 16 (`540 D1` warmup-index cold walkup cross-check) — done. moving-1's fresh 26 → 87 °C walkup gives a second independent cold-walk (the existing table came from 2026-06-17 Run 1 alone). Under strict-idle filter (throttle < 8, RPM < 2200), the D1 values match the existing table within ±1 LSB at every bin covered: 27-30 °C → 0x14 ✓, 33-42 °C → 0x11 ✓, 84-87 °C → 0x0E ✓. The idle-regime coolant → D1 lookup is corroborated. **New finding en passant**: under near-idle throttle at higher RPM (i.e., during overrun — throttle closed, wheels driving engine), D1 spikes to 60-140 rather than staying at the idle-coolant lookup value. A fuel-injection-quantity signal should be zero during decel fuel-cut, but D1 is elevated. This is another independent argument that D1 is *not* a fuel-injection proxy (already suspected from [[fuel-consumption-derivation-from-torque]] Model 3 rejection); it's some broader engine-management-state index — probably idle-air-bypass position anticipating re-engagement, or a load-derived indexing quantity. [[signal-warmup-index]] updated with the cross-check and the overrun anomaly. Script: [`scripts/first_moving_ride_warmup_index_check.py`](../../scripts/first_moving_ride_warmup_index_check.py).

Sub-analysis 18 (ABS-lamp bit cross-check against 15 historical sessions) — done. **One of the 6 originally-classified ABS-lamp bits demoted.** Cross-check via `scripts/abs_lamp_crosscheck.py` confirmed 5 of 6 (`12A D0 b4`, `12A D1 b0`, `12A D5 b3`, `12E D6 b4`, `12E D6 b5`) stay rock-solid in "lit" polarity across every historical stationary/engine-off/hand-spin session — consistent with lamp state. **`12A D1 b2` demoted**: this bit flips independently in almost every historical capture, including the [[2026-06-24-front-wheel-hand-spin]] where the physical ABS lamp stayed lit (rider observation, engine off) yet D1 b2 dropped 1 → 0 at t+112.9 s. Its co-transition with the real ABS bits in moving-1 was coincidence — the initial classifier didn't cross-check against historical stationary state. New finding [[signal-12a-d1-bit2]] carries the observed pattern (t+2 s init handshake + session-varied later transitions; kill-switch or side-stand mirror are the leading candidates) and lists cheap discriminating experiments. [[signal-abs-lamp]] updated to 5 bits with a Correction blockquote and full cross-check table; `docs/signals/{coverage.md, signals.yaml}` updated. **Lesson worth preserving: bit-classifiers on a single event miss the "would this bit have been in this state anyway" question — always cross-check candidates against sessions with a known-different ground truth for the signal.**

Sub-analysis 17 (`121_A` behavior during shift-cut milliseconds) — done. **Second independent corroboration of the signed-torque interpretation.** During the ~60 ms quickshifter ignition cut, `121_A` should drop sharply if it's torque (combustion produces + torque; remove combustion, only drivetrain drag left = - torque). Partitioned 55 shifts by rider intensity through the cut:
- **Aggressive shifts (rider ON throttle through cut, pre-cut `121_A` > +30, n=3)**: pre μ = +88, in-cut min μ = -38, **Δ = -126 LSB** — a huge drop. Individual: -133, -128, -116.
- **Neutral shifts (rider between, n=5)**: pre μ = +8, cut min μ = +9, Δ = +1 (no change).
- The correlation Δ ~ pre-cut-intensity is the discriminator: no non-torque signal (RPM, throttle, ignition-timing) would produce a 130-LSB dip conditioned on the pre-cut throttle-on state, because none of those change in 60 ms in response to the ignition cut. At the working LSB of 0.25 N·m/LSB, +90 → -38 corresponds to +22.5 → -9.5 N·m = 32 N·m instantaneous drop — matches Svartpilen 401 spec peak torque of 37 N·m. [[byte-121-twin-int16]] updated with this section. Script: [`scripts/first_moving_ride_torque_during_cut.py`](../../scripts/first_moving_ride_torque_during_cut.py).

Sub-analysis 14 (fuel-consumption modelling) — done. **Torque-based fuel model beats the old `RPM × throttle` plan.** `scripts/first_moving_ride_fuel_model.py` integrated the full ride and compared three candidate models against the rider's 3.4 L/100km baseline:

- **Model 2 (torque-based)**: `fuel_mL/s = k · RPM · max(0, 121_A)`. Working `k ≈ 2.83e-6 mL/(RPM·LSB·s)`. Physically grounded (torque × RPM = mechanical power). Automatic decel fuel-cut (during overrun `121_A` averaged -19.5 LSB in this ride; clipping to 0 correctly zeros fuel through 15.6 % of ride distance). Implied thermal efficiency at rider baseline = 27 % if `121_A` LSB ≈ 0.25 N·m/LSB, right in the physically-plausible range for a small gasoline single. Under-predicts idle so needs a small `f_idle ≈ 0.083 mL/s` (~ 0.3 L/hour) constant added — 2 unknowns total, same as the old plan.
- **Model 1 (old `RPM × throttle` plan)** — works decently at cruise but has no way to distinguish overrun from idle-at-RPM. Structural limitation; superseded.
- **Model 3 (540 D1 as injection-pulse proxy)** — under-predicts by ~ 3× at moderate load. D1's nonlinear/saturating response with load doesn't scale like fuel injection. Rejected.

New finding: [[fuel-consumption-derivation-from-torque]] carries the math and calibration numbers. Updated: [[fuel-consumption-absent-from-broadcasts]] Consequences section now points at the torque model. Updated memory: [[project-fuel-consumption-derivation]] carries the new model as the design intent for the Phase 3 firmware ADR (still pending write).

Ride-regime breakdown from this analysis, useful in its own right:

| Regime | Time | Distance | Fraction of ride |
|---|---:|---:|---:|
| Drive (throttle > 3 %, `121_A` > +3) | 429 s | ~ 6.5 km | 45 % |
| Idle stop (speed < 3, throttle < 3 %) | 313 s | 0 | 33 % |
| Transitional | 111 s | ~ 1.6 km | 12 % |
| Overrun (throttle < 3 %, RPM > 2000, `121_A` < -3) | 99 s | 1.50 km | **10 % (15.6 % of distance)** |

The overrun fraction (15.6 % of distance at zero fuel) is a meaningful efficiency win the old plan couldn't model; capturing it is the primary reason to upgrade to the torque-based approach.

Sub-analysis 13 (final `?` byte sweep on the corpus-sweep shortlist) — done, **surfaces one new active byte and zero the rest**. Direct byte-value dumps across the 5-file corpus on every remaining `?` cell:

- `120 D3-D6`: all always-zero across 45 592 frames each → promoted to `0`.
- `129 D0 bits 0, 2`: both never fired across 45 717 frames (the "b0, b2 ?" tail of the gear byte, cleared).
- `129 D1, D2, D4, D5, D6`: all always-zero across 45 717 frames each → promoted to `0`.
- `129 D3`: static latched at `0x01` across 45 717 frames → `? static (0x01)`. New static non-zero constant.
- `12A D2, D3, D4, D6`: all always-zero across 18 205 frames each → `0`.
- `12E D0-D5`: all always-zero across 46 115 frames each → `0`.
- `450 D0-D5`: all always-zero, `D6` latched at `0x28` → 6 more `0` + a static non-zero.
- `5A0 D0-D3, D5, D6`: all always-zero across 9 067 frames each → `0`.
- `5B0 D1-D6`: all always-zero across 9 069 frames each → `0`.
- `540 D0, D4`: all always-zero → `0`.
- `541 D0, D5`: all always-zero → `0`.
- **`541 D3`: NEW active byte.** Takes values {0, 1, 2}, walks monotonically 0 → 1 → 2 at ~5-min intervals since engine-start, resets on key-cycle. Semantic open. New finding: [[signal-541-d3-time-bin]].

Cumulative coverage delta over the full 13 sub-analyses: **51 undecoded bytes → 0**. Every byte in the 88-cell always-on payload now has a classification. Unknown structure is bounded to bits inside `S◐` cells (partially-decoded bytes) and to latent-under-untested-input possibilities on the 44 always-zero cells. No black-box bytes remain.

Sub-analysis 7 (real-load discrimination — `540 D1` and `121 A/B` under rolling load) — done. **Two paddock-stand-era rulings retracted.** `scripts/first_moving_ride_load_scan.py` merges the 5 moving-* logs into a single 9521-point resampled grid (100 ms, engine-running), bins by (RPM, throttle) at 500 RPM × 8-throttle-count resolution, and reports each target's within-bin statistics + within-bin correlations against speed (load proxy) and coolant.

Two clean pivots:

- **[[byte-121-twin-int16]] — new leading hypothesis: signed engine torque.** Under real riding the channels show a strong signed pattern the paddock stand missed: strongly *negative* under overrun (throttle 0 %, RPM above idle; magnitude grows with RPM: -16 @ 3500, -20 @ 4500, -23 @ 5000), near zero at idle, positive and monotonically growing with throttle at fixed RPM (-20 → 0 near ~7 % throttle → +59 at ~38 % throttle at 4500 RPM). Zero-crossing throttle grows with RPM. A and B track within ~1 LSB across every rolling-ride bin — much tighter than paddock's r=0.6-0.96. Peak observed magnitude ~ 75; Svartpilen 401 spec peak torque 37 N·m ⇒ suggestive 0.5 N·m/LSB (unverified). The paddock's "not MAP / not load-driven" ruling — based on r ≤ +0.33 vs RPM×throttle on paddock data — was on inadequate load range. Under real load the signed structure is unmistakable.

- **[[signal-warmup-index]] — paddock's "load ruled out" retracted.** At every off-idle bin the rolling-ride D1 mean is 10-50 LSB above the paddock formula `D1 ≈ 14 + 0.8 × throttle%`. Idle regime still matches (14.8 vs 14). Discrepancy grows with RPM and throttle. Paddock's Δ = -0.10 was correct on its own tiny load excursion, but the load range it tested was too narrow to rule anything out. Load axis is real; whether best modelled as MAP-like, injection-quantity-like, or ignition-map-correction-like still open — needs a controlled load capture (e.g., paired same-RPM/same-throttle segments in different gears, or coast-down runs) to disentangle load from RPM+throttle cleanly.

The retractions are documented as blockquote update-notes at the top of each finding, preserving the earlier paddock text for continuity. Analysis: [`scripts/first_moving_ride_load_scan.py`](../../scripts/first_moving_ride_load_scan.py).

Next experiment (proposed):
- Dash-verified steady-state moving procedure: rider holds ~ 20, 40, 60, 80, 100 km/h on the OEM speedo for 10–15 s each, marks each hold. Pins wheel-speed LSBs absolutely. Also gives a controlled ABS-threshold crossing and (with a walking-pace phase + 3–4 hard front-brake pulses) folds in the motion-brake follow-up from [[2026-07-10-brakes-stationary]].

## Follow-ups

- Update or split this file per sub-analysis as they complete. Each sub-analysis that pins something goes into `docs/findings/`.
- Session `procedure.yaml` was not authored for this ride (freeform). A follow-up scripted moving procedure covering the calibration passes deliberately (dash-verified steady-state hold at multiple speeds) would be higher-value than another freeform session.
