"use strict";

const API = "/api";

let currentUser = null;
let selectedAgent = null;
let infrastructureTopology = null;

function byId(id) {
    return document.getElementById(id);
}

function setText(id, value, fallback = "—") {
    const element = byId(id);
    if (element) {
        element.textContent = value ?? fallback;
    }
}

function bind(id, eventName, handler) {
    const element = byId(id);
    if (!element) {
        console.warn(`[Capivara][Agents] Elemento ausente: #${id}`);
        return false;
    }
    element.addEventListener(eventName, handler);
    return true;
}

function authHeader() {
    const token = sessionStorage.getItem("dsm_auth");
    if (!token) {
        window.location.replace("/login.html");
        throw new Error("authentication required");
    }
    return {
        Authorization: `Basic ${token}`,
        Accept: "application/json"
    };
}

async function request(endpoint, options = {}) {
    const headers = {
        ...authHeader(),
        ...(options.headers || {})
    };

    if (options.body) {
        headers["Content-Type"] = "application/json";
    }

    const response = await fetch(`${API}${endpoint}`, {
        ...options,
        headers
    });

    if (response.status === 401) {
        sessionStorage.clear();
        window.location.replace("/login.html");
        return null;
    }

    const body = await response.json();
    if (!response.ok) {
        throw new Error(body.error || `HTTP ${response.status}`);
    }
    return body;
}

function errorMessage(message = "") {
    const box = byId("agents-error");
    if (!box) {
        if (message) console.error(`[Capivara][Agents] ${message}`);
        return;
    }
    box.hidden = !message;
    box.textContent = message;
}

async function loadSidebar() {
    const target = byId("sidebar-component");
    if (!target) return;

    const response = await fetch("/components/sidebar.html");
    if (response.ok) {
        target.innerHTML = await response.text();
    }

    const logout = byId("btn-logout");
    if (logout) {
        logout.addEventListener("click", () => {
            sessionStorage.clear();
            window.location.replace("/login.html");
        });
    }
}

function applyRole() {
    if (!currentUser) return;

    document.querySelectorAll(".admin-only").forEach(element => {
        element.style.display = currentUser.role === "admin" ? "" : "none";
    });

    document.querySelectorAll(".agent-manager-only").forEach(element => {
        element.style.display = ["admin", "controller"].includes(currentUser.role)
            ? ""
            : "none";
    });

    const force = byId("force-wrapper");
    if (force) {
        force.hidden = currentUser.role !== "admin";
    }
}

async function loadInfrastructure() {
    infrastructureTopology = await request("/infrastructure?active_only=true");
    return infrastructureTopology;
}

function collectDatacenters(value, result = []) {
    if (!value) return result;
    if (Array.isArray(value)) {
        value.forEach(item => collectDatacenters(item, result));
        return result;
    }
    if (typeof value !== "object") return result;
    if (value.type === "datacenter" && value.id) result.push(value);
    Object.values(value).forEach(child => {
        if (child && typeof child === "object") collectDatacenters(child, result);
    });
    return result;
}

function renderDatacenters() {
    const select = byId("agent-datacenter");
    if (!select) return;

    const current = select.value;
    select.replaceChildren(new Option("Selecione um datacenter", ""));

    const unique = new Map();
    collectDatacenters(infrastructureTopology).forEach(item => {
        if (item?.id) unique.set(String(item.id), item);
    });

    unique.forEach(item => {
        select.appendChild(new Option(item.name || String(item.id), String(item.id)));
    });

    if (current) select.value = current;
}

function agentCard(agent) {
    const card = document.createElement("article");
    card.className = "agent-card";
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.setAttribute("aria-label", `Abrir informações do Agent ${agent.name || agent.id}`);
    card.innerHTML = `
        <h2>${agent.name || agent.id}</h2>
        <div class="agent-status">${agent.status || "unknown"}</div>
        <p>Agent: ${agent.id || "—"}</p>
        <p>Node: ${agent.node_id || "—"}</p>
        <p>Instâncias: ${agent.instance_count || 0}</p>
    `;

    const open = () => loadAgent(agent.id);
    card.addEventListener("click", open);
    card.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            open();
        }
    });
    return card;
}

async function loadAgents() {
    errorMessage();
    try {
        const result = await request("/agents");
        if (!result) return;

        const list = byId("agents-list");
        if (!list) throw new Error("Área de lista de Agents não encontrada no Dashboard.");

        list.replaceChildren();
        const agents = Array.isArray(result.agents) ? result.agents : [];

        if (!agents.length) {
            const empty = document.createElement("article");
            empty.className = "agent-card agent-card-empty";
            empty.innerHTML = "<h2>Nenhum Agent registrado</h2><p>Instale ou faça o enrollment de um Agent para visualizar suas informações e telemetria.</p>";
            list.appendChild(empty);
            return;
        }

        agents.forEach(agent => list.appendChild(agentCard(agent)));

        if (agents.length === 1 && !selectedAgent) {
            await loadAgent(agents[0].id);
        }
    } catch (error) {
        errorMessage(error.message);
    }
}

function rangeCard(item) {
    const card = document.createElement("article");
    card.className = "range-card";
    if (item.near_exhaustion) card.classList.add("near-exhaustion");
    card.innerHTML = `
        <h3>${String(item.protocol || "").toUpperCase()} ${item.start_port}-${item.end_port}</h3>
        <div class="range-row"><span>Capacidade</span><strong>${item.capacity ?? 0}</strong></div>
        <div class="range-row"><span>Reservadas</span><strong>${item.reserved ?? 0}</strong></div>
        <div class="range-row"><span>Disponíveis</span><strong>${item.available ?? 0}</strong></div>
        <div class="range-row"><span>Uso</span><strong>${item.usage_pct ?? 0}%</strong></div>
    `;
    return card;
}

function formatHeartbeat(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) return date.toLocaleString("pt-BR");
    return String(value);
}

function renderAgentSummary(agent) {
    const status = String(agent.health || agent.health_status || agent.status || "unknown");
    setText("agent-info-hostname", agent.hostname || agent.name || agent.node_id || agent.id);
    setText("agent-info-address", agent.address || agent.ip || agent.public_host || "—");
    setText("agent-info-system", agent.system || agent.os || agent.platform || "—");
    setText("agent-info-version", agent.version || agent.agent_version || agent.installed_version || "—");
    setText("agent-info-health", status);
    setText(
        "agent-info-heartbeat",
        formatHeartbeat(agent.last_heartbeat || agent.heartbeat_at || agent.last_seen || agent.updated_at)
    );

    const badge = byId("agent-detail-health-badge");
    if (badge) {
        const online = ["online", "healthy", "ok", "active"].includes(status.toLowerCase());
        badge.textContent = online ? "Online" : status;
        badge.classList.toggle("offline", !online);
    }
}

async function loadAgent(agentId) {
    if (!agentId) return;
    errorMessage();

    try {
        const result = await request(`/agent/ports?agent_id=${encodeURIComponent(agentId)}`);
        if (!result?.agent) throw new Error("Resposta do Agent inválida.");

        selectedAgent = result.agent.id;

        const detail = byId("agent-detail");
        if (!detail) throw new Error("Área Informações do Agent não encontrada no Dashboard.");
        detail.hidden = false;

        setText("agent-detail-title", `${result.agent.name || result.agent.id} · ${result.agent.id}`);
        renderAgentSummary(result.agent);

        const ranges = byId("agent-ranges");
        if (ranges) {
            ranges.replaceChildren();
            (Array.isArray(result.ranges) ? result.ranges : []).forEach(item => {
                ranges.appendChild(rangeCard(item));
            });
        }

        const conflicts = byId("agent-conflicts");
        if (conflicts) {
            if (result.conflict_count) {
                conflicts.className = "conflict-box conflict-danger";
                conflicts.textContent = `${result.conflict_count} reserva(s) fora das faixas configuradas.`;
            } else {
                conflicts.className = "conflict-box";
                conflicts.textContent = "Nenhum conflito persistente detectado.";
            }
        }

        const first = Array.isArray(result.ranges) ? result.ranges[0] : null;
        if (first) {
            const start = byId("range-start");
            const end = byId("range-end");
            if (start) start.value = first.start_port;
            if (end) end.value = first.end_port;
        }

        detail.scrollIntoView({behavior: "smooth", block: "start"});
    } catch (error) {
        errorMessage(error.message);
    }
}

async function saveAgentLocation(event) {
    event.preventDefault();
    if (!selectedAgent) {
        errorMessage("Selecione um Agent.");
        return;
    }

    const datacenterElement = byId("agent-datacenter");
    const latitudeElement = byId("agent-latitude");
    const longitudeElement = byId("agent-longitude");
    const publicHostElement = byId("agent-public-host");
    const statusElement = byId("agent-location-status");

    if (!datacenterElement) return;
    const datacenter = datacenterElement.value;
    if (!datacenter) {
        errorMessage("Selecione um datacenter.");
        return;
    }

    const latitude = latitudeElement?.value.trim() || "";
    const longitude = longitudeElement?.value.trim() || "";
    const payload = {
        agent_id: selectedAgent,
        datacenter_id: datacenter,
        latitude: latitude === "" ? null : Number(latitude),
        longitude: longitude === "" ? null : Number(longitude),
        public_host: publicHostElement?.value.trim() || null,
        status: statusElement?.value || "active"
    };

    try {
        const result = await request("/agent/location", {
            method: "POST",
            body: JSON.stringify(payload)
        });
        errorMessage();
        await loadInfrastructure();
        renderDatacenters();
        if (result?.datacenter_id && byId("agent-datacenter")) {
            byId("agent-datacenter").value = result.datacenter_id;
        }
    } catch (error) {
        errorMessage(error.message);
    }
}

async function saveRange(event) {
    event.preventDefault();
    if (!selectedAgent) {
        errorMessage("Selecione um Agent.");
        return;
    }

    const protocol = byId("range-protocol");
    const start = byId("range-start");
    const end = byId("range-end");
    const force = byId("range-force");
    if (!protocol || !start || !end) return;

    const payload = {
        agent_id: selectedAgent,
        protocol: protocol.value,
        start_port: Number(start.value),
        end_port: Number(end.value),
        force: Boolean(force?.checked)
    };

    try {
        await request("/agent/ports/set", {
            method: "POST",
            body: JSON.stringify(payload)
        });
        await loadAgent(selectedAgent);
        await loadAgents();
    } catch (error) {
        errorMessage(error.message);
    }
}

async function initialize() {
    try {
        await loadSidebar();
        currentUser = await request("/whoami");
        if (!currentUser) return;

        if (!["admin", "controller"].includes(currentUser.role)) {
            throw new Error("Você não possui permissão para administrar Agents.");
        }

        setText("current-user", `${currentUser.username} (${currentUser.role})`);
        applyRole();

        bind("refresh-agents", "click", loadAgents);
        bind("agent-range-form", "submit", saveRange);
        bind("agent-location-form", "submit", saveAgentLocation);

        await loadInfrastructure();
        renderDatacenters();
        await loadAgents();
    } catch (error) {
        errorMessage(error.message);
    }
}

window.loadAgents = loadAgents;
window.loadAgent = loadAgent;

document.addEventListener("DOMContentLoaded", initialize);
