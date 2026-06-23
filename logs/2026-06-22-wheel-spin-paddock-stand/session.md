# Session: 2026-06-22-wheel-spin-paddock-stand

**Firmware:** can-logger @ 61c64ae
**Bitrate:** 500 kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination [TODO: in / out]
**Capture start:** 2026-06-22T19:27:13+00:00
**Capture end:** 2026-06-22T19:30:50+00:00
**Total frames:** 77694
**Unique IDs:** 11
**Event marks:** 27  (see events.csv)

## Bike state

Ignition ON (position 1), kill switch in RUN, transmission in neutral, **engine OFF throughout**, side stand DOWN, bike held by rear paddock stand only (no front stand available — Phase C of the procedure was skipped). Ambient indoor, evening.

## Rider actions during session

Driven by [`procedure.yaml.snapshot`](procedure.yaml.snapshot). Highlights:

- Early procedure rewinds while getting set up — premature first key-on mark, rewound back to step 1 several times before the real key-on at 19:27:45 UTC (events.csv row 9).
- Phase A: 6 gentle rear-wheel pushes, ~1 s of motion each. Rider deliberately kept these soft to avoid tripping the auto-headlight.
- One stray `b` press at 19:29:19 UTC fell between the first two Phase B pushes (rider testing whether they could press `b` and spin simultaneously — concluded they couldn't). Rider then rewound from step 13 to step 11 and restarted Phase B cleanly. The two pre-rewind Phase B `spin` marks are still in events.csv but should be ignored for analysis; the clean Phase B run is the 8 pushes starting at 19:29:41 UTC.
- Phase B: 8 hard rear-wheel pushes, each ~1–2 s of motion. **No `b` (headlight transition) marks were made** — rider physically can't push the wheel and press a hotkey at the same time. Auto-headlight transitions were observed visually but not timestamped. As a workaround, the rider's report is "headlight came on around the middle of each hard-push step" — roughly t+4 s after each `spin` mark.
- Phase C (front wheel) skipped — no front stand. Rider pressed `q` to end the capture at the Phase C prompt.

## Anomalies

- 90 `12D` motion frames during the inter-phase rest window (+75.8 s → +95.0 s from key-on, peak D2 = 0x34). Almost certainly the rider giving the wheel an extra warm-up spin between Phase A and Phase B. Outside all per-push analysis windows.
- Phase B push 1 (after the restart) — analysis script reports no motion in the t-1→t+6 s window. Almost certainly because the auto-mark fired before the rider was in position; the actual push fell outside the analysis window. Doesn't matter for the finding — pushes 2–8 give 7 clean envelopes.
