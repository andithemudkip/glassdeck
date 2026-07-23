  // -------------------------------------------------------------------------
  // Capture pipeline (M4 / ADR 0018)
  //
  // Browser-primary log sink. The WS handler feeds every raw (prefix-included)
  // line into onCaptureLine; when a capture is active they get batched into
  // IndexedDB every FLUSH_INTERVAL_MS. On WS reconnect performBackfill drains
  // the firmware's /capture ring to splice over the gap; an X-Bike-Gap-Ms
  // header from the firmware translates to a `# GAP <ms>` marker in the file
  // (same comment convention as `# MARK` — see M7a).
  //
  // Storage: IndexedDB (not OPFS) because the ESP32 serves plain HTTP over the
  // LAN and `navigator.storage.getDirectory` is secure-context-gated on every
  // phone browser. IDB works in insecure contexts and is available everywhere
  // we target. On-disk representation is chunk records in the `chunks` store,
  // reassembled to a Blob on export.
  //
  // State discipline: lastPersistedTs is the only piece of "resume anywhere"
  // state, snapshotted to the sidecar record on every flush so a page reload
  // during a capture picks up cleanly.
  // -------------------------------------------------------------------------

  const IDB_NAME = "glassdeck-capture";
  const IDB_VERSION = 1;
  const IDB_CAPTURES = "captures";
  const IDB_CHUNKS = "chunks";
  const IDB_SIDECAR = "sidecar";
  const SIDECAR_KEY = "active-capture";
  const FLUSH_INTERVAL_MS = 500;

  // idle → recording → resuming → recording; back to idle on Stop/Export.
  let captureState = "idle";
  let captureFileName = null;    // logical name; identifies the IDB records
  let captureStartIso = null;    // ISO string embedded in the exported filename
  let captureStartWallMs = 0;    // Date.now() — persists across reloads for the elapsed counter
  let captureLabel = "";         // sanitized user-supplied label, "" if none
  let captureOffset = 0;         // running byte total across all flushed chunks
  let captureFrames = 0;
  let captureGaps = 0;
  let nextSeq = 0;               // next chunk index for the active capture
  let lastPersistedTs = 0;
  let pendingWrites = [];        // string[] queued for the next flush
  let resumeBuffer = [];         // {raw, ts}[] captured during a reconnect
  let flushScheduled = false;
  let wakeLockRef = null;

  // Filename convention (also the IDB record key so it survives reloads
  // without extra sidecar state): capture-<iso>[__<label>].log
  // `__` (double underscore) is the label delimiter — chosen over `-` because
  // the ISO string already has dashes, so a single `-` couldn't split cleanly.
  const LABEL_DELIM = "__";
  function sanitizeLabel(s) {
    return String(s || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40);
  }
  function parseCaptureName(fn) {
    // capture-<iso>[__<label>].log → { iso, label }
    const m = fn.match(/^capture-(.+?)(?:__(.+))?\.log$/);
    if (!m) return null;
    return { iso: m[1], label: m[2] || "" };
  }
  function fmtSize(n) {
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / (1024 * 1024)).toFixed(2) + " MB";
  }
  function fmtDateFromIso(iso) {
    // ISO variant we produce: 2026-07-09T14-32-08 (colons→dashes, no ms).
    // Convert back to a Date-parseable form for display.
    const norm = iso.replace(/T(\d{2})-(\d{2})-(\d{2})/, "T$1:$2:$3");
    const d = new Date(norm + "Z");
    if (isNaN(+d)) return iso;
    const pad = n => (n < 10 ? "0" + n : "" + n);
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  // DOM refs for the capture bar. Declared here so we can null-guard against
  // odd load orders (the M4 chunk runs before the WebSocket, but querySelector
  // still needs the document parsed — which it is inside this IIFE, called
  // from the bottom of <body>).
  const $captureBtn = document.getElementById("captureBtn");
  const $labelIn = document.getElementById("labelIn");
  const $captureStatus = document.getElementById("captureStatus");
  const $capElapsed = document.getElementById("capElapsed");
  const $capFrames = document.getElementById("capFrames");
  const $capGaps = document.getElementById("capGaps");
  const $capGapsWrap = document.getElementById("capGapsWrap");
  const $exportBtn = document.getElementById("exportBtn");
  const $filesBtn = document.getElementById("filesBtn");
  const $drawer = document.getElementById("drawer");
  const $drawerBackdrop = document.getElementById("drawerBackdrop");
  const $drawerList = document.getElementById("drawerList");
  const $drawerCount = document.getElementById("drawerCount");
  const $drawerClose = document.getElementById("drawerClose");
  const $a2hsHint = document.getElementById("a2hsHint");
  const $a2hsDismiss = document.getElementById("a2hsDismiss");

  function fmtElapsed(ms) {
    const s = Math.max(0, Math.floor(ms / 1000));
    const m = Math.floor(s / 60);
    const ss = s % 60;
    return `${m}:${ss < 10 ? "0" : ""}${ss}`;
  }

  // Cached count of captures, refreshed after Stop / delete / start.
  // Drives the Files-button visibility and its (N) badge without needing an
  // async scan on every renderCaptureBar call.
  let captureFileCount = 0;

  function renderCaptureBar() {
    if (captureState === "idle") {
      $captureBtn.textContent = captureFileName ? "New capture" : "Start capture";
      $captureBtn.classList.add("primary");
      $captureBtn.classList.remove("rec");
      $captureStatus.hidden = true;
      $exportBtn.hidden = !captureFileName;
      // Label input only shows when the user is about to Start something new.
      $labelIn.hidden = false;
      $labelIn.disabled = false;
    } else {
      $captureBtn.textContent = captureState === "resuming" ? "Resuming…" : "Stop";
      $captureBtn.classList.remove("primary");
      $captureBtn.classList.add("rec");
      $captureStatus.hidden = false;
      $capFrames.textContent = captureFrames.toLocaleString();
      $capGapsWrap.hidden = captureGaps === 0;
      $capGaps.textContent = String(captureGaps);
      $exportBtn.hidden = true;
      $labelIn.hidden = true;
    }
    if (captureFileCount > 0) {
      $filesBtn.hidden = false;
      $filesBtn.textContent = captureFileCount > 1 ? `Files (${captureFileCount})` : "Files";
    } else {
      $filesBtn.hidden = true;
    }
  }

  function tickCaptureBar() {
    if (captureState !== "idle" && captureStartWallMs > 0) {
      $capElapsed.textContent = fmtElapsed(Date.now() - captureStartWallMs);
    }
    requestAnimationFrame(tickCaptureBar);
  }

  // IndexedDB open + tiny promisified helpers. The DB has three stores:
  //   captures — one record per capture, keyed by name (the filename string).
  //              Carries running size/frames/gaps for the drawer to display
  //              without summing chunks.
  //   chunks   — one record per flush, composite key [name, seq]. Value is
  //              a Uint8Array; concatenated in order for Export.
  //   sidecar  — singleton at SIDECAR_KEY. Same JSON shape as before —
  //              carries lastPersistedTs + resume state.
  //
  // IDB is available in insecure contexts on every browser we target; it
  // sidesteps the secure-context gating that made OPFS unavailable over the
  // ESP32's HTTP endpoint.
  let dbPromise = null;
  function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      if (!window.indexedDB) { reject(new Error("IndexedDB not available")); return; }
      const req = indexedDB.open(IDB_NAME, IDB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(IDB_CAPTURES)) db.createObjectStore(IDB_CAPTURES, { keyPath: "name" });
        if (!db.objectStoreNames.contains(IDB_CHUNKS))   db.createObjectStore(IDB_CHUNKS,   { keyPath: ["name", "seq"] });
        if (!db.objectStoreNames.contains(IDB_SIDECAR))  db.createObjectStore(IDB_SIDECAR);
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return dbPromise;
  }
  function pReq(req) {
    return new Promise((resolve, reject) => {
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  function pTxn(txn) {
    return new Promise((resolve, reject) => {
      txn.oncomplete = () => resolve();
      txn.onerror = () => reject(txn.error);
      txn.onabort = () => reject(txn.error || new Error("txn aborted"));
    });
  }
  // Range covering every chunk of a given capture. `[]` compares greater than
  // any number in IDB key ordering, so `[name, []]` is a valid upper bound.
  function chunkRangeFor(name) {
    return IDBKeyRange.bound([name], [name, []]);
  }

  async function writeSidecar() {
    try {
      const db = await openDb();
      const txn = db.transaction(IDB_SIDECAR, "readwrite");
      txn.objectStore(IDB_SIDECAR).put({
        captureFile: captureFileName,
        startIso: captureStartIso,
        startWallMs: captureStartWallMs,
        offset: captureOffset,
        lastPersistedTs: lastPersistedTs,
        frames: captureFrames,
        gaps: captureGaps,
      }, SIDECAR_KEY);
      await pTxn(txn);
    } catch (e) {
      // Sidecar failures aren't fatal — the chunks themselves are still being
      // written. Resume-across-reload just won't work this session.
      console.warn("sidecar write failed", e);
    }
  }

  async function clearSidecar() {
    try {
      const db = await openDb();
      const txn = db.transaction(IDB_SIDECAR, "readwrite");
      txn.objectStore(IDB_SIDECAR).delete(SIDECAR_KEY);
      await pTxn(txn);
    } catch (e) { /* ignore */ }
  }

  async function readSidecar() {
    try {
      const db = await openDb();
      const txn = db.transaction(IDB_SIDECAR, "readonly");
      const v = await pReq(txn.objectStore(IDB_SIDECAR).get(SIDECAR_KEY));
      return v || null;
    } catch (e) {
      return null;
    }
  }

  // One IDB txn per flush covers the chunk write, the captures-record
  // metadata update, and the sidecar snapshot. Atomic — a reload can never
  // observe a chunk without its sidecar advance.
  async function flushBatch() {
    if (!captureFileName || pendingWrites.length === 0) return;
    const batch = pendingWrites.join("");
    pendingWrites = [];
    const bytes = new TextEncoder().encode(batch);
    const seq = nextSeq;
    const newOffset = captureOffset + bytes.byteLength;
    try {
      const db = await openDb();
      const txn = db.transaction([IDB_CHUNKS, IDB_CAPTURES, IDB_SIDECAR], "readwrite");
      txn.objectStore(IDB_CHUNKS).put({ name: captureFileName, seq, bytes });
      txn.objectStore(IDB_CAPTURES).put({
        name: captureFileName,
        iso: captureStartIso,
        label: captureLabel,
        startWallMs: captureStartWallMs,
        size: newOffset,
        frames: captureFrames,
        gaps: captureGaps,
      });
      txn.objectStore(IDB_SIDECAR).put({
        captureFile: captureFileName,
        startIso: captureStartIso,
        startWallMs: captureStartWallMs,
        offset: newOffset,
        lastPersistedTs: lastPersistedTs,
        frames: captureFrames,
        gaps: captureGaps,
      }, SIDECAR_KEY);
      await pTxn(txn);
      captureOffset = newOffset;
      nextSeq = seq + 1;
      renderCaptureBar();
    } catch (e) {
      // Requeue the batch so the next flush retries.
      pendingWrites.unshift(batch);
      console.error("IDB flush failed", e);
    }
  }

  function scheduleFlush() {
    if (flushScheduled || captureState === "idle") return;
    flushScheduled = true;
    setTimeout(async () => {
      flushScheduled = false;
      await flushBatch();
      if (captureState !== "idle" && (pendingWrites.length > 0 || captureState === "recording")) {
        scheduleFlush();
      }
    }, FLUSH_INTERVAL_MS);
  }

  // Called by the WS onmessage handler for every incoming line (including
  // firmware `# MARK` lines). `raw` is the line without trailing CR/LF; we
  // append \r\n on write to match the on-disk convention.
  function onCaptureLine(raw, ts) {
    if (captureState === "idle") return;
    if (captureState === "resuming") {
      resumeBuffer.push({ raw, ts });
      return;
    }
    if (ts !== null && ts <= lastPersistedTs) return;   // dedup safety
    pendingWrites.push(raw + "\r\n");
    captureFrames++;
    if (ts !== null) lastPersistedTs = Math.max(lastPersistedTs, ts);
    scheduleFlush();
  }

  // iOS Safari serves us over plain HTTP from 192.168.4.1, which fails the
  // secure-context gate on the Screen Wake Lock API — `navigator.wakeLock`
  // exists but `.request("screen")` throws. Fallback: NoSleep.js's silent
  // muted playsinline mp4 loop, which iOS honours as "media is playing" and
  // keeps the display on. The Wake Lock API path stays preferred for
  // Android/desktop where it works.
  const WAKE_MP4 = "data:video/mp4;base64,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";
  let wakeVideo = null;

  function ensureWakeVideo() {
    if (wakeVideo) return wakeVideo;
    const v = document.createElement("video");
    v.setAttribute("playsinline", "");
    v.setAttribute("muted", "");
    v.muted = true;
    v.loop = true;
    v.src = WAKE_MP4;
    // Off-screen 1×1 so the video is present in the DOM (iOS ignores
    // display:none video for playback) but invisible.
    v.style.cssText = "position:fixed;width:1px;height:1px;opacity:0;pointer-events:none;left:-1px;top:-1px;";
    document.body.appendChild(v);
    wakeVideo = v;
    return v;
  }

  async function requestWakeLock() {
    if ("wakeLock" in navigator) {
      try {
        wakeLockRef = await navigator.wakeLock.request("screen");
        wakeLockRef.addEventListener("release", () => { wakeLockRef = null; });
        return;
      } catch (e) { /* fall through to the video fallback */ }
    }
    try {
      const v = ensureWakeVideo();
      await v.play();
    } catch (e) { /* denied — non-fatal, capture continues */ }
  }

  function releaseWakeLock() {
    if (wakeLockRef) {
      try { wakeLockRef.release(); } catch (e) { /* ignore */ }
      wakeLockRef = null;
    }
    if (wakeVideo && !wakeVideo.paused) {
      try { wakeVideo.pause(); } catch (e) { /* ignore */ }
    }
  }

  // Reacquire wake-lock when the page comes back to the foreground — iOS
  // Safari drops the Wake Lock aggressively on tab switch, and pauses
  // background <video> playback too, so both paths need a nudge.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible" || captureState === "idle") return;
    if (!wakeLockRef) requestWakeLock();
    else if (wakeVideo && wakeVideo.paused) wakeVideo.play().catch(() => {});
  });

  async function startCapture() {
    if (captureState !== "idle") return;
    let db;
    try { db = await openDb(); }
    catch (e) {
      alert("This browser doesn't support IndexedDB — capture unavailable.");
      return;
    }
    // Filesystem-safe ISO variant for the filename (colons stripped, sub-second
    // precision dropped) — human readable and preserves ordering.
    const iso = new Date().toISOString().replace(/[:]/g, "-").replace(/\..+$/, "");
    captureLabel = sanitizeLabel($labelIn.value);
    captureFileName = captureLabel
      ? `capture-${iso}${LABEL_DELIM}${captureLabel}.log`
      : `capture-${iso}.log`;
    captureStartIso = iso;
    captureStartWallMs = Date.now();
    captureFrames = 0;
    captureGaps = 0;
    captureOffset = 0;
    nextSeq = 0;
    lastPersistedTs = 0;
    pendingWrites = [];
    resumeBuffer = [];
    try {
      const txn = db.transaction([IDB_CAPTURES, IDB_CHUNKS], "readwrite");
      // Defensive: an ISO-second collision would otherwise leave stale chunks
      // pinned under this key. Shouldn't happen but is trivial to guard.
      txn.objectStore(IDB_CHUNKS).delete(chunkRangeFor(captureFileName));
      txn.objectStore(IDB_CAPTURES).put({
        name: captureFileName,
        iso: captureStartIso,
        label: captureLabel,
        startWallMs: captureStartWallMs,
        size: 0,
        frames: 0,
        gaps: 0,
      });
      await pTxn(txn);
    } catch (e) {
      alert("Failed to create capture record: " + e.message);
      captureFileName = null;
      return;
    }
    // Chrome / Android — asks the browser to keep the DB across storage
    // pressure. iOS ignores; A2HS is the durability lever there.
    if (navigator.storage && navigator.storage.persist) {
      try { await navigator.storage.persist(); } catch (e) { /* ignore */ }
    }
    await requestWakeLock();
    captureState = "recording";
    await writeSidecar();
    scheduleFlush();
    renderCaptureBar();
    // Refresh the drawer's counter so "Files (N)" reflects the new capture
    // right away, in case the user opens the drawer mid-capture.
    refreshCaptureCount();
  }

  async function stopCapture() {
    if (captureState === "idle") return;
    // If we're mid-resume, wait a moment for it to settle so we don't leave
    // the resumeBuffer stranded.
    if (captureState === "resuming") {
      await new Promise(r => setTimeout(r, 200));
    }
    // Drain anything still in memory before flipping state — after the flip,
    // scheduleFlush stops arming new timers.
    await flushBatch();
    captureState = "idle";
    releaseWakeLock();
    // Sidecar's contract is "capture in progress" — a Stop must clear it so a
    // subsequent page refresh boots straight to idle. Without this, reload
    // sends the UI into performBackfill against a since= from the stopped
    // session and can wedge on "Resuming…".
    await clearSidecar();
    renderCaptureBar();
  }

  // Build a download filename from a parsed capture: label sits between the
  // ISO and the frame-count so downloads sort by date but read by intent.
  function downloadNameFor(iso, label, frames) {
    const lbl = label ? `-${label}` : "";
    return `capture-${iso}${lbl}-${frames}.log`;
  }

  // Concatenate every chunk of a capture into a single Blob. Cursors in ISO
  // key order → chunks land in insertion (seq) order. Materialised in memory
  // — long rides depend on the browser handling multi-hundred-MB Blob
  // assembly, which has been fine so far but is the trade vs OPFS getFile().
  async function readCaptureBlob(name) {
    const db = await openDb();
    const txn = db.transaction(IDB_CHUNKS, "readonly");
    const store = txn.objectStore(IDB_CHUNKS);
    const parts = [];
    return new Promise((resolve, reject) => {
      const req = store.openCursor(chunkRangeFor(name));
      req.onsuccess = () => {
        const cur = req.result;
        if (cur) { parts.push(cur.value.bytes); cur.continue(); }
        else { resolve(new Blob(parts, { type: "text/plain" })); }
      };
      req.onerror = () => reject(req.error);
    });
  }

  async function exportCapture() {
    if (captureState !== "idle") {
      await stopCapture();
    }
    if (!captureFileName) return;
    let blob;
    try { blob = await readCaptureBlob(captureFileName); }
    catch (e) {
      alert("Failed to read capture for export: " + e.message);
      return;
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = downloadNameFor(captureStartIso, captureLabel, captureFrames);
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    // Sidecar carries "prior capture available" state; keep it so a page
    // reload after Export still shows the Export button pointing at the
    // last file. Only clear on New capture.
  }

  // Fetches the ring since lastPersistedTs, writes any X-Bike-Gap-Ms as a
  // `# GAP <ms>` marker in the file, appends the backfill body, then drains
  // resumeBuffer deduped against lastPersistedTs. Idempotent across N
  // reconnects within one capture.
  async function performBackfill() {
    if (captureState !== "recording") return;
    captureState = "resuming";
    renderCaptureBar();
    try {
      const resp = await fetch(`/capture?since=${lastPersistedTs}`, { cache: "no-store" });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const gapMs = resp.headers.get("X-Bike-Gap-Ms");
      if (gapMs !== null) {
        pendingWrites.push(`# GAP ${gapMs}\r\n`);
        captureGaps++;
      }
      const body = await resp.text();
      if (body.length > 0) {
        // Normalize CR-only line endings to CRLF. The firmware ring stores
        // each frame as `(sec.us) t...\r`; the /capture handler streams
        // them concatenated so a raw body has `\r` between lines. Live WS
        // frames become `\r\n` when written (see onCaptureLine). Downstream
        // `scripts/capture.py --stdin` uses `sys.stdin.buffer.readline()`
        // in binary mode which only splits on `\n` — a mixed file would
        // read as one giant line and drop most frames. Normalize here so
        // every line on disk ends `\r\n` regardless of source path.
        pendingWrites.push(body.replace(/\r(?!\n)/g, "\r\n"));
        // Advance lastPersistedTs to the newest line's ts.
        const lines = body.split(/\r\n|\r|\n/);
        for (let i = lines.length - 1; i >= 0; i--) {
          const m = lines[i].match(TS_PREFIX_RE);
          if (m) {
            const ts = Number(m[1]) * 1000000 + Number(m[2]);
            if (ts > lastPersistedTs) lastPersistedTs = ts;
            captureFrames++;
            break;
          }
        }
        // Approximate frame count for anything the ring returned (excluding
        // the # GAP line). Iterating every line above just to bump the counter
        // matches what onCaptureLine would have done — cheaper to estimate.
        captureFrames += Math.max(0, lines.filter(l => l.startsWith("(")).length - 1);
      }
      await flushBatch();
      // Drain buffered live frames; drop anything backfill already covered.
      for (const item of resumeBuffer) {
        if (item.ts !== null && item.ts <= lastPersistedTs) continue;
        pendingWrites.push(item.raw + "\r\n");
        captureFrames++;
        if (item.ts !== null) lastPersistedTs = Math.max(lastPersistedTs, item.ts);
      }
      resumeBuffer = [];
      await flushBatch();
    } catch (e) {
      console.error("backfill failed", e);
      // Salvage: dump the buffered frames verbatim (they may double-write a
      // few but that's better than losing them) then resume.
      for (const item of resumeBuffer) {
        pendingWrites.push(item.raw + "\r\n");
        captureFrames++;
      }
      resumeBuffer = [];
      await flushBatch();
    }
    // If stopCapture flipped us to idle while backfill was awaiting the
    // fetch, honor that — otherwise we'd un-stop the capture from under
    // the user (frames would resume being written to a "closed" file).
    if (captureState !== "resuming") return;
    captureState = "recording";
    renderCaptureBar();
    scheduleFlush();
  }

  // Detect iOS Safari not-in-standalone. Only affects the A2HS hint's
  // visibility — capture itself works either way, iOS just evicts site
  // storage aggressively if the page isn't installed.
  function maybeShowA2HS() {
    const ua = navigator.userAgent;
    const isIOS = /iPad|iPhone|iPod/.test(ua) || (ua.includes("Mac") && "ontouchend" in document);
    const isStandalone = navigator.standalone === true
        || window.matchMedia("(display-mode: standalone)").matches;
    const dismissed = (() => { try { return localStorage.getItem("a2hsDismissed") === "1"; } catch { return false; } })();
    if (isIOS && !isStandalone && !dismissed) {
      $a2hsHint.classList.add("show");
    }
  }

  // -------------------------------------------------------------------------
  // Captures drawer — browse / re-export / delete captures.
  //
  // Trigger: the "Files (N)" button in the capture bar (visible when N > 0).
  // Fixes the orphaned-files problem the rider view had — captures piled up
  // in storage with no UI, and Export only pointed at the most recent. The
  // drawer surfaces the full list with per-row Export + inline-confirm Delete.
  // -------------------------------------------------------------------------

  async function listCaptureFiles() {
    const db = await openDb();
    const txn = db.transaction(IDB_CAPTURES, "readonly");
    const all = await pReq(txn.objectStore(IDB_CAPTURES).getAll());
    const items = all
      .filter(it => it && it.name && it.name.startsWith("capture-") && it.name.endsWith(".log"))
      .map(it => ({
        name: it.name,
        size: it.size || 0,
        iso: it.iso || (parseCaptureName(it.name) || {}).iso || it.name,
        label: it.label || "",
      }));
    // Newest first — captureFileName sorts by ISO string lexicographically.
    items.sort((a, b) => (b.iso > a.iso ? 1 : b.iso < a.iso ? -1 : 0));
    return items;
  }

  async function refreshCaptureCount() {
    try {
      const items = await listCaptureFiles();
      captureFileCount = items.length;
    } catch { captureFileCount = 0; }
    renderCaptureBar();
  }

  async function exportCaptureFile(name, iso, label) {
    try {
      const blob = await readCaptureBlob(name);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = downloadNameFor(iso, label, "")
        // Strip a trailing `-` that downloadNameFor leaves when frames === "".
        .replace(/-\.log$/, ".log");
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) {
      alert("Export failed: " + e.message);
    }
  }

  async function deleteCaptureFile(name) {
    try {
      const db = await openDb();
      const txn = db.transaction([IDB_CAPTURES, IDB_CHUNKS], "readwrite");
      txn.objectStore(IDB_CAPTURES).delete(name);
      txn.objectStore(IDB_CHUNKS).delete(chunkRangeFor(name));
      await pTxn(txn);
      // If we just deleted the capture the sidecar / Export button points at,
      // clear that state too so the user doesn't tap Export into thin air.
      if (captureFileName === name && captureState === "idle") {
        captureFileName = null;
        captureStartIso = null;
        captureLabel = "";
        captureFrames = 0;
        captureGaps = 0;
        await clearSidecar();
      }
    } catch (e) {
      alert("Delete failed: " + e.message);
    }
  }

  function renderDrawerList(items) {
    $drawerList.innerHTML = "";
    $drawerCount.textContent = items.length === 0
      ? ""
      : `${items.length} ${items.length === 1 ? "file" : "files"}`;
    if (items.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No captures yet.";
      $drawerList.appendChild(empty);
      return;
    }
    for (const it of items) {
      const row = document.createElement("div");
      row.className = "row";
      const isActive = captureState !== "idle" && it.name === captureFileName;
      if (isActive) row.classList.add("active");

      const info = document.createElement("div");
      info.className = "info";
      const nm = document.createElement("div");
      nm.className = "name";
      if (it.label) {
        const lbl = document.createElement("span");
        lbl.className = "lbl";
        lbl.textContent = it.label;
        nm.appendChild(lbl);
        nm.appendChild(document.createTextNode(" · " + fmtDateFromIso(it.iso)));
      } else {
        nm.textContent = fmtDateFromIso(it.iso);
      }
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = fmtSize(it.size);
      if (isActive) {
        const tag = document.createElement("span");
        tag.className = "rec-tag";
        tag.textContent = "recording";
        meta.appendChild(tag);
      }
      info.appendChild(nm); info.appendChild(meta);

      const actions = document.createElement("div");
      actions.className = "actions";
      const exportBtn = document.createElement("button");
      exportBtn.type = "button";
      exportBtn.className = "export";
      exportBtn.textContent = "Export";
      exportBtn.addEventListener("click", async () => {
        await exportCaptureFile(it.name, it.iso, it.label);
      });
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "del";
      delBtn.textContent = "Delete";
      delBtn.disabled = isActive;
      // Two-tap inline confirmation: first tap arms the button (red fill),
      // second tap within 3 s actually deletes; anything else reverts.
      let armedTimer = null;
      delBtn.addEventListener("click", async () => {
        if (delBtn.classList.contains("confirm")) {
          clearTimeout(armedTimer);
          await deleteCaptureFile(it.name);
          await openDrawer();  // re-render
          await refreshCaptureCount();
        } else {
          delBtn.classList.add("confirm");
          delBtn.textContent = "Confirm?";
          armedTimer = setTimeout(() => {
            delBtn.classList.remove("confirm");
            delBtn.textContent = "Delete";
          }, 3000);
        }
      });
      actions.appendChild(exportBtn);
      actions.appendChild(delBtn);

      row.appendChild(info); row.appendChild(actions);
      $drawerList.appendChild(row);
    }
  }

  async function openDrawer() {
    try {
      const items = await listCaptureFiles();
      renderDrawerList(items);
    } catch (e) {
      renderDrawerList([]);
    }
    $drawer.classList.add("show");
    $drawerBackdrop.classList.add("show");
  }
  function closeDrawer() {
    $drawer.classList.remove("show");
    $drawerBackdrop.classList.remove("show");
  }

  $captureBtn.addEventListener("click", () => {
    if (captureState === "idle") { startCapture(); }
    else if (captureState === "recording") { stopCapture(); }
  });
  $exportBtn.addEventListener("click", exportCapture);
  $filesBtn.addEventListener("click", openDrawer);
  $drawerClose.addEventListener("click", closeDrawer);
  $drawerBackdrop.addEventListener("click", closeDrawer);
  // Enter in the label input starts the capture — matches the "type label,
  // tap Start" flow without needing the tap.
  $labelIn.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && captureState === "idle") {
      ev.preventDefault();
      startCapture();
    }
  });
  $a2hsDismiss.addEventListener("click", () => {
    $a2hsHint.classList.remove("show");
    try { localStorage.setItem("a2hsDismissed", "1"); } catch { /* ignore */ }
  });

  // Resume-in-progress capture on page load if a sidecar survived.
  (async () => {
    const s = await readSidecar();
    if (!s || !s.captureFile) return;
    try {
      const db = await openDb();
      // Fire both reads on their own txns so we don't depend on a single txn
      // staying alive across an await boundary.
      const [meta, chunkCount] = await Promise.all([
        pReq(db.transaction(IDB_CAPTURES, "readonly").objectStore(IDB_CAPTURES).get(s.captureFile)),
        pReq(db.transaction(IDB_CHUNKS, "readonly").objectStore(IDB_CHUNKS).count(chunkRangeFor(s.captureFile))),
      ]);
      if (!meta) throw new Error("captures record missing");
      captureFileName = s.captureFile;
      captureStartIso = s.startIso;
      captureStartWallMs = s.startWallMs || Date.now();
      captureOffset = s.offset || 0;
      captureFrames = s.frames || 0;
      captureGaps = s.gaps || 0;
      lastPersistedTs = s.lastPersistedTs || 0;
      nextSeq = chunkCount;
      // Label is embedded in the filename — recover it so Export gets the
      // right download name after a page reload.
      const parsed = parseCaptureName(s.captureFile);
      captureLabel = parsed ? parsed.label : "";
      // Enter recording so the first ws.onopen (which fires momentarily)
      // triggers a backfill — reload during a disconnect picks up cleanly.
      // hasEverConnected is defined below in the WebSocket section;
      // resumingFromSidecar (assigned via a `let` further down) forces the
      // first onopen to be treated as a reconnect and fire performBackfill.
      captureState = "recording";
      resumingFromSidecar = true;
      await requestWakeLock();
      scheduleFlush();
      renderCaptureBar();
      // Race guard: on a fast LAN the WebSocket handshake can complete
      // before this IIFE's awaits do, in which case ws.onopen already ran
      // with captureState === "idle" and skipped the backfill. If we can
      // see the socket is already open by the time we get here, kick off
      // the backfill ourselves — the gap between last-persisted-ts and
      // reload would otherwise never get spliced from the firmware ring.
      if (ws && ws.readyState === WebSocket.OPEN) {
        resumingFromSidecar = false;
        performBackfill();
      }
    } catch (e) {
      // Sidecar pointed at a capture whose record is gone — clear stale
      // state and let the user start a new capture normally.
      await clearSidecar();
    }
  })();

  // Set by the sidecar-resume path; consumed by ws.onopen to force a backfill
  // on the very first WS connect after a reload. Distinct from
  // hasEverConnected so a fresh Start with lastPersistedTs = 0 doesn't
  // spuriously fetch the whole ring at connect time.
  let resumingFromSidecar = false;

  maybeShowA2HS();
  renderCaptureBar();
  refreshCaptureCount();
  requestAnimationFrame(tickCaptureBar);
