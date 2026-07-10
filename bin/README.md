# bin/

Thin, memorable wrappers around the common `pio` / `curl` / `capture.py`
invocations. Nothing here has logic of its own — if a wrapper starts
growing behavior, it belongs in `scripts/` (Python) or the firmware itself.

Add `bin/` to your `PATH` (or invoke as `bin/<name>` from the repo root).

## Firmware

| Command | What it does |
|---|---|
| `build-firmware <sub> [env]` | `pio run` in `firmware/<sub>`. Sub = `can-logger` or `wifi-bridge`. |
| `flash-usb <sub> [env]` | Build + `pio run -t upload` over the USB-Serial/JTAG port. |
| `monitor-serial <sub> [env]` | `pio device monitor`. Ctrl-] to exit. |
| `ota-wifi-bridge [host]` | Build `wifi-bridge`, then `POST /ota` the resulting `firmware.bin`. Host defaults to `192.168.4.1`. |

Envs default to `logger` for `can-logger` and `wifi-bridge` for `wifi-bridge`.
Use `logger-250k` to build the 250 kbps fallback logger.

## Captures

| Command | What it does |
|---|---|
| `capture-usb <label> [--port …] [extra args]` | Auto-detects `/dev/tty.usbmodem*` and runs `scripts/capture.py`. Extra flags pass through (`--bitrate`, `--experiment`, `--watch`, …). |
| `capture-wifi-bridge <label> [host] [extra args]` | Pipes `ws://<host>/stream` into `scripts/capture.py --stdin`. Requires `websocat`. For rider-side captures use the browser at `http://<host>/` — its OPFS path survives WS drops, this desk pipe does not. |
| `experiment-wifi-bridge <label> <procedure.yaml> [host] [extra args]` | Same pipe as `capture-wifi-bridge`, plus `--experiment <yaml>` so the operator TUI drives a procedure over WiFi. Desk-side only; does not survive WS drops. |

## wifi-bridge ops

| Command | What it does |
|---|---|
| `wifi-bridge-health [host]` | `GET /health`, pretty-printed if `jq` is on PATH. |
| `wifi-bridge-mark <label> [host]` | `POST /mark?label=<label>`. Inserts `# MARK <label>` into the ring and fans out on `/stream`. |
| `wifi-bridge-download-capture <path> [host]` | Snapshot `GET /capture` to `<path>`. Snapshot-only — for splice-on-reconnect use the browser. |

## Conventions

- All scripts are bash, `set -euo pipefail`.
- Positional args first, `--flag` args after. `-h` / `--help` prints usage.
- Errors go to stderr with `error:` prefix, progress with `==>`.
- Shared helpers in `_common.sh` (sourced, not executed).
