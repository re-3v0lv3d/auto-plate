const $ = (sel) => document.querySelector(sel);

// Vacío = mismo origen. En GitHub Pages, apunta al backend público.
const API_BASE = (window.AUTOPLATE_API || "").replace(/\/$/, "");
const AUTH_KEY = "autoplate:auth";

const LABELS = {
  make: "Marca",
  model: "Modelo",
  variant: "Versión",
  year: "Año",
  first_registration: "1ª matriculación",
  vin: "VIN",
  fuel: "Combustible",
  engine_cc: "Cilindrada",
  power_hp: "Potencia",
  color: "Color",
  body: "Carrocería",
  doors: "Puertas",
  seats: "Plazas",
};

const state = { config: null, captchaToken: null };

function authHeaders() {
  const token = sessionStorage.getItem(AUTH_KEY);
  return token ? { Authorization: `Basic ${token}` } : {};
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}), ...authHeaders() };
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (response.status === 401) {
    sessionStorage.removeItem(AUTH_KEY);
    showLogin();
    throw new Error("auth");
  }
  return response;
}

function showLogin() {
  $("#login").classList.remove("hidden");
  $("#app").classList.add("hidden");
  $("#login-user").focus();
}

function hideLogin() {
  $("#login").classList.add("hidden");
  $("#app").classList.remove("hidden");
}

function setMsg(text, kind = "") {
  const el = $("#msg");
  el.textContent = text || "";
  el.className = "msg" + (kind ? " " + kind : "");
}

function normalizeInput(value) {
  return (value || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function prettyPlate(value, country) {
  const v = normalizeInput(value);
  if (country === "ES" && /^\d{4}[A-Z]{3}$/.test(v)) return v.slice(0, 4) + " " + v.slice(4);
  return v;
}

async function loadConfig() {
  const response = await api("/api/config");
  if (!response.ok) throw new Error("config");
  state.config = await response.json();

  const select = $("#country");
  select.innerHTML = "";
  for (const [code, name] of Object.entries(state.config.countries)) {
    const opt = document.createElement("option");
    opt.value = code;
    opt.textContent = `${name} (${code})`;
    if (code === state.config.default_country) opt.selected = true;
    select.appendChild(opt);
  }
}

async function loadStats() {
  try {
    const response = await api("/api/stats");
    if (!response.ok) return;
    const stats = await response.json();
    const parts = Object.entries(stats.by_country || {})
      .slice(0, 4)
      .map(([code, n]) => `${code} ${n.toLocaleString("es-ES")}`);
    $("#stats").textContent = `${stats.vehicles.toLocaleString("es-ES")} matrículas${parts.length ? " · " + parts.join(" · ") : ""}`;
  } catch {
    $("#stats").textContent = "";
  }
}

function formatValue(key, value) {
  if (value === null || value === undefined || value === "") return null;
  if (key === "engine_cc" && Number(value) > 0) return `${(Number(value) / 1000).toFixed(1)} L`;
  if (key === "power_hp") return `${value} CV`;
  return String(value);
}

function renderResult(payload) {
  const box = $("#result");
  const v = payload.vehicle;
  box.classList.remove("hidden");

  if (!v) {
    box.innerHTML = `
      <div class="result-head">
        <div>
          <div class="result-plate">${payload.plate.display}</div>
          <div class="result-title">Sin datos</div>
          <div class="result-sub">${payload.message || "No se encontró información para esta matrícula."}</div>
        </div>
      </div>`;
    return;
  }

  const title = [v.make, v.model].filter(Boolean).join(" ") || "Vehículo";
  const cells = Object.entries(LABELS)
    .map(([key, label]) => {
      const formatted = formatValue(key, v[key]);
      if (!formatted) return "";
      return `<div class="cell"><dt>${label}</dt><dd>${formatted}</dd></div>`;
    })
    .join("");

  const tags = [
    v.complete ? `<span class="tag ok">informe completo</span>` : `<span class="tag warn">datos parciales</span>`,
    payload.cached ? `<span class="tag">caché</span>` : `<span class="tag">en vivo</span>`,
    v.source ? `<span class="tag">fuente: ${v.source}</span>` : "",
    v.updated_at ? `<span class="tag">actualizado ${new Date(v.updated_at * 1000).toLocaleDateString("es-ES")}</span>` : "",
  ]
    .filter(Boolean)
    .join("");

  box.innerHTML = `
    <div class="result-head">
      <div>
        <div class="result-plate">${payload.plate.display}</div>
        <div class="result-title">${title}</div>
        <div class="result-sub">${v.variant || "Identificación por matrícula"}</div>
      </div>
      <div class="tags">${tags}</div>
    </div>
    ${cells ? `<dl class="grid">${cells}</dl>` : ""}`;
}

async function submit(plateOverride) {
  const raw = plateOverride ?? $("#plate").value;
  const plate = normalizeInput(raw);
  const country = $("#country").value;
  if (!plate) {
    setMsg("Escribe una matrícula.", "error");
    return;
  }

  $("#go").disabled = true;
  setMsg("Consultando…");

  try {
    const response = await api("/api/lookup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plate, country, captcha_token: state.captchaToken, refresh: false }),
    });

    const payload = await response.json();

    if (!response.ok) {
      setMsg(payload.detail || "Error en la consulta.", "error");
      return;
    }

    if (payload.captcha_required) {
      setMsg("Este proveedor exige captcha y no hay resolvedor configurado.", "warn");
      $("#captcha").classList.remove("hidden");
      return;
    }

    $("#captcha").classList.add("hidden");
    setMsg(payload.found ? "" : payload.message || "Sin resultados.", payload.found ? "" : "warn");
    renderResult(payload);
    if (payload.found) saveHistory(payload);
  } catch (err) {
    if (err.message !== "auth") setMsg("No se pudo conectar con el servidor.", "error");
  } finally {
    $("#go").disabled = false;
    loadStats();
  }
}

function saveHistory(payload) {
  const key = "autoplate:history";
  const entry = {
    plate: payload.plate.normalized,
    country: payload.plate.country,
    label: [payload.vehicle?.make, payload.vehicle?.model].filter(Boolean).join(" ") || payload.plate.display,
  };
  const list = JSON.parse(localStorage.getItem(key) || "[]").filter(
    (item) => !(item.plate === entry.plate && item.country === entry.country),
  );
  list.unshift(entry);
  localStorage.setItem(key, JSON.stringify(list.slice(0, 8)));
  renderHistory();
}

function renderHistory() {
  const list = JSON.parse(localStorage.getItem("autoplate:history") || "[]");
  const wrap = $("#history");
  const container = $("#history-list");
  if (!list.length) {
    wrap.classList.add("hidden");
    return;
  }
  wrap.classList.remove("hidden");
  container.innerHTML = "";
  for (const item of list) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.textContent = prettyPlate(item.plate, item.country);
    chip.title = item.label;
    chip.addEventListener("click", () => {
      $("#plate").value = prettyPlate(item.plate, item.country);
      $("#country").value = item.country;
      submit(item.plate);
    });
    container.appendChild(chip);
  }
}

async function start() {
  await loadConfig();
  hideLogin();
  loadStats();
  renderHistory();
}

$("#search").addEventListener("submit", (event) => {
  event.preventDefault();
  submit();
});

$("#plate").addEventListener("input", (event) => {
  const cursor = event.target.selectionStart;
  event.target.value = prettyPlate(event.target.value, $("#country").value);
  event.target.setSelectionRange(cursor, cursor);
});

$("#country").addEventListener("change", () => {
  $("#plate").value = prettyPlate($("#plate").value, $("#country").value);
});

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const user = $("#login-user").value.trim();
  const pass = $("#login-pass").value;
  const error = $("#login-error");
  error.textContent = "";

  const token = btoa(`${user}:${pass}`);
  const response = await fetch(`${API_BASE}/api/config`, {
    headers: { Authorization: `Basic ${token}` },
  });

  if (!response.ok) {
    error.textContent = response.status === 401 ? "Usuario o contraseña incorrectos." : "No se pudo conectar.";
    return;
  }

  sessionStorage.setItem(AUTH_KEY, token);
  $("#login-pass").value = "";
  state.config = await response.json();
  await start();
});

$("#logout").addEventListener("click", () => {
  sessionStorage.removeItem(AUTH_KEY);
  showLogin();
});

start().catch(() => showLogin());
