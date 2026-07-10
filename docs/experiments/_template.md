---
date: YYYY-MM-DD
status: planned | success | partial | failure | inconclusive | superseded
phase: 0
related:
  findings: []
  decisions: []
  logs: []
---

# <Short, specific title>

## Hypothesis

What we expect to happen and why.

## Setup

Bike state (engine, key, gear). Hardware in use. Firmware version / script used. Anything non-default about the environment.

## Procedure

Steps taken, in order. Enough detail to reproduce.

*If consistent timing or step ordering matters (e.g. N toggles with fixed settles), also author a `<slug>.procedure.yaml` sidecar and run with `python scripts/capture.py --experiment <path>`. The operator screen drives the rider step-by-step and auto-logs marks at each cue. See ADR 0006.*

## Result

What actually happened. Numbers, observations, screenshots, or links to raw captures under `logs/`.

## Interpretation

What this tells us. What it does NOT tell us. What's still ambiguous.

## Follow-ups

- Findings to write or update.
- Next experiment candidates.
- Decisions this unblocks or forces.
