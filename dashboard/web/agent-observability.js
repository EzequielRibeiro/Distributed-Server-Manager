"use strict";

(() => {
    const $ = id => document.getElementById(id);
    const params = new URLSearchParams(location.search);
    const agentId = params.get("agent_id") || "";
    const requestedView = params.get("view") || "monitoring";
    const views = new Set(["monitoring", "events", "diagnostics", "updates", "logs"]);
    const view = views.has(requestedView) ? requestedView : "monitoring";
    
    let agent = {};
    let refreshTimer = null;

    const labels = {
        monitoring: ["Monitoramento", "Métricas atuais exclusivamente deste Agent."],
        events: ["Eventos", "Eventos operacionais publicados por este Agent."],
        diagnostics: ["Diagnóstico", "Verificações de saúde e comunicação deste Agent."],
        updates: ["Atualizações", "Estado do rollout e versões deste Agent."],
        logs: ["Log", "Saída recente enviada por este Agent ao Controller."],
    };
    const queueLabels = {
        "capivara.runtime.queue.runtime.events": "Eventos pendentes",
        "capivara.runtime.queue.broadcast.state": "Broadcasts pendentes",
        "capivara.runtime.queue.backup.results": "Resultados de backup",
        "capivara.runtime.queue.game.data": "Tarefas de dados de jogos",
        "capivara.runtime.queue.provisioning": "Provisionamentos pendentes",
        "capivara.runtime.queue.instance.results": "Resultados de instâncias",
    };
    const metricPresentation = {
        "system.load.15": ["Carga média (15 min)", "Sistema"],
        "system.load.5": ["Carga média (5 min)", "Sistema"],
        "system.load.per_core": ["Carga por núcleo", "Sistema"],
        "system.uptime_seconds": ["Tempo ligado", "Sistema"],
        "memory.total_bytes": ["Memória total", "Memória"],
        "memory.available_bytes": ["Memória disponível", "Memória"],
        "disk.root.free_bytes": ["Espaço livre em disco", "Armazenamento"],
        "disk.root.used_ratio": ["Uso do disco", "Armazenamento"],
        "network.receive_bytes": ["Dados recebidos", "Rede"],
        "capivara.agent.pid": ["Identificador do processo", "Processo do Agent"],
        "capivara.agent.threads": ["Threads do processo", "Processo do Agent"],
        "capivara.agent.memory.rss_bytes": ["Memória usada pelo Agent", "Processo do Agent"],
        "capivara.agent.cpu.usage_pct": ["CPU usada pelo Agent", "Processo do Agent"],
        "capivara.host.network.tx_bytes_per_second": ["Velocidade de envio", "Rede"],
        "capivara.host.network.rx_bytes_per_second": ["Velocidade de recebimento", "Rede"],
        "capivara.host.network.tx_bytes": ["Total enviado", "Rede"],
        "capivara.host.network.rx_bytes": ["Total recebido", "Rede"],
        "capivara.host.uptime_seconds": ["Tempo ligado", "Sistema"],
        "capivara.host.load.15m": ["Carga média (15 min)", "Sistema"],
        "capivara.host.load.5m": ["Carga média (5 min)", "Sistema"],
        "capivara.host.load.1m": ["Carga média (1 min)", "Sistema"],
        "capivara.host.disk.total_bytes": ["Capacidade total", "Armazenamento"],
        "capivara.host.disk.used_bytes": ["Espaço utilizado", "Armazenamento"],
        "capivara.host.disk.usage_pct": ["Uso do disco", "Armazenamento"],
        "capivara.host.memory.total_bytes": ["Memória total", "Memória"],
        "capivara.host.memory.used_bytes": ["Memória utilizada", "Memória"],
        "capivara.host.memory.usage_pct": ["Uso da memória", "Memória"],
        "capivara.host.cpu.usage_pct": ["Uso da CPU", "Sistema"],
    };
    const legacyMetricReplacement = {
        "system.load.15": "capivara.host.load.15m",
        "system.load.5": "capivara.host.load.5m",
        "system.uptime_seconds": "capivara.host.uptime_seconds",
        "memory.total_bytes": "capivara.host.memory.total_bytes",
        "network.receive_bytes": "capivara.host.network.rx_bytes",
        "disk.root.used_ratio": "capivara.host.disk.usage_pct",
    };

    async function request(path) {
        const response = await fetch(path, {
            headers: {"X-Capivara-Auth-Area":"controller", Accept: "application/json"},
            cache: "no-store",
        });
        if (response.status === 401) {
            sessionStorage.clear();
            location.replace("login.html");
            throw new Error("Sessão expirada.");
        }
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.message || payload.error || `HTTP ${response.status}`);
        return payload;
    }

    function value(input, fallback = "—") {
        return input === null || input === undefined || input === "" ? fallback : String(input);
    }

    function time(input) {
        if (!input) return "—";
        const date = new Date(input);
        return Number.isNaN(date.getTime()) ? String(input) : date.toLocaleString("pt-BR");
    }

    const decimal = new Intl.NumberFormat("pt-BR", {maximumFractionDigits: 2});
    const integer = new Intl.NumberFormat("pt-BR", {maximumFractionDigits: 0});

    function formatBytes(input, suffix = "") {
        const number = Number(input);
        if (!Number.isFinite(number)) return value(input);
        const units = ["bytes", "KB", "MB", "GB", "TB", "PB"];
        let amount = Math.abs(number);
        let index = 0;
        while (amount >= 1024 && index < units.length - 1) {
            amount /= 1024;
            index += 1;
        }
        const signed = number < 0 ? -amount : amount;
        return `${decimal.format(signed)} ${units[index]}${suffix}`;
    }

    function formatDuration(input) {
        const seconds = Number(input);
        if (!Number.isFinite(seconds)) return value(input);
        if (seconds < 60) return `${decimal.format(seconds)} s`;
        if (seconds < 3600) return `${integer.format(Math.floor(seconds / 60))} min ${integer.format(Math.floor(seconds % 60))} s`;
        if (seconds < 86400) return `${integer.format(Math.floor(seconds / 3600))} h ${integer.format(Math.floor((seconds % 3600) / 60))} min`;
        return `${integer.format(Math.floor(seconds / 86400))} d ${integer.format(Math.floor((seconds % 86400) / 3600))} h`;
    }

    function formatMetric(input, unit = "", metricName = "") {
        const normalized = String(unit || "").trim().toLowerCase();
        const number = Number(input);
        if (!Number.isFinite(number)) return value(input);
        if (["byte", "bytes"].includes(normalized)) return formatBytes(number);
        if (["byte_per_second", "bytes_per_second", "bytes/second", "b/s"].includes(normalized)) return formatBytes(number, "/s");
        if (metricName.endsWith("_ratio")) return `${decimal.format(number * 100)}%`;
        if (metricName.endsWith("_pct") || ["percent", "percentage", "%"].includes(normalized)) return `${decimal.format(number)}%`;
        if (metricName.endsWith("_bytes")) return formatBytes(number);
        if (metricName.endsWith("_seconds")) return formatDuration(number);
        if (["second", "seconds", "s"].includes(normalized)) return formatDuration(number);
        if (["celsius", "°c", "c"].includes(normalized)) return `${decimal.format(number)} °C`;
        if (["pid", "threads", "items", "count"].includes(normalized)) return integer.format(number);
        if (["load", "ratio"].includes(normalized)) return decimal.format(number);
        return `${decimal.format(number)}${normalized ? ` ${unit}` : ""}`;
    }

    function item(label, content, detail = "", rawValue = "") {
        const article = document.createElement("article");
        article.className = "cap-agent-context-item";
        const name = document.createElement("span");
        const strong = document.createElement("strong");
        name.textContent = label;
        strong.textContent = value(content);
        if (rawValue !== "") strong.title = `Valor bruto: ${rawValue}`;
        article.append(name, strong);
        if (detail) {
            const small = document.createElement("small");
            small.textContent = detail;
            article.append(small);
        }
        return article;
    }

    function showError(message = "") {
        const box = $("agent-context-error");
        box.hidden = !message;
        box.textContent = message;
    }

    function setContent(...nodes) {
        $("agent-view-content").replaceChildren(...nodes);
    }

    function grid(nodes) {
        const container = document.createElement("div");
        container.className = "cap-agent-context-grid";
        container.append(...nodes);
        return container;
    }

    function humanMetricName(name) {
        if (metricPresentation[name]) return metricPresentation[name][0];
        return String(name || "Métrica")
            .replace(/^capivara\./, "")
            .replace(/[._]+/g, " ")
            .replace(/\b\w/g, letter => letter.toUpperCase());
    }

    function metricGroup(name) {
        return metricPresentation[name]?.[1] || "Outras métricas";
    }

    function metricSection(name, nodes) {
        const section = document.createElement("section");
        section.className = "cap-agent-metric-section";
        const title = document.createElement("h3");
        title.textContent = name;
        section.append(title, grid(nodes));
        return section;
    }

    function queueSummary(metrics) {
        const entries = metrics.map(metric => {
            const name = metric.metric_name || metric.name || metric.key || "";
            const raw = metric.value ?? metric.metric_value ?? metric.latest ?? 0;
            return {name, label: queueLabels[name] || name, value: Number(raw) || 0};
        });
        const total = entries.reduce((sum, entry) => sum + entry.value, 0);
        const card = document.createElement("section");
        card.className = "cap-agent-queue-summary";
        card.dataset.state = total > 0 ? "pending" : "healthy";
        const heading = document.createElement("div");
        const copy = document.createElement("div");
        const title = document.createElement("span");
        const status = document.createElement("strong");
        const badge = document.createElement("b");
        title.textContent = "Filas operacionais";
        status.textContent = total > 0 ? `${integer.format(total)} pendência(s)` : "Sem pendências";
        badge.textContent = total > 0 ? "ATENÇÃO" : "SAUDÁVEL";
        copy.append(title, status);
        heading.append(copy, badge);
        const details = document.createElement("details");
        const summary = document.createElement("summary");
        const list = document.createElement("div");
        summary.textContent = "Ver detalhes das filas";
        list.className = "cap-agent-queue-list";
        entries.forEach(entry => {
            const row = document.createElement("div");
            const label = document.createElement("span");
            const count = document.createElement("strong");
            label.textContent = entry.label;
            label.title = entry.name;
            count.textContent = integer.format(entry.value);
            row.append(label, count);
            list.append(row);
        });
        details.append(summary, list);
        card.append(heading, details);
        return card;
    }

    async function loadIdentity() {
        const result = await request(`/api/agent/ports?agent_id=${encodeURIComponent(agentId)}`);
        agent = result.agent || {};
        const name = agent.name || agent.hostname || agent.node_id || agent.id || agentId;
        $("agent-context-title").textContent = name;
        $("agent-context-subtitle").textContent = `Agent ${agent.id || agentId} · ${labels[view][0]}`;
        document.title = `${name} · ${labels[view][0]}`;
    }

    async function loadMonitoring() {
        const result = await request(`/api/observability?mode=latest&agent_id=${encodeURIComponent(agentId)}&limit=200`);
        const metrics = Array.isArray(result.metrics) ? result.metrics : [];
        const queueMetrics = metrics.filter(metric => queueLabels[metric.metric_name || metric.name || metric.key]);
        const availableNames = new Set(metrics.map(metric => metric.metric_name || metric.name || metric.key));
        const regularMetrics = metrics.filter(metric => {
            const name = metric.metric_name || metric.name || metric.key;
            return !queueLabels[name] && !(legacyMetricReplacement[name] && availableNames.has(legacyMetricReplacement[name]));
        });
        const grouped = new Map();
        regularMetrics.forEach(metric => {
            const name = metric.metric_name || metric.name || metric.key || "Métrica";
            const raw = metric.value ?? metric.metric_value ?? metric.latest ?? metric.status;
            const node = item(
                humanMetricName(name),
                formatMetric(raw, metric.unit, name),
                metric.timestamp ? time(metric.timestamp) : "",
                raw,
            );
            node.title = `${name} · Valor bruto: ${raw}`;
            const group = metricGroup(name);
            if (!grouped.has(group)) grouped.set(group, []);
            grouped.get(group).push(node);
        });
        const sections = [];
        if (queueMetrics.length) sections.push(queueSummary(queueMetrics));
        ["Sistema", "Memória", "Armazenamento", "Rede", "Processo do Agent", "Outras métricas"].forEach(group => {
            const nodes = grouped.get(group);
            if (nodes?.length) sections.push(metricSection(group, nodes));
        });
        setContent(...(sections.length ? sections : [empty("Nenhuma métrica publicada por este Agent.")]));
    }

    function eventMessage(event) {
        return event.message || event.details || event.data?.message || event.event_type || event.type || "Evento";
    }

    async function loadEvents() {
        const result = await request(`/api/events?agent_id=${encodeURIComponent(agentId)}&limit=200`);
        const events = Array.isArray(result) ? result : (result.events || []);
        const list = document.createElement("div");
        events.forEach(event => {
            const row = document.createElement("article");
            row.className = "cap-agent-event";
            const when = document.createElement("time");
            const body = document.createElement("div");
            const message = document.createElement("p");
            const source = document.createElement("small");
            when.textContent = time(event.timestamp || event.time || event.created_at || event.received_at);
            message.textContent = eventMessage(event);
            source.textContent = [event.severity || event.level, event.source || event.producer].filter(Boolean).join(" · ") || "Agent";
            body.append(message, source);
            row.append(when, body);
            list.append(row);
        });
        setContent(events.length ? list : empty("Nenhum evento registrado para este Agent."));
    }

    function check(label, ok, detail) {
        const row = document.createElement("article");
        row.className = "cap-agent-check";
        row.dataset.state = ok ? "healthy" : "failed";
        const body = document.createElement("div");
        const title = document.createElement("b");
        const note = document.createElement("small");
        const state = document.createElement("strong");
        title.textContent = label;
        note.textContent = detail;
        state.textContent = ok ? "OK" : "ATENÇÃO";
        body.append(title, document.createElement("br"), note);
        row.append(body, state);
        return row;
    }

    async function loadDiagnostics() {
        const update = await request(`/api/agents/updates/status?agent_id=${encodeURIComponent(agentId)}`);
        const health = String(agent.health || agent.health_status || agent.status || "").toLowerCase();
        const heartbeat = agent.last_heartbeat || agent.heartbeat_at || agent.last_seen || agent.updated_at;
        const heartbeatAge = heartbeat ? Date.now() - new Date(heartbeat).getTime() : Infinity;
        const nodes = [
            check("Estado operacional", ["online", "active", "healthy"].includes(health), `Estado informado: ${value(health)}`),
            check("Heartbeat", heartbeatAge < 120000, `Último heartbeat: ${time(heartbeat)}`),
            check("Identidade", Boolean(agent.id || agentId), `Agent: ${agent.id || agentId} · Node: ${value(agent.node_id)}`),
            check("Versão", Boolean(update.installed_version), `Instalada: ${value(update.installed_version)} · Desejada: ${value(update.desired_version)}`),
            check("Atualização", update.update_status !== "failed", `Status: ${value(update.update_status)}${update.last_error ? ` · ${update.last_error}` : ""}`),
        ];
        setContent(grid(nodes));
    }

    async function loadUpdates() {
        const status = await request(`/api/agents/updates/status?agent_id=${encodeURIComponent(agentId)}`);
        const card = document.createElement("div");
        card.className = "cap-agent-update-state";
        card.dataset.state = status.update_status || "idle";
        const title = document.createElement("h3");
        title.textContent = value(status.update_status, "idle");
        card.append(title, grid([
            item("Versão instalada", status.installed_version),
            item("Versão desejada", status.desired_version || status.available_version),
            item("Canal", status.update_channel),
            item("Rollout", status.rollout_id),
            item("Lote", status.batch_number),
            item("Última atualização", time(status.last_update || status.updated_at)),
        ]));
        if (status.last_error) {
            const details = document.createElement("details");
            details.className = "cap-agent-update-details";
            const summary = document.createElement("summary");
            const pre = document.createElement("pre");
            summary.textContent = "Ver detalhes do erro";
            pre.textContent = status.last_error;
            details.append(summary, pre);
            card.append(details);
        }
        setContent(card);
    }

    async function loadLogs() {
        const previous = $("agent-view-content").querySelector(".cap-agent-log");
        const previousScrollTop = previous?.scrollTop || 0;
        const wasFollowingLatest = !previous || previous.scrollHeight - previous.scrollTop - previous.clientHeight < 32;
        const query = new URLSearchParams({source: "agent", server: agentId, game: "", instance: "", limit: "500"});
        const response = await request(`/api/log-viewer?${query}`);
        const data = response.data || response || {};
        const logs = Array.isArray(data.logs) ? data.logs : [];
        if (!logs.length) return setContent(empty(data.message || "Nenhum log disponível para este Agent."));
        const box = document.createElement("div");
        box.className = "cap-agent-log";
        logs.forEach(line => {
            const row = document.createElement("div");
            row.className = "cap-agent-log-line";
            row.textContent = line;
            box.append(row);
        });
        setContent(box);
        if (wasFollowingLatest) box.scrollTop = box.scrollHeight;
        else box.scrollTop = Math.min(previousScrollTop, box.scrollHeight - box.clientHeight);
    }

    function empty(message) {
        const node = document.createElement("div");
        node.className = "cap-agent-context-empty";
        node.textContent = message;
        return node;
    }

    async function refresh() {
        clearTimeout(refreshTimer);
        $("agent-view-live-state").textContent = "Atualizando…";
        $("agent-view-content").classList.add("cap-agent-context-loading");
        try {
            await loadIdentity();
            await ({monitoring: loadMonitoring, events: loadEvents, diagnostics: loadDiagnostics, updates: loadUpdates, logs: loadLogs}[view])();
            showError();
            $("agent-view-live-state").textContent = `Atualizado ${new Date().toLocaleTimeString("pt-BR")}`;
        } catch (error) {
            showError(error.message);
            $("agent-view-live-state").textContent = "Falha ao atualizar";
        } finally {
            $("agent-view-content").classList.remove("cap-agent-context-loading");
            refreshTimer = setTimeout(refresh, ["monitoring", "logs", "updates"].includes(view) ? 5000 : 15000);
        }
    }

    async function sidebar() {
        const response = await fetch("components/sidebar-v3.html", {cache: "no-store"});
        if (response.ok) $("sidebar-component").innerHTML = await response.text();
        $("btn-logout")?.addEventListener("click", () => { sessionStorage.clear(); location.replace("login.html"); });
        document.querySelectorAll("nav a").forEach(link => link.classList.toggle("active", link.getAttribute("href") === "agents.html"));
        const who = await request("/api/whoami");
        $("agent-context-user").textContent = who.username || "Usuário";
        $("agent-context-role").textContent = who.role || "";
    }

    async function init() {
        if (!auth()) return location.replace("login.html");
        if (!agentId) {
            showError("Agent não informado na URL.");
            return;
        }
        const [title, description] = labels[view];
        $("agent-view-title").textContent = title;
        $("agent-view-description").textContent = description;
        $("agent-context-back").href = `agent-details.html?agent_id=${encodeURIComponent(agentId)}`;
        document.querySelectorAll("#agent-context-nav [data-view]").forEach(link => {
            const targetView = link.dataset.view;
            link.href = `agent-observability.html?agent_id=${encodeURIComponent(agentId)}&view=${targetView}`;
            link.classList.toggle("active", targetView === view);
        });
        $("agent-context-refresh").addEventListener("click", refresh);
        $("agent-context-menu-toggle").addEventListener("click", () => document.body.classList.toggle(window.innerWidth <= 760 ? "sidebar-open" : "cap-sidebar-collapsed"));
        await sidebar();
        await refresh();
    }

    document.addEventListener("DOMContentLoaded", init);
})();
