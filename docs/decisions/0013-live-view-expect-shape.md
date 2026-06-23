# 0013 — Live view: expect-shape highlight

**Date:** 2026-06-23
**Status:** Accepted
**Extends:** ADR 0010 (operator agency on the discovery surface). No prior decision is superseded.

## Context

The discovery surface as of ADR 0010/0011/0012 is good at telling the operator "something is happening here": bytes light up in the active-unknown pane, bits surface in the continuous anomalies pane, classifier hints (`sensor` / `counter` / `step` / `boolean`) and glyphs (`⊞` / `↻` / `·`) help the eye triage.

What it doesn't do is help the operator when they have a **specific expectation** going in. The dominant discovery workflow is now:

1. Operator picks a hypothesis ("RPM is somewhere on this bus").
2. They perform a targeted physical action — throttle sweep, kill-switch toggle, gear change.
3. They scan the discovery panes for which rows moved during that action.

Step 3 is where the surface stops earning its keep. During a throttle sweep, every sensor-shaped byte, every counter, every checksum bit, every step-state byte that happens to tick over — they all surface simultaneously. The operator knows what they're hunting for (an analog-ish sensor that climbs with throttle) but the pane has no way to weight rows by that expectation. The eye still does the filtering, frame after frame.

The classifier already knows the shape. The pane already knows which rows are which. The operator already knows what they want. Wiring those three together is one step of work that the existing infrastructure has carried right up to.

### Considered and rejected

- **Hard filter** (hide non-matching rows): biggest signal-to-noise win, but bakes the operator's hypothesis into what they can see. RPM that lives across two bytes — low byte counter-shaped, high byte step-shaped — would be partially hidden under "expect sensor." Kill switch that rides inside an arb carrying other live signals would be hidden by a row-level glyph mismatch. Filtering makes the most plausible-but-wrong rows invisible, which is exactly the failure mode discovery tooling should not have.
- **Smarter / per-bit classifier**: would let a richer expectation system work (e.g., "expect bool, ignore arbs already pinned"), but adds analytical surface area when the gap is on the operator-control side. ADR 0010's framing — "the analytical side is past diminishing returns relative to operator-control returns" — still holds.
- **Auto-promote shape on first match**: surfaces the shape the operator was hunting and silently flips to "you found it." Same failure mode as auto-collapse panes (ADR 0010 §1): surprising layout shifts mid-ride are worse than steady-state behaviour the operator is already adapted to.

## Decision

Add a session-local **expect-shape** lens over the existing discovery panes. The lens accents matches and dims non-matches; it never hides a row.

### 1. Expectation state

A single nullable field on the `LiveView` app:

```
self.expect_shape: Literal["sensor", "counter", "step", "boolean"] | None
```

Default `None`. Session-local; never persisted; not a CLI flag. Cleared by the operator the same way it's set.

### 2. Entry — `Ctrl+E` opens an expect picker

Printable chars remain reserved for mark hotkeys (`capture.py` HOTKEYS). `Ctrl+E` is currently unused and survives the Mac-terminal constraints listed in ADR 0010 §2.

The picker is a small centered modal — same envelope as the other modals in `modals.py`:

```
 ┌─ Expect shape ───────────────┐
 │  1  sensor    (∿)            │
 │  2  counter   (↻)            │
 │  3  step      (⊟)            │
 │  4  boolean   (▔_)           │
 │  0  none / clear             │
 │  [dim]Esc cancel[/dim]       │
 └──────────────────────────────┘
```

Digit hotkeys submit immediately. `0` clears. `Esc` cancels without changing state. Pressing `Ctrl+E` while the modal is already open is a no-op (consistent with `WatchModal` / `HypothesisModal` precedent).

### 3. Status pane shows current expectation

The tunables line in `status_text` gains one token when the lens is active:

```
z=3.0  ratio=3.0×  d7=off  suppressed=off  expect=sensor ∿
```

When `expect_shape is None`, no token is rendered — quiet by default, loud when the operator has armed the lens.

### 4. Byte pane — accent matches, dim non-matches

In the Active-unknown-bytes pane (ADR 0008/0012), per row at render time:

- **Classifier returns the expected shape** → accent the `0x<arb> D<byte>` token (green); leave the existing HOT/DIM tier logic untouched. A matching row that's decaying stays dim, but its arb token still shows the accent so the eye can spot it during the cooldown tail.
- **Classifier returns a different shape** → wrap the whole row in `[dim]` regardless of HOT tier. The row stays visible (rule #1: never hide) but loses its loud rendering so matches stand out.
- **Classifier returned `""`** (unclassified — fewer than 4 samples, or doesn't fit a bucket) → no change. This is the explicit "neither match nor non-match" tier. It exists to protect the first ~1 s of a throttle sweep, when the very byte you're hunting hasn't seen enough samples yet to classify as `sensor`. Dimming it during that window would punish the row you're trying to find.

`first_activity` rows (baseline-floor case, suffix `(first activity)`) count as unclassified and also stay neutral.

### 5. Anomaly pane — accent matches, leave non-matches alone

The continuous anomalies pane (ADR 0011) is denser, and its glyphs are a coarser proxy for shape than the byte classifier. Map expectation → glyph:

| Expect | Matches glyph(s) |
|---|---|
| `sensor` | `⊞` (multi-bit on a shared byte — signal-like) |
| `step`   | `⊞` (same — both register as multi-bit bursts) |
| `counter`| `↻` (single bit on a fast-cycling baseline) |
| `boolean`| `·` (isolated single-bit flip) |

Behaviour:

- **Glyph matches expectation** AND the row has no co-occurrence accent AND no halo → green accent on the arb token. (Co-occurrence accent and halo both win — they convey live event semantics that expectation shouldn't overwrite.)
- **Glyph doesn't match** → row renders unchanged. We do NOT dim non-matching rows here. The anomaly pane is already dense and a dim layer on top of its existing dim-by-age tier would make the pane unreadable. The accent on matching rows is enough.

The `sensor`/`step` collapse to the same glyph is intentional: at the bit-flip level the two shapes are indistinguishable (both are multi-bit bursts), so we don't claim a precision the underlying signal can't provide. The byte pane is the right surface to disambiguate `sensor` from `step` — its classifier sees the value series directly.

### 6. Hypothesis-capture interaction

`Ctrl+N` (ADR 0010 §3) is unchanged. The hypothesis modal does NOT pre-filter rows by `expect_shape` — the operator's expectation is a viewing lens, not an authorial constraint. If the lens is armed and the operator captures a row whose classifier shape disagrees with `expect_shape`, that's their call (and probably the most interesting case — a kill-switch hypothesis confirmed by a `step`-classified byte is information).

## Consequences

- **Targeted-sweep workflow gets faster.** A throttle sweep with `expect=sensor` puts the green accent exactly where the eye is hunting, while everything else recedes one tier. Same panes, same data, less cognitive load.
- **Discovery rule preserved.** Nothing is hidden. An unexpected counter that's actually the RPM lives still surfaces — it just doesn't compete for attention with the sensor rows the operator asked for.
- **Status pane stays compact when unused.** The expect token only renders when armed. Default surface area is unchanged for operators who never reach for the lens.
- **Keybinding budget tightens by one.** `Ctrl+E` joins `Ctrl+D` / `Ctrl+Y` / `Ctrl+N` as the active control namespace. The legend pane needs the new entry; nothing else changes.
- **Classifier coverage matters more.** `classify_byte` returning `""` is now a UX-visible state (the neutral tier), not just an empty suffix. Future changes to the classifier need to keep the "uncertain → empty string" contract — emitting a wrong label would now wrongly dim or wrongly accent a row.
- **Scope discipline.** This ADR is one lens over the existing surface. It is not a per-pane filter system, not a hypothesis-driven decoder, not a bit-level shape classifier. Each of those would be its own ADR if needed.
- **Implementation touch points.** `scripts/live_view/modals.py` gains `ExpectShapeModal`. `scripts/live_view/app.py` gains `self.expect_shape`, the `Ctrl+E` handling, the status-pane token, and accent/dim wiring through the byte and anomaly pane renderers. `scripts/live_view/state.py` `_render_byte_row` and `_render_anomaly_row` gain optional accent/dim flags driven by expect-shape; existing call sites remain valid (new parameters default to no-op).
