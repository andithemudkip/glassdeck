  const STALE_MS = 500;
  // Liveness pulse: bump on frame arrival, decay ~240 ms via CSS transition.
  const LIVENESS_HOLD_MS = 240;

  const wsPip = document.getElementById("wsPip");
  const wsText = document.getElementById("wsText");
  const $rssi = document.getElementById("rssi");
  const $uptime = document.getElementById("uptime");
  const $twai = document.getElementById("twai");
  const $seen = document.getElementById("seen");
  const $dropped = document.getElementById("dropped");
  const $mid = document.getElementById("mid");
  const $liveness = document.getElementById("liveness");

  let framesSinceConnect = 0;
  let lastHealth = null;
  let lastLivenessBump = 0;

  function fmtUptime(ms) {
    const s = Math.floor(ms / 1000);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const ss = s % 60;
    const pad = n => n < 10 ? "0" + n : "" + n;
    return h > 0 ? `${h}:${pad(m)}:${pad(ss)}` : `${m}:${pad(ss)}`;
  }

  // Bus liveness pulse. Every incoming frame kicks the header's bottom-edge
  // amber line to full opacity; when frames stop, the CSS transition fades
  // it out over LIVENESS_HOLD_MS. Ambient replacement for the raw ticker —
  // proves "frames are streaming" without taking any decoded panel real estate.
  function bumpLiveness() {
    const now = performance.now();
    // Only re-touch the DOM every ~16 ms so a 1000 fps bus doesn't force
    // a style recalc per frame. The CSS transition holds the opacity high
    // between bumps so the visual read stays steady.
    if (now - lastLivenessBump < 16) return;
    lastLivenessBump = now;
    $liveness.style.opacity = "1";
    setTimeout(() => {
      // Only clear if no newer bump has landed — otherwise let the later
      // bump keep it lit.
      if (performance.now() - lastLivenessBump >= LIVENESS_HOLD_MS - 20) {
        $liveness.style.opacity = "0";
      }
    }, LIVENESS_HOLD_MS);
  }
