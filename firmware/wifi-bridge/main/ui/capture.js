  // -------------------------------------------------------------------------
  // Capture pipeline (M4 / ADR 0018)
  //
  // Browser-primary log sink. The WS handler feeds every raw (prefix-included)
  // line into onCaptureLine; when a capture is active they get batched into an
  // OPFS file every FLUSH_INTERVAL_MS. On WS reconnect performBackfill drains
  // the firmware's /capture ring to splice over the gap; an X-Bike-Gap-Ms
  // header from the firmware translates to a `# GAP <ms>` marker in the file
  // (same comment convention as `# MARK` — see M7a).
  //
  // State discipline: lastPersistedTs is the only piece of "resume anywhere"
  // state, snapshotted to a sidecar OPFS key on every flush so a page reload
  // during a capture picks up cleanly.
  // -------------------------------------------------------------------------

  const SIDECAR_NAME = "active-capture.json";
  const FLUSH_INTERVAL_MS = 500;

  // idle → recording → resuming → recording; back to idle on Stop/Export.
  let captureState = "idle";
  let captureFile = null;        // FileSystemFileHandle (OPFS)
  let captureFileName = null;
  let captureStartIso = null;    // ISO string embedded in the exported filename
  let captureStartWallMs = 0;    // Date.now() — persists across reloads for the elapsed counter
  let captureLabel = "";         // sanitized user-supplied label, "" if none
  let captureOffset = 0;
  let captureFrames = 0;
  let captureGaps = 0;
  let lastPersistedTs = 0;
  let pendingWrites = [];        // string[] queued for the next flush
  let resumeBuffer = [];         // {raw, ts}[] captured during a reconnect
  let flushScheduled = false;
  let wakeLockRef = null;

  // Filename convention (encoded in the OPFS filename so it survives reloads
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

  // Cached count of captures in OPFS, refreshed after Stop / delete / start.
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

  // OPFS may not exist in older browsers or private-mode Safari. If so we
  // gracefully disable capture — the live view still works.
  async function opfsRoot() {
    if (!navigator.storage || !navigator.storage.getDirectory) {
      throw new Error("OPFS not available in this browser");
    }
    return navigator.storage.getDirectory();
  }

  async function writeSidecar() {
    try {
      const root = await opfsRoot();
      const handle = await root.getFileHandle(SIDECAR_NAME, { create: true });
      const w = await handle.createWritable({ keepExistingData: false });
      const payload = JSON.stringify({
        captureFile: captureFileName,
        startIso: captureStartIso,
        startWallMs: captureStartWallMs,
        offset: captureOffset,
        lastPersistedTs: lastPersistedTs,
        frames: captureFrames,
        gaps: captureGaps,
      });
      await w.write(payload);
      await w.close();
    } catch (e) {
      // Sidecar failures aren't fatal — the file itself is still being
      // written. Resume-across-reload just won't work this session.
      console.warn("sidecar write failed", e);
    }
  }

  async function clearSidecar() {
    try {
      const root = await opfsRoot();
      await root.removeEntry(SIDECAR_NAME).catch(() => {});
    } catch (e) { /* ignore */ }
  }

  async function readSidecar() {
    try {
      const root = await opfsRoot();
      const handle = await root.getFileHandle(SIDECAR_NAME);
      const file = await handle.getFile();
      return JSON.parse(await file.text());
    } catch (e) {
      return null;
    }
  }

  // One open/write/close cycle per flush. FileSystemWritableFileStream only
  // commits on close(), so long-lived writables don't actually persist —
  // batching is the correct shape here.
  async function flushBatch() {
    if (!captureFile || pendingWrites.length === 0) return;
    const batch = pendingWrites.join("");
    pendingWrites = [];
    const chunk = new TextEncoder().encode(batch);
    try {
      const w = await captureFile.createWritable({ keepExistingData: true });
      await w.seek(captureOffset);
      await w.write(chunk);
      await w.close();
      captureOffset += chunk.byteLength;
      await writeSidecar();
      renderCaptureBar();
    } catch (e) {
      // Requeue the batch so the next flush retries. Don't dedupe — a
      // half-succeeded write would already have advanced captureOffset.
      pendingWrites.unshift(batch);
      console.error("OPFS flush failed", e);
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

  async function requestWakeLock() {
    if (!("wakeLock" in navigator)) return;
    try {
      wakeLockRef = await navigator.wakeLock.request("screen");
      wakeLockRef.addEventListener("release", () => { wakeLockRef = null; });
    } catch (e) { /* denied — non-fatal, capture continues */ }
  }

  function releaseWakeLock() {
    if (wakeLockRef) {
      try { wakeLockRef.release(); } catch (e) { /* ignore */ }
    }
    wakeLockRef = null;
  }

  // Reacquire wake-lock when the page comes back to the foreground — iOS
  // Safari drops it aggressively on tab switch.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible"
        && captureState !== "idle" && !wakeLockRef) {
      requestWakeLock();
    }
  });

  async function startCapture() {
    if (captureState !== "idle") return;
    let root;
    try { root = await opfsRoot(); }
    catch (e) {
      alert("This browser doesn't support OPFS — capture unavailable.");
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
    lastPersistedTs = 0;
    pendingWrites = [];
    resumeBuffer = [];
    try {
      captureFile = await root.getFileHandle(captureFileName, { create: true });
      // Truncate any prior contents (shouldn't exist under this filename, but
      // paranoid — an ISO-second collision would otherwise silently append).
      const w = await captureFile.createWritable({ keepExistingData: false });
      await w.close();
    } catch (e) {
      alert("Failed to create capture file: " + e.message);
      captureFile = null;
      captureFileName = null;
      return;
    }
    // Chrome / Android — makes OPFS survive storage pressure. iOS ignores.
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
    // Drain anything still in memory before flipping state — flushBatch is a
    // no-op once captureState flips because it wraps createWritable in a
    // captureFile guard.
    await flushBatch();
    captureState = "idle";
    releaseWakeLock();
    renderCaptureBar();
  }

  // Build a download filename from a parsed capture: label sits between the
  // ISO and the frame-count so downloads sort by date but read by intent.
  function downloadNameFor(iso, label, frames) {
    const lbl = label ? `-${label}` : "";
    return `capture-${iso}${lbl}-${frames}.log`;
  }

  async function exportCapture() {
    if (captureState !== "idle") {
      await stopCapture();
    }
    if (!captureFile) return;
    let file;
    try { file = await captureFile.getFile(); }
    catch (e) {
      alert("Failed to open capture file for export: " + e.message);
      return;
    }
    const url = URL.createObjectURL(file);
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
        // frames become `\r\n` on OPFS write (see onCaptureLine). Downstream
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
    captureState = "recording";
    renderCaptureBar();
    scheduleFlush();
  }

  // Detect iOS Safari not-in-standalone. Only affects the A2HS hint's
  // visibility — capture itself works either way, iOS just evicts OPFS
  // after 7 days if the page isn't installed.
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
  // Captures drawer — browse / re-export / delete files in OPFS.
  //
  // Trigger: the "Files (N)" button in the capture bar (visible when N > 0).
  // Fixes the orphaned-files problem the rider view had — captures piled up
  // in OPFS with no UI, and Export only pointed at the most recent. The
  // drawer surfaces the full list with per-row Export + inline-confirm Delete.
  // -------------------------------------------------------------------------

  async function listCaptureFiles() {
    const root = await opfsRoot();
    const items = [];
    // AsyncIterator over root's entries. Chrome / Android / iOS 17.4+ all
    // support this.
    // @ts-ignore (values is on FileSystemDirectoryHandle)
    for await (const [name, handle] of root.entries()) {
      if (handle.kind !== "file") continue;
      if (!name.startsWith("capture-") || !name.endsWith(".log")) continue;
      let size = 0;
      try { size = (await handle.getFile()).size; } catch { /* ignore */ }
      const parsed = parseCaptureName(name) || { iso: name, label: "" };
      items.push({ name, size, iso: parsed.iso, label: parsed.label });
    }
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
      const root = await opfsRoot();
      const handle = await root.getFileHandle(name);
      const file = await handle.getFile();
      // Frame count isn't tracked per historical file; count via a cheap
      // pass over the text. For a fresh capture we already know frames
      // and pass it via the current-capture Export button.
      // Best-effort: sample the file to estimate, but we don't need it in
      // the filename for the drawer path — use size and let the user rename.
      const url = URL.createObjectURL(file);
      const a = document.createElement("a");
      a.href = url;
      a.download = downloadNameFor(iso, label, "");
      // Strip a trailing `-` that downloadNameFor leaves when frames === "".
      a.download = a.download.replace(/-\.log$/, ".log");
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
      const root = await opfsRoot();
      await root.removeEntry(name);
      // If we just deleted the file the sidecar / Export button points at,
      // clear that state too so the user doesn't tap Export into a stale
      // handle.
      if (captureFileName === name && captureState === "idle") {
        captureFile = null;
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
      const root = await opfsRoot();
      const handle = await root.getFileHandle(s.captureFile);
      captureFile = handle;
      captureFileName = s.captureFile;
      captureStartIso = s.startIso;
      captureStartWallMs = s.startWallMs || Date.now();
      captureOffset = s.offset || 0;
      captureFrames = s.frames || 0;
      captureGaps = s.gaps || 0;
      lastPersistedTs = s.lastPersistedTs || 0;
      // Label is embedded in the filename — recover it so Export gets the
      // right download name after a page reload.
      const parsed = parseCaptureName(s.captureFile);
      captureLabel = parsed ? parsed.label : "";
      // Enter recording so the first ws.onopen (which fires momentarily)
      // triggers a backfill — reload during a disconnect picks up cleanly.
      // Also mark hasEverConnected so that first onopen is treated as a
      // reconnect and fires performBackfill. hasEverConnected is defined
      // below in the WebSocket section; assign via globalThis to avoid a
      // TDZ hazard if this async block resolves before the WS block runs.
      captureState = "recording";
      resumingFromSidecar = true;
      await requestWakeLock();
      scheduleFlush();
      renderCaptureBar();
    } catch (e) {
      // Sidecar pointed at a file that's gone — clear stale state and let
      // the user start a new capture normally.
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
