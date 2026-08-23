"use strict";

const HOME_API = "/api";
const $ = id => document.getElementById(id);

function auth() {
    const token = sessionStorage.getItem("dsm_auth");
    if (!token) {
        window.location.replace("/login.html");
        throw new Error("auth required");
    }
    return {
        Authorization: `Basic ${token}`,
        Accept: "application/json"
    };
}

async function get(path) {
    try {
        const response = await fetch(`${HOME_API}${path}`, {
            headers: auth(),
            cache: "no-store"
        });
        if (response.status === 401) {
            sessionStorage.clear();
            window.location.replace("/login.html");
            return null;
        }
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        console.warn("[Capivara Home]", path, error);
        return null;
    }
}

function text(id, value, fallback = "—") {
    const element = $(id);
    if (element) element.textContent = value ?? fallback;
}

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "\"": "&quot;",
        "'": "&#39;"
    })[char]);
}

function isOnline(agent) {
    return ["online", "healthy", "ok", "active", "running"].includes(
        String(agent?.health_status || agent?.health || agent?.status || "").toLowerCase()
    );
}

function formatTime(value) {
    if (!value) return "—";
    const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
    return Number.isNaN(date.getTime())
        ? String(value)
        : date.toLocaleTimeString("pt-BR", {hour: "2-digit", minute: "2-digit"});
}

function eventText(event) {
    const type = String(event?.type || event?.action || "Evento")
        .replaceAll("_", " ")
        .toLowerCase();
    const message = event?.message || event?.details || event?.data?.message || "";
    return message ? `${type} · ${message}` : type;
}

function renderAgents(result) {
    const agents = Array.isArray(result?.agents) ? result.agents : [];
    const online = agents.filter(isOnline).length;
    const instances = agents.reduce((total, agent) => total + Number(agent.instance_count || 0), 0);
    const running = agents.reduce(
        (total, agent) => total + Number(agent.running_instance_count || agent.instances_running || 0),
        0
    );

    text("home-agent-total", agents.length);
    text("home-agent-online", `${online} online`);
    text("home-agent-offline", `${Math.max(0, agents.length - online)} offline`);
    text("home-instance-total", instances);
    text("home-instance-total-copy", instances);
    text("home-running-total", running);
    text("home-infra-agents", agents.length);
    text("home-infra-online", online);

    const list = $("home-agent-bars");
    if (list) {
        const maxInstances = Math.max(1, ...agents.map(agent => Number(agent.instance_count || 0)));
        list.innerHTML = agents.slice(0, 7).map(agent => {
            const count = Number(agent.instance_count || 0);
            const pct = Math.round((count / maxInstances) * 100);
            return `
                <div class="cap-bar-row">
                    <span>${escapeHtml(agent.name || agent.id)}</span>
                    <div class="cap-bar"><i style="width:${pct}%"></i></div>
                    <b>${count}</b>
                </div>`;
        }).join("") || '<div class="cap-empty">Nenhum Agent registrado.</div>';
    }

    const health = $("home-health-agents");
    if (health) {
        health.textContent = agents.length ? `${online} / ${agents.length} online` : "Nenhum Agent";
        health.className = online === agents.length && agents.length ? "cap-good" : "cap-warn";
    }
}

function renderInfrastructure(data) {
    let regions = 0;
    let datacenters = 0;

    function walk(value) {
        if (!value) return;
        if (Array.isArray(value)) {
            value.forEach(walk);
            return;
        }
        if (typeof value !== "object") return;
        if (value.type === "region") regions += 1;
        if (value.type === "datacenter") datacenters += 1;
        Object.values(value).forEach(walk);
    }

    walk(data);
    text("home-infra-regions", regions);
    text("home-infra-datacenters", datacenters);
}

function renderTimeline(result) {
    const events = Array.isArray(result) ? result : (result?.events || []);
    const list = $("home-events");

    if (list) {
        list.innerHTML = events.slice(0, 5).map(event => `
            <div class="cap-event">
                <time>${escapeHtml(formatTime(event.timestamp || event.time))}</time>
                <i class="cap-event-dot"></i>
                <div>
                    <p>${escapeHtml(eventText(event))}</p>
                    <small>${escapeHtml(event.category || event.source || "Sistema")}</small>
                </div>
            </div>`).join("") || '<div class="cap-empty">Nenhuma atividade recente.</div>';
    }

    const important = events.filter(event =>
        ["warning", "warn", "error", "critical", "fatal"].includes(
            String(event.level || "").toLowerCase()
        )
    );

    const alerts = $("home-alerts");
    if (alerts) {
        alerts.innerHTML = important.slice(0, 3).map(event => {
            const critical = ["error", "critical", "fatal"].includes(
                String(event.level || "").toLowerCase()
            );
            return `
                <article class="cap-alert ${critical ? "" : "warning"}">
                    <strong class="${critical ? "cap-bad" : "cap-warn"}">
                        ${escapeHtml(String(event.level || "WARNING").toUpperCase())}
                    </strong>
                    <p>${escapeHtml(eventText(event))}</p>
                    <time>${escapeHtml(formatTime(event.timestamp || event.time))}</time>
                </article>`;
        }).join("") || '<div class="cap-empty">Nenhum alerta importante no período.</div>';
    }

    text("home-alert-total", important.length);
}

function renderHealth(result) {
    const data = result?.data || result || {};
    const status = String(data.status || "").toLowerCase();
    const failed = ["failed", "critical", "offline", "error"].includes(status);

    text("home-controller-health", data.status || "Operacional");

    const dot = $("home-controller-dot");
    if (dot) dot.classList.toggle("off", failed);

    const topStatus = document.querySelector(".cap-controller-state");
    if (topStatus) {
        topStatus.classList.toggle("cap-controller-failed", failed);
        const label = topStatus.querySelector("span");
        if (label) label.textContent = failed ? "Controller com falha" : "Controller Online";
    }
}

function renderUser(user) {
    const role = user?.role || "";
    text("home-user-name", user?.username || "Usuário");
    text("home-user-role", role);
    text("current-user", user?.username || "Sessão ativa");

    document.querySelectorAll(".admin-only").forEach(element => {
        element.style.display = role === "admin" ? "" : "none";
    });
    document.querySelectorAll(".agent-manager-only").forEach(element => {
        element.style.display = ["admin", "controller"].includes(role) ? "" : "none";
    });
    document.querySelectorAll(".instance-manager-only").forEach(element => {
        element.style.display = ["admin", "controller", "client", "customer"].includes(role)
            ? ""
            : "none";
    });
}

async function refresh() {
    const [user, agents, infrastructure, timeline, health] = await Promise.all([
        get("/whoami"),
        get("/agents"),
        get("/infrastructure?active_only=true"),
        get("/timeline?limit=30"),
        get("/health")
    ]);

    if (user) renderUser(user);
    renderAgents(agents);
    renderInfrastructure(infrastructure);
    renderTimeline(timeline);
    renderHealth(health);
    text("home-last-refresh", new Date().toLocaleTimeString("pt-BR"));
}

async function loadSidebar() {
    const target = $("sidebar-component");
    if (!target) return;

    const response = await fetch("/components/sidebar-v3.html", {cache: "no-store"});
    if (response.ok) target.innerHTML = await response.text();

    const logout = $("btn-logout");
    if (logout) {
        logout.onclick = () => {
            sessionStorage.clear();
            window.location.replace("/login.html");
        };
    }
}

document.addEventListener("DOMContentLoaded", async () => {
    await loadSidebar();

    $("home-menu-toggle")?.addEventListener("click", () => {
        if (window.innerWidth <= 760) document.body.classList.toggle("sidebar-open");
        else document.body.classList.toggle("cap-sidebar-collapsed");
    });

    $("home-refresh")?.addEventListener("click", refresh);

    await refresh();
    window.setInterval(refresh, 30000);
});
