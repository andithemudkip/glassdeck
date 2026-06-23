#!/usr/bin/env python3
"""replay_to_pty.py — emit a capture.log as SLCAN frames into a fake serial port.

Spins up a pty pair, prints the slave device name (use it as the `--port`
for `scripts/capture.py --live`), and re-emits every frame in a capture.log
as the SLCAN line the firmware would have produced. Lets you exercise
`--live` end-to-end without the ESP32 or bike.

Usage (two terminals):
    # term 1 — start the replayer
    python scripts/replay_to_pty.py --session logs/2026-06-17-engine-idle-run-3
    # → prints: pty slave: /dev/ttys004 (or similar)
    #          replaying 32145 frames from <session>

    # term 2 — point --live at the pty
    python scripts/capture.py --live --port /dev/ttys004 --label replay-smoketest

Useful flags:
    --speed N       playback speed multiplier (default 1.0 = original timing)
    --loop          restart from the top when the log ends
    --no-timing     emit as fast as possible (handy for stress-testing the UI)
"""

from __future__ import annotations

import argparse
import os
import pty
import re
import sys
import time
from pathlib import Path

LINE_RE = re.compile(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")


def encode_slcan(arb_hex: str, data_hex: str) -> bytes:
    """Encode an 11-bit standard CAN frame as a SLCAN line."""
    arb = int(arb_hex, 16)
    nbytes = len(data_hex) // 2
    return f"t{arb:03X}{nbytes:X}{data_hex.upper()}\r".encode("ascii")


def iter_frames(path: Path):
    with path.open() as f:
        for line in f:
            m = LINE_RE.match(line)
            if not m:
                continue
            ts = float(m.group(1))
            arb_hex = m.group(2)
            data_hex = m.group(3)
            if len(data_hex) % 2 or len(data_hex) > 16:
                continue
            yield ts, encode_slcan(arb_hex, data_hex)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--session", required=True,
                    help="Path to a session directory containing capture.log.")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="Playback speed multiplier (default 1.0 = real-time).")
    ap.add_argument("--loop", action="store_true",
                    help="Restart from the top when the log ends.")
    ap.add_argument("--no-timing", action="store_true",
                    help="Emit as fast as possible; ignore original frame timing.")
    args = ap.parse_args()

    session = Path(args.session)
    log_path = session / "capture.log"
    if not log_path.is_file():
        print(f"capture.log not found at {log_path}", file=sys.stderr)
        return 2

    frames = list(iter_frames(log_path))
    if not frames:
        print(f"no frames in {log_path}", file=sys.stderr)
        return 2

    master_fd, slave_fd = pty.openpty()
    slave_name = os.ttyname(slave_fd)
    print(f"pty slave: {slave_name}", flush=True)
    print(f"replaying {len(frames)} frames from {session.name}"
          f"  ({'no-timing' if args.no_timing else f'{args.speed:.1f}× real-time'}"
          f"{', looping' if args.loop else ''})", flush=True)
    print(f"now run, in another terminal:", flush=True)
    print(f"  python scripts/capture.py --live --port {slave_name} --watch\n",
          flush=True)

    try:
        while True:
            t_origin = frames[0][0]
            wall_start = time.monotonic()
            emitted = 0
            for orig_ts, slcan_bytes in frames:
                if not args.no_timing:
                    target = wall_start + (orig_ts - t_origin) / args.speed
                    delay = target - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                try:
                    os.write(master_fd, slcan_bytes)
                except OSError as e:
                    print(f"\nlink closed: {e}", file=sys.stderr)
                    return 0
                emitted += 1
                if emitted % 5000 == 0:
                    print(f"  emitted {emitted}/{len(frames)} frames", file=sys.stderr)
            if not args.loop:
                break
            print(f"  end of log — looping", file=sys.stderr)
    except KeyboardInterrupt:
        pass
    finally:
        os.close(master_fd)
        os.close(slave_fd)
    print(f"done; emitted {emitted} frames.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
