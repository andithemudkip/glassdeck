# Scripts

Python tooling for working with captures and signal definitions: parsers, decoders, log analyzers, plot generators.

Conventions:

- Pure-Python where possible; use a `pyproject.toml` or `requirements.txt` once dependencies appear.
- Reads from `logs/`, writes derived artifacts beside the original capture (`*.decoded.csv` etc.) or to `docs/findings/` for prose.
- Never writes inside `logs/<session>/` over an existing file unless the filename ends in `.decoded.*` or similar — captures are immutable.
- Scripts that drive hardware (read/write CAN) go in `firmware/` or a clearly named `scripts/hw/` if they're ad-hoc; document them in `docs/experiments/` when used.

A script that reaches a stable shape and gets reused should get a one-line entry below.

## Catalog

(none yet)
