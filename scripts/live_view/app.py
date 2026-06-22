"""LiveView — the Textual App. Owns all per-frame state and timers;
screens are thin views over this state."""

from __future__ import annotations

import csv
import json
import math
import queue
import time
from collections import Counter, deque, defaultdict
from pathlib import Path
from typing import Any, Iterable

from textual.app import App
from textual.binding import Binding

from procedure import Procedure
from signals import Signal, by_id

from .bridge import LiveBridge
from .constants import (
    DECODED_REFRESH_HZ,
    DISCOVERY_PANE_ROWS,
    EWMA_ALPHA,
    FLIP_WINDOW_SECS,
    FRAME_DRAIN_HZ,
    PROCEDURE_TICK_HZ,
    SIGMA_FLOOR,
    STALE_AFTER_SECS,
)
from .modals import LegendScreen, UnpinModal, WatchModal
from .screens import AnalysisScreen, OperatorScreen
from .state import (
    BaselineStats,
    GroupedRow,
    WatchPin,
    _render_group_row,
    _signed_secs,
    sparkline,
)


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
        session_dir: Path | None,
        signals: list[Signal],
        events_log,
        hotkeys: dict[str, tuple[str, str]],
        legend_text: str,
        show_d7: bool = False,
        procedure: Procedure | None = None,
        anomaly_z_threshold: float = 3.0,
        anomaly_warmup_flips: int = 5,
        discovery_retention_secs: float = 60.0,
        show_suppressed: bool = False,
    ) -> None:
        # session_dir=None is the --watch path: render-only, no disk writes.
        super().__init__()
        self.bridge = bridge
        self.session_dir = session_dir
        self.signals = signals
        self.by_arb = by_id(signals)
        # signals.yaml is read once at startup — the bit→signal index is
        # immutable for the session, so cache it instead of rebuilding on
        # every render.
        self._bit_index = self._compute_bit_index()
        self.events_log = events_log
        self.hotkeys = hotkeys
        self.legend_text = legend_text
        self.show_d7 = show_d7
        self.show_suppressed = show_suppressed

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

        # ADR 0007 — continuous per-bit baseline + discovery state.
        self.z_threshold = anomaly_z_threshold
        self.warmup_flips = anomaly_warmup_flips
        self.retention_secs = discovery_retention_secs
        self.baseline_stats: dict[tuple[int, int, int], BaselineStats] = {}
        # At-flip-time verdict snapshot, populated only during a mark window
        # so the mark-driven pane shows the (z, μ, σ) AS THEY WERE at the
        # moment of the flip — not where the EWMA has drifted to by render.
        # Tuple: (z, mu, sigma, transition). Cleared in `_open_flip_window`.
        self.flip_verdict: dict[tuple[int, int, int], tuple[float, float, float, str]] = {}
        # Recent non-suppressed anomalies for the continuous discovery pane.
        # Tuple: (ts, arb, byte, bit, transition, interval, z, mu, sigma).
        # maxlen is a runaway-bounded backstop; aging by `retention_secs`
        # happens at render time in `discovery_text`.
        self.recent_anomalies: deque[
            tuple[float, int, int, int, str, float, float, float, float]
        ] = deque(maxlen=2000)
        # Watch panel pins (UI-only, session-local — see ADR 0007).
        self.watch_pins: list[WatchPin] = []

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
        # regardless of which signal a frame fed. In --watch mode there's
        # no session dir, so the writer (and its file handle) stay None.
        self._csv_file = None
        self._csv_writer = None
        if session_dir is not None:
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
        if self._csv_file is not None:
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
        if ch == "w":
            # Don't stack a second modal if one is already on top.
            if not isinstance(self.screen, (WatchModal, UnpinModal, LegendScreen)):
                self.push_screen(WatchModal(self.signals), self._add_watch_pin)
            return
        if ch == "u":
            if self.watch_pins and not isinstance(
                self.screen, (WatchModal, UnpinModal, LegendScreen)
            ):
                self.push_screen(UnpinModal(self.watch_pins), self._remove_watch_pin)
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
        if drained and self._csv_file is not None:
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
            if self._csv_writer is not None:
                self._csv_writer.writerow([f"{ts:.6f}", sig.name, value, raw])

        # Per-byte tracking. Two concerns share this loop:
        #   (a) Continuous per-bit transition detection — runs on every
        #       frame regardless of mark state, feeds the EWMA baseline
        #       and the continuous discovery pane (ADR 0007).
        #   (b) Mark-window flip accumulation — runs ONLY when a mark
        #       window is open, feeds snapshot-N.json and the mark-driven
        #       pane. Unchanged behaviour from before ADR 0007.
        window_open = self.window_end_ts is not None and ts <= self.window_end_ts
        for b_idx, val in enumerate(data):
            prev = self.current_bytes.get((arb, b_idx))
            self.current_bytes[(arb, b_idx)] = val

            # (a) Continuous detection — only fires on actual transitions.
            if prev is not None and prev != val:
                changed = prev ^ val
                for bit in range(8):
                    if not changed & (1 << bit):
                        continue
                    old_bit = (prev >> bit) & 1
                    new_bit = (val >> bit) & 1
                    self._record_transition(ts, arb, b_idx, bit, old_bit, new_bit)

            # (b) Mark-window accumulation — keyed off the baseline snapshot.
            if not window_open:
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

    def _record_transition(
        self, ts: float, arb: int, byte: int, bit: int, old_bit: int, new_bit: int
    ) -> None:
        """Update per-bit EWMA, score, and (if anomalous) push to the
        recent-anomalies log + the mark-window verdict map. See ADR 0007."""
        key = (arb, byte, bit)
        transition = f"{old_bit}→{new_bit}"
        stats = self.baseline_stats.get(key)
        if stats is None:
            # First-ever observation for this bit — no prior interval to
            # score. Seed the baseline and surface nothing.
            self.baseline_stats[key] = BaselineStats(last_flip_ts=ts, count=1)
            return

        interval = ts - stats.last_flip_ts
        stats.last_flip_ts = ts
        stats.count += 1

        # Score BEFORE updating the EWMA so a single tail event doesn't
        # blunt its own z-score by reshaping the baseline it's measured
        # against. Renderers branch on `isinf(z)` and never read μ/σ in
        # the warmup case — the snapshot values are placeholders.
        mu_snap = stats.mu
        if stats.count <= self.warmup_flips:
            z = math.inf
            sigma_snap = 0.0
            keep = True
        else:
            sigma_snap = max(math.sqrt(stats.var), SIGMA_FLOOR)
            z = (interval - mu_snap) / sigma_snap
            keep = z >= self.z_threshold

        delta = interval - stats.mu
        stats.mu += EWMA_ALPHA * delta
        stats.var = (1 - EWMA_ALPHA) * (stats.var + EWMA_ALPHA * delta * delta)

        if not keep:
            return

        self.recent_anomalies.append(
            (ts, arb, byte, bit, transition, interval, z, mu_snap, sigma_snap)
        )
        if self.window_end_ts is not None and ts <= self.window_end_ts:
            self.flip_verdict[key] = (z, mu_snap, sigma_snap, transition)

    # ---- event marks ------------------------------------------------------

    def _mark(self, key: str, label: str) -> None:
        ts = time.time()
        self.events_log.log(key, label)
        self._open_flip_window(label or key, ts)

    def _open_flip_window(self, label: str, ts: float) -> None:
        self.baseline_bytes = dict(self.current_bytes)
        self.flip_obs.clear()
        self.flip_first_seen.clear()
        self.flip_verdict.clear()
        self.window_label = label
        self.window_end_ts = ts + FLIP_WINDOW_SECS
        self.last_event_ts = ts

    def _handle_snapshot(self) -> None:
        if self.session_dir is None:
            # --watch path: nowhere to write. Surface a hint and bail.
            try:
                self.notify(
                    "snapshots need a real session — relaunch without --watch.",
                    severity="warning",
                    timeout=3,
                )
            except Exception:
                pass
            return
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
        # Sample watch buffers BEFORE rendering so the sparkline reflects
        # the freshest data point. Runs regardless of which screen is
        # active, so the buffer stays populated while the operator screen
        # is up (and the analysis screen shows continuous history on
        # return).
        try:
            self._sample_watch_buffers()
        except Exception:
            pass
        screen = self.screen
        refresher = getattr(screen, "refresh_panes", None)
        if refresher is not None:
            try:
                refresher()
            except Exception:
                pass

    def _add_watch_pin(self, pin: WatchPin | None) -> None:
        if pin is None:
            return
        # Dedup: a given signal / triplet may only be pinned once.
        if pin.kind == "signal":
            if any(p.kind == "signal" and p.label == pin.label for p in self.watch_pins):
                return
        else:
            if any(p.kind == "raw" and p.raw == pin.raw for p in self.watch_pins):
                return
        self.watch_pins.append(pin)

    def _remove_watch_pin(self, idx: int | None) -> None:
        if idx is None or idx < 0 or idx >= len(self.watch_pins):
            return
        self.watch_pins.pop(idx)

    def _sample_watch_buffers(self) -> None:
        """Push the current value of every pinned entry into its sparkline
        ring buffer. Called once per decoded refresh tick."""
        for pin in self.watch_pins:
            pin.sample(self.latest, self.current_bytes)

    # ---- pane content (shared by both screens) ----------------------------

    def watch_text(self) -> str:
        """Render the pinned-watch pane (ADR 0007 #1). One row per pin
        with current value, a 12-cell sparkline of the recent buffer, and
        the pin origin so a raw triplet stays unambiguous."""
        header = "[bold]Watch[/bold]"
        if not self.watch_pins:
            return header + "  [dim](press w to pin a signal; u to unpin)[/dim]"
        body: list[str] = []
        for pin in self.watch_pins:
            value_str = pin.current_text(self.latest, self.current_bytes)
            spark = sparkline(list(pin.buffer), boolean=pin.boolean)
            body.append(
                f"  {pin.label:24s}  {value_str:>10}   {spark}   [dim]{pin.label}[/dim]"
            )
        return header + "\n" + "\n".join(body)

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

    def _compute_bit_index(self) -> dict[tuple[int, int, int], str]:
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
        index = self._bit_index
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

    def _group_rows_by_arb(
        self,
        rows: Iterable[tuple[int, int, int, str, float, float, float, float]],
    ) -> list[GroupedRow]:
        """Group per-bit anomaly rows by arbitration ID (ADR 0007 #5).

        Row tuple: (arb, byte, bit, transition, event_ts, z, mu, sigma).
        `event_ts` is latency-from-mark for the mark-driven pane, or
        wall-clock for the continuous discovery pane — opaque to the
        grouper. `z=math.inf` marks a warmup-tier event."""
        groups: dict[int, list[tuple[int, int, str, float, float, float, float]]] = (
            defaultdict(list)
        )
        for arb, byte, bit, transition, event_ts, z, mu, sigma in rows:
            groups[arb].append((byte, bit, transition, event_ts, z, mu, sigma))

        out: list[GroupedRow] = []
        for arb, items in groups.items():
            bits_seen: set[tuple[int, int]] = set()
            transitions: list[str] = []
            seen_trans: set[str] = set()
            earliest = math.inf
            latest = -math.inf
            best_z = -math.inf
            best_mu = 0.0
            best_sigma = 0.0
            for byte, bit, transition, event_ts, z, mu, sigma in items:
                bits_seen.add((byte, bit))
                if transition not in seen_trans:
                    transitions.append(transition)
                    seen_trans.add(transition)
                if event_ts < earliest:
                    earliest = event_ts
                if event_ts > latest:
                    latest = event_ts
                if z > best_z:
                    best_z, best_mu, best_sigma = z, mu, sigma
            out.append(
                GroupedRow(
                    arb=arb,
                    bits=sorted(bits_seen),
                    earliest_ts=earliest,
                    latest_ts=latest,
                    max_z=best_z,
                    mu=best_mu,
                    sigma=best_sigma,
                    transitions=transitions,
                )
            )
        return out

    def _unknown_pane_groups(self) -> list[GroupedRow]:
        """Mark-driven unknown-flips pane (ADR 0007 #3 + #5).

        Two independent gates:
        - `--show-d7` (default off): D7 byte hidden by default (checksum
          noise).
        - `--show-suppressed` (default off): bits whose EWMA verdict did
          not surface them as anomalous are hidden.
        """
        if self.last_event_ts is None:
            return []
        index = self._bit_index
        mark_ts = self.last_event_ts
        per_bit: list[tuple[int, int, int, str, float, float, float, float]] = []
        for (arb, byte, bit), counter in self.flip_obs.items():
            if not counter:
                continue
            if index.get((arb, byte, bit)):
                continue  # owned by a known signal — known pane handles it
            if byte == 7 and not self.show_d7:
                continue
            verdict = self.flip_verdict.get((arb, byte, bit))
            if verdict is None:
                if not self.show_suppressed:
                    continue
                # Override: surface the row, mark it as below threshold.
                transition = counter.most_common(1)[0][0]
                # Use −inf to sort suppressed rows below any real anomaly.
                z, mu, sigma = -math.inf, 0.0, 0.0
            else:
                z, mu, sigma, transition = verdict
            first_seen = self.flip_first_seen.get((arb, byte, bit), mark_ts)
            latency = first_seen - mark_ts
            per_bit.append((arb, byte, bit, transition, latency, z, mu, sigma))

        groups = self._group_rows_by_arb(per_bit)
        # math.inf naturally sorts above any finite z and -math.inf below;
        # earliest-latency breaks ties at the same z.
        groups.sort(key=lambda g: (-g.max_z, g.earliest_ts))
        return groups

    def _known_signal_rows(self) -> list[tuple[str, str, str, int]]:
        index = self._bit_index
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

        groups = self._unknown_pane_groups()
        z_hint = f"z ≥ {self.z_threshold:.1f}" if not self.show_suppressed else "all flips"
        unknown_header = f"[bold]Unknown bits flipped[/bold]  {ctx}  [dim]({z_hint})[/dim]"
        if not groups:
            hint = (
                "  (no anomalous flips in window — checksum / counter noise suppressed)"
                if not self.show_suppressed
                else "  (no flips in window)"
            )
            unknown_text = unknown_header + "\n" + hint
        else:
            body = [_render_group_row(g, _signed_secs(g.earliest_ts)) for g in groups[:10]]
            if len(groups) > 10:
                body.append(f"  … and {len(groups) - 10} more")
            unknown_text = unknown_header + "\n" + "\n".join(body)

        return known_text, unknown_text

    def discovery_text(self) -> str:
        """Always-on anomaly pane (ADR 0007 #4).

        Surfaces every bit-flip that the EWMA scored as anomalous since
        the last `retention_secs` seconds, grouped by ID, newest-first.
        Marks are NOT required — this fills passively as the bus reacts."""
        now = time.time()
        cutoff = now - self.retention_secs
        # Prune from the left — entries are appended in ts-monotonic order.
        while self.recent_anomalies and self.recent_anomalies[0][0] < cutoff:
            self.recent_anomalies.popleft()
        header = f"[bold]Live anomalies[/bold]  [dim](last {self.retention_secs:.0f}s, z ≥ {self.z_threshold:.1f})[/dim]"
        if not self.recent_anomalies:
            return header + "\n  (idle — no anomalous flips yet)"

        groups = self._group_rows_by_arb(
            (arb, byte, bit, transition, ts, z, mu, sigma)
            for ts, arb, byte, bit, transition, _interval, z, mu, sigma in self.recent_anomalies
        )
        groups.sort(key=lambda g: -g.latest_ts)  # newest first
        max_rows = DISCOVERY_PANE_ROWS - 2
        body = [
            _render_group_row(g, f"-{now - g.latest_ts:.1f}s")
            for g in groups[:max_rows]
        ]
        if len(groups) > max_rows:
            body.append(f"  … and {len(groups) - max_rows} more")
        return header + "\n" + "\n".join(body)

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
