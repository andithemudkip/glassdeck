"""Top-level screens hosted by the LiveView app.

The two main screens are thin views — all per-frame state lives on the
App and screens just read it back out via `self.app`."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from .constants import PREVIEW_LOOKAHEAD

if TYPE_CHECKING:
    from .app import LiveView


class AnalysisScreen(Screen):
    """Three-pane decoded / flipped-bits / status view. Reads App state."""

    CSS = """
    AnalysisScreen { layout: vertical; }
    #watch           { height: auto; min-height: 3; max-height: 8; border: round blue;    padding: 0 1; }
    #decoded         { height: 1fr; border: round green;  padding: 0 1; }
    #flipped-row     { height: 12; layout: horizontal; }
    #flipped-known   { width: 1fr; height: 100%; border: round cyan;   padding: 0 1; }
    #flipped-unknown { width: 1fr; height: 100%; border: round yellow; padding: 0 1; }
    #discovery       { height: 10; border: round magenta; padding: 0 1; }
    #status          { height: 3;  border: round white;  padding: 0 1; }
    """

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("", id="watch"),
            Static("", id="decoded"),
            Horizontal(
                Static("", id="flipped-known"),
                Static("", id="flipped-unknown"),
                id="flipped-row",
            ),
            Static("", id="discovery"),
            Static("", id="status"),
        )

    def on_mount(self) -> None:
        self.refresh_panes()

    def refresh_panes(self) -> None:
        app: LiveView = self.app  # type: ignore[assignment]
        try:
            self.query_one("#watch", Static).update(app.watch_text())
            self.query_one("#decoded", Static).update(app.decoded_text())
            known_text, unknown_text = app.flipped_texts()
            self.query_one("#flipped-known", Static).update(known_text)
            self.query_one("#flipped-unknown", Static).update(unknown_text)
            self.query_one("#discovery", Static).update(app.discovery_text())
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
