"use strict";

(() => {
    function collect(value, type, result = []) {
        if (!value) return result;
        if (Array.isArray(value)) {
            value.forEach(item => collect(item, type, result));
            return result;
        }
        if (typeof value !== "object") return result;
        if (value.type === type && value.id) result.push(value);
        Object.values(value).forEach(child => {
            if (child && typeof child === "object") collect(child, type, result);
        });
        return result;
    }

    function unique(items) {
        const map = new Map();
        items.forEach(item => map.set(String(item.id), item));
        return [...map.values()];
    }

    async function initializeLocationUi() {
        for (let i = 0; i < 50 && !infrastructureTopology; i += 1) {
            await new Promise(resolve => setTimeout(resolve, 100));
        }
        if (!infrastructureTopology) return;

        const regionSelect = document.getElementById("agent-region");
        const datacenterSelect = document.getElementById("agent-datacenter");
        const regions = unique(collect(infrastructureTopology, "region"));
        const datacenters = unique(collect(infrastructureTopology, "datacenter"));

        regionSelect.replaceChildren(new Option("Selecione uma região", ""));
        regions.forEach(item => regionSelect.appendChild(new Option(item.name || item.id, item.id)));

        function renderDatacenters() {
            const previous = datacenterSelect.value;
            datacenterSelect.replaceChildren(new Option("Selecione um datacenter", ""));
            datacenters
                .filter(item => !regionSelect.value || String(item.region_id || item.region?.id || "") === regionSelect.value)
                .forEach(item => datacenterSelect.appendChild(new Option(item.name || item.id, item.id)));
            if ([...datacenterSelect.options].some(item => item.value === previous)) datacenterSelect.value = previous;
        }

        regionSelect.addEventListener("change", renderDatacenters);
        datacenterSelect.addEventListener("change", () => {
            const selected = datacenters.find(item => String(item.id) === datacenterSelect.value);
            if (selected) regionSelect.value = String(selected.region_id || selected.region?.id || regionSelect.value);
        });
        renderDatacenters();
    }

    window.addEventListener("load", initializeLocationUi);
})();
