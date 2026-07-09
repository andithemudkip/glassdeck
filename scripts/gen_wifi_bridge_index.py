#!/usr/bin/env python3
"""gen_wifi_bridge_index.py — codegen for wifi-bridge M6 decoded panel.

Reads docs/signals/signals.yaml through the same loader every analysis
script uses (scripts/signals.py), filters to status=confirmed signals,
and emits a JS block that replaces the `/* __SIGNALS_JS__ */` placeholder
in firmware/wifi-bridge/main/index.html. Writes the merged HTML to
--out, which the CMake build then gzips + embeds.

Also expands `/* __INCLUDE: <relative-path> */` markers in the template
(and recursively in included partials) by inlining the referenced file's
contents. Paths resolve relative to the file containing the marker. One
trailing newline is stripped from each included file so a partial ending
with a POSIX-conventional final `\\n` doesn't turn the marker line into a
double newline. With --deps-file, writes one absolute path per resolved
include, sorted — CMake feeds that list into CMAKE_CONFIGURE_DEPENDS so
a partial edit forces regeneration.

A malformed schema raises SchemaError → non-zero exit → CMake build
fails with the offending entry named. That is the M6 "CI check that
signals.yaml parses cleanly" requirement.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# scripts/ is not a package; adjust sys.path so `import signals` works when
# CMake invokes us from firmware/wifi-bridge/main/.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from signals import Signal, load_signals  # noqa: E402

PLACEHOLDER = "/* __SIGNALS_JS__ */"
INCLUDE_RE = re.compile(r"/\* __INCLUDE:\s*([^*]+?)\s*\*/")


class IncludeError(Exception):
    pass


def expand_includes(text: str, base_dir: Path, deps: set[Path],
                    stack: tuple[Path, ...] = ()) -> str:
    """Recursively expand /* __INCLUDE: <path> */ markers.

    Cycles raise IncludeError with the offending chain. Missing files
    raise IncludeError with the resolved absolute path. Every included
    file's absolute path is added to `deps`.
    """
    def replace(match: re.Match) -> str:
        rel = match.group(1)
        target = (base_dir / rel).resolve()
        if target in stack:
            chain = " -> ".join(str(p) for p in stack + (target,))
            raise IncludeError(f"include cycle: {chain}")
        if not target.is_file():
            raise IncludeError(f"missing include: {target} (from {base_dir})")
        deps.add(target)
        body = target.read_text()
        if body.endswith("\n"):
            body = body[:-1]
        return expand_includes(body, target.parent, deps, stack + (target,))

    return INCLUDE_RE.sub(replace, text)


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
    ap.add_argument("--deps-file", type=Path, default=None,
                    help="write resolved include paths here for CMake")
    args = ap.parse_args()

    # load_signals raises SchemaError with the offending entry index on
    # a bad schema; we let it propagate to stderr and exit non-zero.
    signals = load_signals(args.schema)

    template_path = args.template.resolve()
    template = template_path.read_text()

    deps: set[Path] = set()
    try:
        expanded = expand_includes(template, template_path.parent, deps)
    except IncludeError as e:
        print(f"gen_wifi_bridge_index: {e}", file=sys.stderr)
        return 3

    if PLACEHOLDER not in expanded:
        print(f"gen_wifi_bridge_index: placeholder {PLACEHOLDER!r} not "
              f"found in {args.template}", file=sys.stderr)
        return 2

    merged = expanded.replace(PLACEHOLDER, render_js(signals))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(merged)

    if args.deps_file is not None:
        args.deps_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [str(p) for p in sorted(deps)]
        args.deps_file.write_text("\n".join(lines) + ("\n" if lines else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
