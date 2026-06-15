# Findings

Distilled, current-best knowledge. Each file is atomic, small, and reflects what we currently believe to be true.

Subdirectories:

- `can/` — decoded CAN behavior, per ID or per signal (e.g. `0x280-coolant-temp.md`)
- `hardware/` — confirmed hardware behavior (transceiver quirks, voltage levels, etc.)
- `bike/` — bike-system behavior (ECU, OEM dash, immobilizer, key)

## Rules

- Every finding cites the experiment(s) that established it.
- If new evidence contradicts a finding, **rewrite the file** to match current understanding. Do not append "actually..." paragraphs. Note the flip in the experiment that caused it.
- Findings describe what IS true, not the history of how we got here — that's what `docs/experiments/` is for.
- If you're tempted to write "this is probably..." or "we think...", it doesn't belong here yet. It belongs in an experiment's interpretation section.
