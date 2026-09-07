/*
==============================================================
 Capivara DSM
 Hierarchical Runtime Selector
==============================================================
 Customer discovery follows the canonical CatalogIndex:
 GameDefinition -> Edition -> Distribution -> RuntimeDefinition.
 Flat runtime discovery is used only to hydrate canonical runtime IDs.
==============================================================
*/

(function () {
    "use strict";

    const $ = (id) => document.getElementById(id);
    let openingPromise = null;

    const state = {
        contract: null,
        game: null,
        catalogGame: null,
        runtimeById: new Map(),
        edition: null,
        distribution: null,
        runtime: null,
        version: null,
        build: null,
        regions: [],
        region: null,
        allowCrossRegion: false,
        creating: false,
    };

    function elements() {
        return {
            panel: $("create-instance-panel"),
            title: $("create-instance-title"),
            description: $("create-instance-description"),
            close: $("create-instance-close"),
            gameSummary: $("runtime-game-summary"),
            editions: $("runtime-editions"),
            typeStep: $("runtime-type-step"),
            types: $("runtime-types"),
            versionStep: $("runtime-version-step"),
            version: $("runtime-version"),
            buildStep: $("runtime-build-step"),
            build: $("runtime-build"),
            regionStep: $("runtime-region-step"),
            region: $("runtime-region"),
            regionFallback: $("runtime-region-fallback"),
            regionHelp: $("runtime-region-help"),
            summaryStep: $("runtime-summary-step"),
            summaryGame: $("runtime-summary-game"),
            summaryEdition: $("runtime-summary-edition"),
            summaryRuntime: $("runtime-summary-runtime"),
            summaryVersion: $("runtime-summary-version"),
            summaryBuild: $("runtime-summary-build"),
            summaryRegion: $("runtime-summary-region"),
            summaryRegionFallback: $("runtime-summary-region-fallback"),
            minecraftNotice: $("minecraft-runtime-notice"),
            minecraftEula: $("minecraft-eula-accepted"),
            submit: $("create-instance-submit"),
            message: $("customer-message"),
        };
    }

    function showMessage(text) {
        const node = elements().message;
        if (!node) return;
        node.textContent = text;
        node.classList.add("show");
        clearTimeout(showMessage.timer);
        showMessage.timer = setTimeout(() => node.classList.remove("show"), 4000);
    }

    async function request(path, options = {}) {
        const headers = {
            "X-Capivara-Auth-Area": "customer",
            Accept: "application/json",
            ...(options.headers || {}),
        };
        if (options.body) headers["Content-Type"] = "application/json";
        const response = await fetch(path, {
            ...options,
            headers,
            credentials: "same-origin",
            cache: options.cache || "no-store",
        });
        if (response.status === 401) {
            window.location.href = "/customer-login.html";
            throw new Error("Sessão encerrada.");
        }
        const type = response.headers.get("content-type") || "";
        const data = type.includes("application/json") ? await response.json() : await response.text();
        if (!response.ok) {
            throw new Error(
                data && typeof data === "object"
                    ? (data.message || data.error || `Erro HTTP ${response.status}`)
                    : (String(data || "").trim() || `Erro HTTP ${response.status}`)
            );
        }
        return data;
    }

    function placementClient() {
        const client = window.CapivaraPlacementClient;
        if (!client || typeof client.loadRuntimes !== "function" || typeof client.loadRegions !== "function") {
            throw new Error("O cliente de placement não está disponível.");
        }
        return client;
    }

    function normalize(value) {
        return String(value ?? "").trim().toLowerCase();
    }

    function titleCase(value) {
        return String(value ?? "")
            .replace(/[-_]+/g, " ")
            .replace(/\b\w/g, (letter) => letter.toUpperCase());
    }

    function gameLabel() {
        return state.catalogGame?.name || titleCase(state.game);
    }

    function editionLabel(value) {
        const labels = {java: "Java Edition", bedrock: "Bedrock Edition", default: "Padrão"};
        return labels[normalize(value)] || titleCase(value);
    }

    function distributionLabel(distribution, runtime) {
        const labels = {
            vanilla: "Vanilla", paper: "Paper", purpur: "Purpur", fabric: "Fabric",
            forge: "Forge", neoforge: "NeoForge", quilt: "Quilt", folia: "Folia",
            dedicated_server: "Servidor dedicado", "dedicated-server": "Servidor dedicado",
        };
        return runtime?.name || runtime?.display_name || labels[normalize(distribution?.id)] || titleCase(distribution?.id);
    }

    function currentEditionNode() {
        return state.catalogGame?.editions?.find((item) => item.id === state.edition) || null;
    }

    function currentDistributions() {
        return Array.isArray(currentEditionNode()?.distributions) ? currentEditionNode().distributions : [];
    }

    function runtimeForDistribution(distribution) {
        const ids = Array.isArray(distribution?.runtime_definitions) ? distribution.runtime_definitions : [];
        for (const id of ids) {
            const runtime = state.runtimeById.get(id);
            if (runtime) return runtime;
        }
        return null;
    }

    async function loadCatalog(game) {
        const [hierarchy, runtimeData] = await Promise.all([
            request(`/api/catalog/hierarchy?game=${encodeURIComponent(game)}`),
            placementClient().loadRuntimes(game),
        ]);
        const games = Array.isArray(hierarchy?.games) ? hierarchy.games : [];
        const catalogGame = games.find((item) => normalize(item.id) === game);
        if (!catalogGame) throw new Error("O jogo contratado não está publicado no catálogo hierárquico.");

        const runtimes = Array.isArray(runtimeData)
            ? runtimeData
            : Array.isArray(runtimeData?.runtimes)
                ? runtimeData.runtimes
                : Array.isArray(runtimeData?.entries) ? runtimeData.entries : [];
        const runtimeById = new Map(runtimes.filter((item) => item?.id).map((item) => [item.id, item]));

        const missing = [];
        for (const edition of catalogGame.editions || []) {
            for (const distribution of edition.distributions || []) {
                for (const runtimeId of distribution.runtime_definitions || []) {
                    if (!runtimeById.has(runtimeId)) missing.push(runtimeId);
                }
            }
        }
        if (missing.length) {
            throw new Error(`Catálogo inconsistente: RuntimeDefinition ausente (${missing.join(", ")}).`);
        }
        return {catalogGame, runtimeById};
    }

    async function loadRegions() {
        const contractId = String(state.contract?.id || state.contract?.contract_id || "").trim();
        const data = await placementClient().loadRegions({game: state.game, contract: contractId});
        state.regions = Array.isArray(data?.regions) ? data.regions : [];
    }

    function resetSelectionUI() {
        const el = elements();
        el.editions.replaceChildren();
        el.types.replaceChildren();
        el.typeStep.hidden = true;
        el.versionStep.hidden = true;
        el.buildStep.hidden = true;
        el.regionStep.hidden = true;
        el.summaryStep.hidden = true;
        el.minecraftNotice.hidden = true;
        if (el.minecraftEula) el.minecraftEula.checked = false;
        el.version.replaceChildren(new Option("Selecione…", ""));
        el.build.replaceChildren(new Option("Selecione…", ""));
        el.submit.disabled = true;
    }

    async function openSelector(contract) {
        if (!contract) throw new Error("Contrato não informado.");
        const game = normalize(contract.game_id || contract.game);
        if (!game) throw new Error("O contrato não possui jogo definido.");

        state.contract = contract;
        state.game = game;
        state.catalogGame = null;
        state.runtimeById = new Map();
        state.edition = null;
        state.distribution = null;
        state.runtime = null;
        state.version = null;
        state.build = null;
        state.region = null;
        state.allowCrossRegion = false;

        const el = elements();
        el.panel.hidden = false;
        el.title.textContent = `Criar servidor ${titleCase(game)}`;
        el.description.textContent = "Escolha a edição e a distribuição publicadas no catálogo.";
        resetSelectionUI();
        showMessage("Carregando catálogo e ambientes disponíveis…");

        const [catalog] = await Promise.all([loadCatalog(game), loadRegions()]);
        state.catalogGame = catalog.catalogGame;
        state.runtimeById = catalog.runtimeById;
        el.title.textContent = `Criar servidor ${gameLabel()}`;
        el.gameSummary.textContent = gameLabel();
        renderRegions();
        renderEditions();
        el.panel.scrollIntoView({behavior: "smooth", block: "start"});
    }

    function createSelectionCard(title, description, selected, callback) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "runtime-selector-card";
        if (selected) button.classList.add("selected");
        const strong = document.createElement("strong");
        strong.textContent = title;
        const small = document.createElement("small");
        small.textContent = description;
        button.append(strong, small);
        button.addEventListener("click", callback);
        return button;
    }

    function renderEditions() {
        const el = elements();
        el.editions.replaceChildren();
        const editions = Array.isArray(state.catalogGame?.editions) ? state.catalogGame.editions : [];
        if (!editions.length) throw new Error("O jogo não possui edições publicadas.");

        for (const edition of editions) {
            const description = edition.id === "java"
                ? "Ecossistema Java: escolha a distribuição do servidor."
                : edition.id === "bedrock"
                    ? "Servidor compatível com clientes Bedrock."
                    : "Edição publicada no catálogo.";
            el.editions.append(createSelectionCard(
                editionLabel(edition.id),
                description,
                state.edition === edition.id,
                () => selectEdition(edition.id)
            ));
        }
        if (editions.length === 1 && !state.edition) selectEdition(editions[0].id);
    }

    function selectEdition(edition) {
        state.edition = edition;
        state.distribution = null;
        state.runtime = null;
        state.version = null;
        state.build = null;
        renderEditions();
        renderDistributions();
    }

    function renderDistributions() {
        const el = elements();
        el.typeStep.hidden = false;
        el.versionStep.hidden = true;
        el.buildStep.hidden = true;
        el.regionStep.hidden = true;
        el.summaryStep.hidden = true;
        el.types.replaceChildren();
        const distributions = currentDistributions();

        if (!distributions.length) {
            el.types.textContent = "Nenhuma distribuição publicada para esta edição.";
            return;
        }

        for (const distribution of distributions) {
            const runtime = runtimeForDistribution(distribution);
            if (!runtime) continue;
            const provider = runtime.artifact?.provider || runtime.provider || "";
            el.types.append(createSelectionCard(
                distributionLabel(distribution, runtime),
                provider ? `Provider: ${provider}` : "Distribuição publicada",
                state.distribution === distribution.id && state.runtime?.id === runtime.id,
                () => selectDistribution(distribution, runtime)
            ));
        }
        if (distributions.length === 1 && !state.distribution) {
            const runtime = runtimeForDistribution(distributions[0]);
            if (runtime) selectDistribution(distributions[0], runtime);
        }
    }

    function selectDistribution(distribution, runtime) {
        state.distribution = distribution.id;
        state.runtime = runtime;
        state.version = null;
        state.build = null;
        renderDistributions();
        renderVersions().catch((error) => showMessage(`Não foi possível carregar as versões: ${error.message}`));
    }

    function extractVersions(runtime) {
        let versions = [];
        if (Array.isArray(runtime?.versions)) versions = runtime.versions;
        else if (Array.isArray(runtime?.version?.available)) versions = runtime.version.available;
        else if (Array.isArray(runtime?.version?.versions)) versions = runtime.version.versions;
        else if (runtime?.version && typeof runtime.version === "object" && runtime.version.value) versions = [runtime.version];
        else if (typeof runtime?.version === "string") versions = [runtime.version];
        return versions.map((entry) => {
            if (typeof entry === "string" || typeof entry === "number") return {value: String(entry), label: String(entry), raw: entry};
            const value = entry?.value || entry?.version || entry?.id || entry?.name;
            return value ? {
                value: String(value), label: String(entry.label || entry.name || value),
                recommended: entry.recommended === true, current: entry.current === true, raw: entry,
            } : null;
        }).filter(Boolean);
    }

    async function renderVersions() {
        const el = elements();
        const runtime = state.runtime;
        if (!runtime) return;
        el.versionStep.hidden = false;
        el.version.disabled = true;
        el.version.replaceChildren(new Option("Carregando versões…", ""));
        let versions = [];
        if (runtime.version?.strategy === "dynamic") {
            const data = await request(`/api/catalog/versions?runtime=${encodeURIComponent(runtime.id)}`);
            versions = Array.isArray(data) ? data : (data.versions || []);
        } else {
            versions = extractVersions(runtime);
        }
        if (!versions.length) versions = [{value: "current", label: "Versão atual / recomendada", recommended: true}];
        versions = versions.map((entry) => typeof entry === "object" && entry.value !== undefined ? entry : {
            value: String(entry.value || entry.version || entry.id),
            label: String(entry.label || entry.name || entry.version || entry.value || entry.id),
            recommended: entry.recommended === true,
            current: entry.current === true,
            raw: entry,
        });
        runtime.versions = versions;
        el.version.replaceChildren(new Option("Selecione…", ""));
        for (const version of versions) {
            el.version.append(new Option(
                version.label + ((version.recommended || version.current) ? " — recomendada" : ""),
                version.value
            ));
        }
        el.version.disabled = false;
        const selected = versions.find((item) => item.recommended || item.current) || (versions.length === 1 ? versions[0] : null);
        if (selected) {
            el.version.value = selected.value;
            await selectVersion(selected.value);
        }
    }

    function extractBuilds(runtime, version) {
        let builds = Array.isArray(version?.raw?.builds) ? version.raw.builds : [];
        if (!builds.length && Array.isArray(runtime?.builds)) builds = runtime.builds;
        if (!builds.length && runtime?.build?.value) builds = [runtime.build];
        return builds.map((entry) => {
            if (typeof entry === "string" || typeof entry === "number") return {value: String(entry), label: String(entry), raw: entry};
            const value = entry?.value || entry?.build || entry?.id || entry?.name;
            return value === undefined ? null : {
                value: String(value), label: String(entry.label || entry.name || value),
                recommended: entry.recommended === true, current: entry.current === true, raw: entry,
            };
        }).filter(Boolean);
    }

    async function selectVersion(value) {
        state.version = extractVersions(state.runtime).find((entry) => entry.value === value)
            || state.runtime.versions?.find((entry) => entry.value === value) || null;
        state.build = null;
        if (state.version) await renderBuilds();
    }

    async function renderBuilds() {
        const el = elements();
        el.buildStep.hidden = false;
        el.build.disabled = true;
        el.build.replaceChildren(new Option("Carregando builds…", ""));
        let builds = [];
        if (state.runtime.version?.strategy === "dynamic") {
            const data = await request(`/api/catalog/builds?${new URLSearchParams({
                runtime: state.runtime.id,
                version: state.version.value,
            })}`);
            builds = Array.isArray(data) ? data : (data.builds || []);
        } else {
            builds = extractBuilds(state.runtime, state.version);
        }
        if (!builds.length) builds = [{value: "current", label: "Build atual / recomendada", recommended: true}];
        builds = builds.map((entry) => typeof entry === "object" && entry.value !== undefined ? entry : {
            value: String(entry.value || entry.build || entry.id),
            label: String(entry.label || entry.name || entry.build || entry.value || entry.id),
            recommended: entry.recommended === true,
            current: entry.current === true,
            raw: entry,
        });
        state.version.raw = (state.version.raw && typeof state.version.raw === "object") ? state.version.raw : {value: state.version.value};
        state.version.raw.builds = builds;
        el.build.replaceChildren(new Option("Selecione…", ""));
        for (const build of builds) {
            el.build.append(new Option(
                build.label + ((build.recommended || build.current) ? " — recomendada" : ""),
                build.value
            ));
        }
        el.build.disabled = false;
        const selected = builds.find((item) => item.recommended || item.current) || (builds.length === 1 ? builds[0] : null);
        if (selected) {
            el.build.value = selected.value;
            selectBuild(selected.value);
        }
    }

    function selectBuild(value) {
        state.build = extractBuilds(state.runtime, state.version).find((entry) => entry.value === value)
            || state.version.raw?.builds?.find((entry) => entry.value === value) || null;
        updateSummary();
    }

    function regionLabel(region) {
        if (!region) return "";
        return [region.name, region.country_code].filter(Boolean).join(" - ") || region.id || "Região";
    }

    function renderRegions() {
        const el = elements();
        el.region.replaceChildren(new Option("Selecione…", ""));
        for (const region of state.regions) el.region.append(new Option(regionLabel(region), region.id));
        el.region.disabled = state.regions.length === 0;
        el.regionHelp.textContent = state.regions.length
            ? "A recomendação considera disponibilidade e latência estimada. O Controller selecionará o Agent adequado."
            : "Nenhum servidor elegível está disponível para esta instância.";
    }

    function updateSummary() {
        const el = elements();
        const complete = Boolean(state.game && state.edition && state.distribution && state.runtime && state.version && state.build);
        el.regionStep.hidden = !complete;
        el.summaryStep.hidden = !complete;
        if (!complete) {
            el.submit.disabled = true;
            return;
        }
        el.summaryGame.textContent = gameLabel();
        el.summaryEdition.textContent = editionLabel(state.edition);
        el.summaryRuntime.textContent = distributionLabel({id: state.distribution}, state.runtime);
        el.summaryVersion.textContent = state.version.label;
        el.summaryBuild.textContent = state.build.label;
        el.summaryRegion.textContent = state.region ? regionLabel(state.region) : "Automática";
        el.summaryRegionFallback.textContent = state.allowCrossRegion ? "Sim" : "Não";
        el.minecraftNotice.hidden = state.game !== "minecraft";
        el.submit.disabled = false;
    }

    function createPayload() {
        if (!state.contract || !state.runtime || !state.version || !state.build) throw new Error("A seleção do servidor está incompleta.");
        return {
            game: state.game,
            contract_id: state.contract.id,
            resource_profile_id: state.contract.resource_profile_id || null,
            runtime_id: state.runtime.id,
            edition: state.edition,
            variant: state.distribution,
            version: state.version.value,
            build: state.build.value,
            runtime: {
                id: state.runtime.id,
                game: state.game,
                edition: state.edition,
                variant: state.distribution,
                version: state.version.value,
                build: state.build.value,
            },
            placement: {region_id: state.region?.id || null, allow_cross_region: state.allowCrossRegion},
        };
    }

    async function createInstance() {
        if (state.creating) return;
        const el = elements();
        const payload = createPayload();
        state.creating = true;
        el.submit.disabled = true;
        const original = el.submit.textContent;
        el.submit.textContent = "Criando servidor…";
        try {
            const result = await request("/api/instance/create", {method: "POST", body: JSON.stringify(payload)});
            showMessage("Servidor criado. O provisionamento foi iniciado.");
            closeSelector();
            if (result?.instance_id && result?.node_id && result?.game) {
                const params = new URLSearchParams({server: result.node_id, game: result.game, instance: result.instance_id});
                window.location.href = `/customer-instance.html?${params}`;
                return;
            }
            if (window.CapivaraCustomer?.reload) await window.CapivaraCustomer.reload();
            else window.location.reload();
        } finally {
            state.creating = false;
            el.submit.textContent = original;
            if (!el.panel.hidden) updateSummary();
        }
    }

    function closeSelector() {
        elements().panel.hidden = true;
        state.contract = null;
        state.game = null;
        state.catalogGame = null;
        state.runtimeById = new Map();
        state.edition = null;
        state.distribution = null;
        state.runtime = null;
        state.version = null;
        state.build = null;
        state.regions = [];
        state.region = null;
        state.allowCrossRegion = false;
        resetSelectionUI();
    }

    function installEvents() {
        const el = elements();
        el.close?.addEventListener("click", closeSelector);
        el.version?.addEventListener("change", () => selectVersion(el.version.value).catch((e) => showMessage(e.message)));
        el.build?.addEventListener("change", () => selectBuild(el.build.value));
        el.region?.addEventListener("change", () => {
            state.region = state.regions.find((region) => region.id === el.region.value) || null;
            updateSummary();
        });
        el.regionFallback?.addEventListener("change", () => {
            state.allowCrossRegion = Boolean(el.regionFallback.checked);
            updateSummary();
        });
        el.minecraftEula?.addEventListener("change", updateSummary);
        el.submit?.addEventListener("click", () => createInstance().catch((e) => showMessage(`Não foi possível criar o servidor: ${e.message}`)));
    }

    function open(contract) {
        if (openingPromise) return openingPromise;
        openingPromise = openSelector(contract)
            .catch((error) => {
                console.error(error);
                showMessage(`Não foi possível carregar o catálogo: ${error.message}`);
                throw error;
            })
            .finally(() => { openingPromise = null; });
        return openingPromise;
    }

    window.CapivaraRuntimeSelector = {
        open,
        close: closeSelector,
        state() {
            return {
                contract: state.contract,
                game: state.game,
                edition: state.edition,
                distribution: state.distribution,
                runtime: state.runtime,
                version: state.version,
                build: state.build,
                region: state.region,
                allowCrossRegion: state.allowCrossRegion,
            };
        },
    };

    document.addEventListener("DOMContentLoaded", installEvents);
})();
