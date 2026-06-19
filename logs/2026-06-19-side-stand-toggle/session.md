# Session: 2026-06-19-side-stand-toggle

**Firmware:** can-logger @ 61c64ae
**Bitrate:** 500 kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination [TODO: in / out]
**Capture start:** 2026-06-19T13:03:15+00:00
**Capture end:** 2026-06-19T13:04:34+00:00
**Total frames:** 28943
**Unique IDs:** 11
**Event marks:** 7  (see events.csv)

## Bike state

- Key on (position 1), engine off, kill switch in RUN, neutral.
- Bike on a paddock / centre stand throughout (side stand could be lifted without affecting balance).
- Ambient: indoor garage.

## Rider actions during session

- `mark` @ +0 s — key-on, stand DOWN, settle 30 s before first toggle.
- Six `j` presses, each at the instant the side stand reached its new position, ~5 s held between each:
  - `j[0]` — DOWN → UP
  - `j[1]` — UP → DOWN
  - `j[2]` — DOWN → UP
  - `j[3]` — UP → DOWN
  - `j[4]` — DOWN → UP
  - `j[5]` — UP → DOWN
- Stand left DOWN at end. Key off. `q`.

## Dash reaction

Kickstand icon / interlock indicator was visible on the cluster and tracked the stand state during the toggles.

## Anomalies

None.
