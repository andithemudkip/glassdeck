"""Top-level screens hosted by the LiveView app.

The two main screens are thin views — all per-frame state lives on the
App and screens just read it back out via `self.app`."""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Digits, Static

from .constants import ACT_HIGHLIGHT_SECS, MARK_FLASH_SECS, PREVIEW_LOOKAHEAD

if TYPE_CHECKING:
    from .app import LiveView


# Pane indices (top-to-bottom, excluding the always-visible status pane).
# `flipped-row` is one cycle slot — the side-by-side known/unknown panes
# share their container, so they collapse together (ADR 0010 §1).
PANE_IDS = ["watch", "decoded", "flipped-row", "discovery", "active-bytes"]


class AnalysisScreen(Screen):
    """Three-pane decoded / flipped-bits / status view. Reads App state."""

    CSS = """
    AnalysisScreen { layout: vertical; }
    #watch           { height: auto; min-height: 3; max-height: 8; border: round blue;    padding: 0 1; }
    #decoded         { height: 1fr; min-height: 13; border: round green;  padding: 0 1; }
    #flipped-row     { height: 12; layout: horizontal; }
    #flipped-known   { width: 1fr; height: 100%; border: round cyan;   padding: 0 1; }
    #flipped-unknown { width: 1fr; height: 100%; border: round yellow; padding: 0 1; }
    #discovery       { height: 10; border: round magenta; padding: 0 1; }
    #active-bytes    { height: 12; border: round red;     padding: 0 1; }
    #status          { height: 4;  border: round white;  padding: 0 1; }

    #watch.collapsed,
    #decoded.collapsed,
    #discovery.collapsed,
    #active-bytes.collapsed { height: 3; min-height: 3; max-height: 3; }
    #flipped-row.collapsed { height: 3; }
    """

    # F-keys instead of Ctrl+digit: Mac terminals don't deliver a distinct
    # sequence for Ctrl+1..5 — Textual just sees the bare digit, which then
    # falls into capture.py's printable-char mark fallback.
    BINDINGS = [
        Binding("f1", "toggle_pane(0)", "collapse watch", show=False),
        Binding("f2", "toggle_pane(1)", "collapse decoded", show=False),
        Binding("f3", "toggle_pane(2)", "collapse flipped", show=False),
        Binding("f4", "toggle_pane(3)", "collapse discovery", show=False),
        Binding("f5", "toggle_pane(4)", "collapse active-bytes", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        # Session-local; resets to all-expanded on each launch by design.
        self.is_collapsed: dict[int, bool] = {i: False for i in range(len(PANE_IDS))}

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
            Static("", id="active-bytes"),
            Static("", id="status"),
        )

    def on_mount(self) -> None:
        self.refresh_panes()

    def action_toggle_pane(self, idx: int) -> None:
        if idx not in self.is_collapsed:
            return
        self.is_collapsed[idx] = not self.is_collapsed[idx]
        # Apply the CSS class immediately; refresh_panes() will repaint
        # content. The class lives on the container for flipped-row so
        # the height collapses with both children inside it.
        self._apply_collapse_classes()
        self.refresh_panes()

    def _apply_collapse_classes(self) -> None:
        for idx, pane_id in enumerate(PANE_IDS):
            try:
                widget = self.query_one(f"#{pane_id}")
            except Exception:
                continue
            widget.set_class(self.is_collapsed[idx], "collapsed")

    def refresh_panes(self) -> None:
        app: LiveView = self.app  # type: ignore[assignment]
        try:
            self._apply_collapse_classes()
            # Watch
            if self.is_collapsed[0]:
                self.query_one("#watch", Static).update(app.watch_summary())
            else:
                self.query_one("#watch", Static).update(app.watch_text())
            # Decoded
            if self.is_collapsed[1]:
                self.query_one("#decoded", Static).update(app.decoded_summary())
            else:
                self.query_one("#decoded", Static).update(app.decoded_text())
            # Flipped (known + unknown share one collapse slot)
            if self.is_collapsed[2]:
                self.query_one("#flipped-known", Static).update(app.flipped_summary())
                self.query_one("#flipped-unknown", Static).update("")
            else:
                known_text, unknown_text = app.flipped_texts()
                self.query_one("#flipped-known", Static).update(known_text)
                self.query_one("#flipped-unknown", Static).update(unknown_text)
            # Discovery
            if self.is_collapsed[3]:
                self.query_one("#discovery", Static).update(app.discovery_summary())
            else:
                self.query_one("#discovery", Static).update(app.discovery_text())
            # Active bytes
            if self.is_collapsed[4]:
                self.query_one("#active-bytes", Static).update(app.active_bytes_summary())
            else:
                self.query_one("#active-bytes", Static).update(app.active_bytes_text())
            self.query_one("#status", Static).update(app.status_text())
        except Exception:
            pass


class OperatorScreen(Screen):
    """Big-prompt + countdown screen that drives the rider through a
    procedure.yaml.

    UX model (ADR 0006, refined): the big prompt is always "the action in
    front of you" — never "the rest you're already doing". During the
    trailing `countdown_from` window of a settle step, the big prompt
    swaps to the *upcoming* action so the rider's eye stays locked on the
    text they're about to act on, no preview-vs-current ambiguity.

    Four stoplight modes drive border color:
      • rest  (blue)   — calm settle/setup, hands off
      • ready (yellow) — countdown active, get ready
      • act   (red)    — first ACT_HIGHLIGHT_SECS of an action step
      • end   (dim)    — paused, or terminal manual-advance step
    """

    # CSS classes on the OperatorScreen itself drive the mode color. Same
    # widgets, different borders — minimal layout churn between modes.
    CSS = """
    OperatorScreen { layout: vertical; }
    #op-header    { height: 1; padding: 0 2; }
    #op-prompt    { height: 9; content-align: center middle; border: round blue; margin: 0 2; padding: 1 2; }
    #op-digits    { height: 5; content-align: center middle; color: $text-muted; }
    #op-now       { height: 3; content-align: center middle; }
    #op-flash     { height: 1; padding: 0 4; }
    #op-preview   { height: 5; padding: 0 4; }
    #op-help      { height: 1; padding: 0 2; }
    #op-status    { dock: bottom; height: 4; border: round white; padding: 0 1; }

    OperatorScreen.mode-rest  #op-prompt { border: round blue;   }
    OperatorScreen.mode-ready #op-prompt { border: round yellow; }
    OperatorScreen.mode-act   #op-prompt { border: heavy red;    }
    OperatorScreen.mode-end   #op-prompt { border: round white;  }

    OperatorScreen.mode-ready #op-digits { color: yellow; }
    OperatorScreen.mode-act   #op-digits { color: red;    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="op-header")
        yield Static("", id="op-prompt")
        yield Digits("", id="op-digits")
        yield Static("", id="op-now")
        yield Static("", id="op-flash")
        yield Static("", id="op-preview")
        yield Static("", id="op-help")
        yield Static("", id="op-status")

    def on_mount(self) -> None:
        self.refresh_panes()

    def _set_mode(self, mode: str) -> None:
        for cls in ("mode-rest", "mode-ready", "mode-act", "mode-end"):
            self.set_class(cls == f"mode-{mode}", cls)

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
        n_total = len(steps)
        next_step = steps[i + 1] if i + 1 < n_total else None
        elapsed = app.step_elapsed()
        remaining = (
            None if step.duration_secs is None else step.duration_secs - elapsed
        )

        # --- mode + which prompt is "front of mind" -----------------------
        countdown_active = (
            next_step is not None
            and next_step.countdown_from is not None
            and remaining is not None
            and 0 < remaining <= next_step.countdown_from
        )
        in_act_window = step.mark is not None and elapsed < ACT_HIGHLIGHT_SECS

        if app.paused:
            mode = "end"
        elif step.duration_secs is None:
            mode = "end"
        elif countdown_active:
            mode = "ready"
        elif in_act_window:
            mode = "act"
        else:
            mode = "rest"
        self._set_mode(mode)

        # During the countdown, swap the big prompt to the upcoming action
        # so the rider stares at what they're about to do, not at "rest".
        focus_step = next_step if (countdown_active and next_step is not None) else step
        focus_is_upcoming = countdown_active and next_step is not None

        # --- header: step counter + progress bar + rep counter ----------
        bar_len = 20
        filled = int(bar_len * (i + 1) / n_total)
        bar = "█" * filled + "░" * (bar_len - filled)
        # Rep counter follows the focus_step so it tracks the prompt's loop
        # context even during the cross-fade into a new repeat block.
        rep_chunk = ""
        rep_step = focus_step
        if rep_step.iter is not None and rep_step.loop_count is not None:
            noun = (
                rep_step.mark.key.upper() if rep_step.mark and rep_step.mark.key else "REP"
            )
            rep_chunk = (
                f"  │  [bold cyan]{noun} {rep_step.iter} of {rep_step.loop_count}[/bold cyan]"
            )
        self.query_one("#op-header", Static).update(
            f"[bold]STEP {i + 1} of {n_total}[/bold]   {bar}{rep_chunk}"
        )

        # --- big prompt --------------------------------------------------
        prefix = ""
        if mode == "ready":
            prefix = "[bold yellow]GET READY[/bold yellow]\n"
        elif mode == "act":
            prefix = "[bold red]ACT NOW[/bold red]\n"
        elif focus_is_upcoming:
            # Defensive fallback — focus is upcoming but we're not in ready
            # mode. Shouldn't trigger today but keep the prompt honest.
            prefix = "[bold]NEXT[/bold]\n"
        self.query_one("#op-prompt", Static).update(
            f"{prefix}[bold]{focus_step.prompt}[/bold]"
        )

        # --- giant countdown digits + NOW banner ------------------------
        digits = self.query_one("#op-digits", Digits)
        now_label = self.query_one("#op-now", Static)
        if app.paused:
            digits.update("")
            now_label.update("[bold yellow][PAUSED][/bold yellow]")
        elif step.duration_secs is None:
            digits.update("")
            now_label.update("[dim]— press q to stop —[/dim]")
        elif countdown_active:
            digit = max(1, math.ceil(remaining))  # type: ignore[arg-type]
            digits.update(str(digit))
            now_label.update("")
        elif in_act_window:
            digits.update("")
            now_label.update("[bold red on white] ▼ DO IT ▼ [/bold red on white]")
        else:
            digits.update("")
            if remaining is not None and remaining > 0:
                now_label.update(f"[dim]{remaining:.0f}s[/dim]")
            else:
                now_label.update("")

        # --- mark-fired flash -------------------------------------------
        flash_text = ""
        last = app._last_mark
        if last is not None:
            ts, key, label = last
            age = time.monotonic() - ts
            if age < MARK_FLASH_SECS:
                shown = label if label else key
                flash_text = f"[bold green]✓ marked:[/bold green] {shown}"
        self.query_one("#op-flash", Static).update(flash_text)

        # --- preview -----------------------------------------------------
        # Skip whichever step is currently the big prompt (focus) so the
        # rider doesn't see the same line twice (big + tiny preview).
        skip_idx = i + 1 if focus_is_upcoming else i
        preview_lines: list[str] = ["[bold]Coming up:[/bold]"]
        added = 0
        j = skip_idx + 1
        while added < PREVIEW_LOOKAHEAD and j < n_total:
            ns = steps[j]
            dur = "manual" if ns.duration_secs is None else f"{ns.duration_secs:g}s"
            cd = f", ⏱{ns.countdown_from}" if ns.countdown_from else ""
            preview_lines.append(f"  → {ns.prompt}  [dim]({dur}{cd})[/dim]")
            added += 1
            j += 1
        if added == 0:
            preview_lines.append("  [dim](last step)[/dim]")
        self.query_one("#op-preview", Static).update("\n".join(preview_lines))

        self.query_one("#op-help", Static).update(
            "[dim]Tab: analysis view   Space: pause   ←: prev step   q: quit[/dim]"
        )

        self.query_one("#op-status", Static).update(
            app.status_text(extra=f"step {i + 1}/{n_total}")
        )
