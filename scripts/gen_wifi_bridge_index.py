#!/usr/bin/env python3
"""gen_wifi_bridge_index.py — codegen for wifi-bridge M6 decoded panel.

Reads docs/signals/signals.yaml through the same loader every analysis
script uses (scripts/signals.py), filters to status=confirmed signals,
and emits a JS block that replaces the `/* __SIGNALS_JS__ */` placeholder
in firmware/wifi-bridge/main/index.html. Writes the merged HTML to
--out, which the CMake build then gzips + embeds.

A malformed schema raises SchemaError → non-zero exit → CMake build
fails with the offending entry named. That is the M6 "CI check that
signals.yaml parses cleanly" requirement.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# scripts/ is not a package; adjust sys.path so `import signals` works when
# CMake invokes us from firmware/wifi-bridge/main/.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from signals import Signal, load_signals  # noqa: E402

PLACEHOLDER = "/* __SIGNALS_JS__ */"


def signal_to_dict(s: Signal) -> dict:
    """Emit the minimum shape the browser decoder needs. Field names
    mirror scripts/signals.py so future readers can jump between the
    two without renaming in their head."""
    d: dict = {
        "name": s.name,
        "arb": s.arbitration_id,
        "enc": s.encoding,
        "bit_length": s.bit_length,
        "bit_offset": s.bit_offset,
        "scale": s.scale,
        "offset": s.offset,
        "unit": s.unit,
    }
    if s.is_multi_byte:
        assert s.bytes_ is not None
        d["bytes"] = list(s.bytes_)
        d["order"] = s.byte_order
    else:
        d["byte"] = s.byte
    if s.values:
        # JSON object keys must be strings; the JS decoder coerces back
        # to integer keys via a Map keyed on raw integer.
        d["values"] = {str(k): v for k, v in s.values.items()}
    return d


def render_js(signals: list[Signal]) -> str:
    confirmed = [s for s in signals if s.status == "confirmed"]
    data = [signal_to_dict(s) for s in confirmed]
    # One line per signal keeps the diff readable when signals.yaml grows.
    lines = ["const SIGNALS = ["]
    for entry in data:
        lines.append("  " + json.dumps(entry, separators=(",", ":")) + ",")
    lines.append("];")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", type=Path, required=True,
                    help="firmware/wifi-bridge/main/index.html")
    ap.add_argument("--schema", type=Path, required=True,
                    help="docs/signals/signals.yaml")
    ap.add_argument("--out", type=Path, required=True,
                    help="destination for the merged HTML")
    args = ap.parse_args()

    # load_signals raises SchemaError with the offending entry index on
    # a bad schema; we let it propagate to stderr and exit non-zero.
    signals = load_signals(args.schema)

    template = args.template.read_text()
    if PLACEHOLDER not in template:
        print(f"gen_wifi_bridge_index: placeholder {PLACEHOLDER!r} not "
              f"found in {args.template}", file=sys.stderr)
        return 2

    merged = template.replace(PLACEHOLDER, render_js(signals))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(merged)
    return 0


if __name__ == "__main__":
    sys.exit(main())
