  // -------------------------------------------------------------------------
  // Decoded panel — the M6 addition. SIGNALS is codegen'd from signals.yaml.
  // -------------------------------------------------------------------------

  /* __SIGNALS_JS__ */

  // Order signals for the panel: rider-relevance first, then diagnostic.
  // Any signal in the codegen output that isn't listed here appears after.
  const DISPLAY_ORDER = [
    "rpm", "gear_position", "wheel_speed_rear", "wheel_speed_front",
    "throttle_position", "coolant_temp", "warmup_index",
    "kill_switch", "side_stand", "abs_lamp",
    "clutch", "shift_cut_active", "shift_blip_active", "shift_failed",
    "engine_on_counter", "engine_off_counter",
  ];
  const LABEL = {
    rpm: "RPM",
    gear_position: "GEAR",
    wheel_speed_rear: "WHEEL R",
    wheel_speed_front: "WHEEL F",
    throttle_position: "THROTTLE",
    coolant_temp: "COOLANT",
    warmup_index: "WARMUP",
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
  // Which enum/bool value is the "OK" polarity (green vs red).
  const OK_VALUES = new Set(["RUN", "UP", "RELEASED"]);
  const ERR_VALUES = new Set(["STOP", "DOWN", "PULLED"]);

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
  function extractRaw(sig, data) {
    if (sig.bytes) {
      for (const b of sig.bytes) if (b >= data.length) return null;
      const order = sig.order === "big" ? sig.bytes : sig.bytes.slice().reverse();
      let value = 0;
      for (const b of order) value = (value << 8) | data[b];
      const fullSlot = sig.bit_length === 8 * sig.bytes.length;
      if (!fullSlot || sig.bit_offset !== 0) {
        const mask = (1 << sig.bit_length) - 1;
        // >>> 0 for correct behavior with 16-bit+ values on the boundary
        // where <<16 would go negative in JS's signed 32-bit int semantics.
        value = ((value >>> sig.bit_offset) & mask) >>> 0;
      }
      return value;
    }
    if (sig.byte >= data.length) return null;
    const mask = (1 << sig.bit_length) - 1;
    return (data[sig.byte] >> sig.bit_offset) & mask;
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
    const peak = document.createElement("span");
    peak.className = "peak";
    peak.textContent = "";
    row.appendChild(peak);
    const fresh = document.createElement("div");
    fresh.className = "fresh";
    div.appendChild(meta); div.appendChild(row); div.appendChild(fresh);
    return { div, val, peak, fresh, grip, hideBtn };
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
        st.nodes.val.classList.toggle("enum-ok", OK_VALUES.has(label));
        st.nodes.val.classList.toggle("enum-err", ERR_VALUES.has(label));
      }
      // Peak (scalars only).
      if (!isDiscrete(sig)) {
        if (st.peakRaw === null || raw > st.peakRaw) {
          st.peakRaw = raw;
          const peakStr = formatValue(sig, raw);
          st.nodes.peak.textContent = "▲ " + peakStr;
        }
      }
    }
  }

  // Shared RAF tick: pulse decay + freshness bar + stale fade.
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
    }
    requestAnimationFrame(panelTick);
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
