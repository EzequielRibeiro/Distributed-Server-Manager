(function () {
    "use strict";

    const el = id => document.getElementById(id);
    const params = new URLSearchParams(location.search);
    const agentId = params.get("agent_id") || params.get("id") || "";
    let currentRole = "";
    let currentAdmin = null;
    let collapsed = false;

    async function request(path, options = {}) {
        const headers = {
            "X-Capivara-Auth-Area": "controller",
            Accept: "application/json",
            ...(options.headers || {})
        };
        if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";

        const response = await fetch(path, {
            ...options,
            headers,
            credentials: "same-origin",
            cache: "no-store"
        });

        if (response.status === 401) {
            location.replace("login.html");
            throw new Error("Sessão expirada");
        }

        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.message || payload.error || `HTTP ${response.status}`);
        return payload;
    }

    function post(path, payload) {
        return request(path, {method: "POST", body: JSON.stringify(payload)});
    }

    function text(id, value) {
        const node = el(id);
        if (node) node.textContent = value ?? "—";
    }

    function value(raw, fallback = "—") {
        return raw === null || raw === undefined || raw === "" ? fallback : String(raw);
    }

    function heartbeat(raw) {
        if (!raw) return "—";
        const parsed = new Date(raw);
        return Number.isNaN(parsed.getTime()) ? String(raw) : parsed.toLocaleString("pt-BR");
    }

    function showError(error) {
        const box = el("agent-detail-error");
        if (!box) return;
        box.hidden = false;
        box.textContent = error?.message || String(error);
    }

    function hideError() {
        const box = el("agent-detail-error");
        if (box) box.hidden = true;
    }

    function applySidebar(isCollapsed) {
        collapsed = Boolean(isCollapsed);
        document.body.classList.toggle("cap-sidebar-collapsed", collapsed);
        localStorage.setItem("cap_sidebar_collapsed", collapsed ? "1" : "0");
    }

    function setMobileMenu(open) {
        const toggle = el("agent-detail-menu-toggle");
        const active = Boolean(open) && innerWidth <= 760;
        document.body.classList.toggle("sidebar-open", active);
        toggle?.setAttribute("aria-expanded", active ? "true" : "false");
        toggle?.setAttribute("aria-label", active ? "Fechar menu" : "Abrir menu");
    }

    function bindMenu() {
        el("agent-detail-menu-toggle")?.addEventListener("click", event => {
            event.stopPropagation();
            if (innerWidth <= 760) {
                setMobileMenu(!document.body.classList.contains("sidebar-open"));
                return;
            }
            applySidebar(!collapsed);
        });
    }

    async function sidebar() {
        const host = el("sidebar-component");
        if (!host) throw new Error("Container do menu lateral não encontrado.");

        const response = await fetch("/components/sidebar-v3.html", {
            headers: {"X-Capivara-Auth-Area": "controller"},
            credentials: "same-origin",
            cache: "no-store"
        });

        if (response.status === 401) {
            location.replace("login.html");
            throw new Error("Sessão expirada");
        }
        if (!response.ok) throw new Error(`sidebar HTTP ${response.status}`);

        host.innerHTML = await response.text();
        host.querySelectorAll("nav a").forEach(link => {
            link.classList.toggle("active", link.getAttribute("href") === "agents.html");
        });
        host.querySelectorAll("a").forEach(link => link.addEventListener("click", () => setMobileMenu(false)));
        host.querySelector(".cap-sidebar-close")?.addEventListener("click", () => setMobileMenu(false));

        el("btn-logout")?.addEventListener("click", async event => {
            event.preventDefault();
            try {
                await fetch("/api/auth/logout", {
                    method: "POST",
                    headers: {"X-Capivara-Auth-Area": "controller"},
                    credentials: "same-origin",
                    cache: "no-store"
                });
            } finally {
                location.replace("login.html");
            }
        });

        const who = await request("/api/whoami");
        currentRole = String(who.role || "").toLowerCase();
        text("current-user", `${who.username} (${who.role})`);
        text("agent-detail-user", who.username);
        text("agent-detail-role", who.role);

        document.querySelectorAll(".admin-only").forEach(node => node.hidden = currentRole !== "admin");
        document.querySelectorAll(".agent-manager-only").forEach(node => node.hidden = !["admin", "controller"].includes(currentRole));
        if (!["admin", "controller"].includes(currentRole)) throw new Error("Você não possui permissão para administrar Agents.");

        applySidebar(localStorage.getItem("cap_sidebar_collapsed") === "1");
    }

    function rangeCard(range) {
        const node = document.createElement("div");
        node.className = "cap-range-card";
        const protocol = value(range.protocol, "").toUpperCase();
        node.innerHTML = `<strong>${protocol} ${value(range.start_port, "?")}-${value(range.end_port, "?")}</strong><span>${value(range.available, 0)} disponíveis · ${value(range.reserved, 0)} reservadas · ${value(range.usage_pct, 0)}% de uso</span>`;
        return node;
    }

    const metricPaths = {
        "capivara.host.cpu.usage_pct": "host.cpu_usage_pct",
        "capivara.host.memory.usage_pct": "host.memory.usage_pct",
        "capivara.host.memory.used_bytes": "host.memory.used_bytes",
        "capivara.host.memory.total_bytes": "host.memory.total_bytes",
        "capivara.host.disk.usage_pct": "host.disk.usage_pct",
        "capivara.host.disk.used_bytes": "host.disk.used_bytes",
        "capivara.host.disk.total_bytes": "host.disk.total_bytes",
        "capivara.host.disk.read_bytes_per_second": "host.disk.read_bytes_per_second",
        "capivara.host.disk.write_bytes_per_second": "host.disk.write_bytes_per_second",
        "capivara.host.disk.read_iops": "host.disk.read_iops",
        "capivara.host.disk.write_iops": "host.disk.write_iops",
        "capivara.host.load.1m": "host.load_average.1m",
        "capivara.host.load.5m": "host.load_average.5m",
        "capivara.host.load.15m": "host.load_average.15m",
        "capivara.host.uptime_seconds": "host.uptime_seconds",
        "capivara.host.network.rx_bytes": "host.network.rx_bytes",
        "capivara.host.network.tx_bytes": "host.network.tx_bytes",
        "capivara.host.network.rx_bytes_per_second": "host.network.rx_bytes_per_second",
        "capivara.host.network.tx_bytes_per_second": "host.network.tx_bytes_per_second",
        "capivara.host.temperature_c": "host.temperature_c",
        "capivara.agent.cpu.usage_pct": "agent.cpu_usage_pct",
        "capivara.agent.memory.rss_bytes": "agent.memory_rss_bytes",
        "capivara.agent.threads": "agent.threads",
        "capivara.agent.pid": "agent.pid",
        "capivara.agent.players.online": "node_activity.players_online",
        "capivara.agent.players.capacity": "node_activity.players_capacity",
        "capivara.agent.instances.running": "node_activity.instances_running",
        "capivara.agent.instances.total": "node_activity.instances_total",
        "capivara.agent.storage.free_bytes": "node_activity.storage_free_bytes",
        "capivara.agent.instances.storage_used_bytes": "node_activity.storage_used_bytes"
    };

    function assign(root, path, raw) {
        const keys = path.split(".");
        let target = root;
        keys.forEach((key, index) => {
            if (index === keys.length - 1) target[key] = raw;
            else target = target[key] || (target[key] = {});
        });
    }

    function telemetryHistory(rows) {
        const buckets = new Map();
        (rows || []).forEach(row => {
            const path = metricPaths[row.metric_name];
            if (!path) return;
            const stamp = String(row.collected_at || row.ingested_at || "");
            if (!buckets.has(stamp)) {
                buckets.set(stamp, {
                    collected_at_unix: new Date(stamp).getTime() / 1000,
                    host: {}, agent: {}, node_activity: {}
                });
            }
            assign(buckets.get(stamp), path, Number(row.value));
        });
        return [...buckets.values()].sort((a, b) => a.collected_at_unix - b.collected_at_unix);
    }

    async function loadTelemetry(current) {
        const since = new Date(Date.now() - 3600 * 1000).toISOString();
        const result = await request(`/api/observability?mode=history&agent_id=${encodeURIComponent(agentId)}&since=${encodeURIComponent(since)}&limit=5000`);
        const history = telemetryHistory(result.metrics || []);
        if (!window.CapivaraTelemetry?.render) throw new Error("Widget de telemetria indisponível.");
        window.CapivaraTelemetry.render(el("agent-telemetry"), current || {}, history, {
            label: "Agent",
            processKey: "agent",
            description: "Consumo total do host e consumo exclusivo do processo Capivara Agent."
        });
    }

    function doctorFact(term, description) {
        const box = document.createElement("div");
        const dt = document.createElement("dt");
        const dd = document.createElement("dd");
        dt.textContent = term;
        dd.textContent = description;
        box.append(dt, dd);
        return box;
    }

    function renderDoctor(state) {
        const stateBox = el("agent-doctor-state");
        const reportBox = el("agent-doctor-report");
        const findingsBox = el("agent-doctor-findings");
        const facts = el("agent-doctor-facts");
        if (!state) {
            if (stateBox) stateBox.textContent = "Nenhum diagnóstico solicitado.";
            if (reportBox) reportBox.hidden = true;
            return;
        }
        const status = String(state.status || "unknown");
        if (stateBox) stateBox.textContent = `Estado: ${status}${state.requested_at ? ` · solicitado em ${heartbeat(state.requested_at)}` : ""}${state.completed_at ? ` · concluído em ${heartbeat(state.completed_at)}` : ""}`;
        const report = state.result;
        if (!report || typeof report !== "object") {
            if (reportBox) reportBox.hidden = true;
            return;
        }
        reportBox.hidden = false;
        text("agent-doctor-summary", `Status ${value(report.status)} · ${report.ready ? "Agent apto" : "Agent requer atenção"}`);
        findingsBox.replaceChildren();
        const findings = Array.isArray(report.findings) ? report.findings : [];
        if (!findings.length) {
            const ok = document.createElement("div");
            ok.className = "cap-doctor-finding healthy";
            ok.textContent = "Nenhuma falha encontrada pelo Doctor.";
            findingsBox.append(ok);
        }
        findings.forEach(item => {
            const node = document.createElement("div");
            node.className = `cap-doctor-finding ${String(item.severity || "info").toLowerCase()}`;
            const strong = document.createElement("strong");
            strong.textContent = value(item.code, "finding");
            const span = document.createElement("span");
            span.textContent = value(item.message);
            node.append(strong, span);
            findingsBox.append(node);
        });
        facts.replaceChildren(
            doctorFact("Serviço", value(report.service?.active_state)),
            doctorFact("Controller", report.heartbeat?.controller?.reachable ? "alcançável" : "não alcançável"),
            doctorFact("Enrollment", report.identity?.enrolled ? "credencial permanente presente" : "credencial ausente"),
            doctorFact("Portas", report.ports?.configured ? `${value(report.ports?.conflict_count, 0)} conflito(s)` : "faixas não configuradas"),
            doctorFact("Armazenamento livre", report.host?.storage_root_free_bytes ? `${(Number(report.host.storage_root_free_bytes) / 1024 / 1024 / 1024).toFixed(1)} GiB` : "—")
        );
    }

    function renderStorage(storage) {
        const root = value(storage?.instance_storage_root, "/var/lib/capivara-instances");
        const input = el("agent-instance-storage-root");
        if (input && document.activeElement !== input) input.value = root;
        const source = storage?.source === "managed" ? "configuração gerenciada" : "padrão do Agent";
        const revision = storage?.revision ? ` · revisão ${storage.revision}` : "";
        const migration = storage?.migration_requested ? " · migração solicitada" : "";
        text("agent-storage-state", `Atual/desejado: ${root} · ${source}${revision}${migration}`);
    }

    function renderAdmin(agent) {
        currentAdmin = agent;
        text("detail-name", agent.name);
        text("detail-agent-id", agent.agent_id);
        text("detail-fingerprint", agent.fingerprint);
        const input = el("agent-admin-name");
        if (input && document.activeElement !== input) input.value = value(agent.name, "");
        renderStorage(agent.storage || {});
        renderDoctor(agent.doctor);
    }

    async function loadAdmin() {
        const result = await request(`/api/admin/agent?agent_id=${encodeURIComponent(agentId)}`);
        renderAdmin(result.agent || {});
    }

    async function load() {
        if (!agentId) throw new Error("Agent não informado na URL.");
        const [result] = await Promise.all([
            request(`/api/agent/ports?agent_id=${encodeURIComponent(agentId)}`),
            loadAdmin()
        ]);

        const agent = result.agent || {};
        text("agent-detail-title", `${value(currentAdmin?.name || agent.name || agent.hostname || agent.node_id || agent.id, "Agent")} · ${value(agent.id || currentAdmin?.agent_id, agentId)}`);
        text("detail-hostname", agent.hostname || currentAdmin?.hostname || agent.name || agent.node_id || agent.id);
        text("detail-address", agent.address || currentAdmin?.address || agent.ip || agent.public_host);
        text("detail-system", agent.system || agent.os || agent.os_name || currentAdmin?.os_name || agent.platform);
        text("detail-version", agent.version || agent.capivara_version || currentAdmin?.capivara_version || agent.agent_version || agent.installed_version);
        text("detail-health", agent.health || agent.health_status || currentAdmin?.health_status || agent.status);
        text("detail-heartbeat", heartbeat(agent.last_heartbeat || agent.heartbeat_at || agent.last_seen || currentAdmin?.last_seen || agent.updated_at));
        text("detail-datacenter", agent.datacenter_name || agent.datacenter || agent.location_name || agent.location);
        text("detail-region", agent.region_name || agent.region || agent.region_id);
        text("detail-public-host", agent.public_host || agent.address || currentAdmin?.address || agent.ip);
        text("detail-node", agent.node_id || currentAdmin?.node_id || agent.hostname || agent.id);

        const ranges = el("detail-ranges");
        ranges.replaceChildren(...(Array.isArray(result.ranges) ? result.ranges : []).map(rangeCard));
        if (!ranges.children.length) {
            const empty = document.createElement("div");
            empty.className = "cap-detail-note";
            empty.textContent = "Nenhuma faixa de portas configurada.";
            ranges.appendChild(empty);
        }
        text("detail-conflicts", result.conflict_count ? `${result.conflict_count} conflito(s) persistente(s) detectado(s).` : "Nenhum conflito persistente detectado.");

        const baseTelemetry = result.telemetry || agent.telemetry || agent.metadata?.telemetry || {};
        const instanceTelemetry = result.instance_telemetry || agent.instance_telemetry || agent.metadata?.instance_telemetry || [];
        await loadTelemetry({...baseTelemetry, instance_telemetry: Array.isArray(instanceTelemetry) ? instanceTelemetry : []});
    }

    function bindAgentViews() {
        document.querySelectorAll("[data-agent-view]").forEach(link => {
            const view = link.dataset.agentView;
            link.href = `agent-observability.html?agent_id=${encodeURIComponent(agentId)}&view=${encodeURIComponent(view)}`;
        });
    }

    function setBusy(button, busy, label) {
        if (!button) return;
        button.disabled = busy;
        if (label) button.textContent = label;
    }

    async function saveName() {
        const button = el("agent-admin-save-name");
        const name = el("agent-admin-name").value.trim();
        setBusy(button, true, "Salvando…");
        try {
            await post("/api/admin/agent/rename", {agent_id: agentId, name});
            await loadAdmin();
            hideError();
        } catch (error) {
            showError(error);
        } finally {
            setBusy(button, false, "Salvar nome");
        }
    }

    async function storageAction(migrate) {
        const button = el(migrate ? "agent-admin-migrate-storage" : "agent-admin-save-storage");
        const root = el("agent-instance-storage-root").value.trim();
        setBusy(button, true, migrate ? "Solicitando migração…" : "Salvando…");
        try {
            const path = migrate ? "/api/admin/agent/storage/migrate" : "/api/admin/agent/storage";
            const result = await post(path, {agent_id: agentId, instance_storage_root: root});
            renderStorage(result.storage || {});
            hideError();
            text("agent-storage-state", migrate ? `Migração solicitada para ${root}. Todas as instâncias precisam estar paradas; o root antigo será preservado.` : `Solicitado: ${root} · aguardando aplicação pelo heartbeat do Agent.`);
            setTimeout(refreshAdminOnly, 3500);
        } catch (error) {
            showError(error);
        } finally {
            setBusy(button, false, migrate ? "Migrar instâncias e aplicar" : "Salvar diretório");
        }
    }

    async function runDoctor() {
        const button = el("agent-run-doctor");
        setBusy(button, true, "Solicitando…");
        try {
            const result = await post("/api/admin/agent/doctor", {agent_id: agentId});
            renderDoctor(result.doctor);
            setTimeout(refreshAdminOnly, 3500);
        } catch (error) {
            showError(error);
        } finally {
            setBusy(button, false, "Executar diagnóstico completo");
        }
    }

    async function refreshAdminOnly() {
        try {
            await loadAdmin();
            hideError();
        } catch (error) {
            showError(error);
        }
    }

    async function prepareRelink() {
        const button = el("agent-prepare-relink");
        const box = el("agent-relink-result");
        setBusy(button, true, "Preparando…");
        try {
            const result = await post("/api/admin/agent/relink/prepare", {agent_id: agentId, ttl_seconds: 900});
            box.hidden = false;
            box.replaceChildren();
            const warning = document.createElement("strong");
            warning.textContent = "Token de uso único — expira em " + heartbeat(result.expires_at);
            const token = document.createElement("code");
            token.textContent = result.pairing_token;
            const help = document.createElement("p");
            help.textContent = "No Agent, execute o comando abaixo substituindo <TOKEN> pelo token exibido. O token e a nova credencial não devem ser registrados em logs.";
            const command = document.createElement("pre");
            command.textContent = result.command;
            box.append(warning, token, help, command);
        } catch (error) {
            showError(error);
        } finally {
            setBusy(button, false, "Preparar revinculação");
        }
    }

    async function removeAgent() {
        const button = el("agent-remove");
        const input = el("agent-remove-confirmation");
        const state = el("agent-remove-state");
        if (currentRole !== "admin") return;
        const confirmation = String(input?.value || "").trim();
        if (confirmation !== agentId) {
            showError(new Error("Digite o Agent ID completo para confirmar a remoção."));
            return;
        }
        if (!window.confirm(`Remover definitivamente ${agentId} do Controller? Esta ação não desinstala a máquina remota.`)) return;
        setBusy(button, true, "Removendo…");
        try {
            const result = await post("/api/admin/agent/remove", {agent_id: agentId, confirmation});
            hideError();
            if (state) state.textContent = `Agent ${result.agent_id} e Node ${result.node_id} removidos do Controller.`;
            window.setTimeout(() => location.replace("agents.html?removed=" + encodeURIComponent(result.agent_id)), 700);
        } catch (error) {
            showError(error);
            setBusy(button, false, "Remover Agent");
        }
    }

    async function refresh() {
        const button = el("refresh-agent-detail");
        if (button) button.disabled = true;
        try {
            await load();
            hideError();
        } catch (error) {
            showError(error);
        } finally {
            if (button) button.disabled = false;
        }
    }

    async function init() {
        if (!agentId) {
            location.replace("agents.html?missing_agent=1");
            return;
        }

        bindMenu();
        bindAgentViews();
        el("refresh-agent-detail")?.addEventListener("click", refresh);
        el("agent-admin-save-name")?.addEventListener("click", saveName);
        el("agent-admin-save-storage")?.addEventListener("click", () => storageAction(false));
        el("agent-admin-migrate-storage")?.addEventListener("click", () => storageAction(true));
        el("agent-run-doctor")?.addEventListener("click", runDoctor);
        el("agent-prepare-relink")?.addEventListener("click", prepareRelink);
        el("agent-remove")?.addEventListener("click", removeAgent);

        try {
            await sidebar();
            await refresh();
        } catch (error) {
            showError(error);
        }

        setInterval(refresh, 30000);
    }

    document.addEventListener("DOMContentLoaded", init);
})();
