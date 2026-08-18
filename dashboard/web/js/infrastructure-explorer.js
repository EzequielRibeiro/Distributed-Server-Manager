(() => {
    "use strict";

    const State = window.CapivaraDashboardState;
    const TYPE_LABELS = {
        controller: "Controller",
        region: "Region",
        datacenter: "Datacenter",
        agent: "Agent",
    };

    function statusClass(status) {
        const value = String(status || "unknown").toLowerCase();
        if (["active", "healthy", "online", "running"].includes(value)) return "is-healthy";
        if (["warning", "degraded"].includes(value)) return "is-warning";
        if (["critical", "failed", "error"].includes(value)) return "is-critical";
        if (["busy", "installing", "updating"].includes(value)) return "is-busy";
        return "is-offline";
    }

    function childNodes(node) {
        return Array.isArray(node && node.children) ? node.children : [];
    }

    function makeNode(node, depth = 0) {
        const wrapper = document.createElement("li");
        wrapper.className = "infra-node";

        const row = document.createElement("button");
        row.type = "button";
        row.className = "infra-node-row";
        row.dataset.type = node.type || "unknown";
        row.dataset.id = node.id || "";
        row.style.setProperty("--infra-depth", depth);

        const children = childNodes(node);
        const expandable = children.length > 0;

        const toggle = document.createElement("span");
        toggle.className = "infra-node-toggle";
        toggle.textContent = expandable ? "▾" : "";
        toggle.setAttribute("aria-hidden", "true");

        const status = document.createElement("span");
        status.className = `infra-status ${statusClass(node.aggregate_status || node.status)}`;
        status.setAttribute("aria-hidden", "true");

        const text = document.createElement("span");
        text.className = "infra-node-text";

        const name = document.createElement("span");
        name.className = "infra-node-name";
        name.textContent = node.name || node.id || "Sem nome";

        const meta = document.createElement("span");
        meta.className = "infra-node-meta";
        const typeLabel = TYPE_LABELS[node.type] || node.type || "Item";
        const count = Number.isFinite(Number(node.children_count)) ? ` · ${Number(node.children_count)}` : "";
        meta.textContent = `${typeLabel}${count}`;

        text.append(name, meta);
        row.append(toggle, status, text);
        wrapper.appendChild(row);

        if (expandable) {
            const list = document.createElement("ul");
            list.className = "infra-node-children";
            children.forEach((child) => list.appendChild(makeNode(child, depth + 1)));
            wrapper.appendChild(list);

            toggle.addEventListener("click", (event) => {
                event.stopPropagation();
                const collapsed = wrapper.classList.toggle("is-collapsed");
                toggle.textContent = collapsed ? "▸" : "▾";
            });
        }

        row.addEventListener("click", () => {
            document.querySelectorAll(".infra-node-row.is-selected").forEach((item) => item.classList.remove("is-selected"));
            row.classList.add("is-selected");
            if (State) {
                State.setSelection({ type: node.type, id: node.id, name: node.name });
            }
        });

        return wrapper;
    }

    function render(container, payload) {
        container.replaceChildren();
        const controllers = Array.isArray(payload && payload.controllers) ? payload.controllers : [];
        if (!controllers.length) {
            const empty = document.createElement("div");
            empty.className = "infra-empty";
            empty.textContent = "Nenhuma infraestrutura disponível.";
            container.appendChild(empty);
            return;
        }

        const list = document.createElement("ul");
        list.className = "infra-tree";
        controllers.forEach((controller) => {
            list.appendChild(makeNode(controller, 0));
            const unplaced = Array.isArray(controller.unplaced_agents) ? controller.unplaced_agents : [];
            if (unplaced.length) {
                const group = {
                    type: "datacenter",
                    id: `${controller.id}:unplaced`,
                    name: "Agents sem localização",
                    status: "warning",
                    children_count: unplaced.length,
                    children: unplaced,
                };
                list.appendChild(makeNode(group, 1));
            }
        });
        container.appendChild(list);
    }

    async function load(container, options = {}) {
        if (!container) return;
        if (State) State.setInfrastructureLoading();
        container.innerHTML = '<div class="infra-loading">Carregando infraestrutura…</div>';

        try {
            const query = new URLSearchParams();
            if (options.controllerId) query.set("controller_id", options.controllerId);
            if (options.activeOnly) query.set("active_only", "true");
            const suffix = query.toString() ? `?${query.toString()}` : "";
            const response = await fetch(`/api/infrastructure${suffix}`, { credentials: "same-origin" });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
            if (State) State.setInfrastructure(payload);
            render(container, payload);
        } catch (error) {
            if (State) State.setInfrastructureError(error.message || error);
            container.innerHTML = '<div class="infra-error">Não foi possível carregar a infraestrutura.</div>';
        }
    }

    window.CapivaraInfrastructureExplorer = { load, render };
})();