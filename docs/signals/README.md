# Signals

Canonical CAN signal definitions — the eventual machine-readable output of the reverse-engineering effort.

See [`coverage.md`](coverage.md) for the human-readable map: the table of decoded signals (linking each to its finding) and the per-ID byte coverage matrix that shows where the unknowns still live.

Per-signal markdown files during early decoding; a consolidated `ktm390.dbc` (or YAML equivalent) once enough signals are stable. Each signal entry should include:

- CAN ID (hex), byte offset, bit length, byte order
- scaling factor and offset
- unit
- observed range
- the experiment(s) and finding(s) that established it

A signal lands here only when it has been observed across multiple sessions and survives the next experiment that touches it. Until then it lives in `docs/findings/can/` as a working definition.
