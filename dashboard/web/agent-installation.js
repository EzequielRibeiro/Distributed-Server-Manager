"use strict";

(() => {
    let installationId = null;
    let pollTimer = null;

    function collectType(value, type, result = []) {
        if (!value) return result;
        if (Array.isArray(value)) {
            value.forEach(item => collectType(item, type, result));
            return result;
        }
        if (typeof value !== "object") return result;
        if (value.type === type && value.id) result.push(value);
        Object.values(value).forEach(child => {
            if (child && typeof child === "object") collectType(child, type, result);
        });
        return result;
    }

    function unique(items) {
        const map = new Map();
        items.forEach(item => map.set(String(item.id), item));
        return [...map.values()];
    }

    function option(select, item) {
        const entry = document.createElement("option");
        entry.value = String(item.id);
        entry.textContent = item.name || String(item.id);
        select.appendChild(entry);
    }

    function populateTopology() {
        const regionSelect = document.getElementById("agent-install-region");
        const datacenterSelect = document.getElementById("agent-install-datacenter");
        const controllerSelect = document.getElementById("agent-install-controller");
        const controllerWrapper = document.getElementById("agent-controller-wrapper");
        const regions = unique(collectType(infrastructureTopology, "region"));
        const datacenters = unique(collectType(infrastructureTopology, "datacenter"));
        const controllers = unique(collectType(infrastructureTopology, "controller"));

        regionSelect.replaceChildren(new Option("Selecione uma região", ""));
        regions.forEach(item => option(regionSelect, item));

        function renderDatacenters() {
            datacenterSelect.replaceChildren(new Option("Selecione um datacenter", ""));
            datacenters
                .filter(item => !regionSelect.value || String(item.region_id || item.region?.id || "") === regionSelect.value)
                .forEach(item => option(datacenterSelect, item));
        }
        regionSelect.addEventListener("change", renderDatacenters);
        renderDatacenters();

        if (currentUser.role === "admin") {
            controllerWrapper.hidden = false;
            controllerSelect.replaceChildren(new Option("Selecione um Controller", ""));
            controllers.forEach(item => option(controllerSelect, item));
            if (!controllers.length) {
                const ids = new Set();
                collectType(infrastructureTopology, "agent").forEach(item => {
                    if (item.controller_id) ids.add(String(item.controller_id));
                });
                ids.forEach(id => option(controllerSelect, {id, name: id}));
            }
        }
    }

    function progress(state) {
        const root = document.getElementById("agent-install-progress");
        root.dataset.state = state;
        const order = ["waiting", "pairing", "validating", "online"];
        const current = Math.max(0, order.indexOf(state));
        root.querySelectorAll("[data-step]").forEach((element, index) => {
            element.dataset.complete = index <= current ? "true" : "false";
            element.setAttribute("aria-current", index === current ? "step" : "false");
        });
    }

    async function poll() {
        if (!installationId) return;
        try {
            const status = await request(`/agents/installations/status?installation_id=${encodeURIComponent(installationId)}`);
            progress(status.state);
            if (status.state === "online") {
                clearInterval(pollTimer);
                pollTimer = null;
                await loadAgents();
            }
        } catch (error) {
            errorMessage(error.message);
        }
    }

    async function generate(event) {
        event.preventDefault();
        const platform = document.querySelector('input[name="agent-platform"]:checked').value;
        const method = document.querySelector('input[name="agent-method"]:checked').value;
        const regionId = document.getElementById("agent-install-region").value;
        const datacenterId = document.getElementById("agent-install-datacenter").value;
        const controllerId = currentUser.role === "controller"
            ? currentUser.scope_id
            : document.getElementById("agent-install-controller").value;
        try {
            const result = await request("/agents/installations", {
                method: "POST",
                body: JSON.stringify({
                    platform,
                    method,
                    region_id: regionId,
                    datacenter_id: datacenterId,
                    controller_id: controllerId,
                    controller_url: window.location.origin
                })
            });
            installationId = result.installation_id;
            document.getElementById("agent-install-result").hidden = false;
            document.getElementById("agent-install-command").value = result.instruction;
            document.getElementById("agent-install-expiry").textContent = `Token válido até ${result.expires_at}. Uso único.`;
            progress("waiting");
            if (pollTimer) clearInterval(pollTimer);
            pollTimer = setInterval(poll, 3000);
        } catch (error) {
            errorMessage(error.message);
        }
    }

    async function initializePhase14() {
        for (let i = 0; i < 50 && (!currentUser || !infrastructureTopology); i += 1) {
            await new Promise(resolve => setTimeout(resolve, 100));
        }
        if (!currentUser || !infrastructureTopology) return;
        populateTopology();
        document.getElementById("agent-install-form").addEventListener("submit", generate);
        document.getElementById("add-agent-focus").addEventListener("click", () => {
            document.getElementById("add-agent").scrollIntoView({behavior: "smooth", block: "start"});
        });
        document.getElementById("copy-agent-install").addEventListener("click", async () => {
            await navigator.clipboard.writeText(document.getElementById("agent-install-command").value);
        });
    }

    window.addEventListener("load", initializePhase14);
})();
