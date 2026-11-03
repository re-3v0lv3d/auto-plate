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
  owners_count: "Propietarios",
  env_label: "Etiqueta DGT",
};

const state = { config: null, captchaToken: null, lastPlate: null, lastCountry: "ES" };

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

  const statusTag =
    v.status === "baja"
      ? `<span class="tag danger">de baja</span>`
      : v.status === "alta"
        ? `<span class="tag ok">en circulación</span>`
        : "";

  const tags = [
    statusTag,
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
    ${cells ? `<dl class="grid">${cells}</dl>` : ""}
    ${renderMovements(v)}
    ${state.config?.historialvehiculo_auto ? "" : `<div class="merge">
      <p>Fusionar con HistorialVehículo (propietarios, etiqueta ambiental y movimientos):</p>
      <div class="merge-row">
        <input id="merge-url" type="text" placeholder="Pega el enlace del informe: historialvehiculo.com/vehiculo/..." />
        <button type="button" id="merge-btn">Fusionar</button>
      </div>
    </div>`}
    <p class="dgt-note">
      Baja y titulares solo constan en el informe oficial de la DGT.
      <a href="https://sede.dgt.gob.es/es/vehiculos/informacion-de-vehiculos/informe-de-un-vehiculo/"
         target="_blank" rel="noopener">Consultar en la DGT</a>
    </p>`;
}

function renderMovements(v) {
  const moves = v?.extra?.historialvehiculo?.movimientos;
  if (!Array.isArray(moves) || !moves.length) return "";
  const rows = moves
    .map(
      (m) =>
        `<tr><td>${m.fecha || "—"}</td><td>${m.tipo || "—"}</td><td>${m.localidad || "—"}</td><td>${m.propietario || "—"}</td></tr>`,
    )
    .join("");
  return `
    <div class="moves">
      <h4>Movimientos</h4>
      <table>
        <thead><tr><th>Fecha</th><th>Tipo</th><th>Localidad</th><th>Propietario</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

async function submit(plateOverride) {
  const raw = plateOverride ?? $("#plate").value;
  const plate = normalizeInput(raw);
  const country = $("#country").value;
  state.lastPlate = plate;
  state.lastCountry = country;
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
      body: JSON.stringify({
        plate,
        country,
        captcha_token: state.captchaToken,
        refresh: false,
      }),
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
    if (payload.found) {
      saveHistory(payload);
      $("#hv").classList.remove("hidden");
    }
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
  await handleMergeLink();
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

document.addEventListener("click", async (event) => {
  if (event.target.id !== "merge-btn") return;
  const input = $("#merge-url");
  const url = (input?.value || "").trim();
  if (!url) {
    setMsg("Pega el enlace del informe de HistorialVehículo.", "warn");
    return;
  }
  const button = event.target;
  button.disabled = true;
  button.textContent = "Fusionando…";
  try {
    const response = await api("/api/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plate: state.lastPlate, country: state.lastCountry, source_url: url }),
    });
    const payload = await response.json();
    if (!response.ok) {
      setMsg(payload.detail || "No se pudo fusionar.", "error");
      return;
    }
    setMsg("Datos de HistorialVehículo fusionados.", "");
    renderResult(payload);
  } catch (err) {
    if (err.message !== "auth") setMsg("Error fusionando: " + err.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "Fusionar";
  }
});

function buildBookmarklet() {
  const base = window.location.origin + window.location.pathname;
  const code =
    "javascript:(function(){var p=((document.querySelector('#buscador')||{}).value||'').trim()||prompt('Matr&iacute;cula del veh&iacute;culo:');if(!p)return;" +
    "window.open('" + base + "?merge='+encodeURIComponent(location.href)+'&plate='+encodeURIComponent(p),'_blank');})();";
  $("#hv-bookmarklet").setAttribute("href", code);
}

async function handleMergeLink() {
  const params = new URLSearchParams(window.location.search);
  const merge = params.get("merge");
  const plate = params.get("plate");
  if (!merge || !plate) return;

  history.replaceState({}, "", window.location.pathname);
  setMsg("Importando el informe de HistorialVehículo…");
  try {
    const response = await api("/api/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plate, country: state.lastCountry || "ES", source_url: merge }),
    });
    const payload = await response.json();
    if (!response.ok) {
      setMsg(payload.detail || "No se pudo importar el informe.", "error");
      return;
    }
    setMsg("Informe de HistorialVehículo fusionado.", "");
    $("#plate").value = prettyPlate(plate, payload.plate.country);
    renderResult(payload);
    saveHistory(payload);
    $("#hv").classList.remove("hidden");
  } catch (err) {
    if (err.message !== "auth") setMsg("Error importando: " + err.message, "error");
  }
}

$("#hv-open").addEventListener("click", async () => {
  const plate = normalizeInput($("#plate").value);
  try { await navigator.clipboard.writeText(plate); } catch { /* sin permiso */ }
  window.open("https://www.historialvehiculo.com/informes-gratis-vehiculos", "_blank", "noopener");
  setMsg(plate ? `Matrícula ${plate} copiada. Pégala en HistorialVehículo.` : "Abre HistorialVehículo y busca tu matrícula.");
});

buildBookmarklet();
