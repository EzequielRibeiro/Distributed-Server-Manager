(function () {
    "use strict";

    const params = new URLSearchParams(location.search);
    const agentId = params.get("agent_id") || params.get("id") || "";

    function text(value) {
        return value === null || value === undefined || value === "" ? null : String(value);
    }

    function render(system, fallbackSystem, fallbackArchitecture) {
        const root = document.getElementById("detail-system");
        if (!root) return;

        const data = system && typeof system === "object" ? system : {};
        const family = text(data.family) || text(fallbackSystem) || "—";
        const primary = text(data.pretty_name) || text(data.name) || family;
        const architecture = text(data.architecture) || text(fallbackArchitecture);

        const details = [];
        if (family.toLowerCase() === "windows") {
            const release = text(data.display_version);
            const build = text(data.build);
            const version = text(data.version);
            if (release) details.push(`Versão ${release}`);
            if (build) details.push(`Build ${build}`);
            else if (version) details.push(version);
        } else {
            const kernel = text(data.kernel);
            const version = text(data.version);
            if (version && primary.toLowerCase().indexOf(version.toLowerCase()) === -1) {
                details.push(`Versão ${version}`);
            }
            if (kernel) details.push(`Kernel ${kernel}`);
        }
        if (architecture) details.push(`Arquitetura ${architecture}`);

        root.replaceChildren();
        root.style.display = "grid";
        root.style.gap = "2px";

        const title = document.createElement("span");
        title.textContent = primary;
        root.append(title);

        if (details.length) {
            const secondary = document.createElement("small");
            secondary.textContent = details.join(" · ");
            secondary.style.fontWeight = "500";
            secondary.style.opacity = ".78";
            secondary.style.lineHeight = "1.35";
            root.append(secondary);
        }
    }

    async function refresh() {
        if (!agentId) return;
        try {
            const response = await fetch(`/api/agent/ports?agent_id=${encodeURIComponent(agentId)}`, {
                headers: {
                    "X-Capivara-Auth-Area": "controller",
                    Accept: "application/json"
                },
                credentials: "same-origin",
                cache: "no-store"
            });
            if (!response.ok) return;
            const payload = await response.json().catch(() => ({}));
            const agent = payload.agent || {};
            const telemetry = payload.telemetry || agent.telemetry || agent.metadata?.telemetry || {};
            render(
                telemetry.system,
                agent.system || agent.os || agent.os_name || agent.platform,
                agent.architecture || agent.cpu?.machine
            );
        } catch (_) {
            // The base details script already renders the legacy fallback.
        }
    }

    document.addEventListener("DOMContentLoaded", refresh);
    document.getElementById("refresh-agent-detail")?.addEventListener("click", () => {
        window.setTimeout(refresh, 150);
    });
})();
