# Session: 2026-06-17-engine-idle-run-3

**Firmware:** can-logger @ a9f53db
**Bitrate:** 500 kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination **in place** (not desoldered)
**Capture start:** 2026-06-17T16:18:33+00:00
**Capture end:** 2026-06-17T16:22:24+00:00
**Total frames:** 90216
**Unique IDs:** 11
**Event marks:** 4  (see events.csv)

## Bike state

Engine **at running temperature** at session end. Run 2 ended only ~1.5 min before Run 3 started — minimal key-off cool-down — and another ~3 min of engine-on accumulated during Run 3. Rider-reported coolant gauge at session end: **~half**, i.e. nominal operating temperature for this bike. Bike in neutral, side stand down, no rider on the seat. Ambient ~30 °C, fuel ~50 % (no refuel between runs). Adapter wiring unchanged. Dash: check engine + ABS lit at key-on; check-engine extinguished ~1 s after engine catch; ABS stayed lit (stationary).

## Rider actions during session

Capture started 16:18:33; ~9 s silent head. Key on at 16:18:42.63 (`key_on` mark). Held key-on engine-off for 31.8 s. Starter pressed at 16:19:14.47 (`s` hotkey → `starter button`). Engine settled to idle ~5.22 s later (longer than Run 2 — possibly because the engine was hot enough that the ECU spent longer in startup-enrichment mode, or just rider perception); spacebar pressed at 16:19:19.69 (`idle_settled` second `generic mark`). Held idle for 174.8 s untouched. Kill switch pressed at 16:22:14.44 (`k` hotkey → `kill switch`). Engine decayed, key off after silence, capture stopped at 16:22:24 (~10 s decay tail).

## Anomalies

- WS2812 activity LED still dark — known issue.
- No `bus_err` / status-line cross-check — known limitation. Frame count within ~1 % of Runs 1 and 2.
- **Spacing from Run 2 was only ~1.5 min** — above the ≥60 s power-cycle floor but well below the ~10 min ideal. Combined with the engine-running thermal accumulation across Runs 1 → 2 → 3 (cold → partial-warm → operating temp), the runs are *not* a clean three-power-cycle replicate — they're effectively a thermal sweep. This is an unplanned but useful side effect: any payload byte that encodes coolant temperature should differ between Run 1 (cold) and Run 3 (operating) in a monotone direction. Flagged for Phase 2 payload-diff work.
