  // -------------------------------------------------------------------------
  // Decoded panel — the M6 addition. SIGNALS is codegen'd from signals.yaml.
  // -------------------------------------------------------------------------

  /* __SIGNALS_JS__ */

  // Order signals for the panel: rider-relevance first, then diagnostic.
  // Any signal in the codegen output that isn't listed here appears after.
  const DISPLAY_ORDER = [
    "rpm", "gear_position", "wheel_speed_rear", "wheel_speed_front",
    "throttle_position", "engine_torque", "coolant_temp", "fuel_injection_setpoint",
    "kill_switch", "side_stand", "abs_lamp",
    "clutch", "shift_cut_active", "shift_blip_active", "shift_failed",
    "engine_on_counter", "engine_off_counter",
  ];
  const LABEL = {
    rpm: "RPM",
    gear_position: "GEAR",
    wheel_speed_rear: "SPEED",
    wheel_speed_front: "WHEEL F",
    throttle_position: "THROTTLE",
    engine_torque: "TORQUE",
    coolant_temp: "COOLANT",
    fuel_injection_setpoint: "FUEL SP",
    kill_switch: "KILL",
    side_stand: "STAND",
    abs_lamp: "ABS",
    clutch: "CLUTCH",
    shift_cut_active: "QS CUT",
    shift_blip_active: "QS BLIP",
    shift_failed: "QS ERR",
    engine_on_counter: "ENG-ON",
    engine_off_counter: "ENG-OFF",
    rear_speed_band: "SPEED BAND R",
    time_bin_541_d3: "541 BIN",
    signal_12a_d1_bit2: "12A.D1.2",
  };
  // Discrete label → colour polarity. OK = green (nominal steady state), ERR
  // = red (warning / fault), ACTIVE = amber (transient event, no fault —
  // e.g. quickshifter cutting ignition mid-shift is normal, not a warning).
  // Case-sensitive; matches the exact strings in signals.yaml `values:`.
  //
  // Note the deliberate asymmetry between "OFF" (abs_lamp, uppercase) → OK
  // and "off" (shift_cut/blip, lowercase) → NOT ok. `abs_lamp OFF` is an
  // actively-verified-good state ("self-test passed"). QS `off` is just "not
  // currently firing" — an event-only signal is at rest most of the time,
  // and painting that green makes the amber flash it produces harder to
  // spot against a wall of steady green dots.
  const OK_VALUES     = new Set(["RUN", "UP", "RELEASED", "OFF"]);
  const ERR_VALUES    = new Set(["STOP", "DOWN", "PULLED", "LIT", "FAILED"]);
  const ACTIVE_VALUES = new Set(["cut", "blip"]);
  // How long to hold a transient "active" or "err" flash for visibility.
  // QS cuts run 20–200 ms; shift_failed is a rare 1.5-s-latency FAILED
  // pulse. 300 ms is long enough to catch a single event at a glance,
  // short enough that back-to-back downshifts don't smear into one flash.
  // Latching signals (ABS LIT, KILL STOP) re-trigger every broadcast so
  // the hold is transparent on them.
  const HOLD_MS = 300;

  // Compact location: "120 D0:D1" style. Dev-instrument diagnostic —
  // must fit in the meta row without ellipsis on the smallest supported
  // cell (170 px). The 0x prefix is dropped; 3-hex-digit arb IDs are
  // recognizable as such by any reader who cares about them.
  function locStr(sig) {
    const arb = sig.arb.toString(16).toUpperCase().padStart(3, "0");
    if (sig.bytes) {
      const bl = sig.bytes.map(b => "D" + b).join(":");
      if (sig.bit_length !== 8 * sig.bytes.length) {
        return `${arb} ${bl} b${sig.bit_offset}+${sig.bit_length}`;
      }
      return `${arb} ${bl}`;
    }
    if (sig.bit_length === 1) return `${arb} D${sig.byte}.${sig.bit_offset}`;
    if (sig.bit_length === 4) return `${arb} D${sig.byte} ${sig.bit_offset === 4 ? "hi" : "lo"}`;
    if (sig.bit_length === 8 && sig.bit_offset === 0) return `${arb} D${sig.byte}`;
    return `${arb} D${sig.byte} b${sig.bit_offset}+${sig.bit_length}`;
  }

  // Port of scripts/signals.py Signal._extract_raw. Returns int (raw) or null.
  // For enc == "sint", two's-complement sign-extends before returning.
  function extractRaw(sig, data) {
    let value;
    if (sig.bytes) {
      for (const b of sig.bytes) if (b >= data.length) return null;
      const order = sig.order === "big" ? sig.bytes : sig.bytes.slice().reverse();
      value = 0;
      for (const b of order) value = (value << 8) | data[b];
      const fullSlot = sig.bit_length === 8 * sig.bytes.length;
      if (!fullSlot || sig.bit_offset !== 0) {
        const mask = (1 << sig.bit_length) - 1;
        // >>> 0 for correct behavior with 16-bit+ values on the boundary
        // where <<16 would go negative in JS's signed 32-bit int semantics.
        value = ((value >>> sig.bit_offset) & mask) >>> 0;
      } else {
        // Full-slot uint16+: coerce back to unsigned in case the shift chain
        // produced a negative int (JS bitwise ops are signed 32-bit).
        value = value >>> 0;
      }
    } else {
      if (sig.byte >= data.length) return null;
      const mask = (1 << sig.bit_length) - 1;
      value = (data[sig.byte] >> sig.bit_offset) & mask;
    }
    if (sig.enc === "sint") {
      // Two's-complement sign-extend. 2**N instead of (1 << N) so this stays
      // correct past 31 bits — JS bitshifts operate on 32-bit signed ints.
      const range = 2 ** sig.bit_length;
      const signBit = range / 2;
      if (value >= signBit) value -= range;
    }
    return value;
  }

  function scaled(sig, raw) {
    return raw * sig.scale + sig.offset;
  }

  function formatValue(sig, raw) {
    // Match scripts/signals.py Signal.extract/format semantics.
    if ((sig.enc === "bool" || sig.enc === "enum") && sig.values) {
      return sig.values[String(raw)] ?? String(raw);
    }
    const v = scaled(sig, raw);
    // One decimal for scale<1 (coolant, wheel speeds), integer otherwise.
    return sig.scale < 1 ? v.toFixed(1) : Math.round(v).toString();
  }

  function isDiscrete(sig) {
    return sig.enc === "bool" || sig.enc === "enum";
  }

  const HISTORY_LEN = 60;

  // Pick which band tint applies to a scaled value. Priority: danger > warn
  // > cold > accent > null. `accent_above` is a goal-hit hue (WOT), not a
  // warning — dropped below warn so it never masks an over-limit reading.
  function pickBand(sig, scaledValue) {
    const b = sig.bands;
    if (!b) return null;
    if (b.danger_above !== undefined && scaledValue > b.danger_above) return "danger";
    if (b.warn_above   !== undefined && scaledValue > b.warn_above)   return "warn";
    if (b.cold_below   !== undefined && scaledValue < b.cold_below)   return "cold";
    if (b.accent_above !== undefined && scaledValue > b.accent_above) return "accent";
    return null;
  }

  // Build DOM + per-signal state.
  const byArb = new Map();
  const state = new Map();

  function makeCell(sig) {
    const div = document.createElement("div");
    div.className = "sig empty";
    div.dataset.name = sig.name;
    const meta = document.createElement("div");
    meta.className = "meta";
    const grip = document.createElement("span");
    grip.className = "grip";
    grip.textContent = "⋮⋮";
    grip.setAttribute("aria-hidden", "true");
    const nameEl = document.createElement("span");
    nameEl.className = "name";
    nameEl.textContent = LABEL[sig.name] ?? sig.name;
    let provEl = null;
    if (sig.status && sig.status !== "confirmed") {
      div.classList.add("provisional");
      provEl = document.createElement("span");
      provEl.className = "prov";
      provEl.textContent = "?";
      provEl.title = "Provisional — decoding not fully verified (see docs/findings/can/" + sig.name.replace(/_/g, "-") + ".md)";
    }
    const locEl = document.createElement("span");
    locEl.className = "loc";
    locEl.textContent = locStr(sig);
    const hideBtn = document.createElement("button");
    hideBtn.className = "hide-btn";
    hideBtn.type = "button";
    hideBtn.title = "Hide";
    hideBtn.setAttribute("aria-label", "Hide " + (LABEL[sig.name] ?? sig.name));
    hideBtn.textContent = "×";
    meta.appendChild(grip);
    meta.appendChild(nameEl);
    if (provEl) meta.appendChild(provEl);
    meta.appendChild(locEl);
    meta.appendChild(hideBtn);
    const row = document.createElement("div");
    row.className = "row";
    const val = document.createElement("span");
    val.className = "val";
    val.textContent = "—";
    row.appendChild(val);
    if (sig.unit) {
      const unit = document.createElement("span");
      unit.className = "unit";
      unit.textContent = sig.unit;
      row.appendChild(unit);
    }
    const peak = document.createElement("button");
    peak.className = "peak";
    peak.type = "button";
    peak.title = "Reset peak";
    peak.textContent = "";
    row.appendChild(peak);
    const fresh = document.createElement("div");
    fresh.className = "fresh";
    div.appendChild(meta); div.appendChild(row); div.appendChild(fresh);
    // Sparkline canvas: scalars only. The CSS positions it (behind .val in
    // Diagnostic, below the row in Ride) so nothing here cares about layout.
    let canvas = null, ctx = null;
    if (!isDiscrete(sig)) {
      canvas = document.createElement("canvas");
      canvas.className = "spark";
      canvas.width = 240; canvas.height = 40;   // CSS scales; keep backing store crisp.
      div.appendChild(canvas);
      ctx = canvas.getContext("2d");
    }
    return { div, val, peak, fresh, grip, hideBtn, canvas, ctx };
  }

  // Default order (codegen + hardcoded priority) — used on first load and Reset.
  const known = new Set(SIGNALS.map(s => s.name));
  const defaultOrder = [
    ...DISPLAY_ORDER.filter(n => known.has(n)),
    ...SIGNALS.map(s => s.name).filter(n => !DISPLAY_ORDER.includes(n)),
  ];
  const bySigName = new Map(SIGNALS.map(s => [s.name, s]));

  // Effective order = saved order (filtered to still-existing signals),
  // then any codegen signals not in the saved order. Newly-added signals
  // always appear at the end and default to visible.
  function effectiveOrder() {
    const seen = new Set();
    const out = [];
    for (const n of livePrefs.order) {
      if (known.has(n) && !seen.has(n)) { out.push(n); seen.add(n); }
    }
    for (const n of defaultOrder) {
      if (!seen.has(n)) { out.push(n); seen.add(n); }
    }
    return out;
  }

  for (const name of effectiveOrder()) {
    const sig = bySigName.get(name);
    const nodes = makeCell(sig);
    if (livePrefs.hidden.has(name)) nodes.div.classList.add("hidden");
    $mid.appendChild(nodes.div);
    state.set(name, {
      sig, nodes,
      lastUpdate: 0,       // performance.now() timestamp
      peakRaw: null,       // max raw value seen, null for discrete
      pulseUntil: 0,
      // Sparkline ring buffer — scalars only; unused for discretes.
      history: isDiscrete(sig) ? null : new Float32Array(HISTORY_LEN),
      histIdx: 0,
      histFilled: 0,
      histMin: Infinity, histMax: -Infinity, histDirty: false,
      currentBand: null,   // "cold" | "accent" | "warn" | "danger" | null
    });
    if (!byArb.has(sig.arb)) byArb.set(sig.arb, []);
    byArb.get(sig.arb).push(sig);
  }

  // Hero styling (2-column span at ≥720px, larger digits) follows position:
  // the first visible cell in DOM order wins. Called on boot and after every
  // hide / unhide / reorder.
  function applyHero() {
    let assigned = false;
    for (const el of $mid.children) {
      if (!assigned && !el.classList.contains("hidden")) {
        el.classList.add("hero");
        assigned = true;
      } else {
        el.classList.remove("hero");
      }
    }
  }
  applyHero();

  // SLCAN parse: 't' + 3hex arb + 1hex dlc + (dlc*2 hex) + '\r' (already stripped).
  function parseSlcan(line) {
    if (line.length < 5 || line[0] !== "t") return null;
    const arb = parseInt(line.substring(1, 4), 16);
    if (!Number.isFinite(arb)) return null;
    const dlc = parseInt(line[4], 16);
    if (!Number.isFinite(dlc)) return null;
    const n = Math.min(dlc, 8);
    if (line.length < 5 + n * 2) return null;
    const data = new Uint8Array(n);
    for (let i = 0; i < n; i++) {
      data[i] = parseInt(line.substring(5 + i * 2, 7 + i * 2), 16);
    }
    return { arb, data };
  }

  function routeFrame(line) {
    const p = parseSlcan(line);
    if (!p) return;
    const sigs = byArb.get(p.arb);
    if (!sigs) return;
    const now = performance.now();
    for (const sig of sigs) {
      const raw = extractRaw(sig, p.data);
      if (raw === null) continue;
      const st = state.get(sig.name);
      st.lastUpdate = now;
      st.pulseUntil = now + 150;
      st.nodes.val.textContent = formatValue(sig, raw);
      if (st.nodes.div.classList.contains("empty")) {
        st.nodes.div.classList.remove("empty");
      }
      // Enum/bool color polarity.
      if (isDiscrete(sig) && sig.values) {
        const label = sig.values[String(raw)];
        st.nodes.val.classList.toggle("enum-ok",     OK_VALUES.has(label));
        st.nodes.val.classList.toggle("enum-err",    ERR_VALUES.has(label));
        st.nodes.val.classList.toggle("enum-active", ACTIVE_VALUES.has(label));
      }
      // Scalars: sparkline ring buffer, threshold band, peak.
      if (!isDiscrete(sig)) {
        const v = scaled(sig, raw);
        st.history[st.histIdx] = v;
        st.histIdx = (st.histIdx + 1) % HISTORY_LEN;
        if (st.histFilled < HISTORY_LEN) st.histFilled++;
        st.histDirty = true;

        const band = pickBand(sig, v);
        if (band !== st.currentBand) {
          // Clear the four possibilities and re-apply the active one; only
          // paying the classList cost on transitions keeps this cheap under
          // 100 Hz signals.
          const cls = st.nodes.val.classList;
          cls.remove("band-cold", "band-accent", "band-warn", "band-danger");
          if (band) cls.add("band-" + band);
          st.currentBand = band;
        }

        if (st.peakRaw === null || raw > st.peakRaw) {
          st.peakRaw = raw;
          const peakStr = formatValue(sig, raw);
          st.nodes.peak.textContent = "▲ " + peakStr;
        }
      }
      // Discrete → warning-strip dot; declared later in this module.
      if (isDiscrete(sig)) updateWarnDot(sig, raw, now);
    }
  }

  // Shared RAF tick: pulse decay + freshness bar + stale fade + sparkline
  // redraw + warn-strip stale.
  function panelTick() {
    const now = performance.now();
    for (const st of state.values()) {
      const dt = now - st.lastUpdate;
      // Pulse: brief amber flash on update, then off.
      if (now < st.pulseUntil) st.nodes.val.classList.add("pulse");
      else st.nodes.val.classList.remove("pulse");
      // Freshness bar decays from 100% at t=0 to 0% at t=STALE_MS.
      if (st.lastUpdate === 0) {
        st.nodes.fresh.style.width = "0%";
        st.nodes.val.classList.remove("stale");
      } else if (dt >= STALE_MS) {
        st.nodes.fresh.style.width = "0%";
        st.nodes.val.classList.add("stale");
      } else {
        const pct = 100 * (1 - dt / STALE_MS);
        st.nodes.fresh.style.width = pct.toFixed(1) + "%";
        st.nodes.val.classList.remove("stale");
      }
      // Sparkline: redraw only when new data landed and the cell is visible.
      // getBoundingClientRect gate would be more precise but costs a
      // reflow — the .hidden class check catches the common cases (Edit
      // hides + Ride-mode data-tier hides).
      if (st.histDirty && st.nodes.canvas && !st.nodes.div.classList.contains("hidden")) {
        drawSpark(st);
        st.histDirty = false;
      }
    }
    tickWarnStrip(now);
    requestAnimationFrame(panelTick);
  }

  function drawSpark(st) {
    const { canvas, ctx } = st.nodes;
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    if (st.histFilled < 2) return;
    // Recompute min/max over the filled window each frame. Cheap for
    // HISTORY_LEN=60; avoids drift from an incremental tracker on evict.
    let min = Infinity, max = -Infinity;
    for (let i = 0; i < st.histFilled; i++) {
      const v = st.history[i];
      if (v < min) min = v;
      if (v > max) max = v;
    }
    if (min === max) {
      // Flat line — render as a mid-height stroke so the cell doesn't blink
      // between "empty" and "signal present".
      ctx.strokeStyle = "#f1b500";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, h / 2);
      ctx.lineTo(w, h / 2);
      ctx.stroke();
      return;
    }
    const range = max - min;
    const pad = 2;
    const usableH = h - 2 * pad;
    const start = st.histFilled === HISTORY_LEN ? st.histIdx : 0;
    const step = w / (st.histFilled - 1);
    ctx.strokeStyle = "#f1b500";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < st.histFilled; i++) {
      const idx = (start + i) % HISTORY_LEN;
      const v = st.history[idx];
      const x = i * step;
      const y = pad + usableH - ((v - min) / range) * usableH;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  // ---------------------------------------------------------------------------
  // Warning strip — one dot per discrete signal, shown above the decoded grid.
  // Piggy-backs on routeFrame (via updateWarnDot) for value → colour, and on
  // panelTick (via tickWarnStrip) for stale-fade + hard-stale outline. SAFETY
  // signals go hard-stale on staleness because "we haven't heard from ABS in
  // 5s" is louder than any specific value it might carry.
  // ---------------------------------------------------------------------------
  const $warnStrip = document.getElementById("warnStrip");
  const SAFETY = new Set(["abs_lamp", "kill_switch", "side_stand", "clutch"]);
  // Discretes to expose on the strip, in visual order. Anything discrete in
  // SIGNALS but not listed here is silently absent — intentional: strip is
  // rider-glance surface, not a debug enumeration.
  const STRIP_ORDER = [
    "kill_switch", "side_stand", "abs_lamp", "clutch",
    "shift_cut_active", "shift_blip_active", "shift_failed",
  ];
  const warnDots = new Map();  // name → { dot, slot, lastUpdate }

  (function buildWarnStrip() {
    for (const name of STRIP_ORDER) {
      const sig = bySigName.get(name);
      if (!sig || !isDiscrete(sig)) continue;
      const slot = document.createElement("div");
      slot.className = "slot";
      slot.dataset.name = name;
      slot.title = LABEL[name] ?? name;
      const dot = document.createElement("div");
      dot.className = "dot";
      if (sig.status && sig.status !== "confirmed") dot.classList.add("provisional");
      const lbl = document.createElement("div");
      lbl.className = "lbl";
      lbl.textContent = LABEL[name] ?? name;
      slot.appendChild(dot);
      slot.appendChild(lbl);
      $warnStrip.appendChild(slot);
      warnDots.set(name, { dot, slot, lastUpdate: 0 });
    }
  })();

  $warnStrip.addEventListener("click", () => {
    $warnStrip.classList.toggle("expanded");
  });

  function updateWarnDot(sig, raw, now) {
    const rec = warnDots.get(sig.name);
    if (!rec) return;
    rec.lastUpdate = now;
    const label = sig.values ? sig.values[String(raw)] : null;
    // Compute this frame's target polarity (may be null).
    let polarity = null;
    if      (label && OK_VALUES.has(label))     polarity = "ok";
    else if (label && ERR_VALUES.has(label))    polarity = "err";
    else if (label && ACTIVE_VALUES.has(label)) polarity = "active";
    // Signals without a values map (e.g. signal_12a_d1_bit2) fall through:
    // truthy raw → amber (transient), no wrong-signal red on unknown labels.
    else if (!label && raw)                     polarity = "active";
    rec.polarity = polarity;
    // Hold transient reds and ambers so a single-frame event stays visible.
    // "ok" doesn't need a hold — its interesting event is the transition
    // *out* of ok, which is what err/active capture.
    if (polarity === "active" || polarity === "err") {
      rec.holdClass = polarity;
      rec.holdUntil = now + HOLD_MS;
    }
    applyDotPolarity(rec, now);
  }

  // Apply the effective polarity: if we're still inside a hold window,
  // keep showing the held class even after the underlying signal reverted.
  // Stale/hard-stale are managed by tickWarnStrip; only touch the polarity
  // classes here.
  function applyDotPolarity(rec, now) {
    const holding = rec.holdUntil && rec.holdUntil > now;
    const effective = holding ? rec.holdClass : rec.polarity;
    const cls = rec.dot.classList;
    cls.remove("ok", "err", "active");
    if (effective) cls.add(effective);
  }

  function tickWarnStrip(now) {
    for (const [name, rec] of warnDots) {
      const dt = now - rec.lastUpdate;
      const cls = rec.dot.classList;
      // Decay expired hold: if the underlying frame reverted but we were
      // still holding the transient class, drop back to the current polarity.
      if (rec.holdUntil && now > rec.holdUntil && rec.polarity !== rec.holdClass) {
        applyDotPolarity(rec, now);
      }
      if (rec.lastUpdate === 0) {
        // Never seen — dim, no hard-stale yet (nothing lost since boot).
        cls.add("stale");
        cls.remove("hard-stale");
      } else if (dt >= STALE_MS) {
        if (SAFETY.has(name)) {
          cls.add("hard-stale");
          cls.remove("stale");
        } else {
          cls.add("stale");
          cls.remove("hard-stale");
        }
      } else {
        cls.remove("stale", "hard-stale");
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Edit mode: hide/show + pointer-drag reorder.
  // Pointer Events (not HTML5 drag/drop) so touch + mouse share one code path;
  // iOS Safari doesn't fire dragstart on plain elements without a polyfill.
  // ---------------------------------------------------------------------------

  const $editBtn = document.getElementById("editBtn");
  const $editBar = document.getElementById("editBar");
  const $editDone = document.getElementById("editDoneBtn");
  const $resetBtn = document.getElementById("resetLayoutBtn");
  const $hiddenChips = document.getElementById("hiddenChips");

  function persistOrderFromDOM() {
    livePrefs.order = [...$mid.children].map(el => el.dataset.name);
    savePrefs();
  }

  function hideSignal(name) {
    const st = state.get(name);
    if (!st) return;
    livePrefs.hidden.add(name);
    st.nodes.div.classList.add("hidden");
    savePrefs();
    applyHero();
    rebuildHiddenChips();
  }

  function showSignal(name) {
    const st = state.get(name);
    if (!st) return;
    livePrefs.hidden.delete(name);
    st.nodes.div.classList.remove("hidden");
    savePrefs();
    applyHero();
    rebuildHiddenChips();
  }

  function rebuildHiddenChips() {
    $hiddenChips.textContent = "";
    if (livePrefs.hidden.size === 0) {
      const empty = document.createElement("span");
      empty.className = "chips-empty";
      empty.textContent = "—";
      $hiddenChips.appendChild(empty);
      return;
    }
    // Chip order mirrors the saved layout order so unhiding lands them back
    // where they were, and the tray order is stable across sessions.
    for (const el of $mid.children) {
      const name = el.dataset.name;
      if (!livePrefs.hidden.has(name)) continue;
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.textContent = "+ " + (LABEL[name] ?? name);
      chip.addEventListener("click", () => showSignal(name));
      $hiddenChips.appendChild(chip);
    }
  }

  function resetLayout() {
    resetPrefs();
    // Re-append cells in default order and clear hidden classes.
    for (const name of defaultOrder) {
      const st = state.get(name);
      if (!st) continue;
      st.nodes.div.classList.remove("hidden");
      $mid.appendChild(st.nodes.div);
    }
    applyHero();
    rebuildHiddenChips();
  }

  function setEditMode(on) {
    document.body.classList.toggle("edit-mode", on);
    $editBar.hidden = !on;
    $editBtn.classList.toggle("active", on);
    if (on) rebuildHiddenChips();
  }

  $editBtn.addEventListener("click", () => setEditMode(!document.body.classList.contains("edit-mode")));
  $editDone.addEventListener("click", () => setEditMode(false));
  $resetBtn.addEventListener("click", resetLayout);

  // Hide-button click on each cell (delegated for simplicity).
  $mid.addEventListener("click", (e) => {
    if (!document.body.classList.contains("edit-mode")) return;
    const btn = e.target.closest(".hide-btn");
    if (!btn) return;
    const cell = btn.closest(".sig");
    if (!cell) return;
    hideSignal(cell.dataset.name);
  });

  // Peak reset: tap the ▲ chip to clear the accumulated max for that signal.
  // Works in any mode (not gated on edit-mode) — the peak persists for the
  // whole page lifetime otherwise, useful to zero after warmup / an anomaly.
  $mid.addEventListener("click", (e) => {
    const btn = e.target.closest(".peak");
    if (!btn) return;
    const cell = btn.closest(".sig");
    if (!cell) return;
    const st = state.get(cell.dataset.name);
    if (!st) return;
    st.peakRaw = null;
    st.nodes.peak.textContent = "";
    e.stopPropagation();
  });

  // Pointer-drag reorder. Delegated on $mid so cells created later still work.
  let drag = null;
  $mid.addEventListener("pointerdown", (e) => {
    if (!document.body.classList.contains("edit-mode")) return;
    const grip = e.target.closest(".grip");
    if (!grip) return;
    const cell = grip.closest(".sig");
    if (!cell) return;
    e.preventDefault();
    drag = { cell };
    cell.classList.add("dragging");
    // Capture on the grip so pointermove/up land here even if the finger
    // wanders off the grip's tiny hitbox during the drag.
    try { grip.setPointerCapture(e.pointerId); } catch { /* no capture support */ }
  });

  $mid.addEventListener("pointermove", (e) => {
    if (!drag) return;
    // elementFromPoint doesn't see the captured element until we hide it —
    // but we want the *underlying* cell, so temporarily suppress the drag
    // target's hit-testing via CSS (pointer-events:none on .dragging handles it).
    const under = document.elementFromPoint(e.clientX, e.clientY);
    if (!under) return;
    const target = under.closest(".sig");
    if (!target || target === drag.cell || target.parentElement !== $mid) return;
    // Insert before/after target based on pointer position relative to its midpoint.
    const rect = target.getBoundingClientRect();
    const midY = rect.top + rect.height / 2;
    const midX = rect.left + rect.width / 2;
    // Use whichever axis has the larger gradient to decide direction; for a
    // grid layout, either y or x can be the "next slot" — pick the axis where
    // the pointer is further from the target's center.
    const useY = Math.abs(e.clientY - midY) >= Math.abs(e.clientX - midX);
    const before = useY ? (e.clientY < midY) : (e.clientX < midX);
    if (before) {
      if (target.previousElementSibling !== drag.cell) $mid.insertBefore(drag.cell, target);
    } else {
      if (target.nextElementSibling !== drag.cell) $mid.insertBefore(drag.cell, target.nextElementSibling);
    }
  });

  function endDrag() {
    if (!drag) return;
    drag.cell.classList.remove("dragging");
    drag = null;
    persistOrderFromDOM();
    applyHero();
    rebuildHiddenChips();
  }
  $mid.addEventListener("pointerup", endDrag);
  $mid.addEventListener("pointercancel", endDrag);

  // ---------------------------------------------------------------------------
  // Ride / Diagnostic mode. Diagnostic (default) is the historical layout —
  // everything visible, dev metadata shown. Ride tags a small set of cells
  // with data-tier; CSS handles the rest (hides untagged cells, resizes
  // heroes, reroutes the sparkline out from behind the digits).
  // ---------------------------------------------------------------------------
  const RIDE_TIERS = {
    rpm: "hero-primary",
    wheel_speed_rear: "hero-speed",   // ordered before gear via CSS `order:`
    gear_position: "hero",
    throttle_position: "second",
    coolant_temp: "second",
  };
  const $modeBtn = document.getElementById("modeBtn");

  function applyModeTiers(mode) {
    for (const [name, st] of state) {
      if (mode === "ride") {
        const tier = RIDE_TIERS[name];
        if (tier) st.nodes.div.dataset.tier = tier;
        else delete st.nodes.div.dataset.tier;
      } else {
        delete st.nodes.div.dataset.tier;
      }
      // Force one sparkline redraw next tick so the new canvas dimensions
      // (CSS-driven) render immediately instead of at the next data frame.
      st.histDirty = true;
    }
  }

  function setMode(mode) {
    if (!VALID_MODES.has(mode)) mode = "diag";
    livePrefs.mode = mode;
    savePrefs();
    document.body.classList.toggle("ride-mode", mode === "ride");
    $modeBtn.classList.toggle("active", mode === "ride");
    $modeBtn.textContent = mode === "ride" ? "Diag" : "Ride";
    applyModeTiers(mode);
  }

  // VALID_MODES is declared in prefs.js (same IIFE); reused here.
  $modeBtn.addEventListener("click", () => setMode(livePrefs.mode === "ride" ? "diag" : "ride"));
  setMode(livePrefs.mode);
