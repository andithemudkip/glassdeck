# 0018 — Browser-primary capture with gap-fill ring and on-device timestamps

**Date:** 2026-07-08
**Status:** Accepted
**Relates to:** [ADR 0016](0016-wifi-dev-capture-and-live-view.md) (amends § Capture buffer, § Server, § Operational rules; supersedes the phone-free ride-capture assumption and the § Out of scope "no firmware timestamps" line)

## Context

ADR 0016 § Capture buffer specified a 4 MB PSRAM ring with `GET /capture` as the log-egress path, sized for phone-free rides (leave the ESP on the bike, ride, come back to the desk, download the ring). § Out of scope also committed to host-side timestamping — the receiver stamps frames on arrival, same as `can-logger/` over USB-CDC.

Two things about that plan don't survive contact with actual use:

1. **The 4 MB ring caps captures at ~5 minutes.** Drop-oldest means a 20-minute ride keeps only the last 5, which is the wrong tail for most R&D questions — the interesting moment is usually when *something changed*, not the last thing before parking. Growing the ring to cover a whole ride isn't feasible on 8 MB PSRAM once WebSocket buffers and IDF heap are accounted for, and would still leave a hard ceiling.
2. **Host-side timestamping stops working once `/capture` is asynchronous.** When the only egress was USB-CDC into a live host, receive-time was a fine proxy for send-time. A ring downloaded hours later has no such proxy — the SLCAN comes out timestamp-free, losing ordering precision every downstream analysis script assumes.

The redesign: put the browser in the capture loop for every ride. Frames go over `/stream` (unchanged from M3) directly into the browser's OPFS, appended as they arrive. The ring stops being the primary store and becomes a short-lived backstop that lets the browser splice over transient WebSocket disconnects — the only failure mode a phone-in-loop design still has. Ring frames need on-device timestamps because they are the anchor the browser keys against when requesting the gap; WS frames need the same stamps so the splice-boundary dedup is exact.

Dropping the phone-free-rides assumption is what makes the rest of the redesign cheap: the ring shrinks from 4 MB to ~512 KB, `GET /capture` grows a `?since=` query instead of a filename-disambiguation scheme, and there's one storage clock instead of two (ring µs vs. host wall-time).

### Considered and rejected

- **Grow the ring.** 8 MB PSRAM leaves room for maybe a 6 MB ring; that's ~8 minutes at 300 fps with timestamps. Doesn't solve the hard-ceiling problem, just moves it. Still capped by physical PSRAM; still drops the middle of long rides.
- **Add microSD.** Physically eliminates the ceiling. Rejected in ADR 0016 § Considered and rejected and the reasoning still holds: adds hardware (breakout + four GPIOs + retention policy + writer task with backpressure), and the rider-facing use case now expects a phone in the loop anyway. If a contributor eventually wants ESP-only rides, SD becomes the right answer at that point.
- **Keep host-side timestamps only.** Works while the browser is connected — receive-time is close enough to send-time on WiFi. Breaks the moment the browser reconnects: the ring content has no timestamps, so the browser has no offset to splice at. Any backfill protocol needs firmware stamps.
- **Canusb `T`-suffix timestamp format.** Compact (~4 extra bytes/frame vs ~14 for `(<sec>.<us>)`) and standard, but the 60-second ms wraparound means backfill splices have to unwrap on the host side. Extra parser code with no user-visible benefit; every existing `scripts/` tool would also need the new branch. Rejected — the size delta doesn't buy enough to justify the complexity.
- **Raw `<us_hex>` prefix.** Smallest that's monotonic + no-wrap, but every downstream consumer needs a new parser branch to read it. The `(<sec>.<us>)` format already parses everywhere. Rejected.

## Decision

### Storage architecture

**Browser-primary, ring is a backstop.**

- The browser's OPFS is the primary capture sink. Frames arriving over `/stream` are appended continuously via `navigator.storage.getDirectory()` + `createWritable()`. Capture length is bounded by disk quota, not by PSRAM.
- The PSRAM ring shrinks to ~512 KB (~30 s at 300 fps with timestamps). Its job is to hold enough recent history that when a WebSocket drops and reconnects, the browser can pull the missed window from `/capture?since=<ts>` and splice it into OPFS.
- The TWAI read task still starts before WiFi and writes into the ring immediately — cold-boot frames aren't lost, unchanged from ADR 0016.
- Drop-oldest on ring overflow. `frames_ring_dropped` counter on `/health`.
- Phone-free rides are explicitly dropped from scope. See § Consequences.

### On-device timestamps

- Timestamps are added in the TWAI RX loop via `esp_timer_get_time()` (int64 µs since boot, monotonic, same clock `/health` uptime uses). No RTC, no NTP.
- Both ring entries and `/stream` WebSocket frames carry the same stamp on the same clock. Ring stamps are what the browser keys `since` off; WS stamps are what the browser writes into OPFS and what it uses to dedup the splice boundary on reconnect.
- **Wire format: `(<sec>.<us>) t120806A400001234\r`** — the leading candidate from `firmware/wifi-bridge/README.md` § Deferred / open. Byte-for-byte match to what `capture.py` currently writes to disk, so every existing `scripts/` tool consumes the stream unchanged. Costs ~14 extra bytes per frame vs. bare SLCAN; ring holds ~30 s in 512 KB at 300 fps.
- Timestamp is send-time (µs since boot) formatted as seconds.µs. It never wraps within realistic device uptimes (int64 µs = 292k years). Host-side receivers stop adding their own prefix when the frame already has one — see § Downstream tolerance.

### `/capture?since=<ts_us>` protocol

- `GET /capture?since=<ts_us>` streams every ring entry with `ts > since`, in order, as SLCAN with the timestamp format above.
- If `<ts_us>` fell before the ring's earliest surviving entry (i.e. the ring wrapped during the disconnect), the response carries an `X-Bike-Gap-Ms: <ms>` header stating how much of the requested window is unrecoverable. Body then contains what the ring still has.
- Bare `GET /capture` (no `since` param) returns the full current ring for ad-hoc inspection. No `Content-Disposition` filename semantics — the browser handles naming on export, not the firmware.

### Backfill protocol (browser side)

State: `last_persisted_ts`, the highest µs of any frame successfully flushed to OPFS. Snapshot to a sidecar OPFS key on each flush so a page reload picks up where it left off.

On WS reconnect:

1. Pause live consumption (buffer incoming WS frames to memory).
2. `GET /capture?since=<last_persisted_ts>`.
3. If response carries `X-Bike-Gap-Ms: <ms>`, write `# GAP <ms>` into OPFS.
4. Append the backfill body to OPFS. Advance `last_persisted_ts` to the highest ts returned.
5. Drain the buffered live frames, dropping any with `ts ≤ last_persisted_ts` (deduped splice at the boundary).
6. Resume live-WS → OPFS.

Runs identically for the 1st, 2nd, Nth reconnect within one capture. The only persistent state is `last_persisted_ts`, monotonic.

### Gap markers

Backfill inserts `# GAP <ms>` lines into OPFS at the point of unrecoverable data. Same comment-prefix convention as `# MARK <label>` (from the M7a `/mark` endpoint) so downstream tooling reuses one skip-and-log branch.

### Session durability on the phone

- The rider view acquires `navigator.wakeLock` on capture start to keep the tab alive on the phone; releases on export or user stop.
- iOS Safari (and iOS Chrome, which is WebKit-under-the-hood) evicts script-writable storage after 7 days of no visits unless the site is added to the home screen. The rider view's start-capture flow includes an "Add to Home Screen" prompt on iOS — the resulting standalone-web-app context grants OPFS durability that plain tabs don't get.
- Chrome desktop / Android Chrome call `navigator.storage.persist()` on first write instead. iOS ignores the call and relies on the install path.

### Export flow

An "Export capture" button on the rider view reads the OPFS file and triggers a browser download named `capture-<start_ts_iso>-<frames>.log`. Single code path across platforms. The `showSaveFilePicker` branch on Chrome desktop / Android Chrome is deferred — one export path stays consistent across the audience for now.

### Downstream tolerance

- `scripts/capture.py --stdin` and `scripts/inventory_ids.py` tolerate `# GAP <ms>` (log-and-skip, same treatment as `# MARK`).
- `scripts/capture.py --stdin`'s SLCAN regex loosens to accept both prefixed and unprefixed lines. USB captures from `firmware/can-logger/` still parse (they have no prefix); wifi-bridge captures parse (they do).
- Receivers that already prefix (`capture.py` writing to disk today) do not double-prefix a line that arrives already prefixed. Straight pass-through when the send-side stamp is present.

## Consequences

- **Untethered dev rides are unbounded in length.** Capture size is limited by phone/laptop disk quota, not by PSRAM. Practical ceiling at ~1 GB of OPFS quota on iOS is ~20 hours of ride data at 300 fps.
- **Phone-free ESP-only rides are dropped from scope.** ADR 0016's original M4 use case (leave the rig on the bike, ride, come back and download) is no longer supported by this milestone. Rationale: every reverse-engineer of a bike has a phone; requiring it in the loop simplifies firmware substantially (small ring, one clock, no filename disambiguation). Adding phone-free rides back later is a straightforward extension — grow the ring, keep bare `/capture` responding, keep the timestamp format — and doesn't require changes to anything decided here. Deferred to a follow-up ADR when the need is concrete.
- **PSRAM budget drops from 4 MB to ~512 KB.** Frees ~3.5 MB of PSRAM for future dev-view state (M8's Active-unknown-bytes port), WebSocket buffers, or larger IDF heap. No immediate consumer, but not a scarce resource anymore either.
- **`(<sec>.<us>)` prefix is the wifi-bridge wire format from M4 onward.** All existing `scripts/` tooling consumes it without changes. Old timestamp-free USB captures (from `can-logger/` and pre-M4 wifi-bridge) still parse via the regex loosen. No dual-format code paths in firmware; the ring format is what `/capture` serialises, so this locks at M4 start.
- **Browser session has to survive the ride.** Wake-lock + Add-to-Home-Screen on iOS mitigates most failure modes (tab background, screen lock, ITP eviction). Failure modes that remain: phone battery dies, physical damage, WiFi drops longer than ring capacity. The last of these degrades to `# GAP <ms>` markers rather than silent holes, which is acceptable; the other two are user-managed risks with no cheap firmware mitigation.
- **ADR 0016 § Out of scope "Timestamping in firmware" is superseded.** M4 does firmware timestamps. `firmware/wifi-bridge/README.md` § Out of scope updated to match.
- **ADR 0016 § Capture buffer is amended.** Ring size, drop policy metric name, and boot-order guarantees are updated by § Storage architecture above. The "ring outlives WebSocket reconnects" property from 0016 is preserved and strengthened — reconnects now splice into OPFS via the backfill protocol rather than reading `/capture` manually.
- **ADR 0016 § Server table gains one query parameter.** `/capture` now accepts `?since=<ts_us>`. Bare `GET /capture` still works.
- **No CAN-TX. No backwards-compat shims in firmware.** Consistent with ADR 0016 and the golden no-TX rule.
