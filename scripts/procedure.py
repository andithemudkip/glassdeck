#!/usr/bin/env python3
"""procedure.py — experiment procedure schema loader (ADR 0006).

Reads a per-experiment `docs/experiments/<slug>.procedure.yaml` sidecar
and returns a `Procedure` whose `.steps` is a FLAT tuple of `Step`s with
all `repeat` blocks already expanded. The OperatorScreen in live_view.py
consumes that flat sequence directly — keeping iteration / loop logic
out of the runtime.

Schema (per ADR 0006):

    name: kill-switch-toggle
    description: ...
    experiment: 2026-06-18-kill-switch-toggle    # back-ref to the .md slug
    steps:
      - prompt: "..."
        duration_secs: 10         # positive number, or null = wait for q
        countdown_from: 3         # optional; show last N seconds as cue
        mark: { key: ..., label: "..." }     # optional

      - repeat: 6                 # 1-based; expands to 6 sub-sequences
        steps:
          - prompt: "..."
            mark: { key: ..., label: "kill toggle {iter} of {loop_count}" }

`{iter}` / `{loop_count}` interpolate during loop expansion at load time;
the resulting `Step.mark.label` is fully resolved. Other `{name}`
placeholders are a schema error.

Usage:
    from procedure import load_procedure
    proc = load_procedure(Path("docs/experiments/foo.procedure.yaml"))
    for step in proc.steps: ...
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

ALLOWED_LABEL_FIELDS = {"iter", "loop_count"}


class SchemaError(ValueError):
    """Raised when a procedure.yaml entry is malformed."""


@dataclass(frozen=True)
class Mark:
    key: str
    label: str  # fully interpolated — no template placeholders remain


@dataclass(frozen=True)
class Step:
    prompt: str
    duration_secs: float | None
    countdown_from: int | None
    mark: Mark | None
    # Set when the step came from inside a `repeat` block:
    iter: int | None
    loop_count: int | None
    # Position in the flat sequence (0-based) — used for rewind/log refs.
    source_index: int


@dataclass(frozen=True)
class Procedure:
    name: str
    description: str
    experiment: str
    steps: tuple[Step, ...]
    source_path: Path


# ---------------------------------------------------------------------------


def load_procedure(path: Path) -> Procedure:
    """Load and validate a procedure.yaml. Raises SchemaError on bad input."""
    with path.open("r") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise SchemaError(f"{path}: top-level must be a mapping, got {type(raw).__name__}")

    for required in ("name", "description", "experiment", "steps"):
        if required not in raw:
            raise SchemaError(f"{path}: missing required field {required!r}")

    name = raw["name"]
    description = raw["description"]
    experiment = raw["experiment"]
    if not isinstance(name, str) or not name:
        raise SchemaError(f"{path}: `name` must be a non-empty string")
    if not isinstance(description, str):
        raise SchemaError(f"{path}: `description` must be a string")
    if not isinstance(experiment, str) or not experiment:
        raise SchemaError(f"{path}: `experiment` must be a non-empty string")

    steps_raw = raw["steps"]
    if not isinstance(steps_raw, list) or not steps_raw:
        raise SchemaError(f"{path}: `steps` must be a non-empty list")

    flat: list[Step] = []
    try:
        for entry in steps_raw:
            _expand_entry(entry, flat, in_repeat=False, iter_=None, loop_count=None)
    except SchemaError as e:
        raise SchemaError(f"{path}: {e}") from None

    if not flat:
        raise SchemaError(f"{path}: procedure expanded to zero steps")

    _validate_countdowns(flat, path)

    return Procedure(
        name=name,
        description=description,
        experiment=experiment,
        steps=tuple(flat),
        source_path=path,
    )


def _expand_entry(
    entry,
    flat: list[Step],
    *,
    in_repeat: bool,
    iter_: int | None,
    loop_count: int | None,
) -> None:
    if not isinstance(entry, dict):
        raise SchemaError(f"step entry must be a mapping, got {type(entry).__name__}")

    has_prompt = "prompt" in entry
    has_repeat = "repeat" in entry
    if has_prompt == has_repeat:
        raise SchemaError("each step must have exactly one of `prompt` or `repeat`")

    if has_repeat:
        if in_repeat:
            raise SchemaError("nested `repeat` blocks are not supported")
        n = entry["repeat"]
        if not isinstance(n, int) or n < 1:
            raise SchemaError(f"`repeat` must be a positive int, got {n!r}")
        if "steps" not in entry or not isinstance(entry["steps"], list) or not entry["steps"]:
            raise SchemaError("`repeat` requires a non-empty `steps` list")
        extra = set(entry) - {"repeat", "steps"}
        if extra:
            raise SchemaError(f"`repeat` block has unexpected fields: {sorted(extra)}")
        for i in range(1, n + 1):
            for child in entry["steps"]:
                _expand_entry(child, flat, in_repeat=True, iter_=i, loop_count=n)
        return

    # prompt step
    extra = set(entry) - {"prompt", "duration_secs", "countdown_from", "mark"}
    if extra:
        raise SchemaError(f"step has unexpected fields: {sorted(extra)}")

    prompt = entry["prompt"]
    if not isinstance(prompt, str) or not prompt:
        raise SchemaError("`prompt` must be a non-empty string")

    if "duration_secs" not in entry:
        raise SchemaError("step missing required `duration_secs` (use null for manual advance)")
    duration = entry["duration_secs"]
    if duration is not None:
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
            raise SchemaError(f"`duration_secs` must be a positive number or null, got {duration!r}")
        duration = float(duration)

    countdown_from = entry.get("countdown_from")
    if countdown_from is not None:
        if not isinstance(countdown_from, int) or isinstance(countdown_from, bool) or countdown_from <= 0:
            raise SchemaError(f"`countdown_from` must be a positive int, got {countdown_from!r}")

    mark_raw = entry.get("mark")
    mark: Mark | None = None
    if mark_raw is not None:
        if not isinstance(mark_raw, dict):
            raise SchemaError("`mark` must be a mapping with `key` and `label`")
        for required in ("key", "label"):
            if required not in mark_raw:
                raise SchemaError(f"`mark` missing required field {required!r}")
        key = mark_raw["key"]
        label_tmpl = mark_raw["label"]
        if not isinstance(key, str) or not key:
            raise SchemaError("`mark.key` must be a non-empty string")
        if not isinstance(label_tmpl, str):
            raise SchemaError("`mark.label` must be a string")
        extra_mark = set(mark_raw) - {"key", "label"}
        if extra_mark:
            raise SchemaError(f"`mark` has unexpected fields: {sorted(extra_mark)}")
        label = _interpolate_label(label_tmpl, in_repeat=in_repeat, iter_=iter_, loop_count=loop_count)
        mark = Mark(key=key, label=label)

    flat.append(
        Step(
            prompt=prompt,
            duration_secs=duration,
            countdown_from=countdown_from,
            mark=mark,
            iter=iter_,
            loop_count=loop_count,
            source_index=len(flat),
        )
    )


def _interpolate_label(template: str, *, in_repeat: bool, iter_: int | None, loop_count: int | None) -> str:
    """Substitute {iter} / {loop_count} placeholders. Reject any other field."""
    used: set[str] = set()
    for literal, field_name, format_spec, conversion in string.Formatter().parse(template):
        if field_name is None:
            continue
        # Reject anything fancier than a bare field name (no attr access, no
        # indexing, no format specs / conversions).
        if format_spec or conversion or any(c in field_name for c in ".["):
            raise SchemaError(f"label placeholder {{{field_name}}} must be a bare field name")
        if field_name not in ALLOWED_LABEL_FIELDS:
            raise SchemaError(
                f"label placeholder {{{field_name}}} not allowed (only {sorted(ALLOWED_LABEL_FIELDS)})"
            )
        used.add(field_name)

    if used and not in_repeat:
        raise SchemaError(
            f"label uses {sorted(used)} but step is not inside a `repeat` block"
        )

    try:
        return template.format(iter=iter_, loop_count=loop_count)
    except (KeyError, IndexError) as e:
        raise SchemaError(f"label interpolation failed: {e}") from None


def _validate_countdowns(flat: list[Step], path: Path) -> None:
    """`countdown_from: N` on step i means "show countdown during last N
    seconds of step i-1" — so it must fit in the previous step's duration."""
    for i, step in enumerate(flat):
        if step.countdown_from is None:
            continue
        if i == 0:
            raise SchemaError(f"{path}: step 0 has `countdown_from` but has no preceding step")
        prev = flat[i - 1]
        if prev.duration_secs is None:
            raise SchemaError(
                f"{path}: step {i} `countdown_from` requires a finite-duration preceding step "
                f"(step {i-1} has null duration)"
            )
        if step.countdown_from > prev.duration_secs:
            raise SchemaError(
                f"{path}: step {i} `countdown_from={step.countdown_from}` exceeds preceding "
                f"step's duration_secs={prev.duration_secs}"
            )


def auto_marks(procedure: Procedure) -> list[tuple[int, Mark]]:
    """Return the list of (step_index, Mark) pairs the procedure would auto-log
    when run end-to-end. Used by verify_procedure.py."""
    return [(s.source_index, s.mark) for s in procedure.steps if s.mark is not None]


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        sys.exit("usage: procedure.py <procedure.yaml>")
    proc = load_procedure(Path(sys.argv[1]))
    print(f"Loaded {proc.name} ({len(proc.steps)} steps) from {proc.source_path}")
    for s in proc.steps:
        dur = "manual" if s.duration_secs is None else f"{s.duration_secs:g}s"
        cd = f" ⏱{s.countdown_from}" if s.countdown_from else ""
        mark = f"  → {s.mark.key}: {s.mark.label!r}" if s.mark else ""
        print(f"  [{s.source_index:02d}] ({dur}{cd}) {s.prompt}{mark}")
