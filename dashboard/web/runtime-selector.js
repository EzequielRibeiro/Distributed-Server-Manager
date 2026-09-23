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
        buildRequestGeneration: 0,
        placementRequestGeneration: 0,
        placementAbortController: null,
        placementLoading: false,
        placementReady: false,
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
        const timeoutMs = Number(options.timeoutMs || 0);
        const controller = timeoutMs > 0 && !options.signal ? new AbortController() : null;
        const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
        const headers = {
            "X-Capivara-Auth-Area": "customer",
            Accept: "application/json",
            ...(options.headers || {}),
        };
        if (options.body) headers["Content-Type"] = "application/json";
        const fetchOptions = {...options};
        delete fetchOptions.timeoutMs;
        let response;
        try {
            response = await fetch(path, {
                ...fetchOptions,
                signal: controller?.signal || options.signal,
                headers,
                credentials: "same-origin",
                cache: options.cache || "no-store",
            });
        } catch (error) {
            if (controller?.signal.aborted) throw new Error("A consulta ao catálogo excedeu o tempo limite.");
            throw error;
        } finally {
            if (timer) clearTimeout(timer);
        }
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
            spongevanilla: "SpongeVanilla", arclight: "Arclight", youer: "Youer",
            bedrock: "Bedrock", dedicated_server: "Servidor dedicado",
            "dedicated-server": "Servidor dedicado",
        };
        const variant = normalize(distribution?.id || runtime?.variant || runtime?.loader);
        return labels[variant] || runtime?.display_name || runtime?.name || titleCase(distribution?.id);
    }

    function runtimeCardVariant(distribution, runtime) {
        return normalize(runtime?.variant || runtime?.loader || distribution?.id || "runtime");
    }

    function runtimeCardIconId(distribution, runtime) {
        const icons = {
            vanilla: "runtime-vanilla",
            paper: "runtime-paper",
            purpur: "runtime-purpur",
            fabric: "runtime-fabric",
            forge: "runtime-forge",
            neoforge: "runtime-neoforge",
            quilt: "runtime-quilt",
            folia: "runtime-folia",
            spongevanilla: "runtime-spongevanilla",
            arclight: "runtime-arclight",
            youer: "runtime-youer",
            bedrock: "runtime-bedrock",
        };
        return icons[runtimeCardVariant(distribution, runtime)] || "runtime-default";
    }

    function runtimeCardIconMarkup(iconId) {
        const icons = {
            "runtime-vanilla": '<path d="M24 5 39 13.5V31L24 39 9 31V13.5L24 5Z" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/><path d="m9 13.5 15 8.5 15-8.5M24 22v17" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>',
            "runtime-fabric": '<path d="M10 11h28v26H10zM16 7v34M24 7v34M32 7v34M6 16h36M6 24h36M6 32h36" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
            "runtime-forge": '<path d="M12 13h17l5 5-7 7-5-5-9 9-6-6 9-9-4-1Z" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linejoin="round"/><path d="m29 10 9 9M11 35h26M16 31h16l4 4H12l4-4Z" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>',
            "runtime-neoforge": '<path d="M24 5 39 14v20L24 43 9 34V14L24 5Z" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/><path d="M16 32V16l16 16V16" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>',
            "runtime-quilt": '<path d="M9 9h13v13H9zM26 9h13v13H26zM9 26h13v13H9zM26 26h13v13H26z" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/><path d="m9 22 13-13m4 30 13-13" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>',
            "runtime-paper": '<path d="M14 6h14l8 8v28H14V6Z" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/><path d="M28 6v9h8M19 23h12M19 29h12M19 35h8" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>',
            "runtime-purpur": '<path d="m24 5 16 19-16 19L8 24 24 5Z" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/><path d="M19 32V16h6a6 6 0 0 1 0 12h-6" fill="none" stroke="currentColor" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round"/>',
            "runtime-folia": '<path d="M38 9C24 10 13 18 11 34c11 1 24-5 27-25Z" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/><path d="M13 36c7-10 13-15 22-21M22 28c0-4-1-7-3-10M27 23c4 0 7 1 10 3" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round"/>',
            "runtime-spongevanilla": '<rect x="9" y="9" width="30" height="30" rx="5" fill="none" stroke="currentColor" stroke-width="2.4"/><circle cx="17" cy="17" r="2.5" fill="currentColor"/><circle cx="30" cy="15" r="3" fill="currentColor"/><circle cx="24" cy="26" r="3.5" fill="currentColor"/><circle cx="15" cy="32" r="2.2" fill="currentColor"/><circle cx="33" cy="33" r="2.5" fill="currentColor"/>',
            "runtime-arclight": '<path d="M8 31c5-15 17-22 32-18-11 3-18 10-22 22" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/><path d="m34 8 1.8 4.3L40 14l-4.2 1.7L34 20l-1.8-4.3L28 14l4.2-1.7L34 8Z" fill="currentColor"/><path d="M14 37h21" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/>',
            "runtime-youer": '<path d="M12 10 24 25 36 10M24 25v14" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><path d="M9 34h8M31 34h8M9 40h30" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round"/>',
            "runtime-bedrock": '<path d="M8 13h32v22H8V13Z" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/><path d="M8 21h32M15 13v8M31 13v8M14 35v-8h8v8M27 35v-8h7v8" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linejoin="round"/>',
            "runtime-default": '<circle cx="24" cy="24" r="16" fill="none" stroke="currentColor" stroke-width="2.5"/><path d="M24 13v22M13 24h22" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>',
        };
        return icons[iconId] || icons["runtime-default"];
    }

    function runtimeCardCapabilities(runtime) {
        const types = runtime?.content?.managed?.types || {};
        const bundles = runtime?.content?.bundles || {};
        const ports = Array.isArray(runtime?.network?.ports) ? runtime.network.ports : [];
        const mods = Boolean(types.mod);
        const plugins = Boolean(types.plugin);
        const modpacks = Boolean(bundles.modpack);
        const hasVotifierPort = ports.some((port) => normalize(port?.name) === "votifier");
        let votifierMode = "";
        if (hasVotifierPort && mods && plugins) votifierMode = "Mod/Plugin";
        else if (hasVotifierPort && plugins) votifierMode = "Plugin";
        else if (hasVotifierPort && mods) votifierMode = "Mod";
        const votifier = Boolean(votifierMode);
        return {mods, plugins, modpacks, votifier, votifierMode};
    }

    function runtimeCardDescription(capabilities) {
        if (capabilities.mods && capabilities.plugins && capabilities.modpacks) {
            return "Runtime híbrido para combinar mods, plugins e modpacks.";
        }
        if (capabilities.mods && capabilities.plugins) {
            return "Runtime híbrido com suporte a mods e plugins.";
        }
        if (capabilities.modpacks) {
            return "Indicado para mods e modpacks gerenciados.";
        }
        if (capabilities.plugins) {
            return "Indicado para servidores baseados em plugins.";
        }
        return "Servidor padrão sem camada gerenciada de mods ou plugins.";
    }

    function runtimeCardTag(capabilities) {
        if (capabilities.mods && capabilities.plugins) return "Mods + Plugins";
        if (capabilities.modpacks) return "Modpacks";
        if (capabilities.plugins) return "Plugins";
        if (capabilities.mods) return "Mods";
        return "Padrão";
    }

    function contractAllowsRuntime(runtimeId) {
        const allowed = state.contract?.allowed_runtime_ids;
        if (!Array.isArray(allowed)) return false;
        return allowed.some((value) => String(value || "").trim() === String(runtimeId || "").trim());
    }

    function contractRuntimeMessage() {
        const mode = normalize(state.contract?.content_mode || state.contract?.product_variant || "standard");
        if (state.game === "minecraft" && mode === "standard") {
            return "Exige Minecraft Modificado";
        }
        return "Não incluído neste contrato";
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
        const runtimeId = String(state.runtime?.id || "").trim();
        if (!runtimeId) return;

        state.placementAbortController?.abort();
        const controller = new AbortController();
        state.placementAbortController = controller;
        const generation = ++state.placementRequestGeneration;
        const previousRegionId = state.region?.id || null;
        const isCurrentRequest = () => (
            generation === state.placementRequestGeneration
            && String(state.runtime?.id || "").trim() === runtimeId
        );

        state.placementLoading = true;
        state.placementReady = false;
        state.regions = [];
        state.region = null;
        renderRegions();
        updateSummary();

        try {
            const data = await placementClient().loadRegions({
                game: state.game,
                contract: contractId,
                runtime: runtimeId,
            }, {signal: controller.signal});
            if (!isCurrentRequest()) return;
            state.regions = Array.isArray(data?.regions) ? data.regions : [];
            state.region = previousRegionId
                ? state.regions.find((region) => region.id === previousRegionId) || null
                : null;
            state.placementLoading = false;
            state.placementReady = state.regions.length > 0;
            renderRegions();
            updateSummary();
        } catch (error) {
            if (!isCurrentRequest()) return;
            state.placementLoading = false;
            state.placementReady = false;
            state.regions = [];
            state.region = null;
            renderRegions();
            updateSummary();
            throw error;
        } finally {
            if (state.placementAbortController === controller) {
                state.placementAbortController = null;
            }
        }
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
        state.buildRequestGeneration += 1;
        state.placementRequestGeneration += 1;
        state.placementAbortController?.abort();
        state.placementAbortController = null;
        state.placementLoading = false;
        state.placementReady = false;
        state.regions = [];
        state.region = null;
        state.allowCrossRegion = false;

        const el = elements();
        el.panel.hidden = false;
        el.title.textContent = `Criar servidor ${titleCase(game)}`;
        const contractMode = normalize(contract.content_mode || contract.product_variant || "standard");
        el.description.textContent = game === "minecraft"
            ? `Escolha uma distribuição incluída no contrato ${contractMode === "modified" ? "Minecraft Modificado" : "Minecraft Padrão"}.`
            : "Escolha a edição e a distribuição publicadas no catálogo.";
        resetSelectionUI();
        showMessage("Carregando catálogo e ambientes disponíveis…");

        const catalog = await loadCatalog(game);
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
        button.setAttribute("aria-pressed", selected ? "true" : "false");
        if (selected) button.classList.add("selected");
        const strong = document.createElement("strong");
        strong.textContent = title;
        const small = document.createElement("small");
        small.textContent = description;
        button.append(strong, small);
        button.addEventListener("click", callback);
        return button;
    }

    function createRuntimeCard(distribution, runtime, selected, allowed, callback) {
        const capabilities = runtimeCardCapabilities(runtime);
        const variant = runtimeCardVariant(distribution, runtime);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "runtime-selector-card runtime-distribution-card";
        button.dataset.runtime = variant;
        button.setAttribute("aria-pressed", selected ? "true" : "false");
        button.disabled = !allowed;
        button.setAttribute("aria-disabled", allowed ? "false" : "true");
        if (selected) button.classList.add("selected");
        if (!allowed) button.classList.add("contract-blocked");

        const header = document.createElement("span");
        header.className = "runtime-card-header";

        const mark = document.createElement("span");
        mark.className = "runtime-card-mark";
        mark.setAttribute("aria-hidden", "true");
        const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        icon.classList.add("runtime-card-icon");
        icon.setAttribute("viewBox", "0 0 48 48");
        icon.setAttribute("focusable", "false");
        icon.innerHTML = runtimeCardIconMarkup(runtimeCardIconId(distribution, runtime));
        mark.append(icon);

        const heading = document.createElement("span");
        heading.className = "runtime-card-heading";
        const name = document.createElement("strong");
        name.textContent = distributionLabel(distribution, runtime);
        const tag = document.createElement("span");
        tag.className = "runtime-card-tag";
        tag.textContent = runtimeCardTag(capabilities);
        heading.append(name, tag);
        header.append(mark, heading);

        const description = document.createElement("small");
        description.className = "runtime-card-summary";
        description.textContent = runtimeCardDescription(capabilities);

        const capabilityGrid = document.createElement("span");
        capabilityGrid.className = "runtime-capabilities";
        const entries = [
            ["Mods", capabilities.mods],
            ["Plugins", capabilities.plugins],
            ["Modpacks", capabilities.modpacks],
            [capabilities.votifierMode ? `Votifier · ${capabilities.votifierMode}` : "Votifier", capabilities.votifier],
        ];
        for (const [label, supported] of entries) {
            const capability = document.createElement("span");
            capability.className = `runtime-capability ${supported ? "supported" : "unsupported"}`;
            capability.setAttribute("aria-label", `${label}: ${supported ? "suportado" : "não suportado"}`);
            capability.textContent = `${supported ? "✓" : "—"} ${label}`;
            capabilityGrid.append(capability);
        }

        if (!allowed) {
            const contractNote = document.createElement("span");
            contractNote.className = "runtime-card-contract-note";
            contractNote.textContent = contractRuntimeMessage();
            button.append(header, description, capabilityGrid, contractNote);
        } else {
            button.append(header, description, capabilityGrid);
            button.addEventListener("click", callback);
        }
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
        state.buildRequestGeneration += 1;
        state.edition = edition;
        state.distribution = null;
        state.runtime = null;
        state.version = null;
        state.build = null;
        state.placementRequestGeneration += 1;
        state.placementAbortController?.abort();
        state.placementAbortController = null;
        state.placementLoading = false;
        state.placementReady = false;
        state.regions = [];
        state.region = null;
        renderRegions();
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
            const allowed = contractAllowsRuntime(runtime.id);
            el.types.append(createRuntimeCard(
                distribution,
                runtime,
                state.distribution === distribution.id && state.runtime?.id === runtime.id,
                allowed,
                () => selectDistribution(distribution, runtime)
            ));
        }
        if (distributions.length === 1 && !state.distribution) {
            const runtime = runtimeForDistribution(distributions[0]);
            if (runtime && contractAllowsRuntime(runtime.id)) selectDistribution(distributions[0], runtime);
        }
    }

    function selectDistribution(distribution, runtime) {
        if (!contractAllowsRuntime(runtime?.id)) {
            showMessage(contractRuntimeMessage());
            return;
        }
        state.buildRequestGeneration += 1;
        state.distribution = distribution.id;
        state.runtime = runtime;
        state.version = null;
        state.build = null;
        state.placementRequestGeneration += 1;
        state.placementAbortController?.abort();
        state.placementAbortController = null;
        state.placementLoading = false;
        state.placementReady = false;
        state.regions = [];
        state.region = null;
        renderRegions();
        renderDistributions();
        elements().buildStep.hidden = true;
        updateSummary();
        loadRegions().catch((error) => showMessage(`Não foi possível verificar os servidores disponíveis: ${error.message}`));
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
            const data = await request(`/api/catalog/versions?runtime=${encodeURIComponent(runtime.id)}`, {timeoutMs: 15000});
            versions = Array.isArray(data) ? data : (data.versions || []);
        } else {
            versions = extractVersions(runtime);
        }
        if (!versions.length) {
            if (runtime.version?.strategy === "dynamic") {
                throw new Error("Nenhuma versão publicada foi retornada pelo provedor deste runtime.");
            }
            versions = [{value: "current", label: "Versão atual / recomendada", recommended: true}];
        }
        versions = versions.map((entry) => typeof entry === "object" && entry.value !== undefined ? entry : {
            value: String(entry.value || entry.version || entry.id),
            label: String(entry.label || entry.name || entry.version || entry.value || entry.id),
            recommended: entry.recommended === true,
            current: entry.current === true,
            raw: entry,
        });
        runtime.versions = versions;
        const versionOptions = document.createDocumentFragment();
        versionOptions.append(new Option("Selecione…", ""));
        for (const version of versions) {
            versionOptions.append(new Option(
                version.label + ((version.recommended || version.current) ? " — recomendada" : ""),
                version.value
            ));
        }
        el.version.replaceChildren(versionOptions);
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
        state.buildRequestGeneration += 1;
        state.version = extractVersions(state.runtime).find((entry) => entry.value === value)
            || state.runtime.versions?.find((entry) => entry.value === value) || null;
        state.build = null;
        if (!state.version) {
            elements().buildStep.hidden = true;
            updateSummary();
            return;
        }
        await renderBuilds();
    }

    async function renderBuilds() {
        const el = elements();
        const runtimeId = state.runtime?.id;
        const versionValue = state.version?.value;
        const generation = ++state.buildRequestGeneration;
        const selectionStillActive = () => (
            state.runtime?.id === runtimeId
            && state.version?.value === versionValue
        );
        const isCurrentRequest = () => (
            generation === state.buildRequestGeneration
            && selectionStillActive()
        );

        el.buildStep.hidden = false;
        el.build.disabled = true;
        el.build.replaceChildren(new Option("Carregando builds…", ""));
        let builds = [];

        try {
            if (state.runtime.version?.strategy === "dynamic") {
                const data = await request(`/api/catalog/builds?${new URLSearchParams({
                    runtime: runtimeId,
                    version: versionValue,
                })}`, {timeoutMs: 15000});
                // A selection can invalidate the request generation without
                // changing the active runtime/version. In that case the response
                // is still valid and must not leave the UI stuck on "Carregando builds…".
                if (!selectionStillActive()) return;
                builds = Array.isArray(data) ? data : (data.builds || []);
            } else {
                builds = extractBuilds(state.runtime, state.version);
            }

            if (!selectionStillActive()) return;
            if (!builds.length) builds = [{value: "current", label: "Build atual / recomendada", recommended: true}];
            builds = builds.map((entry) => typeof entry === "object" && entry.value !== undefined ? entry : {
                value: String(entry.value || entry.build || entry.id),
                label: String(entry.label || entry.name || entry.build || entry.value || entry.id),
                recommended: entry.recommended === true,
                current: entry.current === true,
                raw: entry,
            });
            state.version.raw = (state.version.raw && typeof state.version.raw === "object")
                ? state.version.raw
                : {value: state.version.value};
            state.version.raw.builds = builds;
            const buildOptions = document.createDocumentFragment();
            buildOptions.append(new Option("Selecione…", ""));
            for (const build of builds) {
                buildOptions.append(new Option(
                    build.label + ((build.recommended || build.current) ? " — recomendada" : ""),
                    build.value
                ));
            }
            el.build.replaceChildren(buildOptions);
            el.build.disabled = false;
            const selected = builds.find((item) => item.recommended || item.current)
                || (builds.length === 1 ? builds[0] : null);
            if (selected) {
                el.build.value = selected.value;
                selectBuild(selected.value);
            }
        } catch (error) {
            if (!isCurrentRequest()) return;
            state.build = null;
            el.build.replaceChildren(new Option("Não foi possível carregar builds — escolha outra versão", ""));
            el.build.disabled = true;
            updateSummary();
            showMessage(`Não foi possível carregar as builds: ${error.message}`);
        }
    }

    function selectBuild(value) {
        state.build = extractBuilds(state.runtime, state.version).find((entry) => entry.value === value)
            || state.version.raw?.builds?.find((entry) => entry.value === value) || null;
        updateSummary();
    }

    function regionLabel(region) {
        if (!region) return "";
        return region.display_label || [region.name, region.country_code].filter(Boolean).join(" - ") || region.id || "Região";
    }

    function renderRegions() {
        const el = elements();
        const placeholder = state.placementLoading ? "Verificando disponibilidade…" : "Selecione…";
        el.region.replaceChildren(new Option(placeholder, ""));
        for (const region of state.regions) el.region.append(new Option(regionLabel(region), region.id));
        el.region.disabled = state.placementLoading || state.regions.length === 0;
        el.regionHelp.textContent = state.placementLoading
            ? "Verificando a compatibilidade do runtime com os servidores disponíveis."
            : state.regions.length
                ? "A recomendação considera disponibilidade, compatibilidade do runtime e latência estimada. O Controller selecionará o Agent adequado."
                : "Nenhum servidor elegível está disponível para este runtime.";
        if (state.region && state.regions.some((region) => region.id === state.region.id)) {
            el.region.value = state.region.id;
        }
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
        el.submit.disabled = !state.placementReady;
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
        state.buildRequestGeneration += 1;
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
        state.placementRequestGeneration += 1;
        state.placementAbortController?.abort();
        state.placementAbortController = null;
        state.placementLoading = false;
        state.placementReady = false;
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
