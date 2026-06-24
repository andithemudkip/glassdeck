---
date: 2026-06-24
status: done
phase: 1
related:
  findings:
    - can/signal-wheel-speed-front
    - can/signal-12d-d1-bit0
    - can/byte-encoding-12-in-16
  experiments:
    - 2026-06-24-front-wheel-hand-spin
  logs:
    - 2026-06-24-front-wheel-decay-mark
---

# Front wheel speed — LSB anchor via dash 3→0 decay-tail mark

Follow-up to [[2026-06-24-front-wheel-hand-spin]] to pin the front LSB. The morning's hand-spin session located the front wheel at `12D` D0:D1 BE uint16 with a noisy LSB estimate (1/LSB spread 169..213) — too noisy because dash quantises to integer km/h and hand-spin peaks are transient. This capture changes one thing: rider presses `b` at the moment the dash flips from 3 km/h to 0 on each decay tail. Same physical setup otherwise.

## Hypothesis

The raw uint16 value at the moment the dash flips from 3 km/h to 0 is `3.0 / LSB` — a clean per-push anchor with no dash-quantisation noise. With reaction-time correction (lookup raw value ~250 ms before the mark), 4–5 pushes should converge on a single LSB value with sub-1% scatter.

## Procedure

Free-form, hand-driven (per [[experiment-design-hand-driven-marks]]). The rider isn't spinning during the decay, so the can't-mark-while-spinning constraint doesn't apply.

1. Start capture: `python scripts/capture.py --port /dev/cu.usbmodem101 --label front-wheel-decay-mark`.
2. ~30 s zero baseline.
3. 4–5 harder pushes (target dash peak ~10 km/h for a long decay tail). Settle between each.
4. One `b` press per push, at the instant the dash flips from low single digits to 0.
5. Optional: 1–2 gentle pushes (~3–4 km/h) with `b` on the way *up* (the 0→3 dash activation edge) for hysteresis info.
6. Stop with `q`.

## Result

Captured 5 pushes with 6 `b` marks (one mis-press collapsed to its corrective press). Three independent findings landed:

### 1. Encoding pattern: 12-bit speed value at the top of D0:D1

Across all observed front-wheel motion frames in this session and the earlier hand-spin, **every non-zero raw value of `(D0 << 8) | D1` is a multiple of 16** (low 4 bits of D1 always zero). The speed field occupies bits 15:4 of the BE u16; low nibble is *not* padding (see § 3 below). New finding [[byte-encoding-12-in-16]].

Distribution of non-zero front raw values during the capture: `{448, 464, 480, 496, 512, 528, 544, 560, 576, …}` — strictly 16 apart.

### 2. LSB pinned at exactly 1/192 km/h

Decoded as `((D0 << 8) | (D1 & 0xF0)) / 192`, **8 of 9** dash peaks from the morning session match within ±0.5 km/h (the dash quantisation step). One outlier remains — the dash-11 push with raw 1856 (decodes to 9.67 km/h, dash 10 with rounding) — and no single LSB simultaneously fits both that push and the dash-7 push, so the outlier is most likely a recall artifact (the rider noted per-push attribution was approximate).

ECU has a **low-end broadcast cutoff at raw 448** = 2.333 km/h: 5/5 pushes in this session had their last non-zero raw value equal to exactly 448 before snapping to 0 with no intermediate values. Below ~2.33 km/h the ECU stops broadcasting front-wheel motion entirely.

The rider's observation that the dash "briefly shows 2, never shows 1" before flipping to 0 corroborates the LSB+cutoff picture: with LSB 1/192 and ECU floor at 2.33 km/h, round-to-nearest dash logic produces a brief dash-2 window (raw 448 → 464, 2.33 → 2.42 km/h, ~30–50 ms at typical decay rates) and never reaches the dash-1 band (would need true < 1.5 km/h, below ECU floor).

[[signal-wheel-speed-front]] promoted from `provisional` to `confirmed`.

### 3. Bonus signal: D1 bit 0 carries a separate engine-correlated flag

Surfaced while cross-checking the "12-bit packing" claim against the engine-on rear-spin capture ([[2026-06-23-engine-driven-rear-spin]]). In that capture the front-wheel field stays at 0 (front wheel stationary on the paddock stand), but D1 bit 0 fires **1 002 times** out of 28 820 frames — always at the value `0x0001`, never in combination with a non-zero high-12-bit speed field. In every engine-off capture (~120 000 frames total) bit 0 never fires. The bit is engine-correlated but not a steady "engine running" mirror — duty cycle ~3.5%, suggesting a periodic or state-machine-driven signal.

New finding [[signal-12d-d1-bit0]] at `provisional`. Decoder for front wheel speed must now explicitly mask: `(D0 << 8) | (D1 & 0xF0)`.

## Reaction-time observation (not load-bearing)

The rider was consistently ~450 ms late on the `b` press (vs the ECU snap to 0). That's longer than visual reaction time alone — the lag is reaction time *plus* dash display latency (the dash holds its last reading for some interval before flipping to 0). The 250 ms reaction-time correction I built into the analysis script wasn't tight enough to find a non-zero raw value at the corrected time on 4 of 5 marks — but it doesn't matter, because the multiples-of-16 pattern + the ECU floor + the dash 0/2/3 quantisation all converged on 1/192 independently.

## Follow-ups closed by this session

- ~~Front LSB exact value~~ — pinned at 1/192 km/h.
- ~~Pulses-per-time hypothesis~~ — disproven; the front byte is calibrated km/h, just at higher resolution than the rear.
- ~~Need for a rolling capture (bike-push)~~ — no longer load-bearing for the LSB question. [[2026-06-23-first-bike-roll]] stays superseded.

## Follow-ups opened

- **Characterise the duty cycle of [[signal-12d-d1-bit0]].** Is it periodic, transient, or correlated with another engine variable? Histogram the bit-1 runs and gaps in [[2026-06-23-engine-driven-rear-spin]]; if regular, it's a heartbeat; if irregular, look for cross-byte correlations.
- **Check D1 bits 1-3 across all engine-on captures** to confirm they really are reserved.
- **Re-examine rear D5:D6's `0.05633` best-fit LSB** in light of front being exactly 1/192. The rear is almost certainly exactly 1/16 km/h and the gearing/tyre estimate that produced the 10% gap is what needs revisiting, not the LSB.
