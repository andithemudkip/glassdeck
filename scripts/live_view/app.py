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
    ACTIVE_BYTES_PANE_ROWS,
    ACTIVITY_EWMA_ALPHA,
    ANOMALY_ACCENT_COLORS,
    ANOMALY_COOCCUR_SECS,
    BASELINE_FLOOR,
    BYTE_ACTIVITY_RETENTION_SECS,
    BYTE_ACTIVITY_SAMPLE_SECS,
    BYTE_BURST_FREEZE_DELAY_SECS,
    DECODED_REFRESH_HZ,
    DISCOVERY_PANE_ROWS,
    EWMA_ALPHA,
    FLIP_WINDOW_SECS,
    FRAME_DRAIN_HZ,
    PROCEDURE_TICK_HZ,
    SIGMA_FLOOR,
    SPARKLINE_WIDTH,
    STALE_AFTER_SECS,
)
from .modals import (
    EXPECT_CANCEL,
    ExpectShapeModal,
    HypothesisBitRow,
    HypothesisByteRow,
    HypothesisModal,
    HypothesisResult,
    LegendScreen,
    UnpinModal,
    WatchModal,
)
from .screens import AnalysisScreen, OperatorScreen
from .state import (
    BaselineStats,
    ByteActivityStats,
    GroupedRow,
    WatchPin,
    _render_anomaly_row,
    _render_byte_row,
    _render_group_row,
    _signed_secs,
    classify_byte,
    is_halo_active,
    is_hot,
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
        Binding("right", "skip_step", "skip", show=False, priority=True),
        # ADR 0010 §2 — hot-tunable thresholds. Every printable char is
        # reserved for mark hotkeys (capture.py), so we use non-printable
        # keys. Mac-terminal constraints push the specific choices:
        #   - Ctrl+arrow is captured by macOS Mission Control.
        #   - Alt+arrow doesn't send an escape in Terminal.app.
        #   - Shift+↑↓ is swallowed by Terminal.app (text selection),
        #     though Shift+←→ passes through — hence the asymmetric pair.
        Binding("f6", "bump_z(0.5)", show=False, priority=True),
        Binding("f7", "bump_z(-0.5)", show=False, priority=True),
        Binding("shift+right", "bump_ratio(0.5)", show=False, priority=True),
        Binding("shift+left", "bump_ratio(-0.5)", show=False, priority=True),
        Binding("ctrl+d", "toggle_d7", show=False, priority=True),
        Binding("ctrl+y", "toggle_suppressed", show=False, priority=True),
        # ADR 0013 — expect-shape lens. Like Ctrl+N (ADR 0010 §3), bound on
        # `event.key` so the underlying 'e' still falls through to its
        # printable-mark slot when chorded outside Ctrl.
        Binding("ctrl+e", "expect_shape", show=False, priority=True),
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
        byte_activity_window_secs: float = 2.0,
        byte_activity_ratio: float = 3.0,
        byte_activity_hysteresis_secs: float = 5.0,
        byte_activity_retention_secs: float = BYTE_ACTIVITY_RETENTION_SECS,
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
        self._byte_index = self._compute_byte_index()
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

        # ADR 0008 — per-byte rolling range + EWMA baseline.
        # ADR 0012 — `hysteresis_secs` now means "HOT-tier extension past
        # active_now" (was: total exit grace); `retention_secs` is the new
        # total visible window, with `[dim]` decay between the two.
        self.byte_activity_window_secs = byte_activity_window_secs
        self.byte_activity_ratio = byte_activity_ratio
        self.byte_activity_hysteresis_secs = byte_activity_hysteresis_secs
        self.byte_activity_retention_secs = byte_activity_retention_secs
        self.byte_activity: dict[tuple[int, int], ByteActivityStats] = {}

        # ADR 0013 — expect-shape lens. None means "no expectation set"
        # (the surface renders as before). Values: "sensor" / "counter" /
        # "step" / "boolean". Set only via the Ctrl+E picker, never via
        # CLI — session-local by design.
        self.expect_shape: str | None = None

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
        # Most recent mark for the OperatorScreen's confirmation flash —
        # (monotonic_ts, key, label). Read by the screen each refresh; it
        # fades the flash itself by comparing against `time.monotonic()`.
        self._last_mark: tuple[float, str, str] | None = None
        # Skip flash is tracked separately so the "✓ marked" flash isn't
        # overloaded with a non-mark event. Latest of the two wins in the UI.
        self._last_skip: tuple[float, str] | None = None

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
        # Ctrl+N opens the hypothesis modal (ADR 0010 §3). Handled by
        # event.key (not event.character) so the underlying 'n' never
        # reaches the printable-mark fallback below — keeps the "n →
        # neutral mark" hotkey intact when chorded with Ctrl.
        if event.key == "ctrl+n":
            event.stop()
            if not isinstance(
                self.screen,
                (WatchModal, UnpinModal, LegendScreen, HypothesisModal),
            ):
                rows_bytes = self._snapshot_active_byte_rows()
                rows_bits = self._snapshot_anomaly_bit_rows()
                self.push_screen(
                    HypothesisModal(rows_bytes, rows_bits),
                    self._on_hypothesis_submit,
                )
            return
        # ADR 0013 — same handling pattern as Ctrl+N: stop the event so 'e'
        # doesn't fall through to the printable-mark slot, only push the
        # modal when no other overlay is on top.
        if event.key == "ctrl+e":
            event.stop()
            if not isinstance(
                self.screen,
                (
                    WatchModal,
                    UnpinModal,
                    LegendScreen,
                    HypothesisModal,
                    ExpectShapeModal,
                ),
            ):
                self.push_screen(
                    ExpectShapeModal(self.expect_shape),
                    self._on_expect_shape,
                )
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

    def action_skip_step(self) -> None:
        """→ — skip the current step. Logs a procedure-skip event so analysis
        can see the step was abandoned mid-way (not completed). Advances to
        the next step and fires its auto-mark normally — entering a step is
        always a commit to it. No-op on the last step: nowhere to go."""
        if self.procedure is None:
            return
        if self.step_index >= len(self.procedure.steps) - 1:
            return
        step = self.procedure.steps[self.step_index]
        next_index = self.step_index + 1
        # Tag the skipped step's auto-mark (if any) so analyzers can pair
        # this skip with the now-spurious entry mark that already fired.
        mark_tag = (
            f" [mark={step.mark.key}|{step.mark.label or ''}]"
            if step.mark is not None
            else ""
        )
        self.events_log.log(
            "procedure-skip",
            f"skip step {self.step_index + 1} of {len(self.procedure.steps)}: {step.prompt}{mark_tag}",
        )
        self._last_skip = (time.monotonic(), step.prompt)
        self._start_step(next_index)

    # ADR 0010 §2 — hot-tunable thresholds. No explicit refresh call — the
    # 4 Hz tick picks up the new value on its next pass, which is exactly
    # the "watch the pane respond" feedback the ADR wants.

    def action_bump_z(self, delta: float) -> None:
        self.z_threshold = max(0.5, self.z_threshold + delta)

    def action_bump_ratio(self, delta: float) -> None:
        self.byte_activity_ratio = max(0.5, self.byte_activity_ratio + delta)

    def action_toggle_d7(self) -> None:
        self.show_d7 = not self.show_d7

    def action_toggle_suppressed(self) -> None:
        self.show_suppressed = not self.show_suppressed

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

            # (a') Byte-level rolling range + EWMA baseline (ADR 0008).
            # Runs on every sample (not just transitions) — counters and
            # held values contribute to the buffer too, so a flat byte's
            # baseline stays at 0 until the first real sweep.
            self._update_byte_activity(ts, arb, b_idx, val)

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
        self._last_mark = (time.monotonic(), key, label)

    def _open_flip_window(self, label: str, ts: float) -> None:
        self.baseline_bytes = dict(self.current_bytes)
        self.flip_obs.clear()
        self.flip_first_seen.clear()
        self.flip_verdict.clear()
        self.window_label = label
        self.window_end_ts = ts + FLIP_WINDOW_SECS
        self.last_event_ts = ts

    # ---- hypothesis capture (ADR 0010 §3) -------------------------------

    def _snapshot_active_byte_rows(self) -> list[HypothesisByteRow]:
        """Freeze the current active-unknown-bytes pane rows for the modal.

        Mirrors the filter logic in `active_bytes_text()` so the modal
        shows the same rows the operator was just looking at. Sorted by
        ratio descending; capped at ACTIVE_BYTES_PANE_ROWS so the modal
        list and the pane agree on which rows are 'top'."""
        now = time.time()
        rows: list[tuple[float, HypothesisByteRow]] = []
        for (arb, byte), stats in self.byte_activity.items():
            if (arb, byte) in self._byte_index:
                continue
            if byte == 7 and not self.show_d7:
                continue
            buf = stats.buffer
            if len(buf) < 2:
                continue
            lo = min(v for _, v in buf)
            hi = max(v for _, v in buf)
            short_range = hi - lo
            threshold = max(
                BASELINE_FLOOR, self.byte_activity_ratio * stats.baseline_range_ewma
            )
            active_now = short_range > threshold
            in_tail = (
                stats.last_active_ts is not None
                and now - stats.last_active_ts < self.byte_activity_hysteresis_secs
            )
            if not (active_now or in_tail):
                continue
            cur = self.current_bytes.get((arb, byte), 0)
            first_activity = stats.baseline_range_ewma <= BASELINE_FLOOR
            ratio = math.inf if first_activity else short_range / stats.baseline_range_ewma
            shape = classify_byte([v for _, v in buf])
            rows.append(
                (
                    ratio,
                    HypothesisByteRow(
                        arb=arb,
                        byte=byte,
                        value=cur,
                        short_range=int(short_range),
                        ratio=ratio,
                        shape=shape,
                        first_activity=first_activity,
                    ),
                )
            )
        rows.sort(key=lambda r: -r[0])
        return [r for _, r in rows[:ACTIVE_BYTES_PANE_ROWS]]

    def _snapshot_anomaly_bit_rows(self) -> list[HypothesisBitRow]:
        """Freeze the continuous-anomaly pane rows for the modal — one
        entry per (arb, byte, bit) within retention_secs, keeping the
        most recent transition / z snapshot. Sorted newest-first."""
        now = time.time()
        cutoff = now - self.retention_secs
        # Walk newest → oldest, keep first hit per key.
        seen: dict[tuple[int, int, int], HypothesisBitRow] = {}
        order: list[tuple[int, int, int]] = []
        for ts, arb, byte, bit, transition, _interval, z, mu, sigma in reversed(
            self.recent_anomalies
        ):
            if ts < cutoff:
                continue
            key = (arb, byte, bit)
            if key in seen:
                continue
            seen[key] = HypothesisBitRow(
                arb=arb,
                byte=byte,
                bit=bit,
                transition=transition,
                z=z,
                mu=mu,
                sigma=sigma,
            )
            order.append(key)
        return [seen[k] for k in order[:DISCOVERY_PANE_ROWS]]

    def _on_expect_shape(self, result) -> None:
        """ADR 0013 — modal callback. Three branches:
        - `EXPECT_CANCEL` sentinel: Esc — leave self.expect_shape alone.
        - `None`: operator picked "clear" — set self.expect_shape to None.
        - shape string ("sensor" / "counter" / "step" / "boolean"): arm
          the lens. No render call needed — the 4 Hz tick picks it up
          on the next pass (same pattern as the threshold tunables)."""
        if result is EXPECT_CANCEL:
            return
        self.expect_shape = result

    def _on_hypothesis_submit(self, result: HypothesisResult | None) -> None:
        if result is None:
            return
        if self.session_dir is None:
            try:
                self.notify(
                    "hypotheses need a real session — relaunch without --watch.",
                    severity="warning",
                    timeout=3,
                )
            except Exception:
                pass
            return
        self._append_hypothesis(result)
        self.events_log.log("hypothesis", result.name)
        if result.pin_to_watch:
            pin = self._watch_pin_for_hypothesis(result)
            if pin is not None:
                self._add_watch_pin(pin)

    def _append_hypothesis(self, result: HypothesisResult) -> None:
        """Append one YAML stanza to <session_dir>/hypotheses.yaml.

        Stream-appended: every call writes a one-element list document,
        so the file is `yaml.safe_load_all`-able even mid-session. The
        format mirrors `docs/signals/signals.yaml` so a future
        promote-hypothesis script becomes a straight key-by-key carry."""
        assert self.session_dir is not None
        import yaml  # lazy: same convention as scripts/signals.py

        ts_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        if result.kind == "byte":
            ctx = result.notes_ctx
            notes = (
                f"Captured live {ts_iso}; range {ctx['range']}, "
                f"ratio {ctx['ratio']}, shape={ctx['shape']}."
            )
            payload: dict = {
                "name": result.name,
                "status": "hypothesis",
                "arbitration_id": f"0x{result.arb:03X}",
                "byte": result.byte,
                "bit_length": result.bit_length,
                "encoding": result.encoding,
                "scale": 1,
                "offset": 0,
                "notes": notes,
            }
        else:
            ctx = result.notes_ctx
            notes = (
                f"Captured live {ts_iso}; transition {ctx['transition']}, "
                f"z={ctx['z']}, μ={ctx['mu']:.2f}s, σ={ctx['sigma']:.2f}s."
            )
            payload = {
                "name": result.name,
                "status": "hypothesis",
                "arbitration_id": f"0x{result.arb:03X}",
                "byte": result.byte,
                "bit_offset": result.bit,
                "bit_length": result.bit_length,
                "encoding": result.encoding,
                "scale": 1,
                "offset": 0,
                "notes": notes,
            }
        path = self.session_dir / "hypotheses.yaml"
        with path.open("a") as f:
            yaml.safe_dump([payload], f, sort_keys=False, allow_unicode=True)

    def _watch_pin_for_hypothesis(self, result: HypothesisResult) -> WatchPin | None:
        """Build a raw-triplet WatchPin for the captured row. Always raw
        (kind='raw') since the signal isn't in signals.yaml yet — that's
        the entire point of capturing a hypothesis."""
        if result.kind == "byte":
            # Watch pane works at bit granularity; pin bit 0 of the byte
            # as a placeholder. The operator can always pin a richer view
            # via `w` once the signal lands in signals.yaml.
            arb, byte, bit = result.arb, result.byte, 0
        else:
            assert result.bit is not None
            arb, byte, bit = result.arb, result.byte, result.bit
        label = f"hyp:{result.name}  (0x{arb:03X} D{byte}.{bit})"
        return WatchPin(kind="raw", label=label, raw=(arb, byte, bit))

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
        with current value, a 12-cell sparkline of the recent buffer, the
        peak value over the sparkline window (blank for boolean pins),
        and the pin origin so a raw triplet stays unambiguous."""
        header = "[bold]Watch[/bold]"
        if not self.watch_pins:
            return header + "  [dim](press w to pin a signal; u to unpin)[/dim]"
        body: list[str] = []
        for pin in self.watch_pins:
            value_str = pin.current_text(self.latest, self.current_bytes)
            spark = sparkline(list(pin.buffer), boolean=pin.boolean)
            peak = pin.peak_text()
            peak_part = f"peak {peak:>10}" if peak else " " * 15
            body.append(
                f"  {pin.label:24s}  {value_str:>10}   {spark}   {peak_part}   [dim]{pin.label}[/dim]"
            )
        return header + "\n" + "\n".join(body)

    # ---- collapsed-pane summaries (ADR 0010 §1) --------------------------
    # Each one renders the pane's header followed by a brief content
    # summary — the layout doesn't shift because the screen only swaps
    # CSS height + content text, never tree structure.

    def watch_summary(self) -> str:
        n = len(self.watch_pins)
        return f"[bold]Watch[/bold]  [dim][{n} pin{'s' if n != 1 else ''}][/dim]"

    def decoded_summary(self) -> str:
        now = time.time()
        named = len(self.signals)
        live = sum(1 for sig in self.signals if sig.name in self.latest)
        stale = sum(
            1
            for sig in self.signals
            if (entry := self.latest.get(sig.name)) is not None
            and now - entry[2] > STALE_AFTER_SECS
        )
        return (
            f"[bold]Decoded signals[/bold]  "
            f"[dim][{live}/{named} live, {stale} stale][/dim]"
        )

    def flipped_summary(self) -> str:
        if self.window_label is None:
            return "[bold]Flipped bits[/bold]  [dim](no mark yet)[/dim]"
        known = len(self._known_signal_rows())
        unknown = len(self._unknown_pane_groups())
        return (
            f"[bold]Flipped bits[/bold]  "
            f"[dim][{known} known / {unknown} unknown, {self.window_label}][/dim]"
        )

    def discovery_summary(self) -> str:
        # Count distinct (arb, byte, bit) triplets currently in the
        # retention window. Cheaper than a full group — the operator just
        # wants "how busy is this pane right now."
        now = time.time()
        cutoff = now - self.retention_secs
        seen: set[tuple[int, int, int]] = set()
        for ts, arb, byte, bit, *_ in self.recent_anomalies:
            if ts >= cutoff:
                seen.add((arb, byte, bit))
        return (
            f"[bold]Live anomalies[/bold]  "
            f"[dim][{len(seen)} bit{'s' if len(seen) != 1 else ''}, z ≥ {self.z_threshold:.1f}][/dim]"
        )

    def active_bytes_summary(self) -> str:
        # Mirror the filtering in active_bytes_text() so the count matches
        # what the operator would see if the pane were expanded.
        now = time.time()
        rows = 0
        for (arb, byte), stats in self.byte_activity.items():
            if (arb, byte) in self._byte_index:
                continue
            if byte == 7 and not self.show_d7:
                continue
            buf = stats.buffer
            if len(buf) < 2:
                continue
            lo = min(v for _, v in buf)
            hi = max(v for _, v in buf)
            short_range = hi - lo
            threshold = max(
                BASELINE_FLOOR, self.byte_activity_ratio * stats.baseline_range_ewma
            )
            active_now = short_range > threshold
            # ADR 0012 — visibility window is now retention_secs (was
            # hysteresis_secs). Hysteresis is the HOT/DIM boundary inside
            # that window, not the exit gate.
            in_window = (
                stats.last_active_ts is not None
                and now - stats.last_active_ts < self.byte_activity_retention_secs
            )
            if active_now or in_window:
                rows += 1
        return (
            f"[bold]Active unknown bytes[/bold]  "
            f"[dim][{rows} row{'s' if rows != 1 else ''}, ratio ≥ {self.byte_activity_ratio:.1f}×][/dim]"
        )

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
                if sig.bit_length == 8 * len(sig.bytes_):
                    for b in sig.bytes_:
                        for bit in range(8):
                            index[(sig.arbitration_id, b, bit)] = sig.name
                else:
                    ordered = (
                        sig.bytes_ if sig.byte_order == "big" else tuple(reversed(sig.bytes_))
                    )
                    for combined_bit in range(sig.bit_offset, sig.bit_offset + sig.bit_length):
                        byte_from_lsb = combined_bit // 8
                        bit_in_byte = combined_bit % 8
                        byte_index = ordered[-1 - byte_from_lsb]
                        index[(sig.arbitration_id, byte_index, bit_in_byte)] = sig.name
            elif sig.byte is not None:
                for bit in range(sig.bit_offset, sig.bit_offset + sig.bit_length):
                    index[(sig.arbitration_id, sig.byte, bit)] = sig.name
        return index

    def _compute_byte_index(self) -> dict[tuple[int, int], str]:
        """Map every byte touched by any signal (even a single-bit one) to
        that signal's name. Used by the active-unknown-bytes pane (ADR
        0008) to exclude named bytes — those belong to the decoded pane."""
        index: dict[tuple[int, int], str] = {}
        for sig in self.signals:
            if sig.bytes_ is not None:
                for b in sig.bytes_:
                    index[(sig.arbitration_id, b)] = sig.name
            elif sig.byte is not None:
                index[(sig.arbitration_id, sig.byte)] = sig.name
        return index

    def _update_byte_activity(self, ts: float, arb: int, byte: int, val: int) -> None:
        """ADR 0008 — append (ts, val) to the per-byte ring buffer, evict
        old entries past the window, refresh short_range + the long EWMA
        baseline, and timestamp the byte as active if it currently trips
        the threshold (consumed by the pane's hysteresis check).

        ADR 0012 — also drive the separate display buffer (~4 Hz sample
        cadence, fixed length, decoupled from the detection window) and
        track peak ratio + peak timestamp for the persistent annotation
        on the redesigned Active unknown bytes pane. The buffers split
        so the sparkline keeps showing the byte's shape during the
        decay tail instead of washing out as the detection window
        slides past."""
        stats = self.byte_activity.get((arb, byte))
        if stats is None:
            stats = ByteActivityStats()
            self.byte_activity[(arb, byte)] = stats
        buf = stats.buffer
        buf.append((ts, val))
        window = self.byte_activity_window_secs
        while buf and ts - buf[0][0] > window:
            buf.popleft()

        # ADR 0012 — display buffer at ~8 Hz, independent of broadcast rate.
        if ts - stats.last_display_sample_ts >= BYTE_ACTIVITY_SAMPLE_SECS:
            stats.display_buffer.append(float(val))
            stats.last_display_sample_ts = ts

        # Track value-changes. The frozen sparkline snapshot is taken
        # by the render loop once the value has been stable for
        # BYTE_BURST_FREEZE_DELAY_SECS, so we record when the value
        # most recently changed AND wipe any prior frozen snapshot so
        # the next burst gets a fresh capture. Replaces the old
        # "clear frozen on every active frame" rule, which never let a
        # mid-burst plateau settle into a stable snapshot.
        if stats.prev_val is None or stats.prev_val != val:
            stats.last_value_change_ts = ts
            if stats.frozen_buffer:
                stats.frozen_buffer = []
        stats.prev_val = val

        if len(buf) < 2:
            return
        lo = min(v for _, v in buf)
        hi = max(v for _, v in buf)
        short_range = hi - lo
        stats.baseline_range_ewma += ACTIVITY_EWMA_ALPHA * (
            short_range - stats.baseline_range_ewma
        )
        threshold = max(BASELINE_FLOOR, self.byte_activity_ratio * stats.baseline_range_ewma)
        if short_range > threshold:
            stats.last_active_ts = ts
            # ADR 0012 — track peak ratio across the current activity
            # episode. ∞ wins (first-activity case); otherwise the
            # arithmetic ratio. Reset back at retention boundary in the
            # render loop.
            if stats.baseline_range_ewma <= BASELINE_FLOOR:
                cur_ratio = math.inf
            else:
                cur_ratio = short_range / stats.baseline_range_ewma
            # math.inf > finite > 0; cur_ratio either replaces or matches.
            if cur_ratio > stats.peak_ratio or stats.peak_ratio_ts is None:
                stats.peak_ratio = cur_ratio
                stats.peak_ratio_ts = ts

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
        *,
        bucket_window: tuple[float, float] | None = None,
        bucket_count: int = SPARKLINE_WIDTH,
    ) -> list[GroupedRow]:
        """Group per-bit anomaly rows by arbitration ID (ADR 0007 #5).

        Row tuple: (arb, byte, bit, transition, event_ts, z, mu, sigma).
        `event_ts` is latency-from-mark for the mark-driven pane, or
        wall-clock for the continuous discovery pane — opaque to the
        grouper. `z=math.inf` marks a warmup-tier event.

        ADR 0011 — when `bucket_window=(start_ts, end_ts)` is passed,
        every group also gets a `bucket_timeline` of `bucket_count`
        anomaly counts spanning that wall-clock window (used by the
        live anomalies pane's per-row activity sparkline). The
        grouper is opaque to whether `event_ts` is wall-clock or
        latency-from-mark; the caller is responsible for only passing
        a `bucket_window` when `event_ts` lives in the same time base."""
        groups: dict[int, list[tuple[int, int, str, float, float, float, float]]] = (
            defaultdict(list)
        )
        for arb, byte, bit, transition, event_ts, z, mu, sigma in rows:
            groups[arb].append((byte, bit, transition, event_ts, z, mu, sigma))

        if bucket_window is not None:
            bw_start, bw_end = bucket_window
            span = max(bw_end - bw_start, 1e-9)
            bucket_size = span / bucket_count

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
            buckets: list[int] = (
                [0] * bucket_count if bucket_window is not None else []
            )
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
                if bucket_window is not None:
                    idx = int((event_ts - bw_start) / bucket_size)
                    if idx < 0:
                        idx = 0
                    elif idx >= bucket_count:
                        idx = bucket_count - 1
                    buckets[idx] += 1
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
                    count=len(items),
                    bucket_timeline=buckets,
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
        """Always-on anomaly pane (ADR 0007 §4, redesigned in ADR 0011).

        Stable-by-arb rows with a per-row activity sparkline + brightness
        decay + co-occurrence accent + mark halo. The eye anchors on
        positions, fresh events brighten in place, and bursts colour
        together so cross-ID structure is visible at a glance. Marks
        are still NOT required — the pane fills passively as the bus
        reacts; halo just bridges back to the mark-driven pane when
        the operator does press a hotkey."""
        now = time.time()
        cutoff = now - self.retention_secs
        # Prune from the left — entries are appended in ts-monotonic order.
        while self.recent_anomalies and self.recent_anomalies[0][0] < cutoff:
            self.recent_anomalies.popleft()
        header = f"[bold]Live anomalies[/bold]  [dim](last {self.retention_secs:.0f}s, z ≥ {self.z_threshold:.1f})[/dim]"
        if not self.recent_anomalies:
            return header + "\n  (idle — no anomalous flips yet)"

        groups = self._group_rows_by_arb(
            (
                (arb, byte, bit, transition, ts, z, mu, sigma)
                for ts, arb, byte, bit, transition, _interval, z, mu, sigma in self.recent_anomalies
            ),
            bucket_window=(cutoff, now),
            bucket_count=SPARKLINE_WIDTH,
        )
        # Stable position — arb ascending. Rows above an aged-out gap
        # keep their position; everything below shifts up by one (rare,
        # ADR 0011 accepts the small jitter for the no-reshuffle win).
        groups.sort(key=lambda g: g.arb)

        accent_by_arb = self._anomaly_accents(groups, now)
        halo_window_end = (
            self.last_event_ts + FLIP_WINDOW_SECS
            if self.last_event_ts is not None
            else None
        )
        halo_visible = is_halo_active(now, self.last_event_ts)

        max_rows = DISCOVERY_PANE_ROWS - 2
        body: list[str] = []
        for g in groups[:max_rows]:
            row_halo = (
                halo_visible
                and self.last_event_ts is not None
                and halo_window_end is not None
                and self.last_event_ts <= g.latest_ts <= halo_window_end
            )
            body.append(
                _render_anomaly_row(
                    g,
                    now,
                    accent=accent_by_arb.get(g.arb),
                    halo=row_halo,
                    expect_shape=self.expect_shape,
                )
            )
        if len(groups) > max_rows:
            body.append(f"  … and {len(groups) - max_rows} more")
        return header + "\n" + "\n".join(body)

    def _anomaly_accents(
        self, groups: list[GroupedRow], now: float
    ) -> dict[int, str]:
        """ADR 0011 — pick co-occurrence accent colours for the live
        anomalies pane.

        Cluster groups whose `latest_ts` falls within
        ANOMALY_COOCCUR_SECS of each other AND whose latest event is
        recent (within ANOMALY_HOT_SECS). Clusters of size ≥2 get an
        accent from ANOMALY_ACCENT_COLORS in cluster-onset order;
        singletons and stale bursts get nothing. Only the most-recent
        few clusters are coloured — colour exhaustion past that means
        the eye stops reading accents as meaningful."""
        recent = [g for g in groups if is_hot(now, g.latest_ts)]
        if len(recent) < 2:
            return {}
        recent.sort(key=lambda g: g.latest_ts)
        clusters: list[list[GroupedRow]] = []
        current: list[GroupedRow] = [recent[0]]
        for g in recent[1:]:
            if g.latest_ts - current[-1].latest_ts <= ANOMALY_COOCCUR_SECS:
                current.append(g)
            else:
                clusters.append(current)
                current = [g]
        clusters.append(current)
        out: dict[int, str] = {}
        colour_idx = 0
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            colour = ANOMALY_ACCENT_COLORS[colour_idx % len(ANOMALY_ACCENT_COLORS)]
            colour_idx += 1
            for g in cluster:
                out[g.arb] = colour
        return out

    def active_bytes_text(self) -> str:
        """Active-unknown-bytes pane (ADR 0008, redesigned in ADR 0012).

        Lists every (arb, byte) currently tripping the rolling-range
        threshold OR still within the retention window, sorted by
        peak ratio descending so recently-loud rows stay at the top
        through their decay tier. Bytes covered by signals.yaml are
        excluded — they belong to the decoded pane. D7 is gated by
        --show-d7 for parity with the bit panes (D7 checksums would
        dominate).

        Visual contract per ADR 0012:
        - HOT tier (active_now OR age < hysteresis_secs): default
          brightness, live sparkline from `display_buffer`.
        - DIM tier (hysteresis_secs ≤ age < retention_secs): row wrapped
          in `[dim]`, sparkline from `frozen_buffer` (the shape the
          byte was making at peak — preserved through decay).
        - At active→tail transition, snapshot `display_buffer` into
          `frozen_buffer` so the sparkline doesn't wash out. Cleared
          if activity resumes (`_update_byte_activity`).
        - At retention boundary, the row drops AND peak_ratio/ts
          reset so the next episode starts fresh."""
        now = time.time()
        header = (
            f"[bold]Active unknown bytes[/bold]  "
            f"[dim](window {self.byte_activity_window_secs:.1f}s, "
            f"ratio ≥ {self.byte_activity_ratio:.1f}×, "
            f"hold {self.byte_activity_retention_secs:.0f}s)[/dim]"
        )
        rows: list[tuple[float, int, int, int, bool, bool]] = []
        for (arb, byte), stats in self.byte_activity.items():
            if (arb, byte) in self._byte_index:
                continue
            if byte == 7 and not self.show_d7:
                continue
            buf = stats.buffer
            if len(buf) < 2:
                continue
            lo = min(v for _, v in buf)
            hi = max(v for _, v in buf)
            short_range = hi - lo
            threshold = max(
                BASELINE_FLOOR, self.byte_activity_ratio * stats.baseline_range_ewma
            )
            active_now = short_range > threshold

            # Visibility check (ADR 0012): row stays through the full
            # retention window. Past it, drop and reset peak so the next
            # episode for this byte starts clean.
            age = (
                now - stats.last_active_ts
                if stats.last_active_ts is not None
                else math.inf
            )
            if not active_now and age >= self.byte_activity_retention_secs:
                stats.peak_ratio = 0.0
                stats.peak_ratio_ts = None
                stats.frozen_buffer = []
                continue
            if not active_now and stats.last_active_ts is None:
                # Never been active, currently quiet — nothing to show.
                continue

            # Freeze the display buffer once the byte's value has been
            # stable for BYTE_BURST_FREEZE_DELAY_SECS. Earlier than the
            # original active→tail trigger (which fires ~2 s late as the
            # detection buffer slides out) so the burst lands on the
            # right edge of the sparkline instead of drifting middle-
            # left. _update_byte_activity wipes frozen_buffer on every
            # value-change, so a fresh burst always gets re-snapshotted.
            if (
                not stats.frozen_buffer
                and stats.display_buffer
                and stats.last_value_change_ts > 0.0
                and now - stats.last_value_change_ts >= BYTE_BURST_FREEZE_DELAY_SECS
            ):
                stats.frozen_buffer = list(stats.display_buffer)

            first_activity = stats.baseline_range_ewma <= BASELINE_FLOOR
            cur = self.current_bytes.get((arb, byte), 0)
            dim = (not active_now) and age >= self.byte_activity_hysteresis_secs
            rows.append((stats.peak_ratio, arb, byte, cur, dim, first_activity))

        if not rows:
            return header + "\n  (idle — no anonymous byte currently sweeping)"
        # ADR 0012 — sort by peak ratio so recently-loud rows stay anchored
        # at the top across their decay tier. math.inf naturally wins.
        rows.sort(key=lambda r: -r[0])
        max_rows = ACTIVE_BYTES_PANE_ROWS - 2
        body: list[str] = []
        for _peak, arb, byte, cur, dim, first in rows[:max_rows]:
            stats = self.byte_activity[(arb, byte)]
            # Shape leads, first-activity follows as a tag — both surface
            # together so a sweep on a never-before-active byte still tells
            # the operator what kind of signal it looks like.
            shape_src = stats.frozen_buffer or list(stats.display_buffer)
            shape = classify_byte([int(v) for v in shape_src])
            parts: list[str] = []
            if shape:
                parts.append(shape)
            if first:
                parts.append("(first activity)")
            suffix = f"  [dim]{'  '.join(parts)}[/dim]" if parts else ""
            # ADR 0013 — expect-shape lens. Neutral tier when shape is
            # empty (classifier needs ≥4 samples) so the first second
            # of a sweep isn't punished.
            expect_accent = False
            expect_mismatch = False
            if self.expect_shape is not None and shape:
                if shape == self.expect_shape:
                    expect_accent = True
                else:
                    expect_mismatch = True
            body.append(
                _render_byte_row(
                    stats,
                    arb,
                    byte,
                    cur,
                    now=now,
                    dim=dim,
                    shape_suffix=suffix,
                    expect_accent=expect_accent,
                    expect_mismatch=expect_mismatch,
                )
            )
        if len(rows) > max_rows:
            body.append(f"  … and {len(rows) - max_rows} more")
        return header + "\n" + "\n".join(body)

    def status_text(self, extra: str = "") -> str:
        dropped = f"  [red]dropped {self.bridge.dropped}[/red]" if self.bridge.dropped else ""
        elapsed = int(time.monotonic() - self.session_start)
        hh, rem = divmod(elapsed, 3600)
        mm, ss = divmod(rem, 60)
        extra_str = f"   {extra}" if extra else ""
        # ADR 0013 — expect-shape token. Only rendered when armed so the
        # default tunables line stays compact for operators not using
        # the lens.
        expect_token = ""
        if self.expect_shape is not None:
            glyphs = {"sensor": "∿", "counter": "↻", "step": "⊟", "boolean": "▔_"}
            g = glyphs.get(self.expect_shape, "")
            expect_token = f"  [bold green]expect={self.expect_shape} {g}[/bold green]"
        tunables = (
            f"z={self.z_threshold:.1f}  ratio={self.byte_activity_ratio:.1f}×  "
            f"d7={'on' if self.show_d7 else 'off'}  "
            f"suppressed={'on' if self.show_suppressed else 'off'}"
            f"{expect_token}"
        )
        return (
            f"[bold]Status[/bold]  "
            f"[{hh:02d}:{mm:02d}:{ss:02d}]   "
            f"frames {self.total_frames:>8,}   "
            f"ids {len(self.unique_ids):>3}   "
            f"marks {self.events_log.count:>3}   "
            f"snapshots {self.snapshot_seq}{extra_str}{dropped}\n"
            f"[dim]{tunables}[/dim]\n"
            f"[dim]hotkey mark · '.' snap · '?' legend · 'q' quit · "
            f"F6/F7 z · Shift-←→ ratio · Ctrl-D D7 · Ctrl-Y supp · Ctrl-N hyp · Ctrl-E expect · F1..F5 fold[/dim]"
        )
