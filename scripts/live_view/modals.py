"""Modal overlay screens: legend popup, watch-pin search, unpin picker."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, ListItem, ListView, Static

from signals import Signal

from .state import WatchPin


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

    def on_input_changed(self, event: Input.Changed) -> None:
        self._refresh_list(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(self._resolve(event.value.strip()))

    def _resolve(self, text: str) -> WatchPin | None:
        if not text:
            lv = self.query_one("#watch-list", ListView)
            if lv.index is not None and 0 <= lv.index < len(lv.children):
                item = lv.children[lv.index]
                name = getattr(item, "name", None)
                if name:
                    return self._pin_for_signal_name(name)
            return None

        # Raw triplet form 0x<hex>:<byte>.<bit>
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

        # Signal name: exact → prefix → substring.
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
