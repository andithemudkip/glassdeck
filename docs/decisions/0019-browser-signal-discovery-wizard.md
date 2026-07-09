# 0019 — Browser signal-discovery wizard

**Date:** 2026-07-09
**Status:** Proposed
**Supersedes:** [ADR 0009](0009-bike-profile-extraction-wizard.md)

## Context

ADR 0009 established the strategic frame that shifts this project from "reverse-engineer the 390 platform" to "any bike whose owner spends ~an hour following prompts." Its core arguments still hold: the dashboard's signal needs are a closed set (~15–25 signals), each admits a purpose-built procedure, and a curated procedure library is the growth surface that turns per-bike effort into shared capability. It also set the non-negotiables — validation before shipping any inferred mapping, `signals.yaml` as the sole output format, procedure library de-bike-ified, closed-set scope rather than general CAN decoding, ~60–70% realistic first-shot coverage.

What has changed since 0009 was written is the delivery vehicle. Three concrete developments make the browser the right home for the wizard, not `scripts/extract.py`:

- **wifi-bridge exists.** [ADR 0016](0016-wifi-dev-capture-and-live-view.md) established a browser-served viewer on the ESP itself as the phase-2+ dev tool. Every capture session now has a browser already open on the operator's phone. Standing up a second, disconnected CLI on a laptop for the wizard duplicates transport, session management, and marks — for no gain over reusing the browser that is already there.
- **Browser-primary capture is proven.** [ADR 0018](0018-m4-browser-primary-capture.md) shifted the log sink into OPFS, and M6 shipped a browser-native decoded panel with `signals.yaml`-driven codegen. The pattern — codegen at build time, generic `decodeSignal()`, verification-cell layout with freshness bars — is directly reusable for showing candidate signals during the wizard's verification phase. The technical risk of "can the browser do this" is retired.
- **The Python analysis primitives 0009 leaned on (`bit_transition_scan.py`, `cross_session_diff.py`) are the *primitives* of inference, not the *interface*.** Porting them to a Web Worker is a matter of a few hundred lines of numeric code operating on typed arrays. It removes the last dependency that would force a user off the phone during the wizard flow.

The user-visible bar the wizard needs to clear is higher than 0009 framed it. 0009 assumed a savvy-enough operator on a laptop running Python. The realistic target user for the wizard is someone who owns a bike, wants a dashboard, and does not write software — they can flash a prebuilt firmware, connect a phone to an AP, and follow prompts, but should not need Python, a terminal, or knowledge of YAML editing to reach a working profile. The full loop — **capture → analyse → verify → promote → decoded live on the same page** — needs to happen without leaving the browser. Only the eventual contribution back to the shared `docs/signals/signals.yaml` in this repo requires a deliberate export + PR step, because that artifact is upstream of every other user's firmware and warrants human review at a higher bar than the operator's own bike.

The remainder of this ADR reshapes 0009's decision around this browser-first flow. Sections whose intent is unchanged from 0009 are marked as such and reference the earlier text rather than restating it.

## Decision

### The wizard lives at `/discover` on wifi-bridge

Second embedded HTML page in the wifi-bridge binary, served alongside `/` (rider view) via a second `execute_process` + `.S` embed in `main/CMakeLists.txt` — same pattern M6 established for the rider view's codegen. The wizard reuses the existing WS `/stream`, `/capture`, and `/mark` transport; nothing new is required on the CAN or wire-format layers.

This replaces the previously planned wifi-bridge M8 (`/dev` view + Active-unknown-bytes port). The M8 scope was drifting toward a browser port of `scripts/live_view/`, which duplicates existing capability without opening new user segments. `/dev` is dropped from the wifi-bridge milestone plan; the wifi-bridge README will be updated in the same change that lands this ADR. `scripts/live_view/` stays as the R&D deep-dive TUI for advanced users writing custom `.procedure.yaml` files — no retirement plan.

### Typed procedure schema (v2) extends ADR 0006

ADR 0006's step schema is prompt-driven: each step carries a rider-facing string and cue timing, and the operator screen renders it verbatim. That is sufficient for authored experiments where a human writes both the prompt and the analysis, but it forces the inference layer to guess the step's *intent* from prose. Discovery procedures need the intent to be explicit so the browser can render specialized UI (a countdown for a sweep, a hold-target line for an RPM hold, a transition counter for a toggle) and the analyzer can pick the right correlator without prompt parsing.

Schema v2 keeps v1 steps working as `{kind: prompt}` — no existing procedure breaks. New discovery kinds carry structured metadata:

```yaml
- kind: baseline           # idle capture, no operator input; establishes noise floor
  duration_s: 5
- kind: boolean_toggle     # kill switch, sidestand, clutch — find bits that flip N times
  control: kill_switch
  transitions: 4
  hold_ms: 1500
- kind: sweep              # throttle 0→100→0 — find bytes that track a monotonic ramp
  control: throttle
  from: 0
  to: 100
  duration_s: 5
- kind: hold               # RPM at 2500 for 10 s — calibrate scale + offset across N tiers
  control: rpm
  target: 2500
  tolerance: 200
  duration_s: 10
- kind: enum_walk          # gear 1→2→3→4→5→6→N — find bytes with N distinct stable states
  control: gear
  steps: [1, 2, 3, 4, 5, 6, N]
- kind: physical_ramp      # roll wheel by hand — find bytes tracking a physical action
  control: wheel_front
```

Each `.procedure.yaml` carries `schema_version: 2` in its frontmatter; the loader dispatches. Ground-truth values 0009 called for ("hold ~3000 RPM steady, enter the dash reading at the end") are captured via `hold` steps with the operator confirming the achieved value at the end of each step — the browser prompts, the value lands as a `# MARK` in the capture.

### Session model: N runs per procedure, aggregated

A discovery session is `logs/YYYY-MM-DD-discovery-<slug>/` containing one or more capture runs of the same procedure. Each run is a separate capture. The wizard prompts the operator to complete a target number of runs per procedure (default 3) before Stop is enabled — a single-run inference is allowed but flagged low-confidence and requires manual promotion.

Multi-run aggregation is where inference gets sharp: a single throttle sweep can be coincidentally-correlated with a dozen bytes; three cross-referenced sweeps eliminate most of them. The browser stores per-run frames in OPFS as they arrive, keyed by run-id within the session directory. The analyzer consumes all runs of a procedure together.

### Inference layer: JS in a Web Worker

Correlation math ports to JS. The algorithm shape is unchanged from 0009 — boolean/enum extraction by exclusive-window transition, continuous signals by regression against operator-entered reference points, counters by monotonic-increase detection — but the runtime is a Web Worker so the UI stays responsive. Analyzer input is the OPFS-resident session (frames + marks + procedure metadata); output is a set of candidate signal entries with per-candidate evidence blocks.

The specific correlation math (Spearman vs cross-correlation vs custom scoring per kind) is *not* fixed by this ADR — it evolves with the essentials library. Changing scoring does not require a new ADR unless it changes the schema of the candidate output.

**Top-N candidates, not top-1.** For each expected signal the analyzer emits its top-3 ranked candidates, not a single choice. Multiple broadcasters, tied byte layouts, and coincidentally-correlated bytes are common enough that forcing a single answer produces false negatives ("the tool guessed wrong") when the right answer would have been rank 2. Presenting all three lets the operator disambiguate visually in verification.

### Staging area: three tiers

Candidates live in three places along the promotion pipeline:

- **OPFS `staging/`** — analyzer output during a session; browser-local, tied to that browser install. The full top-N per signal with evidence blocks. This is what the verification UI reads from.
- **NVS `user_signals` blob on the ESP** — signals the operator has promoted via the wizard's verification UI. Persists across browser reloads and across different browsers on the AP. The decoded panel at `/` reads from `GET /signals` and merges these with the confirmed built-in list.
- **`docs/signals/staging/<slug>.yaml` in this repo** — used only by the project itself for validation-against-ground-truth work (see below) and for contributions arriving via export. Community users' promoted signals do not land here automatically; they land in NVS on their own device and travel to this repo only via the deliberate export-and-PR flow.

The NVS blob's schema is richer than `signals.yaml`'s `confirmed` entries — it carries the evidence block (procedure slug, session id, correlation score, competing candidates considered, promotion timestamp) alongside the encoding. This is the "why" the operator or a maintainer needs later to audit or debug a bad promotion.

### Verification UI: live-decoded candidates, operator confirms

Reuses the M6 decoded panel's rendering pattern with candidates instead of confirmed signals. For each expected signal in the procedure that just ran, the wizard shows the top-3 candidates side-by-side with live values updating from the ongoing `/stream` frames. Operator does the physical action ("rev to 5000 now"); the candidate that tracks reality is the answer. Operator taps it, then confirms — signal is written to NVS via `POST /signals`, immediately picks up in the rider view's decoded panel on next reload (or on WS message if we push a signal-changed event).

Promoted signals land as `provisional`, not `confirmed`. Watching a live gauge track a physical action catches gross wrong-signal errors but misses subtle scale/offset issues that our existing `confirmed` bar screens for over longer periods. The rider view visually distinguishes user-promoted `provisional` signals from built-in `confirmed` signals so it is clear at a glance which are ground-truth and which are the operator's own bike-specific overlay.

Verification is not skippable. A candidate that the operator does not confirm is not written to NVS, regardless of correlation score. This preserves 0009's non-negotiable and prevents silent wrong-mappings from reaching the rider view.

### `GET /signals` and `POST /signals`: dynamic decoder loading

M6's codegen embeds decoders in the HTML at build time. To make promotion live without a rebuild, the rider view (and the wizard) fetches its signal table at page load rather than reading a baked constant:

- `GET /signals` → `{ confirmed: [...], user: [...] }` — confirmed is the codegen-emitted table from `docs/signals/signals.yaml`; user is the NVS blob.
- `POST /signals` → append a promoted signal to the NVS blob. Body is the full candidate + evidence. Returns the assigned id.
- `DELETE /signals/<id>` → remove a user-promoted signal (mistaken promotion, want to re-run the procedure).

The codegen-emitted table stays baked (small, always present, survives NVS wipe) so the tool is useful the moment the firmware boots on a new bike. The NVS blob layers on top. This is the change that makes the promotion loop zero-touch: no reflash, no rebuild, no export/import.

Security: no authentication beyond the AP's WPA2. Anyone on the AP can `POST /signals`. This is fine for the hobbyist tool at this stage and matches the rest of wifi-bridge's threat model, but it is worth being aware of if the tool ever moves to a shared-network context (see § Deferred).

### Contribution loop back to the repo

The wizard's `/discover` page has an Export button that produces `<bike-slug>.signals.yaml` — a full bike profile in the ADR 0005 schema, with header block (make, model, year, wizard version, session id, procedures run) and the operator's promoted signals stripped of their evidence blocks. The operator downloads this file and opens a PR (or an issue with the file attached) against this repo to contribute it back.

`docs/signals/staging/` is where contributed profiles land during review. A maintainer inspects, may re-run the essentials against a comparable ECU if available, promotes select signals into `docs/signals/signals.yaml` at `provisional`, and later confirms them. The user's own bike keeps working from NVS regardless of whether the PR merges.

### Essentials procedure library

`docs/discovery/essentials/` holds the curated, bike-agnostic procedures the wizard walks the operator through by default. Starting set targets the desk-reachable signals from 0009's scope discipline:

- `key-on-off.procedure.yaml` — ignition switch, wake pattern, initial-broadcast IDs
- `engine-start-stop.procedure.yaml` — engine-on bit, RPM idle baseline
- `kill-switch.procedure.yaml` — toggle N times, exclusive bit
- `sidestand.procedure.yaml` — up/down N times, exclusive bit
- `clutch.procedure.yaml` — in/out N times, exclusive bit
- `gear-walk.procedure.yaml` — sequential 1→2→3→4→5→6→N with clutch and neutral re-checks
- `throttle-sweep.procedure.yaml` — 0→100→0 several times, monotonic byte tracking
- `hold-rpm-tiers.procedure.yaml` — hold at 1500/2500/3500/4500, scale + offset regression
- `wheel-roll-front.procedure.yaml` / `wheel-roll-rear.procedure.yaml` — hand-rolled wheel, physical-ramp detection
- `warmup-coolant.procedure.yaml` — 5+ min idle, slow monotonic upward tracking

Each procedure declares the signals it targets and the evidence weight it produces for each. The wizard runs them in a curated order (booleans first, monotonic scalars next, slow scalars last) so early confidence builds up before the harder procedures run. Bike-specific quirks (e.g. two IDs broadcasting RPM simultaneously) surface as multiple high-confidence candidates in the verification UI — the top-N-candidates design turns quirks into disambiguation rather than failure.

### Validation via our own bike as ground truth

`docs/discovery/validation/` documents running the essentials against this project's Svartpilen 401 where `docs/signals/signals.yaml` already has 11 `confirmed` entries. This is the closed-loop test that keeps the inference layer honest: an inference change that fails to re-derive a known-good signal is a regression. Running validation from scratch is one operator session at the desk with a bike attached; results land as `docs/discovery/validation/YYYY-MM-DD.md` with per-signal recall + false-positive counts.

This is the same regression-set principle 0009 committed to, just made concrete as a documented periodic exercise rather than an ad-hoc test.

### Phased delivery

The full loop is a real project — realistically a couple months of focused work end-to-end. Building it in phases keeps each phase independently valuable and shippable:

- **Phase 1 — Capture only.** Typed procedure schema v2 loader, browser runner UI at `/discover` with countdown / session UX, N-runs-per-procedure enforcement, session export to OPFS. Analysis runs via `scripts/discover.py` (Python) against a downloaded session directory — this validates the schema, the operator UX, and the on-device transport without blocking on the JS analysis engine. Delivers value to us immediately; unblocks essentials library authoring.
- **Phase 2 — Analysis moves to browser.** Web Worker port of the correlation math. Verification UI renders top-3 candidates for each expected signal with live tracking against `/stream`. Operator confirms; confirmed candidates persist to OPFS `staging/`. `scripts/discover.py` stays for CLI / CI use against fixture sessions. Delivers zero-Python for the capture-through-verification flow.
- **Phase 3 — Promote loop.** `GET`/`POST`/`DELETE /signals` + NVS `user_signals` blob. Rider view fetches signals dynamically at load. Promote button in verification UI writes to NVS via `POST /signals`. Export button produces a shareable `<bike-slug>.signals.yaml` for the contribution flow. Delivers the full magical zero-touch loop.

Each phase can pause between them without leaving anything broken. Phase boundaries are also natural points to reassess: if Phase 1's essentials + Python analyzer already deliver enough value for the users we hear from, Phase 2 gets pulled forward or reshaped based on what the friction actually is.

## Consequences

- **ADR 0009 is superseded, not repealed.** Its philosophy (procedure library as growth surface, closed-set scope, validation non-negotiable, ~60–70% first-shot ceiling, "not a generic CAN decoder", "not zero-knowledge") carries forward verbatim. Only the implementation vehicle changes.
- **wifi-bridge M8 is dropped.** The M8 slot (`/dev` view + Active-unknown-bytes port + mark button) is deleted from the wifi-bridge milestone plan in the same change that lands this ADR. `POST /mark` from M7a stays. The mark button as an M7b was not worth the surface area — procedure-driven captures insert marks automatically at step boundaries; free-form marks from the bike side are rare and covered by `curl -X POST /mark` from a nearby laptop.
- **`scripts/live_view/` stays.** The TUI is the R&D deep-dive tool for authored experiments and custom `.procedure.yaml` files with `{kind: prompt}` steps. No retirement plan. The wizard is not trying to reach TUI parity — different tool for a different user.
- **ADR 0006's procedure schema gains a version bump.** Schema v1 (prompt-only) continues to work for existing experiments. Schema v2 adds typed step kinds. The loader (`scripts/capture.py`, browser runner) dispatches on `schema_version`.
- **`signals.yaml` schema becomes load-bearing for outside users** — same commitment 0009 made. Adds a `schema_version: 1` header to every profile (project's own `docs/signals/signals.yaml` and every exported `<bike-slug>.signals.yaml`) for forward compatibility as the schema evolves.
- **NVS `user_signals` blob is a new persistent artifact on the ESP.** Sized generously (~16 KB is a lot of signals). Wiped on OTA-of-a-different-app-slot; survives normal OTA of the same wifi-bridge app. A wipe-signals control lives in the wizard UI for the case where the operator wants to start fresh on a different bike using the same rig.
- **AP-level authentication is the only trust boundary for promotion.** Anyone on the AP can `POST /signals`. Acceptable for the hobbyist tool; called out so it does not become a silent assumption when the tool grows.
- **The rider view now fetches its signal table at page load** instead of reading a baked constant. Small change, but it means the rider view is no longer purely static — it depends on `GET /signals` being reachable. Cached in the browser after first load; falls back to the baked-in confirmed list on fetch failure.
- **Community profile sharing is enabled but not built.** Same posture as 0009 — profiles are shareable artifacts; the mechanism (registry, signing, trust, conflict resolution) is out of scope. Contributed profiles enter this repo through PRs against `docs/signals/staging/`; a maintainer reviews before anything reaches `docs/signals/signals.yaml`.
- **Inference is still the hardest engineering piece.** JS port does not make the algorithm easier — it removes a runtime dependency, not a correctness challenge. Multi-run aggregation, endianness/scale solving, and multi-broadcaster disambiguation are where the wizard's quality bar will be set. Phase 1's Python analyzer is where we iterate the algorithm; Phase 2 ports the version that works.
- **Realistic ceiling stays at ~60–70% first-shot on desk-reachable signals.** JS-in-browser does not raise the ceiling. What it raises is the addressable user population — from "people who write Python" to "people who can flash a firmware and follow prompts."

## Deferred / open

- **Motion-required signals** (wheel speed under way, ABS faults, fuel-burn-over-distance, lean angle). Out of Phase 3. Ride-along tier gets its own follow-up ADR once desk-reachable coverage stabilizes and inference quality is measured against the 390 platform's known answers. `docs/signals/staging/wheel-*.yaml` from static rolls are Phase 3's approximation.
- **Firmware signal-tolerance ADR.** The eventual production dashboard needs to render "widget unavailable" cleanly when a signal is absent from a bike's profile. Called out in 0009; not this ADR's scope. Wifi-bridge's rider view already handles missing signals gracefully because they simply do not render if their arb-ID never fires; the production dashboard has stronger requirements.
- **Community profile registry, signing, trust, inter-profile conflict resolution.** Same posture as 0009 — data-model commitment ("profiles are shareable") is here; distribution mechanics get their own ADR when there is a second contributor.
- **`POST /discover` endpoint** running the analyzer on-device or shelling out to a laptop-hosted companion. Not planned for Phase 3 — the Web Worker in the browser is sufficient. Revisit if the analyzer grows in scope beyond what a phone can handle in ~30 s.
- **Authenticated promotion.** WPA2 AP membership is the trust boundary today. If the tool ever runs on a shared network or the AP becomes open, promotion needs a shared secret or a physical-button-press confirmation on the ESP. Not urgent; called out so the assumption is documented.
- **Schema migration path for `signals.yaml` beyond `schema_version: 1`.** The version field is here; the migration story is not. Deferred until the second schema version actually happens.
- **Inference CI regression suite** against fixture sessions in `docs/discovery/validation/`. Nice to have; not blocking Phase 1. Naturally slots in once the essentials library and Python analyzer are stable enough that fixtures have shelf-life.
