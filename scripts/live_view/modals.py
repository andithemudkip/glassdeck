"""Modal overlay screens: legend popup, watch-pin search, unpin picker,
hypothesis-capture form, expect-shape picker."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, ListItem, ListView, Static

from signals import Signal

from .state import WatchPin


# Rows passed into HypothesisModal — snapshotted at open-time from the
# pane state so numbered selection stays stable while the operator types.

@dataclass(frozen=True)
class HypothesisByteRow:
    arb: int
    byte: int
    value: int
    short_range: int
    ratio: float          # math.inf for first-activity
    shape: str            # "" if classifier returned nothing
    first_activity: bool


@dataclass(frozen=True)
class HypothesisBitRow:
    arb: int
    byte: int
    bit: int
    transition: str       # "0→1" / "1→0"
    z: float              # math.inf for warmup
    mu: float
    sigma: float


@dataclass(frozen=True)
class HypothesisResult:
    """Returned from HypothesisModal.dismiss(). Kind branches the YAML
    stanza shape and the WatchPin construction at app.py:_on_hypothesis_submit."""

    kind: Literal["byte", "bit"]
    name: str
    arb: int
    byte: int
    bit: int | None          # bit_offset for kind="bit", else None
    bit_length: int          # 8 for byte, 1 for bit
    encoding: str
    pin_to_watch: bool
    # Echoed-through context for the YAML `notes` field — keeps the
    # capture-time breadcrumbs visible in `hypotheses.yaml` for the next
    # session to reason about (ADR 0010 §3).
    notes_ctx: dict


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


class _CenteredModal(ModalScreen):
    """Shared envelope for the watch / unpin modals: centered box, white
    border, dismiss-on-Esc with `None`. Subclasses provide their own box
    CSS and compose body."""

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)


_MODAL_BOX_CSS = (
    "height: auto; border: round white; padding: 1 2; background: $surface;"
)


class WatchModal(_CenteredModal):
    """Modal for pinning a signal (or raw `arb:byte.bit` triplet) to the
    watch pane (ADR 0007 #1). Input drives a live-filtered ListView of
    signal names; Enter pins; Esc cancels."""

    CSS = f"""
    WatchModal {{ align: center middle; }}
    #watch-box {{ width: 72; max-height: 18; {_MODAL_BOX_CSS} }}
    #watch-input {{ height: 3; }}
    #watch-list  {{ height: auto; max-height: 8; }}
    """

    def __init__(self, signals: list[Signal]) -> None:
        super().__init__()
        self._signals = signals

    def compose(self) -> ComposeResult:
        with Vertical(id="watch-box"):
            yield Static("[bold]Pin a signal[/bold]")
            yield Input(placeholder="signal name or 0x290:3.2", id="watch-input")
            yield ListView(id="watch-list")
            yield Static("[dim]Enter pin · Esc cancel[/dim]")

    def on_mount(self) -> None:
        self._refresh_list("")
        self.query_one("#watch-input", Input).focus()

    def _refresh_list(self, query: str) -> None:
        lv = self.query_one("#watch-list", ListView)
        lv.clear()
        q = query.strip().lower()
        for s in self._signals:
            if q and q not in s.name.lower():
                continue
            lv.append(ListItem(Static(f"{s.name}  [dim]({s.status})[/dim]"), name=s.name))
        # Highlight the first row so ↑/↓ navigation and the "Enter on
        # highlighted item" path have a starting point. Without this the
        # initial selection is None and Enter on the empty input is a no-op.
        if len(lv.children) > 0:
            lv.index = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        self._refresh_list(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(self._resolve(event.value.strip()))

    def on_list_view_selected(self, event) -> None:
        # Fires on click and on Enter when the ListView has focus.
        name = getattr(event.item, "name", None)
        if name:
            self.dismiss(self._pin_for_signal_name(name))

    def on_key(self, event) -> None:
        # While the Input has focus, ↑/↓ would otherwise be ignored — route
        # them to the ListView so arrow-navigation works without the operator
        # having to Tab over to it. PageUp/PageDown follow the same rule.
        if event.key in ("down", "up", "pagedown", "pageup"):
            lv = self.query_one("#watch-list", ListView)
            n = len(lv.children)
            if n == 0:
                return
            cur = lv.index if lv.index is not None else 0
            if event.key == "down":
                lv.index = min(cur + 1, n - 1)
            elif event.key == "up":
                lv.index = max(cur - 1, 0)
            elif event.key == "pagedown":
                lv.index = min(cur + 5, n - 1)
            elif event.key == "pageup":
                lv.index = max(cur - 5, 0)
            event.stop()
            return
        super().on_key(event)

    def _resolve(self, text: str) -> WatchPin | None:
        # Raw triplet form 0x<hex>:<byte>.<bit> — syntax not present in the
        # signal list, so it always takes precedence over the highlighted row.
        if text.lower().startswith("0x") and ":" in text and "." in text:
            try:
                head, rest = text.split(":", 1)
                byte_s, bit_s = rest.split(".", 1)
                arb = int(head, 16)
                byte = int(byte_s)
                bit = int(bit_s)
                if 0 <= byte <= 7 and 0 <= bit <= 7:
                    return WatchPin(
                        kind="raw",
                        label=f"0x{arb:03X} D{byte}.{bit}",
                        raw=(arb, byte, bit),
                    )
            except ValueError:
                pass

        # Prefer the highlighted list row — what the operator sees selected
        # wins over a substring match against the (possibly stale) input text.
        lv = self.query_one("#watch-list", ListView)
        if lv.index is not None and 0 <= lv.index < len(lv.children):
            item = lv.children[lv.index]
            name = getattr(item, "name", None)
            if name:
                return self._pin_for_signal_name(name)

        if not text:
            return None

        # Fallback when the filter excluded everything: match against the
        # full signal list directly. Exact → prefix → substring.
        lower = text.lower()
        sig = next((s for s in self._signals if s.name.lower() == lower), None)
        if sig is None:
            sig = next((s for s in self._signals if s.name.lower().startswith(lower)), None)
        if sig is None:
            sig = next((s for s in self._signals if lower in s.name.lower()), None)
        if sig is None:
            return None
        return self._pin_for_signal_name(sig.name)

    def _pin_for_signal_name(self, name: str) -> WatchPin | None:
        sig = next((s for s in self._signals if s.name == name), None)
        if sig is None:
            return None
        return WatchPin(kind="signal", label=sig.name, signal=sig)


class UnpinModal(_CenteredModal):
    """Modal listing current watch pins; Enter removes the highlighted
    entry (ADR 0007 #1). Symmetric verbs `w` (pin) / `u` (unpin) avoid
    the toggle-w ambiguity."""

    CSS = f"""
    UnpinModal {{ align: center middle; }}
    #unpin-box {{ width: 60; max-height: 14; {_MODAL_BOX_CSS} }}
    #unpin-list {{ height: auto; max-height: 8; }}
    """

    def __init__(self, pins: list[WatchPin]) -> None:
        super().__init__()
        self._pins = list(pins)

    def compose(self) -> ComposeResult:
        with Vertical(id="unpin-box"):
            yield Static("[bold]Unpin a watch[/bold]")
            yield ListView(id="unpin-list")
            yield Static("[dim]Enter unpin · Esc cancel[/dim]")

    def on_mount(self) -> None:
        lv = self.query_one("#unpin-list", ListView)
        for i, pin in enumerate(self._pins):
            lv.append(ListItem(Static(pin.label), name=str(i)))
        if self._pins:
            lv.index = 0  # otherwise Enter on first show is a no-op
        lv.focus()

    def on_list_view_selected(self, event) -> None:
        self.dismiss(self._index_of(event.item))

    def on_key(self, event) -> None:
        if event.key == "enter":
            # ListView.Selected fires on click but not always on Enter in
            # all Textual versions — read the highlighted index directly.
            lv = self.query_one("#unpin-list", ListView)
            event.stop()
            self.dismiss(lv.index)
            return
        super().on_key(event)

    @staticmethod
    def _index_of(item) -> int | None:
        name = getattr(item, "name", None)
        try:
            return int(name) if name is not None else None
        except ValueError:
            return None


# Encoding defaults per ADR 0010 §3 (classifier shape → encoding string).
_SHAPE_TO_ENCODING = {
    "sensor": "uint",
    "boolean": "bool",
    "counter": "uint",
    "step": "enum",
}


class HypothesisModal(_CenteredModal):
    """Capture a hypothesis from the live discovery surface (ADR 0010 §3).

    Two tabs — bytes (rows from the active-unknown-bytes pane) and bits
    (rows from the continuous-anomaly pane). Operator picks a row,
    optionally edits name / encoding, optionally pins to watch, submits.
    The modal returns a HypothesisResult; the parent screen writes the
    YAML stanza and adds the watch pin (see app.py:_on_hypothesis_submit).
    """

    CSS = f"""
    HypothesisModal {{ align: center middle; }}
    #hyp-box      {{ width: 90; max-height: 24; {_MODAL_BOX_CSS} }}
    #hyp-list     {{ height: auto; max-height: 10; }}
    #hyp-name     {{ height: 3; }}
    #hyp-encoding {{ height: 3; }}
    #hyp-pin      {{ height: 1; }}
    #hyp-tabhint  {{ height: 1; }}
    #hyp-foot     {{ height: 1; }}
    """

    # priority=True so Input doesn't swallow Tab and Ctrl+P. Enter is
    # handled via on_input_submitted instead (matches WatchModal).
    BINDINGS = [
        Binding("tab", "switch_tab", show=False, priority=True),
        Binding("ctrl+p", "toggle_pin", show=False, priority=True),
        Binding("escape", "cancel", show=False, priority=True),
    ]

    def __init__(
        self,
        bytes_rows: list[HypothesisByteRow],
        bits_rows: list[HypothesisBitRow],
    ) -> None:
        super().__init__()
        self._bytes_rows = bytes_rows
        self._bits_rows = bits_rows
        self._tab: Literal["bytes", "bits"] = "bytes"
        self._pin: bool = True
        # Track which list row is selected per-tab so toggling Tab back
        # restores what the operator had highlighted (avoids re-finding
        # row 3 on the bytes tab after a glance at bits).
        self._sel: dict[str, int] = {"bytes": 0, "bits": 0}

    # ---- compose ----------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="hyp-box"):
            yield Static("[bold]Capture hypothesis[/bold]")
            yield Static("", id="hyp-tabhint")
            yield ListView(id="hyp-list")
            yield Input(placeholder="signal name (required)", id="hyp-name")
            yield Input(placeholder="encoding (uint / bool / enum)", id="hyp-encoding")
            yield Static("", id="hyp-pin")
            yield Static(
                "[dim]Tab switch tab · ↑↓ pick row · Enter submit · "
                "Ctrl-P toggle pin · Esc cancel[/dim]",
                id="hyp-foot",
            )

    def on_mount(self) -> None:
        self._refresh_tab_hint()
        self._refresh_list()
        self._refresh_pin_static()
        # Encoding default needs the initial selection's shape.
        self._refresh_encoding_default()
        self.query_one("#hyp-name", Input).focus()

    # ---- tab / list -------------------------------------------------------

    def _refresh_tab_hint(self) -> None:
        if self._tab == "bytes":
            txt = f"[bold green]Bytes[/bold green]  •  [dim]Bits[/dim]  ({len(self._bytes_rows)} rows)"
        else:
            txt = f"[dim]Bytes[/dim]  •  [bold green]Bits[/bold green]  ({len(self._bits_rows)} rows)"
        self.query_one("#hyp-tabhint", Static).update(txt)

    def _refresh_list(self) -> None:
        lv = self.query_one("#hyp-list", ListView)
        lv.clear()
        if self._tab == "bytes":
            for i, r in enumerate(self._bytes_rows):
                ratio_str = "∞" if math.isinf(r.ratio) else f"{r.ratio:.1f}×"
                shape = f"  [dim]{r.shape}[/dim]" if r.shape else ""
                first = "  [dim](first activity)[/dim]" if r.first_activity else ""
                lv.append(
                    ListItem(
                        Static(
                            f"  {i + 1:>2}. 0x{r.arb:03X} D{r.byte}   "
                            f"value={r.value:>3} / 0x{r.value:02X}   "
                            f"range {r.short_range:>4}   ratio={ratio_str}{shape}{first}"
                        ),
                        name=str(i),
                    )
                )
        else:
            for i, r in enumerate(self._bits_rows):
                if math.isinf(r.z):
                    score = "z=∞ (warmup)"
                else:
                    score = f"z={r.z:.1f}  μ={r.mu:.2f}s ±{r.sigma:.2f}s"
                lv.append(
                    ListItem(
                        Static(
                            f"  {i + 1:>2}. 0x{r.arb:03X} D{r.byte}.b{r.bit}   "
                            f"{r.transition}   {score}"
                        ),
                        name=str(i),
                    )
                )
        rows = self._bytes_rows if self._tab == "bytes" else self._bits_rows
        if rows:
            lv.index = min(self._sel[self._tab], len(rows) - 1)

    def _current_index(self) -> int | None:
        lv = self.query_one("#hyp-list", ListView)
        if lv.index is None:
            return None
        rows = self._bytes_rows if self._tab == "bytes" else self._bits_rows
        if 0 <= lv.index < len(rows):
            return lv.index
        return None

    def _refresh_encoding_default(self) -> None:
        idx = self._current_index()
        if idx is None:
            return
        encoding_input = self.query_one("#hyp-encoding", Input)
        # Don't overwrite a value the operator has already typed.
        if encoding_input.value.strip():
            return
        if self._tab == "bytes":
            shape = self._bytes_rows[idx].shape
            default = _SHAPE_TO_ENCODING.get(shape, "uint")
        else:
            default = "bool"
        encoding_input.value = default

    def _refresh_pin_static(self) -> None:
        mark = "x" if self._pin else " "
        self.query_one("#hyp-pin", Static).update(
            f"  [{mark}] pin to watch panel  [dim](Ctrl-P to toggle)[/dim]"
        )

    # ---- input ------------------------------------------------------------

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_switch_tab(self) -> None:
        # Persist current selection before switching tabs.
        idx = self._current_index()
        if idx is not None:
            self._sel[self._tab] = idx
        self._tab = "bits" if self._tab == "bytes" else "bytes"
        self._refresh_tab_hint()
        self._refresh_list()
        # Reset encoding so the new tab's default applies. Only clear if
        # the value matches a known default — otherwise the operator
        # typed something custom and we shouldn't stomp on it.
        encoding_input = self.query_one("#hyp-encoding", Input)
        if encoding_input.value.strip() in {"", "uint", "bool", "enum"}:
            encoding_input.value = ""
        self._refresh_encoding_default()

    def action_toggle_pin(self) -> None:
        self._pin = not self._pin
        self._refresh_pin_static()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        result = self._build_result()
        self.dismiss(result)

    def on_list_view_highlighted(self, event) -> None:
        # Selection changed via ↑/↓ — refresh the encoding default if the
        # encoding field is still on its prefill (operator hasn't customized).
        self._refresh_encoding_default()

    # ---- submit -----------------------------------------------------------

    def _build_result(self) -> HypothesisResult | None:
        idx = self._current_index()
        if idx is None:
            return None
        name = self.query_one("#hyp-name", Input).value.strip()
        if not name:
            return None
        encoding = self.query_one("#hyp-encoding", Input).value.strip() or "uint"
        if self._tab == "bytes":
            r = self._bytes_rows[idx]
            ratio_str = "∞" if math.isinf(r.ratio) else f"{r.ratio:.1f}×"
            notes_ctx = {
                "range": r.short_range,
                "ratio": ratio_str,
                "shape": r.shape or "—",
                "first_activity": r.first_activity,
            }
            return HypothesisResult(
                kind="byte",
                name=name,
                arb=r.arb,
                byte=r.byte,
                bit=None,
                bit_length=8,
                encoding=encoding,
                pin_to_watch=self._pin,
                notes_ctx=notes_ctx,
            )
        else:
            r = self._bits_rows[idx]
            z_str = "∞" if math.isinf(r.z) else f"{r.z:.1f}"
            notes_ctx = {
                "transition": r.transition,
                "z": z_str,
                "mu": r.mu,
                "sigma": r.sigma,
            }
            return HypothesisResult(
                kind="bit",
                name=name,
                arb=r.arb,
                byte=r.byte,
                bit=r.bit,
                bit_length=1,
                encoding=encoding,
                pin_to_watch=self._pin,
                notes_ctx=notes_ctx,
            )


# Order matters — drives both the modal display and the digit hotkeys
# (1..N). Glyph column is the shape's visual identity per ADR 0013.
EXPECT_SHAPES: list[tuple[str, str]] = [
    ("sensor", "∿"),
    ("counter", "↻"),
    ("step", "⊟"),
    ("boolean", "▔_"),
]


class ExpectShapeModal(_CenteredModal):
    """Pick a shape to highlight on the discovery surface (ADR 0013).

    Digit hotkeys submit immediately: `1..4` pick a shape, `0` clears,
    `Esc` cancels. ↑/↓ + Enter also works for operators who'd rather
    not memorize the digit order. The modal returns a shape string
    (`sensor` / `counter` / `step` / `boolean`), `None` to clear, or
    leaves state untouched on cancel — `app.py` distinguishes 'cancel'
    from 'clear' by checking whether the callback fired."""

    CSS = f"""
    ExpectShapeModal {{ align: center middle; }}
    #expect-box  {{ width: 48; max-height: 12; {_MODAL_BOX_CSS} }}
    #expect-list {{ height: auto; max-height: 6; }}
    #expect-foot {{ height: 1; }}
    """

    BINDINGS = [
        Binding("escape", "cancel", show=False, priority=True),
    ]

    def __init__(self, current: str | None) -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="expect-box"):
            cur = f"  [dim](current: {self._current})[/dim]" if self._current else ""
            yield Static(f"[bold]Expect shape[/bold]{cur}")
            yield ListView(id="expect-list")
            yield Static(
                "[dim]1..4 pick · 0 clear · ↑↓ + Enter · Esc cancel[/dim]",
                id="expect-foot",
            )

    def on_mount(self) -> None:
        lv = self.query_one("#expect-list", ListView)
        for i, (name, glyph) in enumerate(EXPECT_SHAPES):
            mark = "[bold green]●[/bold green]" if name == self._current else " "
            lv.append(
                ListItem(
                    Static(f"  {i + 1}  {mark}  {name:<8} ({glyph})"),
                    name=name,
                )
            )
        lv.append(ListItem(Static("  0     none / clear"), name="__clear__"))
        # Highlight current selection so Enter on first show is meaningful.
        if self._current is not None:
            for i, (name, _) in enumerate(EXPECT_SHAPES):
                if name == self._current:
                    lv.index = i
                    break
        else:
            lv.index = 0
        lv.focus()

    def on_list_view_selected(self, event) -> None:
        # Fires on click (and on Enter while ListView has focus, but we
        # already handle Enter explicitly in on_key — that's fine, this
        # branch just becomes redundant in that case).
        name = getattr(event.item, "name", None)
        if name == "__clear__":
            self.dismiss(None)
        elif name:
            self.dismiss(name)

    # Digit hotkeys — handled in on_key so they fire even without the
    # ListView having focus (matches the "press once to dismiss" feel of
    # the LegendScreen rather than the form-driven HypothesisModal).
    def on_key(self, event) -> None:
        ch = event.character
        if ch in ("1", "2", "3", "4"):
            idx = int(ch) - 1
            if idx < len(EXPECT_SHAPES):
                event.stop()
                self.dismiss(EXPECT_SHAPES[idx][0])
                return
        if ch == "0":
            event.stop()
            self.dismiss(None)
            return
        if event.key == "enter":
            event.stop()
            lv = self.query_one("#expect-list", ListView)
            if lv.index is None:
                return
            item = lv.children[lv.index]
            name = getattr(item, "name", None)
            if name == "__clear__":
                self.dismiss(None)
            elif name:
                self.dismiss(name)
            return
        # Fall through to _CenteredModal's Esc handler.
        super().on_key(event)

    def action_cancel(self) -> None:
        # `_CANCEL_SENTINEL` distinguishes "Esc cancel" from "selected
        # clear" — app.py keys off it to leave self.expect_shape alone
        # rather than nulling it.
        self.dismiss(_CANCEL_SENTINEL)


# Module-level sentinel for ExpectShapeModal.action_cancel — a plain
# `None` collides with the "clear" return, so we use a distinct object.
_CANCEL_SENTINEL: object = object()
EXPECT_CANCEL: object = _CANCEL_SENTINEL
