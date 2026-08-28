(function () {
    "use strict";

    const API = "/api";
    
    let activeView = "agents";

    async function request(path) {
        const response = await fetch(`${API}${path}`, {
            headers: { "X-Capivara-Auth-Area":"controller", Accept: "application/json" },
            cache: "no-store"
        });
        if (response.status === 401) {
            
            window.location.replace("/login.html");
            throw new Error("authentication required");
        }
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
    }

    function normalizeState(value) {
        return String(value || "unknown").trim().toLowerCase();
    }

    function ensureDashboardStyles() {
        if (document.querySelector('link[href="/dashboard-home-v3.css"]')) return;
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = "/dashboard-home-v3.css";
        document.head.appendChild(link);
    }

    function ensureV3Topbar() {
        const main = document.querySelector(".agents-main");
        if (!main || document.getElementById("infra-v3-topbar")) return;
        const topbar = document.createElement("header");
        topbar.id = "infra-v3-topbar";
        topbar.className = "infra-v3-topbar";
        topbar.innerHTML = `
            <div class="infra-v3-topbar-title">
                <button id="infra-v3-menu" type="button" aria-label="Recolher menu">☰</button>
                <div><strong>Infraestrutura</strong><span>Regions · Datacenters · Agents · Placement</span></div>
            </div>
            <div class="infra-v3-session">
                <span class="infra-v3-controller"><i></i> Controller Online</span>
                <div><strong id="infra-v3-user">—</strong><small id="infra-v3-role">—</small></div>
            </div>`;
        main.before(topbar);
    }

    function applyRoleVisibility(user) {
        const role = String(user?.role || "");
        document.querySelectorAll(".admin-only").forEach(element => {
            element.style.display = role === "admin" ? "" : "none";
        });
        document.querySelectorAll(".agent-manager-only").forEach(element => {
            element.style.display = ["admin", "controller"].includes(role) ? "" : "none";
        });
        const name = document.getElementById("infra-v3-user");
        const roleLabel = document.getElementById("infra-v3-role");
        if (name) name.textContent = user?.username || "Usuário";
        if (roleLabel) roleLabel.textContent = role || "—";
        const current = document.getElementById("current-user");
        if (current) current.textContent = user?.username || "Sessão ativa";
    }

    function activateInfrastructureNav() {
        document.querySelectorAll(".cap-sidebar-v3 a").forEach(link => link.classList.remove("active"));
        const candidates = [...document.querySelectorAll(".cap-sidebar-v3 a")];
        const agentLink = candidates.find(link => link.textContent.trim() === "Agents") ||
            candidates.find(link => String(link.getAttribute("href") || "").includes("agents.html"));
        if (agentLink) agentLink.classList.add("active");
    }

    async function loadV3Sidebar() {
        const target = document.getElementById("sidebar-component");
        if (!target) return;
        const response = await fetch("/components/sidebar-v3.html", {
            headers: auth() ? { "X-Capivara-Auth-Area":"controller" } : {},
            cache: "no-store"
        });
        if (!response.ok) throw new Error(`sidebar HTTP ${response.status}`);
        target.innerHTML = await response.text();
        activateInfrastructureNav();
        const logout = document.getElementById("btn-logout");
        if (logout) logout.onclick = () => {
            
            window.location.replace("/login.html");
        };
    }

    function wireV3Shell() {
        const menu = document.getElementById("infra-v3-menu");
        if (!menu || menu.dataset.bound) return;
        menu.dataset.bound = "1";
        menu.addEventListener("click", () => {
            if (window.innerWidth <= 760) {
                document.body.classList.toggle("sidebar-open");
            } else {
                document.body.classList.toggle("cap-sidebar-collapsed");
            }
        });
        document.addEventListener("click", event => {
            if (window.innerWidth > 760 || !document.body.classList.contains("sidebar-open")) return;
            if (event.target.closest("#sidebar-component") || event.target.closest("#infra-v3-menu")) return;
            document.body.classList.remove("sidebar-open");
        });
    }

    async function prepareV3Shell() {
        document.body.classList.add("cap-home", "cap-infra-v3");
        ensureDashboardStyles();
        ensureV3Topbar();
        wireV3Shell();
        try {
            await loadV3Sidebar();
            const user = await request("/whoami");
            applyRoleVisibility(user);
        } catch (error) {
            console.warn("[Capivara][InfrastructureV3] shell:", error);
        }
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

    function loadTopologyModule() {
        if (window.CapivaraInfrastructureTopologyV2 || document.getElementById("infra-topology-v2-script")) return;
        const script = document.createElement("script");
        script.id = "infra-topology-v2-script";
        script.src = "/infrastructure-topology-v2.js?v=1";
        script.defer = true;
        document.body.appendChild(script);
    }

    function setView(view) {
        activeView = view;
        const list = document.getElementById("agents-list");
        const title = document.querySelector(".infra-v2-section-title");
        const detail = document.getElementById("agent-detail");
        const install = document.getElementById("add-agent");

        if (list) list.hidden = view !== "agents";
        if (title) title.hidden = view !== "agents";
        if (detail && view !== "agents") detail.hidden = true;
        if (install && view !== "installation") install.hidden = true;

        if (view === "topology") {
            window.CapivaraInfrastructureTopologyV2?.show(true);
        } else {
            window.CapivaraInfrastructureTopologyV2?.show(false);
        }

        if (view === "installation" && install) {
            install.hidden = false;
            install.scrollIntoView({ behavior: "smooth", block: "start" });
        }

        document.querySelectorAll("[data-infra-view]").forEach(button => {
            button.classList.toggle("active", button.dataset.infraView === view);
        });
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
            button.addEventListener("click", () => setView(button.dataset.infraView));
        });

        document.getElementById("infra-agent-search")?.addEventListener("input", filterCards);
    }

    function wireInstallToggle() {
        const panel = document.getElementById("add-agent");
        const button = document.getElementById("add-agent-focus");
        if (!panel || !button || button.dataset.v2Bound) return;
        button.dataset.v2Bound = "1";
        panel.hidden = true;
        button.addEventListener("click", () => setView("installation"));
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
            const online = agents.filter(agent => ["active", "online", "healthy"].includes(normalizeState(agent.health_status || agent.health || agent.status))).length;
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

    async function initialize() {
        await prepareV3Shell();
        ensureSummaryShell();
        wireInstallToggle();
        watchAgentList();
        loadTopologyModule();
        refreshSummary();
        setView("agents");
        document.getElementById("refresh-agents")?.addEventListener("click", () => {
            setTimeout(refreshSummary, 250);
            if (activeView === "topology") {
                window.CapivaraInfrastructureTopologyV2?.load();
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, { once: true });
    } else {
        initialize();
    }
})();
