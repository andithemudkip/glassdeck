# Logs

Raw CAN captures. **Files in this directory are immutable** — never edited, never deleted, never "cleaned up."

Each capture session is its own directory:

```
logs/YYYY-MM-DD-<condition>/
  capture.log              raw capture, untouched
  session.md               required: bike state, rider actions, hardware/firmware, anomalies
  *.decoded.csv            optional: derived artifacts, may be regenerated freely
```

`session.md` is mandatory. A capture without context is half-useless.

Suggested `<condition>` slugs: `idle`, `rev-static`, `ride-mixed`, `indicators-left`, `mode-switch-road-to-supermoto`, `service-reset`, etc. — match the action being tested.

If a capture is bad (wrong bitrate, dropped frames, mis-wired adapter), leave it in place and note the problem in its `session.md`. Future you will want to know what a broken capture looks like.

Captures over ~10MB should eventually move to git LFS; until then, keep an eye on repo size.
