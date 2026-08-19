(() => {
    "use strict";

    const State = window.CapivaraDashboardState;

    const TYPE_LABELS = {
        controller: "Controller",
        region: "Region",
        datacenter: "Datacenter",
        agent: "Agent",
    };

    function findNode(nodes, type, id) {
        for (const node of nodes || []) {
            if (node && node.type === type && node.id === id) {
                return node;
            }

            const found = findNode(node && node.children, type, id);
            if (found) {
                return found;
            }

            if (node && Array.isArray(node.unplaced_agents)) {
                const unplaced = findNode(node.unplaced_agents, type, id);
                if (unplaced) {
                    return unplaced;
                }
            }
        }

        return null;
    }

    function selectedNode(snapshot) {
    const selection = snapshot && snapshot.selection;
    const infrastructure = snapshot && snapshot.infrastructure;

    if (!selection || !infrastructure) {
        return null;
    }

    const node = findNode(
        infrastructure.controllers,
        selection.type,
        selection.id
    );

    if (node) {
        return node;
    }

    if (
        selection.type === "datacenter" &&
        String(selection.id || "").endsWith(":unplaced")
    ) {
        const controllerId = String(selection.id).slice(
            0,
            -":unplaced".length
        );

        const controller = findNode(
            infrastructure.controllers,
            "controller",
            controllerId
        );

        if (
            controller &&
            Array.isArray(controller.unplaced_agents)
        ) {
            return {
                type: "datacenter",
                id: selection.id,
                name: selection.name || "Agents sem localização",
                status: "warning",
                children_count: controller.unplaced_agents.length,
                children: controller.unplaced_agents,
                synthetic: true,
            };
        }
    }

    return null;
}

    function detail(label, value) {
        if (value === undefined || value === null || value === "") {
            return null;
        }

        const row = document.createElement("div");
        row.className = "infra-detail-row";

        const key = document.createElement("span");
        key.className = "infra-detail-label";
        key.textContent = label;

        const content = document.createElement("span");
        content.className = "infra-detail-value";
        content.textContent = String(value);

        row.append(key, content);
        return row;
    }

    function detailsFor(node) {
        const rows = [];

        rows.push(detail("ID", node.id));
        rows.push(detail("Status", node.aggregate_status || node.status));

        if (node.type === "controller") {
            rows.push(detail("Regions", node.children_count));
            rows.push(detail("Agents sem localização", node.unplaced_agent_count));
        }

        if (node.type === "region") {
            rows.push(detail("País", node.country_code));
            rows.push(detail("Continente", node.continent_code));
            rows.push(detail("Datacenters", node.children_count));
        }

        if (node.type === "datacenter") {
            rows.push(detail("Provider", node.provider));
            rows.push(detail("Cidade", node.city));
            rows.push(detail("País", node.country_code));
            rows.push(detail("Agents", node.children_count));
        }

        if (node.type === "agent") {
            rows.push(detail("Node", node.node_id));
            rows.push(detail("Host público", node.public_host));
            rows.push(detail("Localização", node.location_status));
            rows.push(detail("Instâncias", node.children_count));
        }

        return rows.filter(Boolean);
    }

    function render(container, snapshot) {
        if (!container) {
            return;
        }

        container.replaceChildren();

        const node = selectedNode(snapshot);

        if (!node) {
            const empty = document.createElement("div");
            empty.className = "infra-details-empty";
            empty.textContent = "Selecione um item da infraestrutura.";
            container.appendChild(empty);
            return;
        }

        const header = document.createElement("div");
        header.className = "infra-details-header";

        const title = document.createElement("strong");
        title.className = "infra-details-title";
        title.textContent = node.name || node.id || "Sem nome";

        const type = document.createElement("span");
        type.className = "infra-details-type";
        type.textContent = TYPE_LABELS[node.type] || node.type || "Item";

        header.append(title, type);

        const body = document.createElement("div");
        body.className = "infra-details-body";

        detailsFor(node).forEach((row) => body.appendChild(row));

        container.append(header, body);
    }

    function mount(container) {
        if (!container || !State) {
            return () => {};
        }

        return State.subscribe((snapshot) => {
            render(container, snapshot);
        });
    }

    window.CapivaraInfrastructureDetails = {
        findNode,
        selectedNode,
        render,
        mount,
    };
})();
