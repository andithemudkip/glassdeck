#!/usr/bin/env python3
"""live_view.py — Textual TUI surfacing decoded signals and bit-flips live.

Two screens, switchable with Tab when a procedure is loaded:

  • AnalysisScreen (default): the three-pane decoded / flipped-bits view.
    – Decoded signals: current value of every entry in signals.yaml.
    – Flipped since last mark: every (ID, byte, bit) whose value differs
      from the snapshot taken at the most recent event mark.
    – Status: frames / unique IDs / event-mark count.

  • OperatorScreen (only when capture.py is run with --experiment): drives
    the rider step-by-step through a procedure.yaml, auto-logging marks
    at each step's cue moment. See ADR 0006.

ADR 0005 principles applied:
  • Decoded values come from signals.py (same code path as post-hoc
    decoders) — no second implementation of the schema.
  • All event marks and frames are written to capture.log / events.csv
    just as they would be without --live. The TUI is a window onto the
    same artifacts an agent could reconstruct from disk.
  • The `.` hotkey snapshots the current flipped-bits table to
    `snapshot-<n>.json` in the session dir AND records a `snapshot-<n>`
    event mark referencing it.
  • `live_decode.csv` (long format: ts, signal, value, raw) is streamed
    next to capture.log so the per-frame decoded view is available to
    agents without rerunning the decoder.

ADR 0006 additions:
  • `procedure.yaml.snapshot` is copied into the session dir by capture.py
    before the app starts.
  • Procedure-driven auto-marks share the same `_mark()` path as hotkey
    marks — the flip-baselining window opens regardless of which screen
    is visible.

Used only by capture.py when --live (or --experiment) is passed.
"""

from __future__ import annotations

import csv
import json
import math
import queue
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Static

from procedure import Procedure
from signals import Signal, by_id

FLIP_WINDOW_SECS = 0.5  # observe flips for this long after each event mark
DECODED_REFRESH_HZ = 4
FRAME_DRAIN_HZ = 30
PROCEDURE_TICK_HZ = 10
STALE_AFTER_SECS = 2.0  # dim decoded values not updated within this window

PREVIEW_LOOKAHEAD = 3  # number of upcoming steps shown on the operator screen


class LiveBridge:
    """Thread-safe handoff between the capture thread (frame producer +
    serial read) and the Textual main thread (UI + keyboard)."""

    def __init__(self) -> None:
        self.frame_q: queue.Queue[tuple[float, int, bytes]] = queue.Queue(maxsize=20000)
        self.stop = threading.Event()
        self.dropped = 0

    def feed_frame(self, ts: float, arb_id: int, data: bytes) -> None:
        try:
            self.frame_q.put_nowait((ts, arb_id, data))
        except queue.Full:
            self.dropped += 1


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------


class LegendScreen(ModalScreen):
    """Centered overlay showing the hotkey legend. Any key dismisses it.

    Textual's `notify` toast caps width at ~40 cells, so the multi-column
    legend wraps unreadably — a dedicated modal lets the legend render at
    its natural width."""

    CSS = """
    LegendScreen { align: center middle; }
    #legend-box {
        width: auto;
        max-width: 80%;
        height: auto;
        border: round white;
        padding: 1 2;
        background: $surface;
    }
    """

    def __init__(self, legend_text: str) -> None:
        super().__init__()
        self._legend_text = legend_text.strip("\n")

    def compose(self) -> ComposeResult:
        yield Static(
            f"[bold]Hotkey legend[/bold]\n\n{self._legend_text}\n\n[dim](press any key to close)[/dim]",
            id="legend-box",
        )

    def on_key(self, event) -> None:
        event.stop()
        self.dismiss()


class AnalysisScreen(Screen):
    """Three-pane decoded / flipped-bits / status view. Reads App state."""

    CSS = """
    AnalysisScreen { layout: vertical; }
    #decoded         { height: 14; border: round green;  padding: 0 1; }
    #flipped-row     { height: 16; layout: horizontal; }
    #flipped-known   { width: 1fr; height: 100%; border: round cyan;   padding: 0 1; }
    #flipped-unknown { width: 1fr; height: 100%; border: round yellow; padding: 0 1; }
    #status          { height: 3;  border: round white;  padding: 0 1; }
    """

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("", id="decoded"),
            Horizontal(
                Static("", id="flipped-known"),
                Static("", id="flipped-unknown"),
                id="flipped-row",
            ),
            Static("", id="status"),
        )

    def on_mount(self) -> None:
        self.refresh_panes()

    def refresh_panes(self) -> None:
        app: LiveView = self.app  # type: ignore[assignment]
        try:
            self.query_one("#decoded", Static).update(app.decoded_text())
            known_text, unknown_text = app.flipped_texts()
            self.query_one("#flipped-known", Static).update(known_text)
            self.query_one("#flipped-unknown", Static).update(unknown_text)
            self.query_one("#status", Static).update(app.status_text())
        except Exception:
            pass


class OperatorScreen(Screen):
    """Big-prompt + countdown screen that drives the rider through a
    procedure.yaml. Auto-marks fire at each step's start moment via the
    App's _start_step() / _mark() path."""

    CSS = """
    OperatorScreen { layout: vertical; }
    #op-header    { height: 1; padding: 0 2; }
    #op-prompt    { height: 7; content-align: center middle; }
    #op-countdown { height: 5; content-align: center middle; }
    #op-preview   { height: 5; padding: 0 4; }
    #op-help      { height: 1; padding: 0 2; }
    #op-status    { dock: bottom; height: 3; border: round white; padding: 0 1; }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="op-header")
        yield Static("", id="op-prompt")
        yield Static("", id="op-countdown")
        yield Static("", id="op-preview")
        yield Static("", id="op-help")
        yield Static("", id="op-status")

    def on_mount(self) -> None:
        self.refresh_panes()

    def refresh_panes(self) -> None:
        app: LiveView = self.app  # type: ignore[assignment]
        proc = app.procedure
        if proc is None:
            return
        i = app.step_index
        steps = proc.steps
        if i >= len(steps):
            i = len(steps) - 1
        step = steps[i]

        # Header — STEP n of N + a 20-cell progress bar.
        n_total = len(steps)
        bar_len = 20
        filled = int(bar_len * (i + 1) / n_total)
        bar = "█" * filled + "░" * (bar_len - filled)
        self.query_one("#op-header", Static).update(
            f"[bold]STEP {i + 1} of {n_total}[/bold]   {bar}"
        )

        # Big prompt.
        self.query_one("#op-prompt", Static).update(f"[bold]{step.prompt}[/bold]")

        # Countdown: peek at the NEXT step's countdown_from. The cue belongs
        # to the upcoming action — we render it during the trailing seconds
        # of the current step's settle. (ADR 0006's YAML example puts
        # `countdown_from` on the toggle step itself; the cue runs during
        # the preceding settle. See the ADR's "Hotkeys / countdown" section.)
        countdown_text = ""
        if app.paused:
            countdown_text = "[bold yellow][PAUSED][/bold yellow]"
        elif step.duration_secs is None:
            countdown_text = "[dim]— press q to stop —[/dim]"
        else:
            remaining = step.duration_secs - app.step_elapsed()
            next_step = steps[i + 1] if i + 1 < n_total else None
            if next_step is not None and next_step.countdown_from is not None:
                if remaining <= next_step.countdown_from and remaining > 0:
                    digit = max(1, math.ceil(remaining))
                    countdown_text = f"[bold red]{digit}[/bold red]"
                elif remaining <= 0:
                    countdown_text = "[bold red]NOW[/bold red]"
            if not countdown_text:
                # No cue active — show generic remaining time, dim.
                if remaining > 0:
                    countdown_text = f"[dim]{remaining:.0f}s[/dim]"
        self.query_one("#op-countdown", Static).update(countdown_text)

        # Next 3 steps preview.
        preview_lines: list[str] = ["[bold]Coming up:[/bold]"]
        for j in range(i + 1, min(i + 1 + PREVIEW_LOOKAHEAD, n_total)):
            ns = steps[j]
            dur = "manual" if ns.duration_secs is None else f"{ns.duration_secs:g}s"
            cd = f", ⏱{ns.countdown_from}" if ns.countdown_from else ""
            preview_lines.append(f"  → {ns.prompt}  [dim]({dur}{cd})[/dim]")
        if i + 1 >= n_total:
            preview_lines.append("  [dim](last step)[/dim]")
        self.query_one("#op-preview", Static).update("\n".join(preview_lines))

        self.query_one("#op-help", Static).update(
            "[dim]Tab: analysis view   Space: pause   ←: prev step   q: quit[/dim]"
        )

        # Status — same shape as analysis, plus step counter.
        self.query_one("#op-status", Static).update(
            app.status_text(extra=f"step {i + 1}/{n_total}")
        )


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class LiveView(App):
    """Textual app instantiated by capture.py when --live (or --experiment)
    is passed. Owns all per-frame state and timers; screens are views."""

    # `priority=True` so Tab/Space/Left don't get eaten by widget-level
    # focus navigation or text input on either screen.
    BINDINGS = [
        Binding("tab", "toggle_screen", "switch", show=False, priority=True),
        Binding("space", "toggle_pause", "pause", show=False, priority=True),
        Binding("left", "prev_step", "prev", show=False, priority=True),
    ]

    SCREENS = {"analysis": AnalysisScreen, "operator": OperatorScreen}

    def __init__(
        self,
        bridge: LiveBridge,
        session_dir: Path,
        signals: list[Signal],
        events_log,
        hotkeys: dict[str, tuple[str, str]],
        legend_text: str,
        show_d7: bool = False,
        procedure: Procedure | None = None,
    ) -> None:
        super().__init__()
        self.bridge = bridge
        self.session_dir = session_dir
        self.signals = signals
        self.by_arb = by_id(signals)
        self.events_log = events_log
        self.hotkeys = hotkeys
        self.legend_text = legend_text
        self.show_d7 = show_d7

        # Per-signal latest decoded (value, raw_int_or_None, timestamp).
        self.latest: dict[str, tuple[Any, Any, float]] = {}
        # Per-(arb_id, byte) most-recently-seen raw byte value.
        self.current_bytes: dict[tuple[int, int], int] = {}
        # Snapshot of current_bytes taken at the most recent event mark.
        self.baseline_bytes: dict[tuple[int, int], int] = {}
        # While inside an active flip-observation window:
        #   key = (arb_id, byte, bit), value = Counter[ "1→0" | "0→1" | "stable" ]
        self.flip_obs: dict[tuple[int, int, int], Counter[str]] = {}
        # First-seen timestamp per flipped bit, for latency reporting.
        self.flip_first_seen: dict[tuple[int, int, int], float] = {}
        self.window_label: str | None = None
        self.window_end_ts: float | None = None
        self.last_event_ts: float | None = None

        self.snapshot_seq = 0
        self.total_frames = 0
        self.unique_ids: set[int] = set()
        self.session_start = time.monotonic()

        # Procedure state (ADR 0006). step_started_at uses monotonic time so
        # pause/resume can shift it without wall-clock drift.
        self.procedure = procedure
        self.step_index = 0
        self.step_started_at: float | None = None
        self.paused = False
        self._pause_started_at: float | None = None

        # live_decode.csv — long format so per-row content is uniform
        # regardless of which signal a frame fed.
        self._csv_file = (session_dir / "live_decode.csv").open("w", newline="")
        self._csv_writer = csv.writer(self._csv_file)
        self._csv_writer.writerow(["timestamp", "signal", "value", "raw"])
        self._csv_file.flush()

    # ---- Textual lifecycle ------------------------------------------------

    def on_mount(self) -> None:
        # Frame drain runs regardless of which screen is visible — switching
        # to the operator screen must NOT stop decode / live_decode.csv.
        self.set_interval(1.0 / FRAME_DRAIN_HZ, self._drain_frames)
        self.set_interval(1.0 / DECODED_REFRESH_HZ, self._refresh_active_screen)
        if self.procedure is not None:
            self.set_interval(1.0 / PROCEDURE_TICK_HZ, self._procedure_tick)
            self.push_screen("operator")
        else:
            self.push_screen("analysis")

    async def on_unmount(self) -> None:
        try:
            self._csv_file.close()
        except Exception:
            pass

    # ---- input ------------------------------------------------------------

    async def on_key(self, event) -> None:
        ch = event.character
        if event.key in ("q", "ctrl+c"):
            self.bridge.stop.set()
            self.exit()
            return
        if not ch:
            return
        if ch == "?":
            if not isinstance(self.screen, LegendScreen):
                self.push_screen(LegendScreen(self.legend_text))
            return
        if ch == ".":
            self._handle_snapshot()
            return
        if ch in self.hotkeys:
            key, label = self.hotkeys[ch]
            self._mark(key, label)
        elif ch.isprintable():
            self._mark(ch, "")

    # ---- bindings ---------------------------------------------------------

    def action_toggle_screen(self) -> None:
        """Tab — flip between operator and analysis when a procedure is loaded."""
        if self.procedure is None:
            return
        target = "analysis" if self.screen.__class__ is OperatorScreen else "operator"
        self.switch_screen(target)

    def action_toggle_pause(self) -> None:
        """Space — pause/resume the procedure tick. Capture itself never pauses."""
        if self.procedure is None:
            return
        if self.paused:
            # Resuming: shift step_started_at by the pause duration so the
            # countdown picks up where it left off rather than jumping ahead.
            if self._pause_started_at is not None and self.step_started_at is not None:
                self.step_started_at += time.monotonic() - self._pause_started_at
            self._pause_started_at = None
            self.paused = False
        else:
            self.paused = True
            self._pause_started_at = time.monotonic()

    def action_prev_step(self) -> None:
        """← — rewind one step. Logs a procedure-rewind event (NOT a mark —
        no flip window) and re-enters the previous step WITHOUT re-firing
        its auto-mark (the rider already saw that cue)."""
        if self.procedure is None:
            return
        new_index = max(0, self.step_index - 1)
        self.events_log.log(
            "procedure-rewind",
            f"rewind from step {self.step_index + 1} to {new_index + 1}",
        )
        self.step_index = new_index
        self._start_step(new_index, fire_mark=False)

    # ---- frame consumer ---------------------------------------------------

    def _drain_frames(self) -> None:
        drained = 0
        try:
            while drained < 5000:
                ts, arb, data = self.bridge.frame_q.get_nowait()
                self._handle_frame(ts, arb, data)
                drained += 1
        except queue.Empty:
            pass
        if drained:
            try:
                self._csv_file.flush()
            except Exception:
                pass

    def _handle_frame(self, ts: float, arb: int, data: bytes) -> None:
        self.total_frames += 1
        self.unique_ids.add(arb)

        # Decoded pane state + live_decode.csv row(s).
        for sig in self.by_arb.get(arb, ()):
            value = sig.extract(arb, data)
            if value is None:
                continue
            raw = sig._extract_raw(data)
            self.latest[sig.name] = (value, raw, ts)
            self._csv_writer.writerow([f"{ts:.6f}", sig.name, value, raw])

        # Per-byte tracking. Update current; check baseline if a flip
        # window is open.
        for b_idx, val in enumerate(data):
            self.current_bytes[(arb, b_idx)] = val
            if self.window_end_ts is None or ts > self.window_end_ts:
                continue
            base = self.baseline_bytes.get((arb, b_idx))
            if base is None or base == val:
                continue
            diff = base ^ val
            for bit in range(8):
                if not diff & (1 << bit):
                    continue
                key = (arb, b_idx, bit)
                old_bit = (base >> bit) & 1
                new_bit = (val >> bit) & 1
                transition = f"{old_bit}→{new_bit}"
                self.flip_obs.setdefault(key, Counter())[transition] += 1
                self.flip_first_seen.setdefault(key, ts)

    # ---- event marks ------------------------------------------------------

    def _mark(self, key: str, label: str) -> None:
        ts = time.time()
        self.events_log.log(key, label)
        self._open_flip_window(label or key, ts)

    def _open_flip_window(self, label: str, ts: float) -> None:
        self.baseline_bytes = dict(self.current_bytes)
        self.flip_obs.clear()
        self.flip_first_seen.clear()
        self.window_label = label
        self.window_end_ts = ts + FLIP_WINDOW_SECS
        self.last_event_ts = ts

    def _handle_snapshot(self) -> None:
        self.snapshot_seq += 1
        seq = self.snapshot_seq
        ts = time.time()
        path = self.session_dir / f"snapshot-{seq}.json"
        rows = self._flip_rows()
        payload = {
            "snapshot_seq": seq,
            "timestamp": ts,
            "window_label": self.window_label,
            "window_secs": FLIP_WINDOW_SECS,
            "schema": "live_view.snapshot.v1",
            "flips": [
                {
                    "arbitration_id": f"0x{arb:03X}",
                    "byte": byte,
                    "bit": bit,
                    "transition": transition,
                    "count": count,
                    "fraction": fraction,
                    "signal": match_name,
                    "latency_secs": round(latency, 4),
                }
                for arb, byte, bit, transition, count, fraction, match_name, latency in rows
            ],
        }
        path.write_text(json.dumps(payload, indent=2))
        # Event mark references the sidecar by name — agents can locate
        # it from events.csv without any out-of-band knowledge.
        self.events_log.log(f"snapshot-{seq}", f"snapshot → {path.name}")

    # ---- procedure --------------------------------------------------------

    def step_elapsed(self) -> float:
        """Seconds elapsed since the current step started — frozen while paused."""
        if self.step_started_at is None:
            return 0.0
        if self.paused and self._pause_started_at is not None:
            return self._pause_started_at - self.step_started_at
        return time.monotonic() - self.step_started_at

    def _start_step(self, i: int, fire_mark: bool = True) -> None:
        """Enter step `i`. Fires the step's auto-mark by default; pass
        fire_mark=False on rewind so the mark isn't logged twice."""
        assert self.procedure is not None
        self.step_index = i
        self.step_started_at = time.monotonic()
        # If a rewind happens while paused, reset the pause anchor too so
        # step_elapsed() remains consistent.
        if self.paused:
            self._pause_started_at = self.step_started_at
        step = self.procedure.steps[i]
        if fire_mark and step.mark is not None:
            self._mark(step.mark.key, step.mark.label)

    def _procedure_tick(self) -> None:
        if self.procedure is None or self.paused:
            return
        if self.step_index >= len(self.procedure.steps):
            return
        if self.step_started_at is None:
            # First tick for this step — initialize and fire mark.
            self._start_step(self.step_index)
            return
        step = self.procedure.steps[self.step_index]
        if step.duration_secs is None:
            # Terminal wait-for-q step — never auto-advance.
            return
        if self.step_elapsed() >= step.duration_secs:
            next_index = self.step_index + 1
            if next_index >= len(self.procedure.steps):
                # Last step finished but had a duration — stay put; let the
                # rider press q. (No more steps to advance into.)
                return
            self._start_step(next_index)

    # ---- screen refresh dispatch ------------------------------------------

    def _refresh_active_screen(self) -> None:
        screen = self.screen
        refresher = getattr(screen, "refresh_panes", None)
        if refresher is not None:
            try:
                refresher()
            except Exception:
                pass

    # ---- pane content (shared by both screens) ----------------------------

    def decoded_text(self) -> str:
        now = time.time()
        lines: list[str] = ["[bold]Decoded signals[/bold]"]
        for sig in self.signals:
            entry = self.latest.get(sig.name)
            if entry is None:
                lines.append(f"  {sig.name:24s} —                {sig.status}")
                continue
            value, _raw, ts = entry
            age = now - ts
            rendered = sig.format(value)
            stale = " [dim](stale)[/dim]" if age > STALE_AFTER_SECS else ""
            lines.append(f"  {sig.name:24s} {rendered:<16} {sig.status}{stale}")
        return "\n".join(lines)

    def _bit_to_signal(self) -> dict[tuple[int, int, int], str]:
        """Map every bit covered by any signal to that signal's name."""
        index: dict[tuple[int, int, int], str] = {}
        for sig in self.signals:
            if sig.bytes_ is not None:
                for b in sig.bytes_:
                    for bit in range(8):
                        index[(sig.arbitration_id, b, bit)] = sig.name
            elif sig.byte is not None:
                for bit in range(sig.bit_offset, sig.bit_offset + sig.bit_length):
                    index[(sig.arbitration_id, sig.byte, bit)] = sig.name
        return index

    def _flip_rows(self) -> list[tuple[int, int, int, str, int, float, str, float]]:
        """Per-bit flip rows used by the unknown pane and snapshot JSON."""
        index = self._bit_to_signal()
        mark_ts = self.last_event_ts
        rows = []
        for (arb, byte, bit), counter in self.flip_obs.items():
            total = sum(counter.values())
            if not total:
                continue
            transition, count = counter.most_common(1)[0]
            fraction = count / total
            match = index.get((arb, byte, bit), "")
            first_seen = self.flip_first_seen.get((arb, byte, bit), 0.0)
            latency = first_seen - mark_ts if mark_ts is not None else 0.0
            rows.append((arb, byte, bit, transition, count, fraction, match, latency))
        rows.sort(key=lambda r: r[7])
        return rows

    def _known_signal_rows(self) -> list[tuple[str, str, str, int]]:
        index = self._bit_to_signal()
        per_signal_flips: dict[str, int] = {}
        for (arb, byte, bit), counter in self.flip_obs.items():
            name = index.get((arb, byte, bit))
            if not name:
                continue
            per_signal_flips[name] = per_signal_flips.get(name, 0) + sum(counter.values())
        if not per_signal_flips:
            return []
        sig_by_name = {s.name: s for s in self.signals}
        rows: list[tuple[str, str, str, int]] = []
        for name, count in per_signal_flips.items():
            sig = sig_by_name[name]
            baseline = self._signal_value_from(sig, self.baseline_bytes)
            current = self._signal_value_from(sig, self.current_bytes)
            rows.append((name, sig.format(baseline), sig.format(current), count))
        rows.sort(key=lambda r: -r[3])
        return rows

    def _signal_value_from(self, sig: Signal, bytes_map: dict[tuple[int, int], int]):
        if sig.bytes_ is not None:
            data_bytes = bytearray(8)
            for b in sig.bytes_:
                if (sig.arbitration_id, b) not in bytes_map:
                    return None
                data_bytes[b] = bytes_map[(sig.arbitration_id, b)]
            return sig.extract(sig.arbitration_id, bytes(data_bytes))
        assert sig.byte is not None
        if (sig.arbitration_id, sig.byte) not in bytes_map:
            return None
        data_bytes = bytearray(8)
        data_bytes[sig.byte] = bytes_map[(sig.arbitration_id, sig.byte)]
        return sig.extract(sig.arbitration_id, bytes(data_bytes))

    def flipped_texts(self) -> tuple[str, str]:
        """Return (known_pane_text, unknown_pane_text)."""
        if self.window_label is None:
            empty = "  (no mark yet — press a hotkey to baseline)"
            return (
                "[bold]Known signals changed[/bold]\n" + empty,
                "[bold]Unknown bits flipped[/bold]\n" + empty,
            )
        age = time.time() - (self.last_event_ts or 0)
        ctx = f"[dim]({self.window_label} +{age:.1f}s)[/dim]"

        known_rows = self._known_signal_rows()
        known_header = f"[bold]Known signals changed[/bold]  {ctx}"
        if not known_rows:
            known_text = f"{known_header}\n  (none — every schema-mapped signal steady this window)"
        else:
            body = []
            for name, baseline, current, _flips in known_rows[:10]:
                if baseline == current:
                    body.append(f"  [green]{name:22s}[/green]  {current}  [dim](no decoded delta)[/dim]")
                else:
                    body.append(f"  [green]{name:22s}[/green]  {baseline}  →  [bold]{current}[/bold]")
            if len(known_rows) > 10:
                body.append(f"  … and {len(known_rows) - 10} more")
            known_text = known_header + "\n" + "\n".join(body)

        unknown_rows = [r for r in self._flip_rows() if not r[6]]
        d7_hidden = 0
        if not self.show_d7:
            kept = [r for r in unknown_rows if r[1] != 7]
            d7_hidden = len(unknown_rows) - len(kept)
            unknown_rows = kept
        unknown_header = f"[bold]Unknown bits flipped[/bold]  {ctx}"
        if not unknown_rows:
            footer = ""
            if d7_hidden:
                footer = f"\n  [dim]({d7_hidden} D7 bit(s) hidden — checksum noise; --show-d7 to reveal)[/dim]"
            unknown_text = (
                f"{unknown_header}\n  (none — no novel bit flips in last {FLIP_WINDOW_SECS:.1f}s)"
                + footer
            )
        else:
            body = []
            for arb, byte, bit, transition, count, fraction, _, latency in unknown_rows[:10]:
                lat = f"+{latency:.2f}s" if latency >= 0 else f"{latency:.2f}s"
                body.append(
                    f"  0x{arb:03X} D{byte} bit {bit}  {transition}  {lat:>7}  ×{count}  "
                    f"frac={fraction:.2f}"
                )
            if len(unknown_rows) > 10:
                body.append(f"  … and {len(unknown_rows) - 10} more")
            if d7_hidden:
                body.append(f"  [dim]({d7_hidden} D7 bit(s) hidden — checksum noise; --show-d7 to reveal)[/dim]")
            unknown_text = unknown_header + "\n" + "\n".join(body)

        return known_text, unknown_text

    def status_text(self, extra: str = "") -> str:
        dropped = f"  [red]dropped {self.bridge.dropped}[/red]" if self.bridge.dropped else ""
        elapsed = int(time.monotonic() - self.session_start)
        hh, rem = divmod(elapsed, 3600)
        mm, ss = divmod(rem, 60)
        extra_str = f"   {extra}" if extra else ""
        return (
            f"[bold]Status[/bold]  "
            f"[{hh:02d}:{mm:02d}:{ss:02d}]   "
            f"frames {self.total_frames:>8,}   "
            f"ids {len(self.unique_ids):>3}   "
            f"marks {self.events_log.count:>3}   "
            f"snapshots {self.snapshot_seq}{extra_str}{dropped}\n"
            f"[dim]Press hotkey to mark; '.' snapshot; '?' legend; 'q' quit[/dim]"
        )
