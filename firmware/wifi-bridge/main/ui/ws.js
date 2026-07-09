  // --- WebSocket ---
  let ws = null;
  let backoffMs = 1000;
  let hasEverConnected = false;
  // Most recent (sec.us) parsed off /stream. Anchors backfill on reconnect.
  let lastFrameTs = 0;

  // Matches ADR 0018's `(<sec>.<us>) ` firmware prefix. Backward-compatible:
  // an unprefixed line (older firmware, or an unprefixed test feed) falls
  // through untouched and lastFrameTs simply doesn't advance.
  const TS_PREFIX_RE = /^\((\d+)\.(\d+)\)\s+/;

  function setWs(state, klass) {
    wsText.textContent = state;
    wsPip.className = "pip " + klass;
  }

  function connect() {
    setWs("connecting", "warn");
    try {
      ws = new WebSocket(`ws://${location.host}/stream`);
    } catch (e) {
      scheduleReconnect();
      return;
    }
    ws.onopen = () => {
      const wasReconnect = hasEverConnected;
      hasEverConnected = true;
      backoffMs = 1000;
      setWs("connected", "ok");
      // Trigger backfill in three cases:
      //   1) real reconnect while recording — normal M4 splice
      //   2) first connect after page reload during a live capture (resumed
      //      from OPFS sidecar; catches whatever the ring covers of the
      //      offline window)
      // Fire-and-forget — performBackfill flips captureState internally,
      // buffers live frames while it runs, and clears itself on error.
      if (captureState === "recording" && (wasReconnect || resumingFromSidecar)) {
        resumingFromSidecar = false;
        performBackfill();
      }
    };
    ws.onmessage = (ev) => {
      let raw = typeof ev.data === "string" ? ev.data : "";
      while (raw.length && (raw.charCodeAt(raw.length - 1) === 13 || raw.charCodeAt(raw.length - 1) === 10)) {
        raw = raw.slice(0, -1);
      }
      if (!raw.length) return;
      framesSinceConnect++;
      bumpLiveness();

      // Strip (sec.us) prefix for the decoded panel; capture pipeline keeps
      // the full raw line so the OPFS file is byte-identical to what
      // GET /capture would return.
      let payload = raw;
      let ts = null;
      const m = raw.match(TS_PREFIX_RE);
      if (m) {
        ts = Number(m[1]) * 1000000 + Number(m[2]);
        lastFrameTs = ts;
        payload = raw.slice(m[0].length);
      }
      onCaptureLine(raw, ts);
      routeFrame(payload);
    };
    ws.onerror = () => { /* onclose will fire */ };
    ws.onclose = () => {
      setWs("disconnected", "err");
      scheduleReconnect();
    };
  }
  function scheduleReconnect() {
    setTimeout(connect, backoffMs);
    backoffMs = Math.min(backoffMs * 2, 5000);
  }

  // --- /health poll ---
  async function pollHealth() {
    try {
      const r = await fetch("/health", { cache: "no-store" });
      if (!r.ok) throw new Error("http " + r.status);
      const j = await r.json();
      lastHealth = j;
      framesSinceConnect = 0;

      if (j.ap_client_rssi_dbm === null || j.ap_client_rssi_dbm === undefined) {
        $rssi.textContent = "—";
        $rssi.className = "v mute";
      } else {
        $rssi.textContent = j.ap_client_rssi_dbm + " dBm";
        $rssi.className = "v";
      }
      $uptime.textContent = fmtUptime(j.uptime_ms || 0);
      $twai.textContent = j.twai_state || "—";
      $twai.className = "v " + (j.twai_state === "running" ? "ok"
                              : j.twai_state === "bus_off" ? "err" : "warn");
      $seen.textContent = (j.frames_seen || 0).toLocaleString();
      const dropped = j.frames_ws_dropped || 0;
      $dropped.textContent = dropped.toLocaleString();
      $dropped.className = "v " + (dropped > 0 ? "warn" : "");
    } catch (e) {
      $rssi.className = $uptime.className = $twai.className = "v mute";
    }
  }

  function tickLocal() {
    if (lastHealth) {
      const est = (lastHealth.frames_seen || 0) + framesSinceConnect;
      $seen.textContent = est.toLocaleString();
    }
    requestAnimationFrame(tickLocal);
  }
