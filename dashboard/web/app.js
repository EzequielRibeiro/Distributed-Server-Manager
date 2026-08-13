/*
=============================================================
 DSM Dashboard Web - app.js v3.2.0 (Consolidated)
 Dashboard Principal com Suporte a Componentes
 Main Dashboard with Component Support
=============================================================
*/

"use strict";

/* ============================================================
 * CONFIGURAÇÃO | CONFIGURATION
 * ============================================================ */
const API = "/api";
const REFRESH_INTERVAL = 5000;
const MAX_POINTS = 30;
const DSM_DEBUG = true;

const COLORS = {
    cpu:"#00ff66",
    ram:"#ffd000"
};

/* ============================================================
 * DSM Logger
 * ============================================================ */
const Logger = {
    info(message, ...args) {
        if (!DSM_DEBUG) return;
        console.log(`%c[DSM][INFO] ${message}`, "color:#4CAF50;font-weight:bold;", ...args);
    },
    warn(message, ...args) {
        if (!DSM_DEBUG) return;
        console.warn(`%c[DSM][WARN] ${message}`, "color:#FFC107;font-weight:bold;", ...args);
    },
    error(message, ...args) {
        console.error(`%c[DSM][ERROR] ${message}`, "color:#F44336;font-weight:bold;", ...args);
    },
    api(endpoint, data = null) {
        if (!DSM_DEBUG) return;
        console.log(`%c[DSM][API] ${endpoint}`, "color:#03A9F4;font-weight:bold;", data);
    },
    event(type, data = null) {
        if (!DSM_DEBUG) return;
        console.log(`%c[DSM][EVENT] ${type}`, "color:#9C27B0;font-weight:bold;", data);
    }
};

/* ============================================================
 * ESTADO GLOBAL | GLOBAL STATE
 * ============================================================ */
let timelineEvents = [];
let timelineFilter = "all";
let cpuHistory = [];
let ramHistory = [];
let refreshTimer = null;

/* ============================================================
 * AUTENTICAÇÃO | AUTHENTICATION
 * ============================================================ */
function getAuth() {
    return sessionStorage.getItem("dsm_auth");
}

function checkAuth() {
    const auth = getAuth();
    if (!auth) {
         Logger.warn("Usuário não autenticado!");
         Logger.warn("User not authenticated!");
         window.location.replace("login.html");
         return false;
    }
    Logger.info("Autenticação validada!");
    Logger.info("Authentication validated!");
    return true;
}

function logout() {
     Logger.info("Logout solicitado.");
     Logger.info("Logout requested.");
     sessionStorage.clear();
     window.location.replace("login.html");
}

/* ============================================================
 * CLIENTE HTTP | HTTP CLIENT
 * ============================================================ */
async function apiRequest(endpoint, method = "GET", body = null) {
    Logger.api(endpoint, body);

    try {
        const headers = {
            Authorization: "Basic " + getAuth(),
            Accept: "application/json"
        };

        if (body !== null) {
            headers["Content-Type"] = "application/json";
        }

        const response = await fetch(`${API}/${endpoint}`, {
            method,
            headers,
            body:
                body !== null
                    ? JSON.stringify(body)
                    : undefined
        });
        Logger.api(endpoint, response.status);
        if (response.status === 401) {
            Logger.warn("Sessão expirada.");
            Logger.warn("Session expired.");
            logout();
            return null;
        }
        if (!response.ok) {
            Logger.error("Erro HTTP", endpoint, response.status);
            Logger.error("HTTP Error", endpoint, response.status);
            return null;
        }
        return await response.json();
    } catch (err) {
        Logger.error("Erro API", endpoint, err);
        Logger.error("API Error", endpoint, err);
        return null;
    }
}

async function apiGet(endpoint) {
    return apiRequest(endpoint, "GET");
}

async function apiPost(endpoint, body = null) {
    return apiRequest(endpoint, "POST", body);
}

/* ============================================================
 * HELPERS
 * ============================================================ */
function setText(id, value) {
    const el = document.getElementById(id);
    if (!el) {
            Logger.warn(
                `Elemento inexistente: ${id}`
            );
            Logger.warn(
                `Non-existent element: ${id}`
            );
            return;
        }
        el.innerText =
            value ?? "-";
}

function setHTML(id, value) {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = value ?? "";
}

function setStatus(id, status) {
    const el = document.getElementById(id);
    if (!el) return;
    const rawState = status && typeof status === "object"
        ? (status.state ?? status.status ?? "offline")
        : status;
    const state = String(rawState || "offline").toLowerCase();
    el.className = "status " + state;
    el.innerText = state.toUpperCase();
    Logger.info("Status atualizado:", state);
    Logger.info("Status updated:", state);
}

function progress(id, value) {
    const el = document.getElementById(id);
    if (!el) return;
    const pct = Number(value) || 0;
    el.style.width = pct + "%";
}

function formatPercent(value) { return Number(value || 0).toFixed(1) + "%"; }

function unixToLocale(timestamp) {
    if (!timestamp) return "-";
    return new Date(timestamp * 1000).toLocaleString();
}

function applyRBAC(role) {
    Logger.info("RBAC:", role);
    document.querySelectorAll(".admin-only").forEach(el => {
        el.style.display = role === "admin" ? "" : "none";
    });
    document.querySelectorAll(".instance-manager-only").forEach(el => {
        el.style.display = ["admin", "controller", "client", "customer"].includes(role) ? "" : "none";
    });
}

/* ============================================================
 * CARREGAMENTO DE COMPONENTES | COMPONENTS LOADING
 * ============================================================ */
async function loadComponent(id, file) {
    const element = document.getElementById(id);
    if (!element) return;
    try {
        const response = await fetch(file);
        if (!response.ok) throw new Error(file);
        element.innerHTML = await response.text();

        // Rebind logout if sidebar was loaded
        if (id === "sidebar-component") {
            const btnLogout = document.getElementById("btn-logout");
            if (btnLogout) btnLogout.onclick = logout;
        }
    } catch (error) {
        Logger.error("Erro carregando componente:", error);
        Logger.error("Error loading component:", error);
    }
}

/* ============================================================
 * LOADERS DE DADOS | DATA LOADERS
 * ============================================================ */
async function loadUser() {
    const data = await apiGet("whoami");
    if (!data) return;
    Logger.info("Usuário | User:", data);
    setText("current-user", `${data.username} (${data.role})`);
    applyRBAC(data.role);
}

async function loadServer() {
    const data = await apiGet("server");
    if (!data) return;
    setStatus("server-status", data.status);
    setText("server-name", data.name);
    setText("server-ip", data.ip);
    setText("server-pid", data.pid);
    setText("server-uptime", data.uptime);
    setText("server-players", data.players ?? 0);
    Logger.info("Servidor | Server:", data);
}

async function loadMetrics() {
    try {
        const response = await apiGet("metrics");
        if (!response) return;
        const data = response.data ?? response;

        progress("cpu-bar", data.cpu?.host_pct);
        setText("cpu-value", formatPercent(data.cpu?.host_pct));
        progress("ram-bar", 100 - Number(data.memory?.free_pct));
        setText("ram-value", formatPercent(100 - Number(data.memory?.free_pct)));
        progress("disk-bar", data.disk?.used_pct);
        setText("disk-value", formatPercent(data.disk?.used_pct));

        setText("host-name", data.system?.hostname);
        setText("kernel", data.system?.kernel);
        setText("uptime", data.system?.uptime);
        setText("dayz-processes", data.system?.dayz_processes);
        setText("dayz-memory", `${Number(data.memory?.dayz_mb ?? 0)} MB`);

        // Atualiza Histórico Realtime | Updates Realtime History
        cpuHistory.push(Number(data.cpu?.host_pct ?? 0));
        ramHistory.push(100 - Number(data.memory?.free_pct ?? 0));
        if (cpuHistory.length > MAX_POINTS) {
            cpuHistory.shift();
            ramHistory.shift();
        }
        Logger.info(`CPU ${data.cpu?.host_pct}% RAM ${100 - Number(data.memory?.free_pct)}%`);
        drawChart();
    } catch (err) {
        Logger.error("Erro Metrics:", err);
        Logger.error("Metrics Error:", err);
    }
}

async function loadMods() {
    const response = await apiGet("mods");
    if (!response) return;
    const data = response.data ?? response;
    setText("mods-total", data.total ?? 0);
    setText("mods-status", data.status ?? "-");
}

async function loadBackups() {
    const response = await apiGet("backups");
    if (!response) return;
    const data = response.data ?? response;
    setText("backup-total", data.total ?? 0);
    setText("backup-last", data.last_date ?? data.last ?? "-");
}

async function loadScheduler() {
    const response = await apiGet("scheduler");
    const container = document.getElementById("scheduler-list");
    if (!response || !container) return;
    const data = response.data ?? response;
    const jobs = Array.isArray(data.jobs) ? data.jobs : [];
    container.innerHTML = jobs.length === 0 ? '<div class="job-item">Nenhum job agendado | No jobs scheduled.</div>' : "";
    jobs.forEach(job => {
        const row = document.createElement("div");
        row.className = "job-item";
        row.innerHTML = `<div class="job-name">${job.name}</div><div class="job-status">${job.schedule}</div>`;
        container.appendChild(row);
    });
}

async function loadLogs() {
    const box =
        document.getElementById("logs");

    if (!box) return;

    const source =
        document.getElementById("log-source")
            ?.value ||
        "controller";

    const server =
        document.getElementById("catalog-v2-node")
            ?.value ||
        "";

    const game =
        document.getElementById("catalog-v2-game")
            ?.value ||
        "";

    const instance =
        document.getElementById("catalog-v2-instance")
            ?.value ||
        "";

    const params =
        new URLSearchParams({
            source,
            server,
            game,
            instance,
            limit: "500"
        });

    const response =
        await apiGet(
            `log-viewer?${params.toString()}`
        );

    if (!response) return;

    const data =
        response.data ??
        response;

    const context =
        document.getElementById(
            "logs-context"
        );

    if (context) {
        const labels = {
            controller: "Controller",
            agent: `Agent / Node ${server || ""}`,
            instance:
                instance ||
                "Instância"
        };

        context.textContent =
            labels[source] ||
            source;
    }

    box.replaceChildren();

    const logs =
        Array.isArray(data.logs)
            ? data.logs
            : [];

    logs.forEach(line => {
        const div =
            document.createElement("div");

        div.className =
            "log-line";

        /*
         * textContent evita interpretação
         * de HTML vindo dos logs.
         */
        div.textContent =
            line;

        box.appendChild(div);
    });

    if (!logs.length) {
        const empty =
            document.createElement("div");

        empty.className =
            "log-empty";

        empty.textContent =
            data.message ||
            "Nenhum log disponível.";

        box.appendChild(empty);
    }
}

async function loadHealth() {
    const response = await apiGet("health");
    if (!response) return;
    const data = response.data ?? response;
    setText("health-score", (data.score ?? 0) + "%");
    setText("health-status", data.status ?? "-");
}

/* ============================================================
 * TIMELINE
 * ============================================================ */
function timelineIcon(category) {
    const icons = { server: "🖥️", player: "👤", combat: "⚔️", mods: "🧩", backup: "💾", audit: "🔒", alert: "🚨", doctor: "🩺", monitor: "📊", scheduler: "⏰", notification: "📢", discord: "💬" };
    return icons[(category || "").toLowerCase()] || "📄";
}

async function loadTimeline(limit = 50) {
    const response = await apiGet(`timeline?limit=${limit}`);
    if (!response) return;
    timelineEvents = Array.isArray(response) ? response : (response.events ?? []);
    timelineEvents.sort((a, b) => (b.timestamp ?? b.time ?? 0) - (a.timestamp ?? a.time ?? 0));
    Logger.event("Timeline", timelineEvents.length);
    renderTimeline();
}

/* ============================================================
 * Criação de Item da Timeline | Timeline Item Creation
 * ============================================================ */
function createTimelineItem(event) {
    const item = document.createElement("div");
    item.className = "timeline-item";

    const category = event.category ?? event.source ?? "server";
    const title = event.type ?? event.action ?? "EVENT";
    const message = event.message ?? event.details ?? event.data?.message ?? event.data?.raw ?? "";
    const level = (event.level ?? "INFO").toUpperCase();
    const timestamp = event.timestamp ?? event.time ?? Math.floor(Date.now() / 1000);

    item.classList.add(`timeline-${level.toLowerCase()}`);
    item.innerHTML = `
        <div class="timeline-icon">${timelineIcon(category)}</div>
        <div class="timeline-body">
            <div class="timeline-header">
                <span class="timeline-title">${title}</span>
                <span class="timeline-level level-${level.toLowerCase()}">${level}</span>
            </div>
            <div class="timeline-message">${message}</div>
            <div class="timeline-footer">
                <span class="timeline-category">${category.toUpperCase()}</span>
                <span class="timeline-date">${unixToLocale(timestamp)}</span>
            </div>
        </div>`;

    Logger.event("Timeline Item", { category, title, level, timestamp });
    return item;
}

function renderTimeline() {
    const container = document.getElementById("timeline-list");
    if (!container) return;
    container.innerHTML = "";

    const list = timelineFilter === "all"
        ? timelineEvents
        : timelineEvents.filter(e => (e.category ?? e.source ?? "server") === timelineFilter);

    if (list.length === 0) {
        container.innerHTML = '<div class="timeline-empty">Nenhum evento encontrado | No events found.</div>';
        return;
    }

    list.forEach(event => {
        container.appendChild(createTimelineItem(event));
    });
}

function setTimelineFilter(filter) {
    timelineFilter = filter;
    renderTimeline();
}

/* ============================================================
 * GRÁFICOS | CHARTS
 * ============================================================ */

const nodeCpuHistory = [];
const nodeRamHistory = [];

let lastNodeHistoryIdentity = "";


function drawNodeChart() {
    const canvas =
        document.getElementById(
            "node-resource-chart"
        );

    if (!canvas) return;

    const ctx =
        canvas.getContext("2d");

    ctx.clearRect(
        0,
        0,
        canvas.width,
        canvas.height
    );

    const draw = (
        history,
        color
    ) => {
        if (!history.length) return;

        ctx.beginPath();

        history.forEach(
            (value, index) => {
                const x =
                    index *
                    (
                        canvas.width /
                        Math.max(
                            MAX_POINTS - 1,
                            1
                        )
                    );

                const normalized =
                    Math.max(
                        0,
                        Math.min(
                            100,
                            Number(value) || 0
                        )
                    );

                const y =
                    canvas.height -
                    (
                        normalized /
                        100
                    ) *
                    canvas.height;

                if (index === 0) {
                    ctx.moveTo(x, y);
                } else {
                    ctx.lineTo(x, y);
                }
            }
        );

        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.stroke();
    };

    draw(
        nodeCpuHistory,
        COLORS.cpu
    );

    draw(
        nodeRamHistory,
        COLORS.ram
    );

    if (nodeCpuHistory.length) {
        setText(
            "node-chart-cpu-value",
            formatPercent(
                nodeCpuHistory.at(-1)
            )
        );
    }

    if (nodeRamHistory.length) {
        setText(
            "node-chart-ram-value",
            formatPercent(
                nodeRamHistory.at(-1)
            )
        );
    }
}


async function loadNodeMetricsHistory() {
    const server =
        document.getElementById(
            "catalog-v2-node"
        )?.value || "";

    const game =
        document.getElementById(
            "catalog-v2-game"
        )?.value || "";

    const instance =
        document.getElementById(
            "catalog-v2-instance"
        )?.value || "";

    if (
        !server ||
        !game ||
        !instance
    ) {
        return;
    }

    const identity =
        `${server}/${game}/${instance}`;

    /*
     * Ao selecionar outro Node,
     * inicia uma nova série.
     */
    if (
        lastNodeHistoryIdentity &&
        lastNodeHistoryIdentity !== identity
    ) {
        nodeCpuHistory.length = 0;
        nodeRamHistory.length = 0;
    }

    lastNodeHistoryIdentity =
        identity;

    const params =
        new URLSearchParams({
            server,
            game,
            instance
        });

    const response =
        await apiGet(
            `runtime?${params.toString()}`
        );

    if (!response) return;

    const data =
        response.data ??
        response;

    const metrics =
        data.metrics || {};

    const cpu =
        Number(
            metrics.cpu?.host_pct ??
            0
        );

    const totalMemory =
        Number(
            metrics.memory?.total_mb ??
            0
        );

    const usedMemory =
        Number(
            metrics.memory?.used_mb ??
            0
        );

    const ramPercent =
        totalMemory > 0
            ? (
                usedMemory /
                totalMemory
            ) * 100
            : 0;

    nodeCpuHistory.push(cpu);
    nodeRamHistory.push(ramPercent);

    if (
        nodeCpuHistory.length >
        MAX_POINTS
    ) {
        nodeCpuHistory.shift();
    }

    if (
        nodeRamHistory.length >
        MAX_POINTS
    ) {
        nodeRamHistory.shift();
    }

    setText(
        "node-chart-title",
        `Node ${server}`
    );

    drawNodeChart();
}


function drawChart() {
    const canvas = document.getElementById("resource-chart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const draw = (history, color) => {
        if (history.length === 0) return;
        ctx.beginPath();
        history.forEach((val, i) => {
            const x = i * (canvas.width / MAX_POINTS);
            const y = canvas.height - (val / 100) * canvas.height;
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();
    };
    draw(cpuHistory, COLORS.cpu);
    draw(ramHistory, COLORS.ram);
    if (cpuHistory.length) setText("chart-cpu-value", formatPercent(cpuHistory.at(-1)));
    if (ramHistory.length) setText("chart-ram-value", formatPercent(ramHistory.at(-1)));
}

/* ============================================================
 * REFRESH E AÇÕES | REFRESH AND ACTIONS
 * ============================================================ */
async function refreshDashboard() {
    await Promise.all([
        loadServer(),
        loadMetrics(),
        loadNodeMetricsHistory(),
        loadMods(),
        loadBackups(),
        loadScheduler(),
        loadLogs(),
        loadHealth(),
        loadTimeline()
    ]);
    Logger.info("Dashboard atualizado.");
    Logger.info("Dashboard updated.");
}

function selectedInstanceIdentity() {
    return {
        server:
            document.getElementById("catalog-v2-node")
                ?.value || "",

        game:
            document.getElementById("catalog-v2-game")
                ?.value || "",

        instance:
            document.getElementById("catalog-v2-instance")
                ?.value || ""
    };
}


async function serverAction(action, msg) {
    const identity =
        selectedInstanceIdentity();

    if (
        !identity.server ||
        !identity.game ||
        !identity.instance
    ) {
        alert(
            "Selecione Node, jogo e instância."
        );
        return;
    }

    const btnStart =
        document.getElementById("btn-start");

    const btnStop =
        document.getElementById("btn-stop");

    const btnRestart =
        document.getElementById("btn-restart");

    const buttons = [
        btnStart,
        btnStop,
        btnRestart
    ];

    buttons.forEach(button => {
        if (button) {
            button.disabled = true;
        }
    });

    const endpoint =
        `instance/${action}`;

    Logger.event(
        endpoint,
        identity
    );

    try {
        const result = await apiPost(
            endpoint,
            identity
        );

        Logger.info(
            "Resposta da instância | Instance response:",
            result
        );

        if (result) {
            alert(
                result.message ||
                result.result ||
                msg
            );
        }

        /*
         * Atualiza imediatamente a área geral.
         */
        await refreshDashboard();

        /*
         * O catálogo mantém o resumo detalhado
         * da instância selecionada. Disparamos uma
         * atualização sem acoplamento direto entre
         * app.js e catalog-v2.js.
         */
        document
            .getElementById("catalog-v2-refresh")
            ?.click();

    } finally {
        buttons.forEach(button => {
            if (button) {
                button.disabled = false;
            }
        });
    }
}


window.startServer = () =>
    serverAction(
        "start",
        "Instância iniciada."
    );

window.stopServer = () =>
    serverAction(
        "stop",
        "Instância parada."
    );

window.restartServer = () =>
    serverAction(
        "restart",
        "Instância reiniciada."
    );
window.setTimelineFilter = setTimelineFilter;

/* ============================================================
 * EXPORTAR TIMELINE | EXPORT TIMELINE
 * ============================================================ */
async function exportTimeline(format = "json") {
    Logger.info(`Exportando | Exporting Timeline (${format})`);
    try {
        const response = await apiGet(`timeline?limit=1000`);
        if (!response) {
            Logger.warn("Nenhum evento disponível para exportação | No events available for export.");
            return;
        }
        const events = Array.isArray(response) ? response : (response.events ?? []);
        if (events.length === 0) {
            Logger.warn("Timeline vazia | Timeline empty.");
            return;
        }

        const filename = `timeline_${new Date().toISOString().replace(/[:.]/g, "-")}.${format}`;
        let content;
        let mime;

        if (format === "csv") {
            const header = "timestamp,category,type,level,message";
            const rows = events.map(event => [
                event.timestamp ?? event.time ?? "",
                event.category ?? event.source ?? "",
                event.type ?? event.action ?? "",
                event.level ?? "",
                `"${(event.message ?? event.details ?? "").replace(/"/g, '""')}"`
            ].join(","));
            content = [header, ...rows].join("\n");
            mime = "text/csv";
        } else {
            content = JSON.stringify(events, null, 2);
            mime = "application/json";
        }

        const blob = new Blob([content], { type: mime });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        Logger.info("Timeline exportada com sucesso | exported successfully.");
    } catch (err) {
        Logger.error("Erro ao exportar Timeline | Error exporting Timeline", err);
    }
}
window.exportTimeline = exportTimeline;

/* ============================================================
 * INICIALIZAÇÃO | INITIALIZATION
 * ============================================================ */
function startAutoRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(refreshDashboard, REFRESH_INTERVAL);
    Logger.info("Auto Refresh iniciado | started.");
}

document.addEventListener("DOMContentLoaded", async () => {
    if (!checkAuth()) return;

    // Carregar Componentes | Load Components
    await loadComponent("sidebar-component", "components/sidebar.html");
    await loadComponent("cards-component", "components/cards.html");
    await loadComponent("alerts-component", "components/alerts.html");

    if (typeof window.initializeNotifications === "function") {
        await window.initializeNotifications();
    }

    // Eventos de Botões | Button Events
    const btnStart = document.getElementById("btn-start");
    if (btnStart) btnStart.onclick = window.startServer;
    const btnStop = document.getElementById("btn-stop");
    if (btnStop) btnStop.onclick = window.stopServer;
    const btnRestart = document.getElementById("btn-restart");
    if (btnRestart) btnRestart.onclick = window.restartServer;
    const btnRefreshLogs = document.getElementById("btn-refresh-logs");
    if (btnRefreshLogs) btnRefreshLogs.onclick = loadLogs;

    const logSource = document.getElementById("log-source");
    if (logSource) {
        logSource.addEventListener(
            "change",
            () => loadLogs()
        );
    }

    await loadUser();
    await refreshDashboard();
    startAutoRefresh();
    Logger.info("Componentes carregados | Components loaded.");
});

document.addEventListener("visibilitychange", () => {
    if (document.hidden){
        Logger.info("Dashboard pausado | paused.");
        if (refreshTimer) {
            clearInterval(refreshTimer);
            refreshTimer = null;
        }
    } else {
        Logger.info("Dashboard retomado | resumed.");
        startAutoRefresh();
    }
});

window.addEventListener("resize", () => {
    drawChart();
    drawNodeChart();
});

/* ============================================================
 * GLOBAL ERROR HANDLER
 * ============================================================ */
window.addEventListener("error", (event) => {
    Logger.error("Erro JavaScript | JavaScript Error", event.message, {
        file: event.filename,
        line: event.lineno,
        column: event.colno
    });
});

/* ============================================================
 * UNHANDLED PROMISES
 * ============================================================ */
window.addEventListener("unhandledrejection", (event) => {
    Logger.error("Promise rejeitada | rejected", event.reason);
});
