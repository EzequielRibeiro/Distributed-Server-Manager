"use strict";

const OBS_API = "/api";
const byId = id => document.getElementById(id);

function authHeaders() {
  const token = sessionStorage.getItem("dsm_auth");
  if (!token) {
    window.location.replace("/login.html");
    throw new Error("auth required");
  }
  return {Authorization: `Basic ${token}`, Accept: "application/json"};
}

async function get(path) {
  try {
    const response = await fetch(`${OBS_API}${path}`, {headers: authHeaders(), cache: "no-store"});
    if (response.status === 401) {
      sessionStorage.clear();
      window.location.replace("/login.html");
      return null;
    }
    if (!response.ok) return null;
    return await response.json();
  } catch (error) {
    console.warn("[Capivara Observability]", path, error);
    return null;
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
}

function text(id, value, fallback = "—") {
  const element = byId(id);
  if (element) element.textContent = value ?? fallback;
}

function formatTime(value) {
  if (!value) return "—";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("pt-BR", {dateStyle:"short", timeStyle:"short"});
}

function eventLabel(event) {
  const type = String(event?.type || event?.action || event?.event_type || "Evento").replaceAll("_", " ").toLowerCase();
  const message = event?.message || event?.details || event?.data?.message || "";
  return message ? `${type} · ${message}` : type;
}

function renderUser(user) {
  const role = String(user?.role || "").toLowerCase();
  text("observability-user-name", user?.username || "Usuário");
  text("observability-user-role", role);
  text("current-user", user?.username || "Sessão ativa");
  document.querySelectorAll(".admin-only").forEach(el => { el.style.display = role === "admin" ? "" : "none"; });
  document.querySelectorAll(".agent-manager-only").forEach(el => { el.style.display = ["admin", "controller", "operator"].includes(role) ? "" : "none"; });
  document.querySelectorAll(".instance-manager-only").forEach(el => { el.style.display = ["admin", "controller", "client", "customer"].includes(role) ? "" : "none"; });
}

function renderTimeline(result) {
  const events = Array.isArray(result) ? result : (result?.events || []);
  text("observability-event-total", events.length);
  const eventsTarget = byId("observability-events");
  if (eventsTarget) {
    eventsTarget.innerHTML = events.slice(0, 30).map(event => `
      <article class="cap-event-item">
        <time>${escapeHtml(formatTime(event.occurred_at || event.timestamp || event.time || event.created_at || event.received_at))}</time>
        <div><p>${escapeHtml(eventLabel(event))}</p><small>${escapeHtml(event.category || event.source || event.producer || "Sistema")}</small></div>
      </article>`).join("") || '<div class="cap-empty-state">Nenhum evento recente.</div>';
  }
}

function renderAlerts(result) {
  const alerts = Array.isArray(result) ? result : (result?.alerts || []);
  text("observability-alert-total", alerts.length);
  const target = byId("observability-alerts");
  if (!target) return;
  target.innerHTML = alerts.slice(0, 30).map(alert => {
    const level = String(alert.level || "warning").toLowerCase();
    const state = String(alert.state || "OPEN").toUpperCase();
    const scope = [alert.agent_id, alert.instance_id].filter(Boolean).join(" · ") || alert.scope || "Controller";
    return `<article class="cap-alert-item" data-level="${escapeHtml(level)}">
      <strong>${escapeHtml(level)} · ${escapeHtml(state)}</strong>
      <p>${escapeHtml(alert.message || alert.rule_id || alert.id || "Alerta")}</p>
      <small>${escapeHtml(scope)}</small>
      <time>${escapeHtml(formatTime(alert.updated_at || alert.opened_at))}</time>
    </article>`;
  }).join("") || '<div class="cap-empty-state">Nenhum alerta ativo.</div>';
}

function metricTitle(metric) {
  return metric?.metric_name || metric?.name || metric?.key || metric?.type || "Métrica";
}

function metricValue(metric) {
  const value = metric?.value ?? metric?.metric_value ?? metric?.latest ?? metric?.avg ?? metric?.average;
  if (value !== undefined && value !== null && typeof value !== "object") return value;
  return metric?.status || metric?.state || "Disponível";
}

function renderMetrics(result) {
  const metrics = Array.isArray(result?.metrics) ? result.metrics : [];
  text("observability-metric-total", result?.count ?? metrics.length);
  const target = byId("observability-metrics");
  if (!target) return;
  target.innerHTML = metrics.slice(0, 24).map(metric => {
    const scope = [metric?.agent_id, metric?.instance_id].filter(Boolean).join(" · ") || metric?.scope || "Control Plane";
    const unit = metric?.unit ? ` ${metric.unit}` : "";
    return `<article class="cap-metric-card"><span>${escapeHtml(metricTitle(metric))}</span><strong>${escapeHtml(metricValue(metric))}${escapeHtml(unit)}</strong><small>${escapeHtml(scope)}</small></article>`;
  }).join("") || '<div class="cap-empty-state">Nenhuma métrica publicada.</div>';
}

function scalarEntries(value, prefix = "", depth = 0) {
  if (!value || typeof value !== "object" || depth > 2) return [];
  const rows = [];
  for (const [key, child] of Object.entries(value)) {
    const label = prefix ? `${prefix} · ${key}` : key;
    if (child === null || ["string","number","boolean"].includes(typeof child)) rows.push([label, child]);
    else if (!Array.isArray(child)) rows.push(...scalarEntries(child, label, depth + 1));
  }
  return rows;
}

function renderDoctor(result) {
  const target = byId("observability-doctor");
  const status = String(result?.status || result?.health || result?.state || "operacional");
  text("observability-doctor-state", status);
  if (!target) return;
  const rows = scalarEntries(result).slice(0, 18);
  target.innerHTML = rows.map(([label, value]) => {
    const state = String(value || "").toLowerCase();
    return `<article class="cap-doctor-card" data-state="${escapeHtml(state)}"><span>${escapeHtml(label.replaceAll("_", " "))}</span><strong>${escapeHtml(value)}</strong></article>`;
  }).join("") || '<div class="cap-empty-state">Diagnóstico concluído sem detalhes adicionais.</div>';
}

function renderHealth(result) {
  const data = result?.data || result || {};
  const status = String(data.status || "online").toLowerCase();
  const failed = ["failed","critical","offline","error"].includes(status);
  text("observability-controller-status", failed ? "Controller com falha" : "Controller Online");
  document.querySelector(".cap-controller-state")?.classList.toggle("cap-controller-failed", failed);
}

async function loadAgentsForLogs() {
  const select = byId("log-agent");
  if (!select || select.options.length) return;
  const response = await get("/agents");
  const agents = response?.agents || [];
  agents.forEach(agent => select.add(new Option(agent.name || agent.id, agent.id)));
}

function syncLogSource() {
  const source = byId("log-source")?.value || "controller";
  const isAgent = source === "agent";
  const isInstance = source === "instance";
  const agentWrap = byId("log-agent-wrap");
  const serverWrap = byId("log-server-wrap");
  const gameWrap = byId("log-game-wrap");
  const instanceWrap = byId("log-instance-wrap");
  if (agentWrap) agentWrap.hidden = !isAgent;
  if (serverWrap) serverWrap.hidden = !isInstance;
  if (gameWrap) gameWrap.hidden = !isInstance;
  if (instanceWrap) instanceWrap.hidden = !isInstance;
  if (isAgent) loadAgentsForLogs();
}

async function loadLogs() {
  const target = byId("logs");
  if (!target) return;
  const source = byId("log-source")?.value || "controller";
  const server = source === "agent" ? (byId("log-agent")?.value || "") : (byId("log-server")?.value || "");
  const game = source === "instance" ? (byId("log-game")?.value || "") : "";
  const instance = source === "instance" ? (byId("log-instance")?.value || "") : "";
  const params = new URLSearchParams({source, server, game, instance, limit:"500"});
  const response = await get(`/log-viewer?${params.toString()}`);
  const data = response?.data || response || {};
  const logs = Array.isArray(data.logs) ? data.logs : [];
  text("logs-context", source === "controller" ? "Controller" : source === "agent" ? `Agent / Node ${server || ""}` : (instance || "Instância"));
  target.replaceChildren();
  if (!logs.length) {
    const empty = document.createElement("div");
    empty.className = "cap-empty-state";
    empty.textContent = data.message || "Nenhum log disponível.";
    target.appendChild(empty);
    return;
  }
  logs.forEach(line => {
    const div = document.createElement("div");
    div.className = "cap-log-line";
    div.textContent = line;
    target.appendChild(div);
  });
}

async function refresh() {
  const [user, timeline, alerts, metrics, doctor, health] = await Promise.all([
    get("/whoami"),
    get("/events?limit=100"),
    get("/admin/alerts?active=true&limit=100"),
    get("/observability?mode=latest&limit=100"),
    get("/infrastructure/doctor"),
    get("/health")
  ]);
  if (user) renderUser(user);
  renderTimeline(timeline);
  renderAlerts(alerts);
  renderMetrics(metrics || {});
  if (doctor) renderDoctor(doctor);
  else {
    text("observability-doctor-state", "Indisponível");
    const target = byId("observability-doctor");
    if (target) target.innerHTML = '<div class="cap-empty-state">Diagnóstico indisponível para esta sessão.</div>';
  }
  renderHealth(health);
}

async function loadSidebar() {
  const target = byId("sidebar-component");
  if (!target) return;
  const response = await fetch("/components/sidebar-v3.html", {cache:"no-store"});
  if (response.ok) target.innerHTML = await response.text();
  const logout = byId("btn-logout");
  if (logout) logout.onclick = () => { sessionStorage.clear(); window.location.replace("/login.html"); };
  document.querySelectorAll(".cap-sidebar-v3 a").forEach(link => link.classList.remove("active"));
  document.querySelectorAll('.cap-sidebar-v3 a[href^="observability.html"]').forEach(link => link.classList.add("active"));
}

document.addEventListener("DOMContentLoaded", async () => {
  await loadSidebar();
  byId("observability-menu-toggle")?.addEventListener("click", () => {
    if (window.innerWidth <= 760) document.body.classList.toggle("sidebar-open");
    else document.body.classList.toggle("cap-sidebar-collapsed");
  });
  byId("observability-refresh")?.addEventListener("click", refresh);
  byId("btn-refresh-logs")?.addEventListener("click", loadLogs);
  byId("log-source")?.addEventListener("change", () => { syncLogSource(); loadLogs(); });
  byId("log-agent")?.addEventListener("change", loadLogs);
  syncLogSource();
  await refresh();
  await loadLogs();
  window.setInterval(refresh, 30000);
});
