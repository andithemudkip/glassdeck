# Glassdeck

Open-source dashboard replacement for a 2020 Husqvarna Svartpilen 401 (KTM 390 platform). Long-term reverse-engineering + hardware project.

Start here:
- `docs/research.md` — project brief, goals, phase plan
- `docs/status.md` — current phase, blockers, next actions

## Golden rules

1. **Never transmit CAN until the OEM message is fully decoded.** Listen-only through Phase 4. Active TX requires (a) the message documented in `docs/signals/` and (b) a `docs/decisions/` ADR authorizing it.
2. **Never modify or delete files under `logs/`.** Raw captures are immutable evidence.
3. **Preserve failed experiments.** "We tried X and it didn't work because Y" is as valuable as a success — it stops the next session from re-running it.
4. **A hypothesis is not a finding.** Promote to `docs/findings/` only after an experiment confirms it.

## Repo layout

```
bike-dash/
├── CLAUDE.md                  this file
├── docs/
│   ├── research.md            project brief + phase plan (stable)
│   ├── status.md              current phase, blockers, next actions (volatile)
│   ├── decisions/             ADR-style records: choice + reasoning
│   ├── experiments/           chronological log of attempts (incl. failures)
│   ├── findings/               distilled current-best knowledge
│   │   ├── can/               decoded CAN behavior (per ID or signal)
│   │   ├── hardware/          confirmed hardware behavior
│   │   └── bike/              bike-system behavior (ECU, dash, immobilizer)
│   ├── hardware/              wiring, pinouts, BOM, schematics
│   ├── images/                screenshots and build photos used by READMEs
│   ├── references/            external sources, datasheets, third-party projects
│   └── signals/               canonical CAN signal definitions (eventual .dbc)
├── logs/                      raw CAN captures, immutable
├── scripts/                   Python tooling: parsers, decoders, analyzers
├── bin/                       thin wrappers around common commands
└── firmware/                   ESP32 firmware
```

## Where things go

| Information | Location |
|---|---|
| External link, datasheet, third-party project | `docs/references/<topic>.md` |
| Hypothesis tested (success or failure) | `docs/experiments/YYYY-MM-DD-slug.md` |
| Confirmed fact about the bike or CAN bus | `docs/findings/<area>/<slug>.md` |
| Architectural / hardware choice + reasoning | `docs/decisions/NNNN-slug.md` |
| Wiring, pinouts, hardware setup | `docs/hardware/<slug>.md` |
| Raw CAN capture | `logs/YYYY-MM-DD-<condition>/` |
| Canonical signal definition | `docs/signals/` |
| Parser, decoder, analysis script | `scripts/` |
| ESP32 firmware | `firmware/` |

## Conventions

### Experiments — chronological, include failures

One markdown file per non-trivial test: `docs/experiments/YYYY-MM-DD-slug.md`. Use the template at `docs/experiments/_template.md`. Required: hypothesis, setup, result, interpretation. Link any raw data in `logs/`. Failures stay — don't delete them when the next attempt works; link forward instead.

Scripted procedures (timed/ordered steps where consistency matters) get a sidecar `docs/experiments/<slug>.procedure.yaml`. The `.md` links to it; the YAML is the source of truth. Run with `python scripts/capture.py --port <port> --label <slug> --experiment <path>` — the operator screen drives the rider step-by-step and auto-logs marks at each step's cue moment. Free-form / exploratory captures don't need one. See ADR 0006.

Experiments produce two outputs, not one: the bike-specific result, and (where the procedure is general enough) a candidate for the signal-discovery essentials library at `docs/discovery/essentials/`. When authoring a procedure, favor bike-agnostic prompts so it can graduate into the library without a rewrite. Promotion is a conscious authoring step, not automatic — the experiment stays where it is and links forward to the library file. See ADR 0019.

### Findings — atomic, editable, current-state

Each finding is a small file under `docs/findings/<area>/`. Cite the experiment(s) that established it. When new evidence contradicts a finding, **rewrite** the file (don't append "actually..." paragraphs) and note the flip in the contradicting experiment. The finding always reflects current best understanding.

**Brevity.** Lead with the answer in one paragraph (what the signal is, where it lives, confidence). Put method, evidence, and edge cases below. Aim for ≤30 lines; if a finding grows past that, most of the excess is probably experiment detail — move it to the experiment file and link. Same rule for experiments: hypothesis + result up top, procedure and raw observations below.

### Logs — immutable, described

Each capture session gets its own directory: `logs/YYYY-MM-DD-<condition>/`, containing:
- the raw capture file(s) — never edited
- `session.md` — bike state, rider actions, hardware/firmware used, anomalies

Derived/decoded artifacts live alongside as `*.decoded.csv` etc., or get promoted into `docs/findings/`.

### Decisions — ADR-style, superseded not deleted

Choices that constrain the rest of the project: `docs/decisions/NNNN-slug.md`. Sections: context, decision, consequences. Supersede with a new ADR rather than rewriting history.

### Status — single source of "where are we"

`docs/status.md` is short and gets updated every meaningful session. If you want to know what to do next, look here first.

**Structure** — these sections only, in this order:
1. `Phase` — one line.
2. `Last touched` — date + one sentence pointing to the artefact that captures the detail (README, ADR, experiment). Not a changelog entry.
3. `Blocked on` — usually empty.
4. `In progress` — 3–6 bullets, each a one-line pointer.
5. `Next actions` — numbered, each a one-line pointer to an experiment/plan file.
6. `Open questions` — mirrors `docs/research.md`.
7. `Where things live` — the doc-tree pointer table.

**Hard limits.** Target ≤80 lines. No section over ~15 lines. No bullet over 3 lines. If a bullet needs more, the content belongs in the file it points to.

**Do not put in status.md:**
- Dated update log / changelog entries. Experiments, findings, and ADRs are the record — `git log` is the timeline.
- Per-finding paragraph summaries. `docs/findings/` is the index; link, don't re-narrate. `docs/signals/coverage.md` is the human-readable roll-up.
- Multi-paragraph "what we shipped" narratives. Those live in the relevant README or ADR.
- Struck-through completed items. Once done, delete the bullet — the experiment/finding file is the record.

**When updating:** edit in place. Replace the `Last touched` line, adjust `In progress` / `Next actions` bullets, remove what's no longer current. Never append; the file describes *now*, not history.

### Scripts — Python tooling around captures

`scripts/` holds parsers, decoders, log analyzers, plot generators. Reads from `logs/`, writes derived artifacts beside the original capture (`*.decoded.csv` etc.) or prose into `docs/findings/`. Never overwrites raw capture files. See `scripts/README.md` for the catalog and conventions.

### Firmware — ESP32 code, listen-only by default

`firmware/` holds subprojects (`can-logger/`, `dashboard/`, etc.), each self-contained with its own build config and README. **Default to listen-only** (`CAN_MODE_LISTEN_ONLY` / TWAI equivalent); transmit must be a compile-time opt-in gated by a `docs/decisions/` ADR for each TX'd message. Capture sessions identify the firmware commit they used in their `session.md`. See `firmware/README.md`.

### Code style — no what-narration

Default to no comments. Write one only when the *why* is non-obvious: a hidden constraint, a subtle invariant, a workaround for a specific bug, behavior that would surprise a reader. Don't explain what the code does — well-named identifiers cover that. Don't reference the current task, PR, issue, or caller ("added for the fuel walkdown", "used by capture.py") — that rots as the codebase evolves and belongs in the commit message. Same rule applies to Python scripts, firmware C, and shell.

## For AI agents working on this project

- **Read before reasoning.** Before answering bike- or CAN-specific questions, read `docs/research.md` and skim `docs/findings/<relevant area>/`. Don't reason from model memory about KTM/Husqvarna specifics — verify against findings or mark as hypothesis.
- **Propose experiments before running them.** When asked to investigate, draft the `docs/experiments/...md` file as a plan first (hypothesis + procedure), get user sign-off, then execute, then update findings.
- **Surface conflicts.** If a finding contradicts `research.md` or the user's stated assumption, flag it — don't silently override either.
- **Logs are evidence.** If asked to "clean up" or "rewrite" log data, refuse and ask what's actually wanted — usually it's a derived artifact, which belongs elsewhere.
