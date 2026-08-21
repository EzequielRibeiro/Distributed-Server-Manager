"use strict";

(() => {
    const API = "/api";
    let topology = null;
    let selected = null;

    function authHeaders() {
        return {
            Authorization: `Basic ${sessionStorage.getItem("dsm_auth") || ""}`,
            Accept: "application/json"
        };
    }

    async function request(path) {
        const response = await fetch(`${API}${path}`, { headers: authHeaders() });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
        return payload;
    }

    function normalize(value) {
        return String(value || "unknown").trim().toLowerCase();
    }

    function childrenOf(node) {
        return Array.isArray(node?.children) ? node.children : [];
    }

    function typeLabel(type) {
        return ({
            controller: "Controller",
            region: "Region",
            datacenter: "Datacenter",
            agent_location: "Agent Location",
            agent: "Agent"
        })[type] || type || "Item";
    }

    function isHealthy(value) {
        return ["active", "online", "healthy", "ready", "running"].includes(normalize(value));
    }

    function placementState(node, ancestors = []) {
        if (node?.placement_ready === true) return { ready: true, derived: false };
        if (node?.placement_ready === false) return { ready: false, derived: false };
        if (node?.type !== "agent") return { ready: null, derived: false };

        const chainHealthy = ancestors
            .filter(item => ["controller", "region", "datacenter"].includes(item.type))
            .every(item => isHealthy(item.aggregate_status || item.status));
        const agentHealthy = isHealthy(node.aggregate_status || node.status);
        const locationHealthy = !node.location_status || isHealthy(node.location_status);
        return { ready: chainHealthy && agentHealthy && locationHealthy, derived: true };
    }

    function ensureShell() {
        const title = document.querySelector(".infra-v2-section-title");
        if (!title || document.getElementById("infra-topology-v2")) return;

        const section = document.createElement("section");
        section.id = "infra-topology-v2";
        section.className = "infra-topology-v2";
        section.innerHTML = `
            <div class="infra-topology-tree">
                <div class="infra-topology-titlebar">
                    <div><h2>Topologia</h2><span>Controller → Region → Datacenter → Agent</span></div>
                    <button id="infra-topology-refresh" type="button">Atualizar</button>
                </div>
                <div id="infra-topology-tree-body" class="infra-topology-empty">Carregando topologia...</div>
            </div>
            <aside class="infra-topology-detail">
                <div class="infra-topology-titlebar">
                    <div><h3>Detalhes</h3><span id="infra-topology-detail-type">Selecione um item</span></div>
                </div>
                <div id="infra-topology-detail-body" class="infra-topology-empty">Selecione um item da topologia para visualizar os detalhes.</div>
            </aside>`;
        title.after(section);

        document.getElementById("infra-topology-refresh")?.addEventListener("click", loadTopology);
    }

    function makeRow(node, ancestors) {
        const li = document.createElement("li");
        li.className = "infra-v2-tree-node";

        const row = document.createElement("button");
        row.type = "button";
        row.className = "infra-v2-tree-row";
        row.dataset.state = normalize(node.aggregate_status || node.status);

        const placement = placementState(node, ancestors);
        const count = Number(node.children_count ?? childrenOf(node).length ?? 0);
        const badge = node.type === "agent" && placement.ready !== null
            ? `<span class="infra-placement-badge ${placement.ready ? "ready" : "blocked"}">${placement.ready ? "placement ready" : "bloqueado"}${placement.derived ? "*" : ""}</span>`
            : `<span class="infra-v2-tree-badge">${count}</span>`;

        row.innerHTML = `
            <span class="infra-v2-tree-status" aria-hidden="true"></span>
            <span class="infra-v2-tree-copy"><strong>${escapeHtml(node.name || node.id || "Sem nome")}</strong><small>${escapeHtml(typeLabel(node.type))} · ${escapeHtml(node.id || "")}</small></span>
            ${badge}`;

        row.addEventListener("click", () => {
            document.querySelectorAll(".infra-v2-tree-row.is-selected").forEach(item => item.classList.remove("is-selected"));
            row.classList.add("is-selected");
            selected = { node, ancestors };
            renderDetails(node, ancestors);
        });

        li.appendChild(row);
        const children = childrenOf(node);
        if (children.length) {
            const ul = document.createElement("ul");
            children.forEach(child => ul.appendChild(makeRow(child, [...ancestors, node])));
            li.appendChild(ul);
        }
        return li;
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function renderTree() {
        const container = document.getElementById("infra-topology-tree-body");
        if (!container) return;
        const controllers = Array.isArray(topology?.controllers) ? topology.controllers : [];
        container.replaceChildren();
        if (!controllers.length) {
            container.className = "infra-topology-empty";
            container.textContent = "Nenhuma infraestrutura disponível.";
            return;
        }

        container.className = "";
        const list = document.createElement("ul");
        list.className = "infra-v2-tree-list";
        controllers.forEach(controller => {
            list.appendChild(makeRow(controller, []));
            const unplaced = Array.isArray(controller.unplaced_agents) ? controller.unplaced_agents : [];
            if (unplaced.length) {
                const synthetic = {
                    type: "datacenter",
                    id: `${controller.id}:unplaced`,
                    name: "Agents sem localização",
                    status: "warning",
                    children_count: unplaced.length,
                    children: unplaced,
                    synthetic: true
                };
                list.appendChild(makeRow(synthetic, [controller]));
            }
        });
        container.appendChild(list);
    }

    function row(label, value) {
        if (value === undefined || value === null || value === "") return "";
        return `<div class="infra-topology-detail-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
    }

    function renderDetails(node, ancestors) {
        const type = document.getElementById("infra-topology-detail-type");
        const body = document.getElementById("infra-topology-detail-body");
        if (!body) return;
        if (type) type.textContent = typeLabel(node.type);

        const path = [...ancestors, node]
            .map(item => `<span>${escapeHtml(typeLabel(item.type))}: ${escapeHtml(item.name || item.id)}</span>`)
            .join("");
        const placement = placementState(node, ancestors);

        const details = [
            row("ID", node.id),
            row("Status", node.aggregate_status || node.status),
            node.type === "region" ? row("País", node.country_code) : "",
            node.type === "region" ? row("Continente", node.continent_code) : "",
            node.type === "datacenter" ? row("Provider", node.provider) : "",
            node.type === "datacenter" ? row("Cidade", node.city) : "",
            node.type === "datacenter" ? row("País", node.country_code) : "",
            node.type === "agent" ? row("Node", node.node_id) : "",
            node.type === "agent" ? row("Host público", node.public_host) : "",
            node.type === "agent" ? row("Agent Location", node.location_status || "não informado") : "",
            node.type === "agent" ? row("Instâncias", node.children_count ?? 0) : "",
            node.type === "agent" && placement.ready !== null ? row("Placement", placement.ready ? "READY" : "BLOQUEADO") : ""
        ].join("");

        body.className = "infra-topology-detail-body";
        body.innerHTML = `<div class="infra-topology-path">${path}</div>${details}`;

        if (node.type === "agent") {
            const actions = document.createElement("div");
            actions.className = "infra-topology-agent-actions";
            const manage = document.createElement("button");
            manage.type = "button";
            manage.textContent = "Gerenciar Agent";
            manage.addEventListener("click", async () => {
                if (typeof window.loadAgent === "function") {
                    await window.loadAgent(node.id);
                    document.getElementById("agent-detail")?.scrollIntoView({ behavior: "smooth", block: "start" });
                }
            });
            const install = document.createElement("button");
            install.type = "button";
            install.textContent = "Adicionar Agent";
            install.addEventListener("click", () => {
                const panel = document.getElementById("add-agent");
                if (panel) {
                    panel.hidden = false;
                    panel.scrollIntoView({ behavior: "smooth", block: "start" });
                }
            });
            actions.append(manage, install);
            body.appendChild(actions);
        }

        if (node.type === "agent" && placement.derived) {
            const note = document.createElement("small");
            note.style.color = "#718198";
            note.textContent = "* placement_ready estimado a partir dos estados disponíveis nesta resposta da API.";
            body.appendChild(note);
        }
    }

    async function loadTopology() {
        ensureShell();
        const container = document.getElementById("infra-topology-tree-body");
        if (container) {
            container.className = "infra-topology-empty";
            container.textContent = "Carregando topologia...";
        }
        try {
            topology = await request("/infrastructure?active_only=true");
            renderTree();
            if (selected) renderDetails(selected.node, selected.ancestors);
        } catch (error) {
            if (container) container.textContent = `Não foi possível carregar a topologia: ${error.message}`;
        }
    }

    function show(show) {
        const panel = document.getElementById("infra-topology-v2");
        if (!panel) return;
        panel.classList.toggle("is-visible", Boolean(show));
        if (show && !topology) loadTopology();
    }

    document.addEventListener("DOMContentLoaded", () => {
        ensureShell();
        loadTopology();
    });

    window.CapivaraInfrastructureTopologyV2 = { show, load: loadTopology };
})();
