---
date: 2026-06-18
status: superseded
phase: 1
related:
  findings:
    - can/always-on-broadcast-ids
    - can/post-kill-decay-groups
    - can/signal-rpm
    - can/signal-throttle-position
    - can/signal-warmup-index
  references:
    - ktm-can-decoder
    - svartpilen-401-dash-user-manual
  experiments:
    - 2026-07-12-dash-inputs
    - 2026-07-12-neutral-rpm-sweep
  logs: []
---

# Engine-on stationary inputs — SUPERSEDED, split in two

> **Superseded 2026-07-12 — never ran.** Split into two focused experiments because the original bundled two unrelated rider postures (fingers on dash buttons vs. hand on throttle) and two unrelated analysis pipelines (cluster-side momentary-bit diffs vs. `engine_load_scan.py` matched-RPM tables against the in-gear rear-spin capture) into a single 5+ min session. The bundling made a mode-toggle fault (per the manual, dash flashing = fault, abort) block the throttle work as well, and mixed idle-RPM jitter into per-window diffs of dash-button presses.
>
> Splits:
>
> - Phases A + B + C (mode toggle, trip reset, dash button short-presses) → [2026-07-12-dash-inputs](2026-07-12-dash-inputs.md). Cluster-side only, **engine-off** for cleanest per-window bit diffs on the slow-decay group (`12A`, `12D`, `12E`, `450`, `541`). Phase A carries a contingency: if mode toggle needs engine-on, abort Phase A but keep B/C and re-run A engine-on later.
> - Phases D + E (throttle blip engine-on, five held RPM setpoints in neutral) → [2026-07-12-neutral-rpm-sweep](2026-07-12-neutral-rpm-sweep.md). Matched to [[2026-06-23-engine-driven-rear-spin]] for the `540` D1 / [[signal-warmup-index]] re-attribution and the `121` D0..D3 characterization. Free MIL bit + side-stand engine-on confirmation from the timeline.
>
> Both split experiments also drop the initial key-off silence window: the wifi-bridge is now bike-powered (ADR 0018 / [[project-wifi-bridge-ota]]), so the ESP is off until the key is on and the capture host connects to `ws://<esp>/stream` after key-on. The dash-inputs procedure yaml is the first one written under that constraint.
>
> **Mode-vs-engine independence cross-check** — the original had this as analysis point 8 (in-session comparison of engine-side bytes across ROAD and SUPERMOTO). With the two experiments now split, this becomes a small back-to-back comparison after both complete rather than a within-session invariant. Noted as a follow-up in both split files.
>
> Original plan is not preserved here — it lives in git history at commit 5d8f406 and in the paired split files. The `.procedure.yaml` sidecar has been removed; use the two new sidecars instead.
