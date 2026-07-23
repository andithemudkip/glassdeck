#!/usr/bin/env python3
"""replay_browser.py — serve the wifi-bridge live view backed by a capture log.

Runs the same gen_wifi_bridge_index.py the firmware build uses to codegen
`SIGNALS[]` into `index.html`, serves the merged HTML at `/`, stubs `/health`,
and replays a session's CAN log through `/stream` (WebSocket) at recorded
cadence. Point a browser at http://localhost:8080/ to render the actual
live view against a recorded ride — no bike or ESP required.

Handles both log formats we've captured:
    (unix_ts)  can0 12D#0000000000000000       ← Phase 1 candump-style
    (sec.us)   t12D80000000000000008B          ← firmware SLCAN + ADR 0018 ts
The wifi-bridge JS strips the (sec.us) prefix internally, so we always
emit that form and forward the original timestamp verbatim.

Usage:
    python scripts/replay_browser.py                          # default session, real time
    python scripts/replay_browser.py --session logs/2026-07-22-first-moving-ride
    python scripts/replay_browser.py --pattern 'moving-*.log' # multi-file session, sorted
    python scripts/replay_browser.py --speed 4                # 4x playback
    python scripts/replay_browser.py --no-timing              # firehose (UI stress)
    python scripts/replay_browser.py --loop                   # restart on EOF
    python scripts/replay_browser.py --port 8081
"""

from __future__ import annotations

import argparse
import asyncio
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from aiohttp import WSMsgType, web

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "firmware" / "wifi-bridge" / "main" / "index.html"
SCHEMA = REPO_ROOT / "docs" / "signals" / "signals.yaml"
CODEGEN = REPO_ROOT / "scripts" / "gen_wifi_bridge_index.py"

# Old candump-style: "(1781713122.693132) can0 12D#0000... [R]"
CANDUMP_RE = re.compile(r"^\((\d+(?:\.\d+)?)\)\s+\S+\s+([0-9A-Fa-f]{3,8})#([0-9A-Fa-f]*)")
# Firmware SLCAN with (sec.us) prefix: "(63.519656) t12D80000..."
SLCAN_RE = re.compile(r"^\((\d+)\.(\d+)\)\s+(t[0-9A-Fa-f]+)")


def build_html() -> bytes:
    """Run gen_wifi_bridge_index.py into a tempfile; return the merged bytes."""
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".html", delete=False) as tmp:
        out_path = Path(tmp.name)
    try:
        subprocess.check_call([
            sys.executable, str(CODEGEN),
            "--template", str(TEMPLATE),
            "--schema", str(SCHEMA),
            "--out", str(out_path),
        ])
        return out_path.read_bytes()
    finally:
        try: out_path.unlink()
        except OSError: pass


def parse_line(line: str) -> tuple[float, str] | None:
    """Return (ts_seconds, slcan_frame_without_prefix) or None if unparseable.

    slcan_frame is the raw 't<arb><dlc><data>' form the wifi-bridge firmware
    would have emitted on its serial output.
    """
    line = line.rstrip("\r\n")
    if not line: return None
    m = SLCAN_RE.match(line)
    if m:
        sec, us, slcan = m.group(1), m.group(2), m.group(3)
        return (int(sec) + int(us) / 1e6, slcan)
    m = CANDUMP_RE.match(line)
    if m:
        ts = float(m.group(1))
        arb_hex = m.group(2)
        data_hex = m.group(3)
        try:
            arb = int(arb_hex, 16)
        except ValueError:
            return None
        if len(data_hex) % 2: return None
        dlc = len(data_hex) // 2
        if dlc > 8: return None  # SLCAN classic max
        # SLCAN standard-ID frame: 't' + 3-hex arb + 1-hex dlc + 2*dlc hex data.
        slcan = f"t{arb & 0x7FF:03X}{dlc:X}{data_hex.upper()}"
        return (ts, slcan)
    return None


def collect_log_paths(session: Path, pattern: str | None) -> list[Path]:
    if pattern:
        paths = sorted(session.glob(pattern))
        if not paths:
            raise FileNotFoundError(f"no files matching {pattern!r} in {session}")
        return paths
    single = session / "capture.log"
    if single.is_file(): return [single]
    logs = sorted(session.glob("*.log"))
    if not logs:
        raise FileNotFoundError(f"no *.log under {session}")
    return logs


def iter_frames(paths: list[Path]):
    """Yield (ts_s, slcan) across all paths. Bad lines silently skipped."""
    for p in paths:
        with p.open() as f:
            for line in f:
                parsed = parse_line(line)
                if parsed is not None:
                    yield parsed


# Global counter surfaced to /health, so pollHealth sees frames climb.
STATS = {"frames_seen": 0, "started": time.monotonic()}


async def stream_handler(request: web.Request) -> web.WebSocketResponse:
    cfg = request.app["cfg"]
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    print(f"[replay] /stream connected from {request.remote}", flush=True)

    async def pump() -> None:
        # Loop the whole log set until either --loop is off (one pass) or
        # the client disconnects (caught by the send-side exception).
        while True:
            first_ts: float | None = None
            wall_start = time.monotonic()
            for ts, slcan in iter_frames(cfg["paths"]):
                if first_ts is None: first_ts = ts
                if not cfg["no_timing"]:
                    target = wall_start + (ts - first_ts) / cfg["speed"]
                    delay = target - time.monotonic()
                    if delay > 0:
                        await asyncio.sleep(delay)
                # Firmware emits "(sec.us) <slcan>\r\n"; the browser's ws.js
                # strips the prefix before decoding. Reconstruct exactly.
                sec = int(ts); us = int((ts - sec) * 1_000_000)
                payload = f"({sec}.{us:06d}) {slcan}"
                try:
                    await ws.send_str(payload)
                except ConnectionResetError:
                    return
                STATS["frames_seen"] += 1
            if not cfg["loop"]: return

    pump_task = asyncio.create_task(pump())
    try:
        # Drain client → server (control frames, an eventual close) so aiohttp
        # doesn't buffer them forever. We don't care about the payloads.
        async for msg in ws:
            if msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                break
    finally:
        pump_task.cancel()
        try: await pump_task
        except asyncio.CancelledError: pass
        print(f"[replay] /stream disconnected {request.remote}", flush=True)
    return ws


async def health_handler(request: web.Request) -> web.Response:
    uptime_ms = int((time.monotonic() - STATS["started"]) * 1000)
    return web.json_response({
        "ap_client_rssi_dbm": -55,
        "uptime_ms": uptime_ms,
        "twai_state": "running",
        "frames_seen": STATS["frames_seen"],
        "frames_ws_dropped": 0,
    })


async def index_handler(request: web.Request) -> web.Response:
    return web.Response(
        body=request.app["html"],
        content_type="text/html",
        charset="utf-8",
    )


def build_app(cfg: dict, html: bytes) -> web.Application:
    app = web.Application()
    app["cfg"] = cfg
    app["html"] = html
    app.router.add_get("/", index_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/stream", stream_handler)
    return app


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--session", type=Path,
                    default=REPO_ROOT / "logs" / "2026-07-22-first-moving-ride",
                    help="session directory under logs/ (default: 2026-07-22-first-moving-ride)")
    ap.add_argument("--pattern", type=str, default=None,
                    help="glob within the session directory (default: capture.log, else *.log sorted)")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="playback speed multiplier (default 1.0)")
    ap.add_argument("--no-timing", action="store_true",
                    help="emit as fast as possible (ignores recorded cadence)")
    ap.add_argument("--loop", action="store_true",
                    help="restart from the top when the log ends")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    session = args.session if args.session.is_absolute() else (REPO_ROOT / args.session).resolve()
    if not session.is_dir():
        print(f"error: session {session} not found", file=sys.stderr)
        return 2
    paths = collect_log_paths(session, args.pattern)
    total_lines = sum(1 for p in paths for _ in p.open())
    print(f"[replay] session:    {session}")
    print(f"[replay] logs:       {', '.join(p.name for p in paths)} ({total_lines} lines)")
    print(f"[replay] speed:      {'firehose' if args.no_timing else f'{args.speed}x'}")
    print(f"[replay] loop:       {args.loop}")

    print(f"[replay] rebuilding merged HTML via {CODEGEN.name}…")
    html = build_html()
    print(f"[replay] HTML:       {len(html):,} bytes")

    cfg = {
        "paths": paths,
        "speed": args.speed,
        "no_timing": args.no_timing,
        "loop": args.loop,
    }
    print(f"[replay] listening on http://{args.host}:{args.port}/  (Ctrl-C to stop)")
    web.run_app(build_app(cfg, html), host=args.host, port=args.port, print=lambda *_: None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
