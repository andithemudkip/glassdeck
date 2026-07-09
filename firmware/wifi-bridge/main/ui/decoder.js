  // -------------------------------------------------------------------------
  // Decoded panel — the M6 addition. SIGNALS is codegen'd from signals.yaml.
  // -------------------------------------------------------------------------

  /* __SIGNALS_JS__ */

  // Order signals for the panel: rider-relevance first, then diagnostic.
  // Any signal in the codegen output that isn't listed here appears after.
  const DISPLAY_ORDER = [
    "rpm", "gear_position", "wheel_speed_rear", "wheel_speed_front",
    "throttle_position", "coolant_temp",
    "kill_switch", "side_stand", "clutch",
    "engine_on_counter", "engine_off_counter",
  ];
  const HERO = "rpm";
  const LABEL = {
    rpm: "RPM",
    gear_position: "GEAR",
    wheel_speed_rear: "WHEEL R",
    wheel_speed_front: "WHEEL F",
    throttle_position: "THROTTLE",
    coolant_temp: "COOLANT",
    kill_switch: "KILL",
    side_stand: "STAND",
    clutch: "CLUTCH",
    engine_on_counter: "ENG-ON",
    engine_off_counter: "ENG-OFF",
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
    div.className = "sig empty" + (sig.name === HERO ? " hero" : "");
    div.dataset.name = sig.name;
    const meta = document.createElement("div");
    meta.className = "meta";
    const nameEl = document.createElement("span");
    nameEl.className = "name";
    nameEl.textContent = LABEL[sig.name] ?? sig.name;
    const locEl = document.createElement("span");
    locEl.className = "loc";
    locEl.textContent = locStr(sig);
    meta.appendChild(nameEl); meta.appendChild(locEl);
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
    return { div, val, peak, fresh };
  }

  // Emit cells in DISPLAY_ORDER, with any codegen'd signals not listed appended.
  const known = new Set(SIGNALS.map(s => s.name));
  const ordered = [
    ...DISPLAY_ORDER.filter(n => known.has(n)),
    ...SIGNALS.map(s => s.name).filter(n => !DISPLAY_ORDER.includes(n)),
  ];
  const bySigName = new Map(SIGNALS.map(s => [s.name, s]));

  for (const name of ordered) {
    const sig = bySigName.get(name);
    const nodes = makeCell(sig);
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
