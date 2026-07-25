# Session: 2026-07-24-abs-mode-toggle-3

**Firmware:** can-logger @ 4855deb
**Bitrate:** 500 kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination [TODO: in / out]
**Capture start:** 2026-07-24T15:21:42+00:00
**Capture end:** 2026-07-24T15:24:20+00:00
**Total frames:** 33862
**Unique IDs:** 11
**Event marks:** 5  (see events.csv)
**Clock:** wifi-bridge `(sec.us)` prefixes normalized to host wall-clock (added +1784906365.698094 s to every frame; capture.log frames and events.csv marks share one time base)

## Bike state

Key ON, engine OFF throughout. Kill switch RUN, neutral. **Side stand UP, rider seated** — the planned "stand-down / rider-standing" setup was not possible because the side-stand-down warning takes over the dash and blocks all menu navigation on this bike (see [[project-dash-menu-blocked-by-sidestand]]). Rider had to sit on the bike to keep it upright with the stand up.

Starting ABS mode: **ROAD** (read from the 4 s startup display).

## Rider actions during session

Followed the procedure YAML as authored. All 4 SET-holds took effect — dash mode indicator changed cleanly on each hold, no flash-fault behavior, no delays. Sequence: ROAD → SUPERMOTO → ROAD → SUPERMOTO → ROAD (round-tripped as planned).

Dash UX for each toggle: SET press → "keep holding" prompt → ~3 s later "release" prompt → rider releases → old mode shown for ~0.5 s → new mode appears. Consistent across all 4 toggles.

## Anomalies

None. Third attempt of the day — first attempt (`2026-07-24-abs-mode-toggle/`) captured only 13 s of frames before the wifi-bridge websocket apparently dropped silently; second attempt (`2026-07-24-abs-mode-toggle-2/`) had 0 frames (connection setup problem). This third attempt ran cleanly end-to-end with ~250 fps sustained.
