# bike-dash

Open-source dashboard replacement for a 2020 Husqvarna Svartpilen 401 (KTM 390 platform). Long-term reverse-engineering + hardware project.

Start here:
- `docs/research.md` — project brief, goals, phase plan
- `docs/status.md` — current phase, blockers, next actions

## Golden rules

1. **Never transmit CAN until the OEM message is fully decoded.** Listen-only through Phase 4.
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
│   ├── findings/              distilled current-best knowledge
│   │   ├── can/               decoded CAN behavior (per ID or signal)
│   │   ├── hardware/          confirmed hardware behavior
│   │   └── bike/              bike-system behavior (ECU, dash, immobilizer)
│   ├── hardware/              wiring, pinouts, BOM, schematics
│   ├── references/            external sources, datasheets, third-party projects
│   └── signals/               canonical CAN signal definitions (eventual .dbc)
├── logs/                      raw CAN captures, immutable
├── scripts/                   Python tooling: parsers, decoders, analyzers
└── firmware/                  ESP32 firmware
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

### Findings — atomic, editable, current-state

Each finding is a small file under `docs/findings/<area>/`. Cite the experiment(s) that established it. When new evidence contradicts a finding, **rewrite** the file (don't append "actually..." paragraphs) and note the flip in the contradicting experiment. The finding always reflects current best understanding.

### Logs — immutable, described

Each capture session gets its own directory: `logs/YYYY-MM-DD-<condition>/`, containing:
- the raw capture file(s) — never edited
- `session.md` — bike state, rider actions, hardware/firmware used, anomalies

Derived/decoded artifacts live alongside as `*.decoded.csv` etc., or get promoted into `docs/findings/`.

### Decisions — ADR-style, superseded not deleted

Choices that constrain the rest of the project: `docs/decisions/NNNN-slug.md`. Sections: context, decision, consequences. Supersede with a new ADR rather than rewriting history.

### Status — single source of "where are we"

`docs/status.md` is short and gets updated every meaningful session. If you want to know what to do next, look here first.

### Scripts — Python tooling around captures

`scripts/` holds parsers, decoders, log analyzers, plot generators. Reads from `logs/`, writes derived artifacts beside the original capture (`*.decoded.csv` etc.) or prose into `docs/findings/`. Never overwrites raw capture files. See `scripts/README.md` for the catalog and conventions.

### Firmware — ESP32 code, listen-only by default

`firmware/` holds subprojects (`can-logger/`, `dashboard/`, etc.), each self-contained with its own build config and README. **Default to listen-only** (`CAN_MODE_LISTEN_ONLY` / TWAI equivalent); transmit must be a compile-time opt-in gated by a `docs/decisions/` ADR for each TX'd message. Capture sessions identify the firmware commit they used in their `session.md`. See `firmware/README.md`.

## For AI agents working on this project

- **Read before reasoning.** Before answering bike- or CAN-specific questions, read `docs/research.md` and skim `docs/findings/<relevant area>/`. Don't reason from model memory about KTM/Husqvarna specifics — verify against findings or mark as hypothesis.
- **Propose experiments before running them.** When asked to investigate, draft the `docs/experiments/...md` file as a plan first (hypothesis + procedure), get user sign-off, then execute, then update findings.
- **Surface conflicts.** If a finding contradicts `research.md` or the user's stated assumption, flag it — don't silently override either.
- **No CAN transmission.** Never suggest or generate code that transmits CAN frames to the bike until (a) the relevant message is documented in `docs/signals/` and (b) a `docs/decisions/` ADR authorizes active TX for that message.
- **Logs are evidence.** If asked to "clean up" or "rewrite" log data, refuse and ask what's actually wanted — usually it's a derived artifact, which belongs elsewhere.
