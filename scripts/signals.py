#!/usr/bin/env python3
"""signals.py — canonical decoded-signal loader and decoder.

Reads docs/signals/signals.yaml (the schema established by ADR 0005) and
returns a list of Signal objects. Decoder scripts import lookup() / by_id()
to replace hardcoded (arbitration_id, byte, bit) constants; the live
visualizer uses the same Signal.extract() to render the decoded pane.

Schema fields per entry — see the comment block at the top of signals.yaml
for the authoritative description.

Usage:
    from signals import load_signals, lookup, by_id

    signals = load_signals()
    kill = lookup(signals, "kill_switch")
    by_arb_id = by_id(signals)
    decoded = by_arb_id[0x541][0].extract(msg)   # msg: can.Message
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA_PATH = REPO_ROOT / "docs" / "signals" / "signals.yaml"

VALID_STATUS = {"confirmed", "provisional", "partial"}
VALID_ENCODING = {"bool", "uint", "sint", "enum"}
VALID_BYTE_ORDER = {"big", "little"}
VALID_BAND_KEYS = {"cold_below", "warn_above", "danger_above", "accent_above"}


class SchemaError(ValueError):
    """Raised when signals.yaml contains a malformed entry."""


@dataclass(frozen=True)
class Signal:
    name: str
    status: str
    finding: str
    arbitration_id: int
    bit_length: int
    encoding: str
    # Single-byte (or bit/nibble within a byte) location:
    byte: int | None = None
    bit_offset: int = 0
    # Multi-byte location:
    bytes_: tuple[int, ...] | None = None
    byte_order: str | None = None
    # Decoding:
    scale: float = 1.0
    offset: float = 0.0
    unit: str | None = None
    values: dict[int, str] = field(default_factory=dict)
    bands: dict[str, float] = field(default_factory=dict)
    notes: str = ""

    @property
    def is_multi_byte(self) -> bool:
        return self.bytes_ is not None

    def extract(self, arbitration_id: int, data: bytes) -> int | float | str | None:
        """Decode this signal from a raw CAN payload. Returns None if the
        arbitration ID doesn't match.

        For bool/enum encodings, returns the rendered label (if a values map
        is present) or the raw integer. For uint, returns float when scale
        applies, else int.
        """
        if arbitration_id != self.arbitration_id:
            return None
        raw = self._extract_raw(data)
        if raw is None:
            return None
        if self.encoding in ("bool", "enum") and self.values:
            return self.values.get(raw, raw)
        if self.encoding in ("uint", "sint"):
            if self.scale != 1.0 or self.offset != 0.0:
                return raw * self.scale + self.offset
            return raw
        return raw

    def _extract_raw(self, data: bytes) -> int | None:
        if self.is_multi_byte:
            assert self.bytes_ is not None
            if max(self.bytes_) >= len(data):
                return None
            order = self.bytes_ if self.byte_order == "big" else tuple(reversed(self.bytes_))
            value = 0
            for b_index in order:
                value = (value << 8) | data[b_index]
            if self.bit_offset != 0 or self.bit_length != 8 * len(self.bytes_):
                mask = (1 << self.bit_length) - 1
                value = (value >> self.bit_offset) & mask
            return self._sign_extend(value)
        assert self.byte is not None
        if self.byte >= len(data):
            return None
        mask = (1 << self.bit_length) - 1
        value = (data[self.byte] >> self.bit_offset) & mask
        return self._sign_extend(value)

    def _sign_extend(self, raw: int) -> int:
        """Two's-complement sign-extend when encoding=='sint'. Uint stays as-is."""
        if self.encoding != "sint":
            return raw
        sign_bit = 1 << (self.bit_length - 1)
        if raw & sign_bit:
            return raw - (1 << self.bit_length)
        return raw

    def format(self, value: int | float | str | None) -> str:
        """Render a decoded value for display. Adds unit suffix if set."""
        if value is None:
            return "—"
        if isinstance(value, float):
            text = f"{value:.1f}" if self.scale < 1 else f"{value:.0f}"
        else:
            text = str(value)
        if self.unit and self.unit not in ("ticks", "counts", "index"):
            return f"{text} {self.unit}"
        return text

    def location_str(self) -> str:
        """Human-readable '0x541 D2 bit 4' style location string."""
        arb = f"0x{self.arbitration_id:03X}"
        if self.is_multi_byte:
            assert self.bytes_ is not None
            byte_list = ",".join(f"D{b}" for b in self.bytes_)
            if self.bit_length != 8 * len(self.bytes_):
                return (
                    f"{arb} {byte_list} bits {self.bit_offset}.."
                    f"{self.bit_offset + self.bit_length - 1} "
                    f"({self.byte_order}-endian uint{self.bit_length})"
                )
            return f"{arb} {byte_list} ({self.byte_order}-endian uint{self.bit_length})"
        assert self.byte is not None
        if self.bit_length == 1:
            return f"{arb} D{self.byte} bit {self.bit_offset}"
        if self.bit_length == 4 and self.bit_offset in (0, 4):
            nibble = "hi" if self.bit_offset == 4 else "lo"
            return f"{arb} D{self.byte} {nibble} nibble"
        if self.bit_length == 8 and self.bit_offset == 0:
            return f"{arb} D{self.byte}"
        return f"{arb} D{self.byte} bits {self.bit_offset}..{self.bit_offset + self.bit_length - 1}"


def load_signals(path: Path | None = None) -> list[Signal]:
    """Load and validate signals.yaml. Raises SchemaError on bad entries."""
    schema_path = path or DEFAULT_SCHEMA_PATH
    with schema_path.open("r") as f:
        raw = yaml.safe_load(f) or []
    if not isinstance(raw, list):
        raise SchemaError(f"{schema_path}: top-level must be a list, got {type(raw).__name__}")
    signals: list[Signal] = []
    seen_names: set[str] = set()
    for i, entry in enumerate(raw):
        try:
            sig = _parse_entry(entry)
        except SchemaError as e:
            raise SchemaError(f"{schema_path} entry #{i}: {e}") from None
        if sig.name in seen_names:
            raise SchemaError(f"{schema_path} entry #{i}: duplicate name {sig.name!r}")
        seen_names.add(sig.name)
        signals.append(sig)
    return signals


def _parse_entry(entry: dict) -> Signal:
    if not isinstance(entry, dict):
        raise SchemaError(f"entry must be a mapping, got {type(entry).__name__}")
    for required in ("name", "status", "finding", "arbitration_id", "bit_length", "encoding"):
        if required not in entry:
            raise SchemaError(f"missing required field {required!r}")

    name = entry["name"]
    if not isinstance(name, str) or not name:
        raise SchemaError("name must be a non-empty string")

    status = entry["status"]
    if status not in VALID_STATUS:
        raise SchemaError(f"status {status!r} not in {sorted(VALID_STATUS)}")

    encoding = entry["encoding"]
    if encoding not in VALID_ENCODING:
        raise SchemaError(f"encoding {encoding!r} not in {sorted(VALID_ENCODING)}")

    arbitration_id = entry["arbitration_id"]
    if not isinstance(arbitration_id, int) or not 0 <= arbitration_id <= 0x7FF:
        raise SchemaError(f"arbitration_id {arbitration_id!r} out of 11-bit range")

    bit_length = entry["bit_length"]
    if not isinstance(bit_length, int) or not 1 <= bit_length <= 64:
        raise SchemaError(f"bit_length {bit_length!r} out of range")

    # Mutually exclusive: byte vs bytes
    has_byte = "byte" in entry
    has_bytes = "bytes" in entry
    if has_byte == has_bytes:
        raise SchemaError("exactly one of `byte` or `bytes` is required")

    bytes_: tuple[int, ...] | None = None
    byte: int | None = None
    bit_offset = int(entry.get("bit_offset", 0))
    byte_order: str | None = None

    if has_bytes:
        bs = entry["bytes"]
        if not isinstance(bs, list) or not bs or not all(isinstance(b, int) for b in bs):
            raise SchemaError("`bytes` must be a non-empty list of ints")
        bytes_ = tuple(bs)
        byte_order = entry.get("byte_order")
        if byte_order not in VALID_BYTE_ORDER:
            raise SchemaError(f"byte_order {byte_order!r} not in {sorted(VALID_BYTE_ORDER)}")
        max_bits = 8 * len(bytes_)
        if bit_length > max_bits:
            raise SchemaError(
                f"bit_length {bit_length} exceeds {len(bytes_)} bytes ({max_bits})"
            )
        if bit_offset < 0 or bit_offset + bit_length > max_bits:
            raise SchemaError(
                f"bit_offset+bit_length ({bit_offset}+{bit_length}) overflows {len(bytes_)}-byte slot"
            )
    else:
        byte = entry["byte"]
        if not isinstance(byte, int) or not 0 <= byte <= 7:
            raise SchemaError(f"byte {byte!r} out of 0..7 range")
        if not 0 <= bit_offset <= 7:
            raise SchemaError(f"bit_offset {bit_offset!r} out of 0..7 range")
        if bit_offset + bit_length > 8:
            raise SchemaError(
                f"bit_offset+bit_length ({bit_offset}+{bit_length}) overflows byte"
            )

    if encoding == "bool" and bit_length != 1:
        raise SchemaError(f"bool encoding requires bit_length=1, got {bit_length}")

    values_raw = entry.get("values") or {}
    if not isinstance(values_raw, dict):
        raise SchemaError("`values` must be a mapping")
    # Guard YAML 1.1 boolean coercion: unquoted OFF/ON/YES/NO/TRUE/FALSE get
    # parsed as Python bool, then str() would silently produce "False"/"True".
    # We already had abs_lamp bite us this way (2026-07-23) — hard-fail so the
    # fix is "quote it in the YAML" instead of "hunt a rendering bug".
    for k, v in values_raw.items():
        if isinstance(v, bool):
            raise SchemaError(
                f"`values.{k}` is a bool ({v!r}) — YAML coerced an unquoted "
                f"OFF/ON/YES/NO/TRUE/FALSE token. Quote it in the YAML: `{k}: \"OFF\"`."
            )
    values: dict[int, str] = {int(k): str(v) for k, v in values_raw.items()}

    bands_raw = entry.get("bands")
    bands: dict[str, float] = {}
    if bands_raw is not None:
        if not isinstance(bands_raw, dict):
            raise SchemaError("`bands` must be a mapping")
        if encoding not in ("uint", "sint"):
            raise SchemaError(f"`bands` only valid on uint/sint signals, got {encoding!r}")
        unknown = set(bands_raw) - VALID_BAND_KEYS
        if unknown:
            raise SchemaError(f"unknown `bands` keys {sorted(unknown)}; valid: {sorted(VALID_BAND_KEYS)}")
        for k, v in bands_raw.items():
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise SchemaError(f"`bands.{k}` must be numeric, got {type(v).__name__}")
            bands[k] = float(v)

    return Signal(
        name=name,
        status=status,
        finding=entry["finding"],
        arbitration_id=arbitration_id,
        bit_length=bit_length,
        encoding=encoding,
        byte=byte,
        bit_offset=bit_offset,
        bytes_=bytes_,
        byte_order=byte_order,
        scale=float(entry.get("scale", 1)),
        offset=float(entry.get("offset", 0)),
        unit=entry.get("unit"),
        values=values,
        bands=bands,
        notes=str(entry.get("notes", "")),
    )


def lookup(signals: Iterable[Signal], name: str) -> Signal:
    """Return the signal with the given name, or raise KeyError."""
    for s in signals:
        if s.name == name:
            return s
    raise KeyError(f"signal {name!r} not found in schema")


def by_id(signals: Iterable[Signal]) -> dict[int, list[Signal]]:
    """Index signals by arbitration ID for per-frame lookup."""
    out: dict[int, list[Signal]] = {}
    for s in signals:
        out.setdefault(s.arbitration_id, []).append(s)
    return out


def arb_str(arbitration_id: int) -> str:
    """Render an arbitration ID as the 3-char uppercase hex string the
    byte-level decoder scripts use as keys (e.g. 0x541 → "541")."""
    return f"{arbitration_id:03X}"


def byte_coords(signals: Iterable[Signal]) -> list[tuple[str, int, str]]:
    """For each signal, enumerate the (arb_str, byte_index, name) tuples
    naming the bytes it covers. Used by byte-level decoder self-checks."""
    out: list[tuple[str, int, str]] = []
    for s in signals:
        if s.bytes_ is not None:
            for b in s.bytes_:
                out.append((arb_str(s.arbitration_id), b, s.name))
        elif s.byte is not None:
            out.append((arb_str(s.arbitration_id), s.byte, s.name))
    return out


def bit_coords(signals: Iterable[Signal]) -> list[tuple[str, int, int, str]]:
    """For each single-bit signal, return (arb_str, byte, bit, name).
    Multi-bit / multi-byte signals are skipped — bit-level self-checks
    only care about specific bits."""
    out: list[tuple[str, int, int, str]] = []
    for s in signals:
        if s.bit_length == 1 and s.byte is not None:
            out.append((arb_str(s.arbitration_id), s.byte, s.bit_offset, s.name))
    return out


if __name__ == "__main__":
    sigs = load_signals()
    print(f"Loaded {len(sigs)} signals from {DEFAULT_SCHEMA_PATH}")
    for s in sigs:
        print(f"  {s.name:30s} {s.status:11s} {s.location_str()}")
