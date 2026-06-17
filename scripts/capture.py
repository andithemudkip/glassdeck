#!/usr/bin/env python3
"""capture.py — host-side CAN capture script for the can-logger firmware.

Opens the ESP32-S3's USB-CDC serial port with pyserial, parses incoming
SLCAN (Lawicel ASCII) lines into `can.Message` objects, writes them to
`logs/<date>-<label>/capture.log` in candump format with host timestamps,
and lets you press hotkeys during the session to mark rider actions into a
sidecar `events.csv`. On exit, drops a `session.md` stub for you to fill in.

The firmware is firmware→host only (ADR 0004); python-can's `slcan`
interface assumes a Lawicel adapter that answers config commands and
blocks in `tcdrain()` if it doesn't, so we read the serial port directly
and parse the same wire format ourselves.

Usage:
    python scripts/capture.py --port /dev/tty.usbmodem* --label key-on
    python scripts/capture.py --port <port> --label idle --bitrate 250000

Press '?' during capture for the hotkey legend. Ctrl-C (or 'q') to stop.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import select
import subprocess
import sys
import termios
import threading
import time
import tty
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Max bytes for one SLCAN line: T (1) + id (8) + dlc (1) + data (16) + \r (1)
# plus slack for the firmware's `# ...` status comment lines.
SLCAN_MAX_LINE = 128

# Hotkey → (CSV key, human label). Anything else the user presses is recorded
# verbatim with no label, so ad-hoc markers are still captured.
HOTKEYS: dict[str, tuple[str, str]] = {
    " ": ("mark", "generic mark"),
    "i": ("indicator", "indicator left"),
    "I": ("indicator", "indicator right"),
    "b": ("beam", "high beam toggle"),
    "g": ("gear", "gear shift"),
    "n": ("neutral", "neutral"),
    "m": ("mode", "ROAD/SUPERMOTO toggle"),
    "r": ("trip", "trip reset"),
    "t": ("throttle", "throttle blip"),
    "k": ("kill", "kill switch"),
    "s": ("start", "starter button"),
    "h": ("horn", "horn"),
    "e": ("idle_settled", "idle settled"),
}

LEGEND = """
  space  generic mark         i  indicator L     I  indicator R
  b      high beam            g  gear shift      n  neutral
  m      ROAD/SUPERMOTO       r  trip reset      t  throttle blip
  k      kill switch          s  starter         h  horn
  e      idle settled         ?  this legend     q  stop capture
  (any other key: recorded raw, label it later in session.md)
"""


def parse_slcan_line(line: bytes, timestamp: float):
    """Parse one SLCAN line into a `can.Message`, or return None.

    Returns None for empty lines, firmware `# ...` status comments, and
    malformed frames. Importing `can` lazily so this module loads even
    when python-can isn't installed yet.
    """
    import can

    s = line.strip(b"\r\n\x00 \t")
    if not s:
        return None
    head = s[:1]
    if head not in (b"t", b"T", b"r", b"R"):
        return None
    extended = head in (b"T", b"R")
    rtr = head in (b"r", b"R")
    id_hex_len = 8 if extended else 3
    if len(s) < 1 + id_hex_len + 1:
        return None
    try:
        arb_id = int(s[1 : 1 + id_hex_len], 16)
        dlc = int(s[1 + id_hex_len : 2 + id_hex_len], 16)
    except ValueError:
        return None
    data = b""
    if not rtr:
        nbytes = min(dlc, 8)
        start = 2 + id_hex_len
        hex_data = s[start : start + nbytes * 2]
        if len(hex_data) != nbytes * 2:
            return None
        try:
            data = bytes.fromhex(hex_data.decode("ascii"))
        except ValueError:
            return None
    return can.Message(
        timestamp=timestamp,
        arbitration_id=arb_id,
        is_extended_id=extended,
        is_remote_frame=rtr,
        dlc=dlc,
        data=data,
        channel="can0",
    )


def detect_firmware_rev() -> str | None:
    """Best-effort git short-hash of firmware/can-logger/."""
    try:
        out = subprocess.run(
            ["git", "log", "-n", "1", "--pretty=%h", "--", "firmware/can-logger"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=2,
        )
        rev = out.stdout.strip()
        return rev or None
    except (FileNotFoundError, subprocess.SubprocessError):
        return None


class EventLogger:
    """Append-only writer for events.csv. Thread-safe."""

    def __init__(self, path: Path) -> None:
        self._lock = threading.Lock()
        self._file = path.open("w", newline="")
        self._writer = csv.writer(self._file)
        self._writer.writerow(["timestamp_iso", "timestamp_monotonic", "key", "label"])
        self._file.flush()
        self.count = 0

    def log(self, key: str, label: str) -> None:
        now_iso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds")
        now_mono = time.monotonic()
        with self._lock:
            self._writer.writerow([now_iso, f"{now_mono:.6f}", key, label])
            self._file.flush()
            self.count += 1

    def close(self) -> None:
        with self._lock:
            self._file.close()


class KeyReader(threading.Thread):
    """Reads single keystrokes from stdin in cbreak mode and dispatches them."""

    def __init__(self, events: EventLogger, stop_flag: threading.Event) -> None:
        super().__init__(daemon=True)
        self.events = events
        self.stop_flag = stop_flag
        self._fd = sys.stdin.fileno()
        self._old_attrs = None

    def __enter__(self) -> "KeyReader":
        if sys.stdin.isatty():
            self._old_attrs = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        if self._old_attrs is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_attrs)

    def run(self) -> None:
        if not sys.stdin.isatty():
            return
        while not self.stop_flag.is_set():
            r, _, _ = select.select([self._fd], [], [], 0.2)
            if not r:
                continue
            ch = os.read(self._fd, 1).decode("utf-8", errors="replace")
            if not ch:
                continue
            if ch == "q" or ch == "\x03":  # q or Ctrl-C
                self.stop_flag.set()
                return
            if ch == "?":
                sys.stderr.write("\n" + LEGEND + "\n")
                sys.stderr.flush()
                continue
            if ch in HOTKEYS:
                key, label = HOTKEYS[ch]
                self.events.log(key, label)
            elif ch.isprintable():
                self.events.log(ch, "")


def resolve_session_dir(label: str) -> Path:
    today = dt.date.today().isoformat()
    name = f"{today}-{label}"
    session = REPO_ROOT / "logs" / name
    session.mkdir(parents=True, exist_ok=True)
    capture_path = session / "capture.log"
    if capture_path.exists() and capture_path.stat().st_size > 0:
        sys.exit(
            f"refusing to overwrite existing capture at {capture_path}.\n"
            f"logs/ is immutable — pick a different --label (e.g. '{label}-2')."
        )
    return session


def write_session_stub(
    session_dir: Path,
    label: str,
    bitrate: int,
    fw_rev: str | None,
    start_iso: str,
    end_iso: str,
    total_frames: int,
    unique_ids: int,
    event_count: int,
) -> None:
    path = session_dir / "session.md"
    if path.exists():
        return
    fw_line = f"can-logger @ {fw_rev}" if fw_rev else "can-logger @ <TODO: commit hash>"
    bitrate_kbps = bitrate // 1000
    content = f"""# Session: {session_dir.name}

**Firmware:** {fw_line}
**Bitrate:** {bitrate_kbps} kbps
**Adapter:** ESP32-S3-DevKitC-1 + SN65HVD230, GPIO4/5, on-board 120 Ω termination [TODO: in / out]
**Capture start:** {start_iso}
**Capture end:** {end_iso}
**Total frames:** {total_frames}
**Unique IDs:** {unique_ids}
**Event marks:** {event_count}  (see events.csv)

## Bike state
<TODO: ignition position, gear, engine running, ambient temp, anything odd>

## Rider actions during session
<TODO: narrative if events.csv isn't enough on its own>

## Anomalies
<TODO or "none">
"""
    path.write_text(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", required=True, help="ESP32 USB-CDC port (e.g. /dev/tty.usbmodem101)")
    parser.add_argument("--label", default="capture", help="Session label (becomes part of logs/<date>-<label>/)")
    parser.add_argument("--bitrate", type=int, default=500_000, help="CAN bitrate in bps (must match firmware build)")
    parser.add_argument(
        "--firmware-rev",
        default=None,
        help="Firmware git short hash; auto-detected from firmware/can-logger/ if omitted",
    )
    parser.add_argument(
        "--silence-warn-secs",
        type=float,
        default=5.0,
        help="Seconds of bus silence before printing the bring-up diagnostic",
    )
    args = parser.parse_args()

    try:
        import can
    except ImportError:
        sys.exit(
            "python-can is not installed.\n"
            "  pip install -r scripts/requirements.txt"
        )
    try:
        import serial
    except ImportError:
        sys.exit(
            "pyserial is not installed.\n"
            "  pip install -r scripts/requirements.txt"
        )

    session_dir = resolve_session_dir(args.label)
    fw_rev = args.firmware_rev or detect_firmware_rev()

    sys.stderr.write(f"capture session: {session_dir}\n")
    sys.stderr.write(f"port: {args.port}   bitrate: {args.bitrate} bps   firmware: {fw_rev or 'unknown'}\n")
    sys.stderr.write("press '?' for hotkey legend, 'q' or Ctrl-C to stop.\n\n")

    events = EventLogger(session_dir / "events.csv")
    stop = threading.Event()

    start_time = time.monotonic()
    start_iso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    total_frames = 0
    unique_ids: set[int] = set()
    silence_warned = False
    last_status = 0.0

    try:
        # USB-CDC ignores baudrate; pyserial still needs a value. 1 s read
        # timeout matches the original bus.recv() cadence so the status line
        # ticks and the stop flag is checked at least once per second.
        ser = serial.Serial(args.port, baudrate=115200, timeout=1.0)
    except KeyboardInterrupt:
        events.close()
        sys.stderr.write("\naborted before capture started.\n")
        return 1
    except (serial.SerialException, OSError) as e:
        events.close()
        sys.exit(f"failed to open serial port {args.port}: {e}")

    writer = can.Logger(filename=str(session_dir / "capture.log"))

    with KeyReader(events, stop):
        try:
            while not stop.is_set():
                try:
                    line = ser.read_until(b"\r", size=SLCAN_MAX_LINE)
                except (serial.SerialException, OSError) as e:
                    # Adapter unplugged, serial port closed — anything that
                    # breaks the link mid-run. Record where capture died,
                    # then fall through to finally to save what we have.
                    sys.stderr.write(f"\nbus disconnected: {e}\n")
                    events.log("disconnect", f"{type(e).__name__}: {e}")
                    stop.set()
                    break
                if line.endswith(b"\r"):
                    msg = parse_slcan_line(line, time.time())
                    if msg is not None:
                        writer.on_message_received(msg)
                        total_frames += 1
                        unique_ids.add(msg.arbitration_id)

                now = time.monotonic()
                elapsed = now - start_time

                if not silence_warned and total_frames == 0 and elapsed > args.silence_warn_secs:
                    sys.stderr.write(
                        "\n"
                        f"no frames after {elapsed:.0f}s — the bus looks silent. check:\n"
                        "  1. you opened the right port — the firmware emits on the chip's native\n"
                        "     USB-Serial/JTAG (the port labelled USB on the DevKitC-1), not the\n"
                        "     UART/COM bridge port. macOS typically enumerates both as\n"
                        "     /dev/cu.usbmodem* — `ls -la /dev/cu.*` shows timestamps to disambiguate.\n"
                        "  2. continuity from diagnostic connector to transceiver (pin 2 CANH, pin 5 CANL, pin 3 GND)\n"
                        "  3. bike at key-on (ignition position 1)\n"
                        "  4. firmware bitrate matches the bus — if 500 kbps stays silent, try:\n"
                        "       cd firmware/can-logger && pio run -e logger-250k -t upload\n"
                        "     and re-run capture with --bitrate 250000\n"
                        "still listening...\n\n"
                    )
                    silence_warned = True

                if now - last_status >= 1.0:
                    mins, secs = divmod(int(elapsed), 60)
                    hours, mins = divmod(mins, 60)
                    sys.stderr.write(
                        f"\r[{hours:02d}:{mins:02d}:{secs:02d}]  "
                        f"{total_frames:>8} frames   {len(unique_ids):>3} IDs   "
                        f"{events.count:>3} marks"
                    )
                    sys.stderr.flush()
                    last_status = now
        except KeyboardInterrupt:
            stop.set()
        finally:
            sys.stderr.write("\n")
            try:
                writer.stop()
            except Exception:
                pass
            try:
                ser.close()
            except Exception:
                pass
            events.close()

    end_iso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    write_session_stub(
        session_dir,
        args.label,
        args.bitrate,
        fw_rev,
        start_iso,
        end_iso,
        total_frames,
        len(unique_ids),
        events.count,
    )
    sys.stderr.write(
        f"\ncaptured {total_frames} frames, {len(unique_ids)} unique IDs, {events.count} event marks.\n"
        f"now fill in the TODOs in {session_dir / 'session.md'}.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
