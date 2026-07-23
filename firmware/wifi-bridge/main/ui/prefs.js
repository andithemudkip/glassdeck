  // Live-view customization prefs: hidden signal names + user-defined order.
  // Persisted to localStorage; per-browser. Corrupt/absent → defaults, no crash.
  const LIVE_PREFS_KEY = "liveViewPrefs";
  const livePrefs = { hidden: new Set(), order: [] };
  (function loadLivePrefs() {
    try {
      const raw = localStorage.getItem(LIVE_PREFS_KEY);
      if (!raw) return;
      const obj = JSON.parse(raw);
      if (Array.isArray(obj.hidden)) livePrefs.hidden = new Set(obj.hidden);
      if (Array.isArray(obj.order)) livePrefs.order = obj.order.filter(n => typeof n === "string");
    } catch { /* keep defaults */ }
  })();
  function savePrefs() {
    try {
      localStorage.setItem(LIVE_PREFS_KEY, JSON.stringify({
        hidden: [...livePrefs.hidden],
        order: livePrefs.order,
      }));
    } catch { /* ignore quota / private mode */ }
  }
  function resetPrefs() {
    livePrefs.hidden.clear();
    livePrefs.order = [];
    try { localStorage.removeItem(LIVE_PREFS_KEY); } catch { /* ignore */ }
  }
