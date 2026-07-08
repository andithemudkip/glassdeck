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
import re
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
    "j": ("sidestand", "side stand"),
    "c": ("clutch", "clutch pump"),
}

LEGEND = """
  space  generic mark         i  indicator L     I  indicator R
  b      high beam            g  gear shift      n  neutral
  m      ROAD/SUPERMOTO       r  trip reset      t  throttle blip
  k      kill switch          s  starter         h  horn
  e      idle settled         j  side stand      c  clutch pump
  ?      this legend          q  stop capture
  w      pin a signal to the Watch pane (live-only)
  u      unpin a Watch entry                     .  snapshot
  (any other key: recorded raw, label it later in session.md)

  -- ADR 0010 (live-view only) --
  F1..F5     collapse / expand pane (top→bottom)
  F6 / F7    z-threshold +0.5 / -0.5    Shift-←→  activity ratio ±0.5
  Ctrl-D     toggle D7                  Ctrl-Y    toggle suppressed
  Ctrl-N     capture hypothesis from active byte / continuous bit
  Ctrl-E     arm expect-shape lens (highlight matching rows; ADR 0013)
"""


# wifi-bridge M4 (ADR 0018) emits every frame with a leading `(<sec>.<us>) `
# stamp so that a browser-side capture download reproduces the same candump
# shape scripts/capture.py writes when timestamping on the host. Regex here
# tolerates both prefixed (wifi-bridge) and unprefixed (can-logger USB) input
# — see docs/decisions/0018-m4-browser-primary-capture.md § Downstream tolerance.
_TS_PREFIX_RE = re.compile(rb"^\((\d+)\.(\d+)\)\s+")


def parse_slcan_line(line: bytes, timestamp: float):
    """Parse one SLCAN line into a `can.Message`, or return None.

    Returns None for empty lines, firmware `# ...` status comments, and
    malformed frames. If the line carries a wifi-bridge `(<sec>.<us>) `
    prefix, the parsed send-time replaces the host `timestamp` argument.
    Importing `can` lazily so this module loads even when python-can
    isn't installed yet.
    """
    import can

    s = line.strip(b"\r\n\x00 \t")
    if not s:
        return None
    m = _TS_PREFIX_RE.match(s)
    if m is not None:
        try:
            timestamp = float(m.group(1)) + float(m.group(2)) / 1_000_000.0
        except ValueError:
            pass  # keep host timestamp
        s = s[m.end():]
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


class NullEventLogger:
    """Drop-in EventLogger for --watch: counts marks (so the live view's
    `marks N` status stays meaningful) but never touches disk."""

    def __init__(self) -> None:
        self.count = 0

    def log(self, key: str, label: str) -> None:
        self.count += 1

    def close(self) -> None:
        pass


class _NullCanLogger:
    """can.Logger stand-in for --watch — accepts frames, writes nothing."""

    def on_message_received(self, msg) -> None:
        pass

    def stop(self) -> None:
        pass


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
    parser.add_argument("--port", default=None, help="ESP32 USB-CDC port (e.g. /dev/tty.usbmodem101). Mutually exclusive with --stdin.")
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read SLCAN from stdin instead of a serial port. Intended for "
             "`websocat -n ws://<esp>/stream | capture.py --stdin --label <lbl>`. "
             "Incompatible with --live / --watch / --experiment (they need stdin "
             "for hotkeys). No silence-warn diagnostic — SLCAN reception depends "
             "on whatever produced the stdin bytes, out of our control.",
    )
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
    parser.add_argument(
        "--live",
        action="store_true",
        help="Open a Textual TUI with decoded signals + flipped-since-mark pane "
             "(see scripts/live_view.py and ADR 0005). Writes live_decode.csv "
             "next to capture.log; snapshot hotkey '.' dumps snapshot-<n>.json.",
    )
    parser.add_argument(
        "--show-d7",
        action="store_true",
        help="Include D7 bytes in the live unknown-bits pane (off by default — "
             "D7 churns deterministically per byte-d7-cycle-hash and "
             "would swamp the pane). Snapshot JSON always records D7 flips.",
    )
    parser.add_argument(
        "--anomaly-z-threshold",
        type=float,
        default=3.0,
        help="z-score threshold above which a bit-flip is treated as anomalous "
             "(ADR 0007). Higher = stricter / fewer rows; lower = noisier panes.",
    )
    parser.add_argument(
        "--anomaly-warmup-flips",
        type=int,
        default=5,
        help="Number of initial flips per bit during which every flip surfaces "
             "with z=∞, before the EWMA baseline takes over (ADR 0007).",
    )
    parser.add_argument(
        "--discovery-retention-secs",
        type=float,
        default=60.0,
        help="How long an anomalous flip stays visible in the continuous "
             "discovery pane before aging out (ADR 0007).",
    )
    parser.add_argument(
        "--show-suppressed",
        action="store_true",
        help="In the mark-driven pane, also surface bits whose EWMA verdict "
             "suppressed them (ADR 0007). Orthogonal to --show-d7.",
    )
    parser.add_argument(
        "--byte-activity-window-secs",
        type=float,
        default=2.0,
        help="Rolling window over which a byte's short_range is computed for "
             "the active-unknown-bytes pane (ADR 0008).",
    )
    parser.add_argument(
        "--byte-activity-ratio",
        type=float,
        default=3.0,
        help="Multiplicative threshold over each byte's EWMA baseline range "
             "before it surfaces in the active-unknown-bytes pane (ADR 0008).",
    )
    parser.add_argument(
        "--byte-activity-hysteresis-secs",
        type=float,
        default=5.0,
        help="HOT-tier extension past active_now in the active-unknown-bytes "
             "pane (ADR 0012 — was ADR 0008's exit grace; now the boundary "
             "between bright and [dim] tiers inside the retention window).",
    )
    parser.add_argument(
        "--byte-activity-retention-secs",
        type=float,
        default=30.0,
        help="Total time a byte stays visible in the active-unknown-bytes "
             "pane after activity ends (ADR 0012). The first hysteresis_secs "
             "of that window are HOT (default brightness, frozen sparkline "
             "preserving peak shape); the remainder is DIM.",
    )
    parser.add_argument(
        "--experiment",
        type=Path,
        default=None,
        help="Path to a procedure.yaml sidecar (ADR 0006). Implies --live: "
             "the operator screen drives the rider through the procedure "
             "step-by-step and auto-logs marks at each step's cue moment. "
             "The YAML is byte-copied into <session>/procedure.yaml.snapshot.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Open the live TUI without writing anything to disk — no session "
             "dir, no capture.log, no events.csv, no live_decode.csv, no "
             "session.md. Hotkeys still baseline flip windows; the '.' "
             "snapshot hotkey becomes a no-op (it needs a real session). "
             "Implies --live; incompatible with --experiment.",
    )
    args = parser.parse_args()

    if args.watch and args.experiment:
        sys.exit("--watch is incompatible with --experiment (procedures need persisted marks).")
    if args.experiment and not args.live:
        sys.stderr.write("--experiment implies --live; enabling live mode.\n")
        args.live = True
    if args.watch and not args.live:
        args.live = True

    # --stdin / --port validation. Exactly one must be set; --stdin is
    # incompatible with any mode that consumes stdin for keystrokes.
    if args.stdin and args.port:
        sys.exit("--stdin and --port are mutually exclusive.")
    if not args.stdin and not args.port:
        sys.exit("either --port <device> or --stdin is required.")
    if args.stdin and (args.live or args.watch or args.experiment):
        sys.exit("--stdin is incompatible with --live / --watch / --experiment "
                 "(those modes need stdin for keystrokes).")

    try:
        import can
    except ImportError:
        sys.exit(
            "python-can is not installed.\n"
            "  pip install -r scripts/requirements.txt"
        )
    if not args.stdin:
        try:
            import serial
        except ImportError:
            sys.exit(
                "pyserial is not installed.\n"
                "  pip install -r scripts/requirements.txt"
            )

    if args.watch:
        session_dir = None
        fw_rev = None
    else:
        session_dir = resolve_session_dir(args.label)
        fw_rev = args.firmware_rev or detect_firmware_rev()

    procedure = None
    if args.experiment:
        # --watch + --experiment was already rejected above; session_dir is real here.
        assert session_dir is not None
        try:
            from procedure import load_procedure  # type: ignore
            procedure = load_procedure(args.experiment)
        except Exception as e:
            sys.exit(f"failed to load procedure {args.experiment}: {e}")
        # Byte-identical copy preserves comments / ordering — the session
        # becomes self-documenting per ADR 0005's reconstructibility rule.
        snapshot_path = session_dir / "procedure.yaml.snapshot"
        snapshot_path.write_bytes(args.experiment.read_bytes())
        sys.stderr.write(
            f"loaded procedure {procedure.name} ({len(procedure.steps)} steps); "
            f"snapshot → {snapshot_path}\n"
        )

    if args.watch:
        sys.stderr.write("watch mode: no logs will be written.\n")
    else:
        sys.stderr.write(f"capture session: {session_dir}\n")
    source = "stdin" if args.stdin else args.port
    sys.stderr.write(f"source: {source}   bitrate: {args.bitrate} bps   firmware: {fw_rev or 'unknown'}\n")
    if args.stdin:
        sys.stderr.write("stdin mode: hotkeys disabled. Ctrl-C or EOF to stop.\n\n")
    else:
        sys.stderr.write("press '?' for hotkey legend, 'q' or Ctrl-C to stop.\n\n")

    events: EventLogger | NullEventLogger
    if args.watch:
        events = NullEventLogger()
    else:
        assert session_dir is not None
        events = EventLogger(session_dir / "events.csv")
    stop = threading.Event()

    start_time = time.monotonic()
    start_iso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    total_frames = 0
    unique_ids: set[int] = set()
    silence_warned = False
    last_status = 0.0

    ser = None
    if not args.stdin:
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

    if args.watch:
        writer = _NullCanLogger()
    else:
        assert session_dir is not None
        writer = can.Logger(filename=str(session_dir / "capture.log"))

    # The capture loop is wrapped in a small inner function so it can run
    # either in the main thread (default — KeyReader handles input + stderr
    # status line) or as a worker thread under the Textual live view (which
    # owns the terminal). on_frame_cb fires after each successful frame.
    def capture_loop(
        on_frame_cb=None,
        on_silence_cb=None,
        on_status_cb=None,
    ) -> None:
        nonlocal total_frames, silence_warned, last_status
        try:
            while not stop.is_set():
                if args.stdin:
                    # readline() splits on \n and returns b'' on EOF. Producers
                    # like `websocat -n` emit one payload per line with a
                    # trailing \n; the SLCAN line itself ends in \r, which the
                    # parser tolerates via the strip() at the top of
                    # parse_slcan_line.
                    line = sys.stdin.buffer.readline()
                    if not line:
                        stop.set()
                        break
                    ready = True
                else:
                    try:
                        line = ser.read_until(b"\r", size=SLCAN_MAX_LINE)
                    except (serial.SerialException, OSError) as e:
                        sys.stderr.write(f"\nbus disconnected: {e}\n")
                        events.log("disconnect", f"{type(e).__name__}: {e}")
                        stop.set()
                        break
                    ready = line.endswith(b"\r")

                if ready:
                    ts = time.time()
                    msg = parse_slcan_line(line, ts)
                    if msg is not None:
                        writer.on_message_received(msg)
                        total_frames += 1
                        unique_ids.add(msg.arbitration_id)
                        if on_frame_cb is not None:
                            on_frame_cb(ts, msg.arbitration_id, bytes(msg.data))

                now = time.monotonic()
                elapsed = now - start_time

                # Silence warn is a serial-mode diagnostic — the checklist
                # (right port, continuity, bitrate) doesn't apply to stdin.
                if not args.stdin and not silence_warned and total_frames == 0 and elapsed > args.silence_warn_secs:
                    if on_silence_cb is not None:
                        on_silence_cb(elapsed)
                    silence_warned = True

                if now - last_status >= 1.0:
                    if on_status_cb is not None:
                        on_status_cb(elapsed, total_frames, len(unique_ids), events.count)
                    last_status = now
        except KeyboardInterrupt:
            stop.set()

    def write_silence(elapsed: float) -> None:
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

    def write_status_line(elapsed, frames, ids, marks) -> None:
        mins, secs = divmod(int(elapsed), 60)
        hours, mins = divmod(mins, 60)
        sys.stderr.write(
            f"\r[{hours:02d}:{mins:02d}:{secs:02d}]  "
            f"{frames:>8} frames   {ids:>3} IDs   "
            f"{marks:>3} marks"
        )
        sys.stderr.flush()

    try:
        if args.stdin:
            # No KeyReader — stdin is consumed for data, not keystrokes.
            capture_loop(on_status_cb=write_status_line)
        elif args.live:
            # Live mode: Textual owns the terminal + input; capture loop
            # runs in a worker thread, frames cross via LiveBridge.
            from live_view import LiveBridge, LiveView  # type: ignore
            from signals import load_signals  # type: ignore

            try:
                signals = load_signals()
            except Exception as e:
                sys.exit(f"failed to load docs/signals/signals.yaml: {e}")

            bridge = LiveBridge()
            app = LiveView(
                bridge=bridge,
                session_dir=session_dir,
                signals=signals,
                events_log=events,
                hotkeys=HOTKEYS,
                legend_text=LEGEND,
                show_d7=args.show_d7,
                procedure=procedure,
                anomaly_z_threshold=args.anomaly_z_threshold,
                anomaly_warmup_flips=args.anomaly_warmup_flips,
                discovery_retention_secs=args.discovery_retention_secs,
                show_suppressed=args.show_suppressed,
                byte_activity_window_secs=args.byte_activity_window_secs,
                byte_activity_ratio=args.byte_activity_ratio,
                byte_activity_hysteresis_secs=args.byte_activity_hysteresis_secs,
                byte_activity_retention_secs=args.byte_activity_retention_secs,
            )

            worker = threading.Thread(
                target=capture_loop,
                kwargs={"on_frame_cb": bridge.feed_frame},
                daemon=True,
            )
            worker.start()
            try:
                app.run()
            finally:
                stop.set()
                worker.join(timeout=2.0)
        else:
            with KeyReader(events, stop):
                capture_loop(
                    on_silence_cb=write_silence,
                    on_status_cb=write_status_line,
                )
    finally:
        sys.stderr.write("\n")
        try:
            writer.stop()
        except Exception:
            pass
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        events.close()

    end_iso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    if args.watch:
        sys.stderr.write(
            f"\nwatched {total_frames} frames, {len(unique_ids)} unique IDs, {events.count} marks (nothing written).\n"
        )
    else:
        assert session_dir is not None
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
