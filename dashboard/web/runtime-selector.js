/*
==============================================================
 Capivara DSM
 Runtime Selector
==============================================================

 Canonical customer runtime selector. Placement/catalog discovery
 is consumed explicitly through CapivaraPlacementClient; the
 selector no longer depends on fetch interception or an outer shim.
==============================================================
*/

(function () {
    "use strict";

    const $ = (id) => document.getElementById(id);
    let openingPromise = null;

    const state = {
        contract: null,
        game: null,
        runtimes: [],
        edition: null,
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
            editionStep: $("runtime-edition-step"),
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
            submit: $("create-instance-submit"),
            message: $("customer-message"),
        };
    }

    function showMessage(text) {
        const node = elements().message;
        if (!node) {
            console.log(text);
            return;
        }
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

        const contentType = response.headers.get("content-type") || "";
        const data = contentType.includes("application/json")
            ? await response.json()
            : await response.text();

        if (!response.ok) {
            let errorMessage = `Erro HTTP ${response.status}`;
            if (data && typeof data === "object" && (data.message || data.error)) {
                errorMessage = data.message || data.error;
            } else if (typeof data === "string" && data.trim()) {
                errorMessage = data.trim();
            }
            throw new Error(errorMessage);
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

    function gameLabel(game) {
        const labels = {
            minecraft: "Minecraft",
            dayz: "DayZ",
            arma3: "Arma 3",
            rust: "Rust",
            mindustry: "Mindustry",
        };
        return labels[normalize(game)] || titleCase(game);
    }

    function editionLabel(edition) {
        const value = normalize(edition);
        const labels = {
            java: "Java Edition",
            java_edition: "Java Edition",
            "java-edition": "Java Edition",
            bedrock: "Bedrock Edition",
            bedrock_edition: "Bedrock Edition",
            "bedrock-edition": "Bedrock Edition",
            default: "Padrão",
        };
        return labels[value] || titleCase(edition);
    }

    function runtimeLabel(runtime) {
        if (!runtime) return "—";
        if (runtime.name) return runtime.name;
        if (runtime.display_name) return runtime.display_name;
        const variant = runtime.variant || runtime.loader || runtime.server_type;
        if (variant) {
            const labels = {
                vanilla: "Vanilla",
                paper: "Paper",
                purpur: "Purpur",
                fabric: "Fabric",
                forge: "Forge",
                neoforge: "NeoForge",
                quilt: "Quilt",
                folia: "Folia",
                bedrock: "Bedrock Dedicated Server",
                bds: "Bedrock Dedicated Server",
            };
            return labels[normalize(variant)] || titleCase(variant);
        }
        return runtime.id || "Servidor";
    }

    function runtimeEdition(runtime) {
        if (!runtime) return "default";
        const explicit = runtime.edition || runtime.game_edition;
        if (explicit) return normalize(explicit);
        const variant = normalize(
            runtime.variant || runtime.loader || runtime.server_type || runtime.id
        );
        if (variant.includes("bedrock") || variant === "bds") return "bedrock";
        if (normalize(runtime.game) === "minecraft") return "java";
        return "default";
    }

    function extractVersions(runtime) {
        if (!runtime) return [];
        let versions = [];
        if (Array.isArray(runtime.versions)) {
            versions = runtime.versions;
        } else if (runtime.version && Array.isArray(runtime.version.available)) {
            versions = runtime.version.available;
        } else if (runtime.version && Array.isArray(runtime.version.versions)) {
            versions = runtime.version.versions;
        } else if (runtime.version && typeof runtime.version === "object") {
            const single = runtime.version.value || runtime.version.version || runtime.version.id;
            if (single) versions = [runtime.version];
        } else if (typeof runtime.version === "string") {
            versions = [runtime.version];
        }

        const result = versions.map((entry) => {
            if (typeof entry === "string") {
                return {value: entry, label: entry, raw: entry};
            }
            if (entry && typeof entry === "object") {
                const value = entry.value || entry.version || entry.id || entry.name;
                if (!value) return null;
                return {
                    value: String(value),
                    label: String(entry.label || entry.name || value),
                    recommended: entry.recommended === true,
                    current: entry.current === true,
                    raw: entry,
                };
            }
            return null;
        }).filter(Boolean);

        if (!result.length) {
            result.push({
                value: "current",
                label: "Versão atual / recomendada",
                recommended: true,
            });
        }
        return result;
    }

    function extractBuilds(runtime, version) {
        if (!runtime) return [];
        let builds = [];
        const rawVersion = version?.raw;
        if (rawVersion && typeof rawVersion === "object" && Array.isArray(rawVersion.builds)) {
            builds = rawVersion.builds;
        }
        if (!builds.length && Array.isArray(runtime.builds)) builds = runtime.builds;
        if (!builds.length && runtime.build) {
            if (Array.isArray(runtime.build.available)) builds = runtime.build.available;
            else if (Array.isArray(runtime.build.builds)) builds = runtime.build.builds;
            else {
                const single = runtime.build.value || runtime.build.id || runtime.build.build;
                if (single) builds = [runtime.build];
            }
        }

        const result = builds.map((entry) => {
            if (typeof entry === "string" || typeof entry === "number") {
                return {value: String(entry), label: String(entry), raw: entry};
            }
            if (entry && typeof entry === "object") {
                const value = entry.value || entry.build || entry.id || entry.name;
                if (value === undefined || value === null) return null;
                return {
                    value: String(value),
                    label: String(entry.label || entry.name || value),
                    recommended: entry.recommended === true,
                    current: entry.current === true,
                    raw: entry,
                };
            }
            return null;
        }).filter(Boolean);

        if (!result.length) {
            result.push({value: "current", label: "Build recomendada", recommended: true});
        }
        return result;
    }

    async function loadRuntimes(game) {
        const data = await placementClient().loadRuntimes(game);
        if (Array.isArray(data)) return data;
        if (data && Array.isArray(data.runtimes)) return data.runtimes;
        if (data && Array.isArray(data.entries)) return data.entries;
        return [];
    }

    async function loadRegions() {
        const contractId = String(
            state.contract?.id || state.contract?.contract_id || ""
        ).trim();
        const data = await placementClient().loadRegions({
            game: state.game,
            contract: contractId,
        });
        const regions = Array.isArray(data?.regions) ? data.regions : [];
        state.regions = regions;
        return regions;
    }

    async function openSelector(contract) {
        if (!contract) throw new Error("Contrato não informado.");
        const game = normalize(contract.game_id || contract.game);
        if (!game) throw new Error("O contrato não possui jogo definido.");

        state.contract = contract;
        state.game = game;
        state.edition = null;
        state.runtime = null;
        state.version = null;
        state.build = null;
        state.regions = [];
        state.region = null;
        state.allowCrossRegion = false;

        const el = elements();
        el.panel.hidden = false;
        el.title.textContent = `Criar servidor ${gameLabel(game)}`;
        el.description.textContent = "Escolha o ambiente de execução desta instância.";
        el.gameSummary.textContent = gameLabel(game);
        resetSelectionUI();
        showMessage("Carregando ambientes disponíveis…");

        const [runtimes] = await Promise.all([
            loadRuntimes(game),
            loadRegions(),
        ]);
        state.runtimes = runtimes;
        renderRegions();

        if (!state.runtimes.length) {
            throw new Error("Nenhum ambiente de execução está disponível para este jogo.");
        }

        renderEditions();
        el.panel.scrollIntoView({behavior: "smooth", block: "start"});
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
        el.version.replaceChildren(new Option("Selecione…", ""));
        el.build.replaceChildren(new Option("Selecione…", ""));
        el.submit.disabled = true;
    }

    function availableEditions() {
        const values = new Map();
        for (const runtime of state.runtimes) {
            const edition = runtimeEdition(runtime);
            if (!values.has(edition)) values.set(edition, editionLabel(edition));
        }
        return [...values.entries()].map(([value, label]) => ({value, label}));
    }

    function renderEditions() {
        const el = elements();
        el.editions.replaceChildren();
        const editions = availableEditions();

        if (editions.length === 1) {
            state.edition = editions[0].value;
            state.runtime = null;
            state.version = null;
            state.build = null;
            el.editions.append(createSelectionCard(
                editions[0].label,
                "Edição disponível",
                true,
                () => {}
            ));
            renderRuntimeTypes();
            return;
        }

        editions.forEach((edition) => {
            const description = edition.value === "java"
                ? "Ecossistema Java: Vanilla, Paper, Fabric, Forge e outros."
                : edition.value === "bedrock"
                    ? "Servidor oficial compatível com clientes Bedrock."
                    : "Ambiente disponível para este jogo.";
            el.editions.append(createSelectionCard(
                edition.label,
                description,
                state.edition === edition.value,
                () => selectEdition(edition.value)
            ));
        });
    }

    function selectEdition(edition) {
        state.edition = edition;
        state.runtime = null;
        state.version = null;
        state.build = null;
        renderEditions();
        renderRuntimeTypes();
    }

    function matchingRuntimes() {
        return state.runtimes.filter((runtime) => runtimeEdition(runtime) === state.edition);
    }

    function renderRuntimeTypes() {
        const el = elements();
        el.typeStep.hidden = false;
        el.versionStep.hidden = true;
        el.buildStep.hidden = true;
        el.regionStep.hidden = true;
        el.summaryStep.hidden = true;
        el.submit.disabled = true;
        el.types.replaceChildren();

        const runtimes = matchingRuntimes();
        if (!runtimes.length) {
            el.types.textContent = "Nenhum servidor disponível para esta edição.";
            return;
        }

        runtimes.forEach((runtime) => {
            const provider = runtime.artifact?.provider || runtime.provider || "";
            const variant = runtime.variant || runtime.loader || runtime.server_type || "";
            const details = [
                variant ? titleCase(variant) : null,
                provider ? `Provider: ${provider}` : null,
            ].filter(Boolean).join(" · ");
            el.types.append(createSelectionCard(
                runtimeLabel(runtime),
                details || "Ambiente de execução",
                state.runtime?.id === runtime.id,
                () => selectRuntime(runtime)
            ));
        });

        if (runtimes.length === 1 && !state.runtime) selectRuntime(runtimes[0]);
    }

    function selectRuntime(runtime) {
        state.runtime = runtime;
        state.version = null;
        state.build = null;
        renderRuntimeTypes();
        renderVersions().catch((error) => {
            console.error(error);
            showMessage(`Não foi possível carregar as versões: ${error.message}`);
        });
    }

    async function renderVersions() {
        const el = elements();
        el.version.replaceChildren(new Option("Carregando versões…", ""));
        el.version.disabled = true;
        el.versionStep.hidden = false;
        el.buildStep.hidden = true;
        el.summaryStep.hidden = true;

        let versions = [];
        const runtime = state.runtime;
        if (!runtime) return;
        const strategy = runtime.version?.strategy || "static";

        try {
            if (strategy === "dynamic") {
                const data = await request(
                    `/api/catalog/versions?runtime=${encodeURIComponent(runtime.id)}`
                );
                versions = Array.isArray(data) ? data : (data.versions || []);
            } else {
                versions = extractVersions(runtime);
            }

            if (!versions.length) {
                throw new Error("Nenhuma versão disponível para este tipo de servidor.");
            }

            versions = versions.map((entry) => {
                if (typeof entry === "string" || typeof entry === "number") {
                    return {value: String(entry), label: String(entry), raw: entry};
                }
                return {
                    value: String(entry.value || entry.version || entry.id),
                    label: String(
                        entry.label || entry.name || entry.version || entry.value || entry.id
                    ),
                    recommended: entry.recommended === true,
                    current: entry.current === true,
                    raw: entry,
                };
            });

            runtime.versions = versions;
            el.version.replaceChildren(new Option("Selecione…", ""));
            versions.forEach((version) => {
                el.version.append(new Option(
                    version.label + ((version.recommended || version.current) ? " — recomendada" : ""),
                    version.value
                ));
            });
            el.version.disabled = false;

            const recommended = versions.find((item) => item.recommended || item.current);
            if (versions.length === 1 || recommended) {
                const selected = recommended || versions[0];
                el.version.value = selected.value;
                await selectVersion(selected.value);
            }
        } catch (error) {
            el.version.replaceChildren(new Option("Nenhuma versão disponível", ""));
            el.version.disabled = true;
            throw error;
        }
    }

    async function selectVersion(value) {
        const versions = extractVersions(state.runtime);
        state.version = versions.find((entry) => entry.value === value) || null;
        state.build = null;
        if (!state.version) {
            elements().buildStep.hidden = true;
            elements().summaryStep.hidden = true;
            return;
        }
        await renderBuilds();
    }

    async function renderBuilds() {
        const el = elements();
        el.build.replaceChildren(new Option("Carregando builds…", ""));
        el.build.disabled = true;
        el.buildStep.hidden = false;
        el.summaryStep.hidden = true;

        const runtime = state.runtime;
        const version = state.version;
        if (!runtime || !version) return;
        let builds = [];

        try {
            const strategy = runtime.version?.strategy || "static";
            if (strategy === "dynamic") {
                const data = await request(
                    `/api/catalog/builds?${new URLSearchParams({
                        runtime: runtime.id,
                        version: version.value,
                    })}`
                );
                builds = Array.isArray(data) ? data : (data.builds || []);
            } else {
                const staticBuild = runtime.version?.build;
                if (staticBuild) {
                    builds = [{
                        value: String(staticBuild),
                        label: "Build recomendada",
                        recommended: true,
                    }];
                } else {
                    builds = extractBuilds(runtime, version);
                }
            }

            if (!builds.length) {
                builds = [{
                    value: "current",
                    label: "Build atual / recomendada",
                    recommended: true,
                }];
            }

            builds = builds.map((entry) => {
                if (typeof entry === "string" || typeof entry === "number") {
                    return {value: String(entry), label: String(entry), raw: entry};
                }
                return {
                    value: String(entry.value || entry.build || entry.id),
                    label: String(
                        entry.label || entry.name || entry.build || entry.value || entry.id
                    ),
                    recommended: entry.recommended === true,
                    current: entry.current === true,
                    raw: entry,
                };
            });

            if (state.version.raw && typeof state.version.raw === "object") {
                state.version.raw.builds = builds;
            } else {
                state.version.raw = {value: state.version.value, builds};
            }

            el.build.replaceChildren(new Option("Selecione…", ""));
            builds.forEach((build) => {
                el.build.append(new Option(
                    build.label + ((build.recommended || build.current) ? " — recomendada" : ""),
                    build.value
                ));
            });
            el.build.disabled = false;

            const recommended = builds.find((item) => item.recommended || item.current);
            if (builds.length === 1 || recommended) {
                const selected = recommended || builds[0];
                el.build.value = selected.value;
                selectBuild(selected.value);
            }
        } catch (error) {
            el.build.replaceChildren(new Option("Nenhuma build disponível", ""));
            el.build.disabled = true;
            throw error;
        }
    }

    function selectBuild(value) {
        const builds = extractBuilds(state.runtime, state.version);
        state.build = builds.find((entry) => entry.value === value) || null;
        updateSummary();
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

    function regionLabel(region) {
        if (!region) return "";
        const parts = [];
        if (region.name) parts.push(region.name);
        if (region.country_code) parts.push(region.country_code);
        return parts.join(" - ") || region.id || "Região";
    }

    function renderRegions() {
        const el = elements();
        el.region.replaceChildren(new Option("Selecione…", ""));
        for (const region of state.regions) {
            el.region.append(new Option(regionLabel(region), region.id));
        }
        el.region.disabled = state.regions.length === 0;
        if (!state.regions.length) {
            el.region.replaceChildren(new Option("Nenhuma região disponível", ""));
            el.regionHelp.textContent = "Nenhum servidor elegível está disponível para esta instância.";
        } else {
            el.regionHelp.textContent =
                "A recomendação considera disponibilidade e latência estimada. O Controller selecionará o Agent adequado.";
        }
    }

    function selectRegion(value) {
        state.region = state.regions.find((region) => region.id === value) || null;
        updateSummary();
    }

    function updateSummary() {
        const el = elements();
        const complete = Boolean(
            state.game && state.edition && state.runtime && state.version && state.build
        );
        el.regionStep.hidden = !complete;
        el.summaryStep.hidden = !complete;
        if (!complete) {
            el.submit.disabled = true;
            return;
        }

        el.summaryGame.textContent = gameLabel(state.game);
        el.summaryEdition.textContent = editionLabel(state.edition);
        el.summaryRuntime.textContent = runtimeLabel(state.runtime);
        el.summaryVersion.textContent = state.version.label;
        el.summaryBuild.textContent = state.build.label;
        el.summaryRegion.textContent = state.region ? regionLabel(state.region) : "Automática";
        el.summaryRegionFallback.textContent = state.allowCrossRegion ? "Sim" : "Não";
        el.minecraftNotice.hidden = state.game !== "minecraft";
        el.submit.disabled = false;
    }

    function createPayload() {
        if (!state.contract || !state.game || !state.runtime || !state.version || !state.build) {
            throw new Error("A seleção do servidor está incompleta.");
        }
        return {
            game: state.game,
            contract_id: state.contract.id,
            resource_profile_id: state.contract.resource_profile_id || null,
            runtime_id: state.runtime.id,
            edition: state.edition,
            variant: state.runtime.variant || state.runtime.loader || state.runtime.server_type || null,
            version: state.version.value,
            build: state.build.value,
            runtime: {
                id: state.runtime.id,
                game: state.game,
                edition: state.edition,
                variant: state.runtime.variant || state.runtime.loader || state.runtime.server_type || null,
                version: state.version.value,
                build: state.build.value,
            },
            placement: {
                region_id: state.region?.id || null,
                allow_cross_region: state.allowCrossRegion,
            },
        };
    }

    async function createInstance() {
        if (state.creating) return;
        const payload = createPayload();
        const el = elements();
        state.creating = true;
        el.submit.disabled = true;
        const originalText = el.submit.textContent;
        el.submit.textContent = "Criando servidor…";

        try {
            const result = await request("/api/instance/create", {
                method: "POST",
                body: JSON.stringify(payload),
            });
            showMessage("Servidor criado. O provisionamento foi iniciado.");
            closeSelector();

            if (result && result.instance_id && result.node_id && result.game) {
                const params = new URLSearchParams({
                    server: result.node_id,
                    game: result.game,
                    instance: result.instance_id,
                });
                window.location.href = `/customer-instance.html?${params.toString()}`;
                return result;
            }

            if (window.CapivaraCustomer && typeof window.CapivaraCustomer.reload === "function") {
                await window.CapivaraCustomer.reload();
            } else {
                window.location.reload();
            }
            return result;
        } finally {
            state.creating = false;
            el.submit.textContent = originalText;
            if (!el.panel.hidden) updateSummary();
        }
    }

    function closeSelector() {
        const el = elements();
        el.panel.hidden = true;
        state.contract = null;
        state.game = null;
        state.runtimes = [];
        state.edition = null;
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
        if (el.close) el.close.addEventListener("click", closeSelector);
        if (el.version) {
            el.version.addEventListener("change", () => {
                selectVersion(el.version.value).catch((error) => {
                    console.error(error);
                    showMessage(`Não foi possível carregar as builds: ${error.message}`);
                });
            });
        }
        if (el.build) {
            el.build.addEventListener("change", () => selectBuild(el.build.value));
        }
        if (el.region) {
            el.region.addEventListener("change", () => selectRegion(el.region.value));
        }
        if (el.regionFallback) {
            el.regionFallback.addEventListener("change", () => {
                state.allowCrossRegion = Boolean(el.regionFallback.checked);
                updateSummary();
            });
        }
        if (el.submit) {
            el.submit.addEventListener("click", () => {
                createInstance().catch((error) => {
                    console.error(error);
                    showMessage(`Não foi possível criar o servidor: ${error.message}`);
                });
            });
        }
    }

    function open(contract) {
        if (openingPromise) return openingPromise;

        openingPromise = Promise.resolve()
            .then(() => openSelector(contract))
            .catch((error) => {
                console.error(error);
                showMessage(`Não foi possível carregar os tipos de servidor: ${error.message}`);
                throw error;
            })
            .finally(() => {
                openingPromise = null;
            });

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
