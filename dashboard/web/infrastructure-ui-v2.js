(function () {
    "use strict";

    const API = "/api";
    const auth = () => sessionStorage.getItem("dsm_auth") || "";

    async function request(path) {
        const response = await fetch(`${API}${path}`, {
            headers: { Authorization: `Basic ${auth()}`, Accept: "application/json" }
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
    }

    function normalizeState(value) {
        return String(value || "unknown").trim().toLowerCase();
    }

    function collectDatacenters(value, result = new Map()) {
        if (!value) return result;
        if (Array.isArray(value)) {
            value.forEach(item => collectDatacenters(item, result));
            return result;
        }
        if (typeof value !== "object") return result;
        if (value.type === "datacenter" && value.id) result.set(String(value.id), value);
        Object.values(value).forEach(child => {
            if (child && typeof child === "object") collectDatacenters(child, result);
        });
        return result;
    }

    function ensureSummaryShell() {
        const main = document.querySelector(".agents-main");
        const header = document.querySelector(".agents-header");
        if (!main || !header || document.getElementById("infra-v2-summary")) return;

        const summary = document.createElement("section");
        summary.id = "infra-v2-summary";
        summary.className = "infra-v2-summary";
        summary.innerHTML = `
            <article class="infra-v2-stat"><span>Agents</span><strong id="infra-stat-agents">—</strong><small>registrados</small></article>
            <article class="infra-v2-stat"><span>Online</span><strong id="infra-stat-online">—</strong><small>ativos agora</small></article>
            <article class="infra-v2-stat"><span>Instâncias</span><strong id="infra-stat-instances">—</strong><small>alocadas</small></article>
            <article class="infra-v2-stat"><span>Datacenters</span><strong id="infra-stat-datacenters">—</strong><small>na topologia</small></article>`;

        const toolbar = document.createElement("section");
        toolbar.className = "infra-v2-toolbar";
        toolbar.innerHTML = `
            <button type="button" class="active" data-infra-view="agents">Agents</button>
            <button type="button" data-infra-view="topology">Topologia</button>
            <button type="button" data-infra-view="installation">Instalação</button>
            <span class="infra-v2-spacer"></span>
            <input id="infra-agent-search" type="search" placeholder="Buscar Agent, Node ou status..." autocomplete="off">`;

        const title = document.createElement("div");
        title.className = "infra-v2-section-title";
        title.innerHTML = `<h2>Agents gerenciados</h2><span id="infra-agent-count-label">Carregando...</span>`;

        header.after(summary, toolbar, title);

        toolbar.querySelectorAll("[data-infra-view]").forEach(button => {
            button.addEventListener("click", () => {
                toolbar.querySelectorAll("[data-infra-view]").forEach(item => item.classList.remove("active"));
                button.classList.add("active");
                const view = button.dataset.infraView;
                if (view === "installation") {
                    showInstallation();
                } else if (view === "agents") {
                    document.getElementById("agents-list")?.scrollIntoView({ behavior: "smooth", block: "start" });
                } else {
                    document.getElementById("agent-detail")?.scrollIntoView({ behavior: "smooth", block: "start" });
                }
            });
        });

        document.getElementById("infra-agent-search")?.addEventListener("input", filterCards);
    }

    function showInstallation() {
        const panel = document.getElementById("add-agent");
        if (!panel) return;
        panel.hidden = false;
        panel.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function wireInstallToggle() {
        const panel = document.getElementById("add-agent");
        const button = document.getElementById("add-agent-focus");
        if (!panel || !button || button.dataset.v2Bound) return;
        button.dataset.v2Bound = "1";
        panel.hidden = true;
        button.addEventListener("click", () => {
            panel.hidden = !panel.hidden;
            if (!panel.hidden) panel.scrollIntoView({ behavior: "smooth", block: "start" });
        });
    }

    function decorateCards() {
        const cards = [...document.querySelectorAll("#agents-list .agent-card")];
        cards.forEach(card => {
            const status = card.querySelector(".agent-status")?.textContent || "unknown";
            card.dataset.state = normalizeState(status);
        });
        const label = document.getElementById("infra-agent-count-label");
        if (label) label.textContent = `${cards.length} Agent${cards.length === 1 ? "" : "s"}`;
        filterCards();
    }

    function filterCards() {
        const query = String(document.getElementById("infra-agent-search")?.value || "").trim().toLowerCase();
        document.querySelectorAll("#agents-list .agent-card").forEach(card => {
            card.hidden = query ? !card.textContent.toLowerCase().includes(query) : false;
        });
    }

    async function refreshSummary() {
        try {
            const [agentsData, topology] = await Promise.all([
                request("/agents"),
                request("/infrastructure?active_only=true").catch(() => null)
            ]);
            const agents = Array.isArray(agentsData) ? agentsData : (agentsData.agents || []);
            const online = agents.filter(agent => ["active", "online"].includes(normalizeState(agent.status))).length;
            const instances = agents.reduce((total, agent) => total + Number(agent.instance_count || 0), 0);
            const dcs = collectDatacenters(topology).size;
            const values = {
                "infra-stat-agents": agents.length,
                "infra-stat-online": online,
                "infra-stat-instances": instances,
                "infra-stat-datacenters": dcs
            };
            Object.entries(values).forEach(([id, value]) => {
                const el = document.getElementById(id);
                if (el) el.textContent = String(value);
            });
        } catch (_) {
            // The base Agents page already exposes operational errors.
        }
    }

    function watchAgentList() {
        const list = document.getElementById("agents-list");
        if (!list) return;
        new MutationObserver(decorateCards).observe(list, { childList: true, subtree: true });
        decorateCards();
    }

    function initialize() {
        ensureSummaryShell();
        wireInstallToggle();
        watchAgentList();
        refreshSummary();
        document.getElementById("refresh-agents")?.addEventListener("click", () => setTimeout(refreshSummary, 250));
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, { once: true });
    } else {
        initialize();
    }
})();
