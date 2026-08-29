(function () {
    "use strict";

    const state = {
        resources: [],
        agents: [],
        catalogEnvironments: [],
        runtimeSummary: null,
        runtimes: [],
        content: [],
        installed: []
    };

    const byId = id => document.getElementById(id);

    async function request(path, options = {}) {
        const headers = {
            "X-Capivara-Auth-Area":"controller",
            Accept: "application/json"
        };
        if (options.body) headers["Content-Type"] = "application/json";

        const response = await fetch(path, {
            ...options,
            headers: { ...headers, ...(options.headers || {}) }
        });
        const payload = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
        if (!response.ok) throw new Error(payload.error || payload.output || `HTTP ${response.status}`);
        return payload;
    }

    function setStatus(text, type = "idle") {
        const element = byId("catalog-v2-status");
        if (!element) return;
        element.textContent = text;
        element.dataset.state = type;
    }

    function setSummary(text) {
        const element = byId("catalog-v2-summary");
        if (element) element.textContent = text;
    }

    function showResult(value, summary) {
        if (summary) setSummary(summary);
        const result = byId("catalog-v2-result");
        if (!result) return;
        result.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
        result.hidden = false;
    }

    function hideResult() {
        const result = byId("catalog-v2-result");
        if (result) result.hidden = true;
    }

    function unique(values) {
        return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
    }

    function fillSelect(select, values, placeholder) {
        if (!select) return;
        const previous = select.value;
        select.replaceChildren();

        if (!values.length) {
            const option = document.createElement("option");
            option.value = "";
            option.textContent = placeholder;
            select.appendChild(option);
            select.disabled = true;
            return;
        }

        values.forEach(value => {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = value;
            select.appendChild(option);
        });
        select.disabled = false;
        if (values.includes(previous)) select.value = previous;
    }

    function currentIdentity() {
        return {
            server: byId("catalog-v2-node")?.value || "",
            game: byId("catalog-v2-game")?.value || "",
            instance: byId("catalog-v2-instance")?.value || ""
        };
    }

    function instancePath() {
        const { server, game, instance } = currentIdentity();
        if (!server || !game || !instance) throw new Error("Selecione Node, jogo e instância.");
        return `/opt/dsm/instances/${server}/${game}/${instance}`;
    }

    function selectedRuntime() {
        return state.runtimes.find(item => item.id === byId("catalog-v2-runtime")?.value);
    }


    function fillCatalogSelect(select, entries, placeholder) {
        if (!select) return;

        const previous = select.value;
        select.replaceChildren();

        if (!Array.isArray(entries) || !entries.length) {
            const option = document.createElement("option");
            option.value = "";
            option.textContent = placeholder;
            select.appendChild(option);
            select.disabled = true;
            return;
        }

        entries.forEach(entry => {
            const option = document.createElement("option");

            if (entry && typeof entry === "object") {
                option.value = String(
                    entry.value ??
                    entry.version ??
                    entry.id ??
                    entry.number ??
                    ""
                );

                option.textContent = String(
                    entry.label ??
                    entry.version ??
                    entry.value ??
                    entry.id ??
                    entry.number ??
                    option.value
                );
            } else {
                option.value = String(entry);
                option.textContent = String(entry);
            }

            select.appendChild(option);
        });

        select.disabled = false;

        if (
            previous &&
            [...select.options].some(option => option.value === previous)
        ) {
            select.value = previous;
        }
    }


    async function loadRuntimeBuilds(runtime, version) {
        const loaderSelect = byId("catalog-v2-loader-version");

        if (!loaderSelect) return;

        loaderSelect.replaceChildren();

        if (!runtime || !version) {
            fillCatalogSelect(
                loaderSelect,
                [],
                "Aguardando versão..."
            );
            return;
        }

        /*
         * O conceito de segundo seletor depende do runtime:
         *
         * Paper       -> build
         * Fabric      -> loader/build
         * outros      -> quando o resolver fornecer builds
         */

        try {
            const params = new URLSearchParams({
                runtime: runtime.id,
                version
            });

            const response = await request(
                `/api/catalog/builds?${params.toString()}`
            );

            const entries =
                Array.isArray(response)
                    ? response
                    : (
                        response.builds ||
                        response.versions ||
                        response.entries ||
                        []
                    );

            if (!entries.length) {
                fillCatalogSelect(
                    loaderSelect,
                    [],
                    runtime.loader
                        ? "Sem versão adicional"
                        : "Não aplicável"
                );
                return;
            }

            fillCatalogSelect(
                loaderSelect,
                entries,
                "Nenhuma build disponível"
            );

        } catch (error) {
            /*
             * Runtime sem endpoint de builds não deve bloquear
             * a seleção da versão principal.
             */
            fillCatalogSelect(
                loaderSelect,
                [],
                runtime.loader
                    ? "Não disponível"
                    : "Não aplicável"
            );
        }
    }


    async function syncExecutionEnvironmentForm() {
        const runtime = selectedRuntime();

        const versionSelect = byId("catalog-v2-version");
        const loaderSelect = byId("catalog-v2-loader-version");
        const javaInput = byId("catalog-v2-java");
        const osSelect = byId("catalog-v2-os");
        const archSelect = byId("catalog-v2-arch");
        const installButton = byId("catalog-v2-environment-install");
        const reinstallButton =
            byId("catalog-v2-instance-reinstall");

        if (!runtime) {
            fillCatalogSelect(
                versionSelect,
                [],
                "Aguardando ambiente..."
            );

            fillCatalogSelect(
                loaderSelect,
                [],
                "Aguardando versão..."
            );

            if (javaInput) {
                javaInput.value = "";
                javaInput.disabled = true;
            }

            if (reinstallButton) {
            reinstallButton.disabled =
                !currentIdentity().instance;
        }

        if (installButton) {
                installButton.disabled = true;
            }

            renderContent();
            return;
        }

        const requirements = runtime.requirements || {};

        fillCatalogSelect(
            osSelect,
            requirements.os || [],
            "Não informado"
        );

        fillCatalogSelect(
            archSelect,
            requirements.architectures || [],
            "Não informado"
        );

        if (javaInput) {
            const javaRequirement = requirements.java || {};

            javaInput.value =
                javaRequirement.min ??
                javaRequirement.version ??
                "";

            javaInput.disabled =
                runtime.process?.engine !== "java";
        }

        if (installButton) {
            const provider =
                runtime?.artifact?.provider ||
                runtime?.provider ||
                "";

            installButton.disabled = false;

            installButton.textContent =
                provider === "steam"
                    ? "Instalar jogo via Steam"
                    : "Instalar jogo";
        }

        updateContentActions();

        try {
            const params = new URLSearchParams({
                runtime: runtime.id
            });

            const response = await request(
                `/api/catalog/versions?${params.toString()}`
            );

            let entries =
                Array.isArray(response)
                    ? response
                    : (
                        response.versions ||
                        response.entries ||
                        []
                    );

            /*
             * Runtime estático.
             */
            if (!entries.length && runtime.version?.value) {
                entries = [{
                    value: runtime.version.value,
                    label: runtime.version.value,
                    recommended: true
                }];
            }

            fillCatalogSelect(
                versionSelect,
                entries,
                "Nenhuma versão disponível"
            );

            const version = versionSelect?.value || "";

            await loadRuntimeBuilds(
                runtime,
                version
            );

        } catch (error) {
            if (runtime.version?.value) {
                fillCatalogSelect(
                    versionSelect,
                    [runtime.version.value],
                    "Nenhuma versão disponível"
                );
            } else {
                fillCatalogSelect(
                    versionSelect,
                    [],
                    "Falha ao consultar versões"
                );
            }
        }

        renderContent();
    }

    function selectedContent() {
        return Array.from(
            document.querySelectorAll("[data-catalog-content]:checked"),
            item => item.value
        );
    }

    function updateContentActions() {
        const available = Boolean(selectedRuntime() && currentIdentity().instance && selectedContent().length);
        ["catalog-v2-check", "catalog-v2-plan", "catalog-v2-install"].forEach(id => {
            const button = byId(id);
            if (button) button.disabled = !available;
        });
    }

    function fillEnvironmentSelect(id, values) {
        const select = byId(id);
        if (!select) return;
        select.replaceChildren();

        if (!values.length) {
            const option = document.createElement("option");
            option.value = "";
            option.textContent = "Indisponível";
            select.appendChild(option);
            select.disabled = true;
            return;
        }

        values.forEach(value => {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = value;
            select.appendChild(option);
        });
        select.disabled = false;
    }


    function normalizeStatus(value) {
        if (typeof value === "string") return value;
        if (value && typeof value === "object") return value.state || value.status || "unknown";
        return "unknown";
    }

    function text(value, fallback = "-") {
        return value === undefined || value === null || value === "" ? fallback : String(value);
    }

    function setDetail(id, value, fallback = "-") {
        const element = byId(id);
        if (element) element.textContent = text(value, fallback);
    }

    function renderInstanceProfile(metadata = {}) {
        const identity = currentIdentity();
        const owner = metadata.owner || metadata.responsible || {};
        const customer = metadata.customer || metadata.client || {};
        const displayName = metadata.display_name || metadata.name || identity.instance || "Instância";
        const ownerName = typeof owner === "string" ? owner : (owner.name || owner.username);
        const customerName = typeof customer === "string" ? customer : (customer.name || customer.company);
        const customerId = typeof customer === "object" ? (customer.id || customer.code) : null;
        const contact = typeof customer === "object"
            ? (customer.email || customer.phone)
            : (metadata.contact || null);

        setDetail("catalog-v2-instance-display-name", displayName);
        setDetail("catalog-v2-instance-controller", metadata.controller_id, "Não informado");
        setDetail("catalog-v2-instance-agent", metadata.agent_id, "Não informado");
        setDetail("catalog-v2-instance-owner", ownerName, "Não informado");
        setDetail("catalog-v2-instance-customer", customerName, "Não informado");
        setDetail("catalog-v2-instance-customer-id", customerId, "Não informado");
        setDetail("catalog-v2-instance-contact", contact, "Não informado");

        const logo = byId("catalog-v2-instance-logo");
        const fallback = byId("catalog-v2-instance-logo-fallback");
        const logoUrl = metadata.logo_url || metadata.logo || "";
        const allowedLogo = /^(https?:\/\/|data:image\/|\/)/i.test(logoUrl);
        if (logo) {
            logo.hidden = !allowedLogo;
            if (allowedLogo) logo.src = logoUrl;
            else logo.removeAttribute("src");
            logo.onerror = () => {
                logo.hidden = true;
                if (fallback) fallback.hidden = false;
            };
        }
        if (fallback) {
            fallback.hidden = allowedLogo;
            fallback.textContent = displayName.trim().charAt(0).toUpperCase() || "?";
        }
    }

    function renderRuntimeSummary() {
        const summary = state.runtimeSummary || {};
        const serverState = summary.server_state || {};
        const status = serverState.status || {};
        const metrics = summary.metrics || {};
        const mods = summary.mods || {};
        const backup = summary.backup || {};

        const stateValue = normalizeStatus(status);
        const healthValue = status.health || serverState.health || "unknown";
        const players =
            serverState.players?.current ??
            serverState.players ??
            metrics.players?.current ??
            "-";

        const instancePid =
            serverState.pid ??
            serverState.process?.pid ??
            metrics.instance?.pid ??
            null;

        const hasInstanceProcess =
            instancePid !== null &&
            instancePid !== undefined &&
            instancePid !== "";

        const pid =
            hasInstanceProcess
                ? instancePid
                : "-";

        const cpu =
            hasInstanceProcess
                ? (
                    metrics.instance?.cpu_pct ??
                    metrics.cpu_pct ??
                    metrics.cpu?.pct ??
                    metrics.cpu?.cpu_pct ??
                    0
                )
                : (
                    metrics.cpu?.host_pct ??
                    metrics.cpu?.process_pct ??
                    "-"
                );

        const ram =
            hasInstanceProcess
                ? (
                    metrics.instance?.memory_mb ??
                    metrics.memory_mb ??
                    metrics.ram_mb ??
                    0
                )
                : (
                    metrics.memory?.used_mb ??
                    "-"
                );

        const modsCount =
            Array.isArray(state.installed)
                ? state.installed.length
                : (
                    Array.isArray(mods.mods)
                        ? mods.mods.length
                        : (
                            Number.isFinite(
                                Number(mods.total)
                            )
                                ? Number(mods.total)
                                : 0
                        )
                );

        const backupValue = backup.last_backup || backup.last || backup.created_at || backup.status;

        setDetail("catalog-v2-runtime-state", stateValue.toUpperCase());
        setDetail("catalog-v2-runtime-health", text(healthValue).toUpperCase());
        setDetail("catalog-v2-runtime-pid", pid);
        setDetail("catalog-v2-runtime-players", players);
        setDetail("catalog-v2-runtime-cpu", cpu === undefined ? "-" : `${cpu}%`);
        setDetail("catalog-v2-runtime-ram", ram === undefined ? "-" : `${ram} MB`);
        setDetail("catalog-v2-runtime-mods", modsCount);
        setDetail("catalog-v2-runtime-backup", backupValue);
        renderInstanceProfile(summary.instance_metadata || {});

        const panel = byId("catalog-v2-runtime-summary");
        if (panel) panel.dataset.state = stateValue.toLowerCase();
    }

    function renderRuntimes() {
        const select = byId("catalog-v2-runtime");
        if (!select) return;

        const previous = select.value;

        select.replaceChildren();

        if (!state.runtimes.length) {
            const option = document.createElement("option");
            option.value = "";
            option.textContent =
                "Nenhum ambiente de execução disponível no catálogo";

            select.appendChild(option);
            select.disabled = true;
            return;
        }

        state.runtimes.forEach(runtime => {
            const option = document.createElement("option");

            option.value = runtime.id;

            const edition =
                runtime.edition
                    ? ` · ${runtime.edition}`
                    : "";

            const loader =
                runtime.loader
                    ? ` · ${runtime.loader}`
                    : "";

            option.textContent =
                `${runtime.name || runtime.id}${edition}${loader}`;

            select.appendChild(option);
        });

        select.disabled = false;

        /*
         * Preserva a seleção anterior quando o catálogo
         * for recarregado.
         */
        if (
            previous &&
            [...select.options].some(
                option => option.value === previous
            )
        ) {
            select.value = previous;
        }
    }

    function contentCompatibleWithRuntime(content) {
        const runtime = selectedRuntime();

        if (!runtime) return true;

        const compatibility =
            content.compatibility || {};

        const version =
            byId("catalog-v2-version")?.value || "";

        const edition =
            runtime.edition || "";

        const loader =
            runtime.loader ||
            runtime.variant ||
            "";

        const gameVersions =
            compatibility.game_versions || [];

        const editions =
            compatibility.editions || [];

        const loaders =
            compatibility.loaders || [];

        if (
            gameVersions.length &&
            version &&
            !gameVersions.includes(version)
        ) {
            return false;
        }

        if (
            editions.length &&
            edition &&
            !editions.includes(edition)
        ) {
            return false;
        }

        if (loaders.length) {
            if (!loader) return false;

            if (!loaders.includes(loader)) {
                return false;
            }
        }

        return true;
    }


    function renderContent() {
        const container =
            byId("catalog-v2-content");

        if (!container) return;

        container.replaceChildren();

        const compatible =
            state.content.filter(
                contentCompatibleWithRuntime
            );

        if (!compatible.length) {
            const empty =
                document.createElement("span");

            empty.className =
                "catalog-v2-empty";

            empty.textContent =
                state.content.length
                    ? "Nenhum conteúdo adicional compatível com este Ambiente de Execução e versão."
                    : "Nenhum conteúdo adicional disponível para este jogo.";

            container.appendChild(empty);
            updateContentActions();
            return;
        }

        compatible.forEach(content => {
            const label =
                document.createElement("label");

            label.className =
                "catalog-v2-content-item";

            const input =
                document.createElement("input");

            input.type = "checkbox";
            input.value = content.id;
            input.dataset.catalogContent =
                "true";

            input.addEventListener(
                "change",
                updateContentActions
            );

            const body =
                document.createElement("span");

            body.className =
                "catalog-v2-content-body";

            const title =
                document.createElement("strong");

            title.textContent =
                content.name ||
                content.id;

            const meta =
                document.createElement("small");

            meta.textContent = [
                content.content_type,
                content.version,
                content.catalog?.provider,
                content.artifact?.provider
            ]
                .filter(Boolean)
                .join(" · ");

            body.append(
                title,
                meta
            );

            label.append(
                input,
                body
            );

            container.appendChild(label);
        });

        updateContentActions();
    }

    function renderInstalled() {
        const container = byId("catalog-v2-installed-list");
        if (!container) return;
        container.replaceChildren();

        if (!state.installed.length) {
            const empty = document.createElement("span");
            empty.className = "catalog-v2-empty";
            empty.textContent = "Nenhum conteúdo registrado no lockfile desta instância.";
            container.appendChild(empty);
            return;
        }

        state.installed.forEach(entry => {
            const item = document.createElement("div");
            item.className = "catalog-v2-installed-item";
            const name = document.createElement("strong");
            name.textContent = entry.name || entry.id || entry.content_id || "Conteúdo";
            const meta = document.createElement("small");
            meta.textContent = [entry.version, entry.provider, entry.status].filter(Boolean).join(" · ");
            const remove = document.createElement("button");
            remove.className = "instance-manager-only catalog-v2-danger";
            remove.textContent = "Remover";
            remove.addEventListener("click", () => removeContent(entry.id || entry.content_id));
            item.append(name, meta, remove);
            container.appendChild(item);
        });
    }

    async function removeContent(contentId) {
        if (!contentId || !window.confirm(`Remover ${contentId} desta instância?`)) return;
        try {
            const data = await request("/api/catalog/remove", {
                method: "POST",
                body: JSON.stringify({ instance: instancePath(), content_id: contentId })
            });
            showResult(data, "Conteúdo removido da instância.");
            await loadInstalled({ silent: true });
        } catch (error) {
            showResult(error.message, "Não foi possível remover o conteúdo.");
        }
    }

    async function loadConfigFiles() {
        const select = byId("catalog-v2-config-file");
        const editor = byId("catalog-v2-config-editor");
        const save = byId("catalog-v2-config-save");
        if (!select || !editor || !save) return;
        select.replaceChildren();
        editor.value = "";
        editor.disabled = true;
        save.disabled = true;
        if (!currentIdentity().instance) return;
        try {
            const data = await request(`/api/instance/config?instance=${encodeURIComponent(instancePath())}`);
            fillSelect(select, data.files || [], "Nenhum arquivo de configuração");
            if ((data.files || []).length) await loadConfigFile();
        } catch (error) {
            fillSelect(select, [], "Acesso indisponível");
        }
    }

    async function loadConfigFile() {
        const file = byId("catalog-v2-config-file")?.value;
        const editor = byId("catalog-v2-config-editor");
        const save = byId("catalog-v2-config-save");
        if (!file || !editor || !save) return;
        const params = new URLSearchParams({ instance: instancePath(), file });
        try {
            const data = await request(`/api/instance/config?${params.toString()}`);
            editor.value = data.content || "";
            editor.disabled = false;
            save.disabled = false;
        } catch (error) {
            showResult(error.message, "Não foi possível abrir a configuração.");
        }
    }

    async function saveConfigFile() {
        const file = byId("catalog-v2-config-file")?.value;
        const content = byId("catalog-v2-config-editor")?.value;
        if (!file) return;
        try {
            const data = await request("/api/instance/config", {
                method: "POST",
                body: JSON.stringify({ instance: instancePath(), file, content })
            });
            showResult(data, "Configuração salva com sucesso.");
        } catch (error) {
            showResult(error.message, "Não foi possível salvar a configuração.");
        }
    }

    function availableNodeIds() {
        const runtimeNodes = state.resources.map(item => item.server);
        const agentNodes = state.agents
            .filter(agent => agent && String(agent.status || "").toLowerCase() === "active")
            .map(agent => agent.node_id);
        return unique([...runtimeNodes, ...agentNodes]);
    }

    function updateNodeOptions() {
        fillSelect(byId("catalog-v2-node"), availableNodeIds(), "Nenhum Node disponível");
        updateGameOptions();
    }

    function updateGameOptions() {
        const node = byId("catalog-v2-node")?.value;
        const games = unique([
            ...state.resources.filter(item => item.server === node).map(item => item.game),
            ...state.catalogEnvironments.map(item => item.game)
        ]);
        fillSelect(byId("catalog-v2-game"), games, "Nenhum jogo disponível");
        updateInstanceOptions();
    }

    function updateInstanceOptions() {
        const { server, game } = currentIdentity();
        const instances = unique(
            state.resources
                .filter(item => item.server === server && item.game === game)
                .map(item => item.instance)
        );
        fillSelect(byId("catalog-v2-instance"), instances, "Nenhuma instância disponível");
    }

    function buildRequest() {
        const runtime = selectedRuntime();
        const identity = currentIdentity();
        if (!identity.instance) throw new Error("Selecione uma instância.");
        if (!runtime) throw new Error("Selecione um ambiente de execução do catálogo.");

        const javaRawValue = byId("catalog-v2-java")?.value || "";
        const javaValue = javaRawValue === "" ? null : Number(javaRawValue);
        const version = byId("catalog-v2-version")?.value.trim() || "";
        const loaderVersion = byId("catalog-v2-loader-version")?.value.trim() || "";

        return {
            schema_version: 2,
            runtime: {
                id: runtime.id,
                game: runtime.game || identity.game.toLowerCase(),
                version,
                edition: runtime.edition || null,
                loader: runtime.loader || null,
                loader_version: runtime.loader ? (loaderVersion || null) : null
            },
            environment: {
                os: byId("catalog-v2-os")?.value || "",
                architecture: byId("catalog-v2-arch")?.value || "",
                java: runtime.process?.engine === "java" && javaValue !== null && Number.isFinite(javaValue)
                    ? javaValue
                    : null
            },
            content: selectedContent(),
            installed_content: state.installed
                .map(item => item.id || item.content_id)
                .filter(Boolean)
        };
    }

    async function loadInstalled({ silent = true } = {}) {
        const identity = currentIdentity();
        if (!identity.instance) {
            state.installed = [];
            renderInstalled();
            return;
        }

        try {
            const path = encodeURIComponent(instancePath());
            const data = await request(`/api/catalog/installed?instance=${path}`);
            state.installed = Array.isArray(data) ? data : (data.entries || data.content || []);
            renderInstalled();
            if (!silent) showResult(data, `${state.installed.length} conteúdo(s) instalado(s).`);
        } catch (error) {
            state.installed = [];
            renderInstalled();
            if (!silent) showResult(error.message, "Não foi possível ler o lockfile.");
        }
    }

    async function loadCatalogForGame() {
        const game = currentIdentity().game;
        if (!game) {
            state.runtimes = [];
            state.content = [];
            renderRuntimes();
            renderContent();
            return;
        }

        const catalogGame = game.toLowerCase();
        const [runtimes, content] = await Promise.all([
            request(`/api/catalog/runtimes?game=${encodeURIComponent(catalogGame)}`),
            request(`/api/catalog/content?game=${encodeURIComponent(catalogGame)}`)
        ]);

        state.runtimes = Array.isArray(runtimes) ? runtimes : (runtimes.runtimes || []);
        state.content = Array.isArray(content) ? content : (content.content || content.entries || []);
        renderRuntimes();
        await syncExecutionEnvironmentForm();
        renderContent();
    }

    async function loadSelectedInstance() {
        const { server, game, instance } = currentIdentity();
        hideResult();

        if (!server || !game) {
            state.runtimeSummary = null;
            renderRuntimeSummary();
            setStatus("SEM JOGO", "error");
            setSummary("Selecione um Node e um jogo.");
            return;
        }

        if (!instance) {
            try {
                await loadCatalogForGame();
                state.runtimeSummary = null;
                renderRuntimeSummary();
                setStatus("CATÁLOGO", "success");
                setSummary("Nenhuma instância deste jogo no Node. O jogo pode ser instalado pelo Ambiente de Execução.");
            } catch (error) {
                setStatus("ERRO", "error");
                showResult(error.message, "Não foi possível carregar o catálogo do jogo.");
            }
            return;
        }

        try {
            setStatus("SINCRONIZANDO", "pending");
            const params = new URLSearchParams({ server, game, instance });
            const [summary] = await Promise.all([
                request(`/api/runtime?${params.toString()}`),
                loadCatalogForGame()
            ]);
            state.runtimeSummary = summary;
            renderRuntimeSummary();
            await loadInstalled({ silent: true });
            renderRuntimeSummary();
            await loadConfigFiles();
            setStatus("PRONTO", "success");
            setSummary(`${server} / ${game} / ${instance} sincronizada com o Catálogo de Conteúdo.`);
        } catch (error) {
            setStatus("ERRO", "error");
            showResult(error.message, "Não foi possível sincronizar Runtime e Catálogo de Conteúdo.");
        }
    }

    async function loadRuntimeResources() {
        try {
            setStatus("CARREGANDO", "pending");
            const [data, catalogEnvironments, agentData] = await Promise.all([
                request("/api/runtime/list"),
                request("/api/catalog/runtimes"),
                request("/api/agents").catch(() => ({ agents: [] }))
            ]);
            state.resources = Array.isArray(data) ? data : (data.resources || []);
            state.agents = Array.isArray(agentData) ? agentData : (agentData.agents || []);
            state.catalogEnvironments = Array.isArray(catalogEnvironments)
                ? catalogEnvironments
                : (catalogEnvironments.runtimes || []);
            updateNodeOptions();

            if (!state.resources.length && !availableNodeIds().length) {
                state.runtimes = state.catalogEnvironments;
                state.content = [];
                setStatus("VAZIO", "error");
                setSummary("Nenhuma instância foi publicada no Runtime e nenhum Agent ativo está disponível.");
                renderRuntimeSummary();
                renderRuntimes();
                renderContent();
                renderInstalled();
                return;
            }

            await loadSelectedInstance();
        } catch (error) {
            setStatus("ERRO", "error");
            showResult(error.message, "Não foi possível carregar as instâncias do Runtime.");
        }
    }

    async function execute(action) {
        try {
            setStatus("PROCESSANDO", "pending");
            const path = instancePath();
            let body;

            if (["compatibility", "plan", "install"].includes(action)) {
                body = { request: buildRequest(), instance: path };
            } else {
                body = { instance: path };
            }

            const data = await request(`/api/catalog/${action}`, {
                method: "POST",
                body: JSON.stringify(body)
            });

            const compatible = data.compatible;
            setStatus(
                compatible === false ? "BLOQUEADO" : "CONCLUÍDO",
                compatible === false ? "error" : "success"
            );

            const messages = {
                compatibility: compatible === false ? "Compatibilidade bloqueada." : "Compatibilidade validada.",
                plan: "Plano de instalação gerado.",
                install: "Instalação solicitada.",
                verify: "Verificação concluída.",
                rollback: "Rollback concluído."
            };
            showResult(data, messages[action] || "Operação concluída.");

            if (["install", "verify", "rollback"].includes(action)) {
                await loadInstalled({ silent: true });
                await loadSelectedInstance();
            }
        } catch (error) {
            setStatus("ERRO", "error");
            showResult(error.message, "A operação não foi concluída.");
        }
    }


    function bindExecutionEnvironmentSelectors() {
        const runtimeSelect =
            byId("catalog-v2-runtime");

        const versionSelect =
            byId("catalog-v2-version");

        const loaderSelect =
            byId("catalog-v2-loader-version");

        if (
            runtimeSelect &&
            !runtimeSelect.dataset.dynamicBound
        ) {
            runtimeSelect.dataset.dynamicBound = "1";

            runtimeSelect.addEventListener(
                "change",
                () => {
                    syncExecutionEnvironmentForm()
                        .catch(error => {
                            showResult(
                                error.message,
                                "Não foi possível carregar as versões do Ambiente de Execução."
                            );
                        });
                }
            );
        }

        if (
            versionSelect &&
            !versionSelect.dataset.dynamicBound
        ) {
            versionSelect.dataset.dynamicBound = "1";

            versionSelect.addEventListener(
                "change",
                async () => {
                    await loadRuntimeBuilds(
                        selectedRuntime(),
                        versionSelect.value
                    );

                    renderContent();
                }
            );
        }

        if (
            loaderSelect &&
            !loaderSelect.dataset.dynamicBound
        ) {
            loaderSelect.dataset.dynamicBound = "1";

            loaderSelect.addEventListener(
                "change",
                renderContent
            );
        }
    }



    async function reinstallSelectedInstance() {
        const identity = currentIdentity();

        if (
            !identity.server ||
            !identity.game ||
            !identity.instance
        ) {
            showResult(
                "Selecione Node, jogo e instância.",
                "A reinstalação não foi iniciada."
            );
            return;
        }

        const onlineState =
            String(
                state.runtimeSummary
                    ?.server_state
                    ?.status
                    ?.state ||
                ""
            ).toLowerCase();

        if (
            onlineState === "online" ||
            onlineState === "running"
        ) {
            showResult(
                "A instância precisa estar offline antes da reinstalação.",
                "Reinstalação bloqueada."
            );
            return;
        }

        const confirmed = window.confirm(
            `Reinstalar a instância ${identity.instance} usando os arquivos do game-data?\n\n` +
            `Os serverfiles atuais serão substituídos.`
        );

        if (!confirmed) {
            return;
        }

        const preserveConfig = window.confirm(
            "Deseja preservar os arquivos de configuração atuais da instância?"
        );

        const button =
            byId("catalog-v2-instance-reinstall");

        try {
            if (button) {
                button.disabled = true;
            }

            setStatus(
                "REINSTALANDO INSTÂNCIA",
                "pending"
            );

            setSummary(
                `Recriando ${identity.instance} a partir do game-data...`
            );

            const result = await request(
                "/api/instance/reinstall",
                {
                    method: "POST",
                    body: JSON.stringify({
                        server: identity.server,
                        game: identity.game,
                        instance: identity.instance,
                        preserve_config: preserveConfig
                    })
                }
            );

            setStatus(
                "INSTÂNCIA REINSTALADA",
                "success"
            );

            showResult(
                result,
                `Instância ${identity.instance} reinstalada com sucesso.`
            );

            await loadSelectedInstance();

        } catch (error) {
            setStatus(
                "ERRO NA REINSTALAÇÃO",
                "error"
            );

            showResult(
                error.message,
                "A reinstalação da instância não foi concluída."
            );

        } finally {
            if (button) {
                button.disabled = false;
            }
        }
    }



    async function installExecutionEnvironment() {
        const runtime = selectedRuntime();
        if (!runtime) {
            showResult("Selecione um Ambiente de Execução.", "A instalação do jogo não foi iniciada.");
            return;
        }

        const button = byId("catalog-v2-environment-install");
        try {
            if (button) button.disabled = true;
            setStatus("INSTALANDO JOGO", "pending");
            setSummary(`Instalando ${runtime.name || runtime.game} pelo provedor ${runtime.artifact?.provider || runtime.provider || "configurado"}...`);
            const gameVersion =
                byId("catalog-v2-version")?.value || "current";

            const loaderVersion =
                byId("catalog-v2-loader-version")?.value || "";

            const selector =
                loaderVersion
                    ? `${gameVersion}@${loaderVersion}`
                    : gameVersion;
            const data = await request("/api/catalog/environment-install", {
                method: "POST",
                body: JSON.stringify({ environment_id: runtime.id, selector })
            });
            setStatus("JOGO INSTALADO", "success");
            showResult(data, `${runtime.name || runtime.game} instalado com sucesso.`);
        } catch (error) {
            setStatus("ERRO NA INSTALAÇÃO", "error");
            showResult(error.message, "A instalação do jogo não foi concluída.");
        } finally {
            syncExecutionEnvironmentForm();
        }
    }

    function bind() {
        bindExecutionEnvironmentSelectors();
        byId("catalog-v2-node")?.addEventListener("change", async () => {
            updateGameOptions();
            await loadSelectedInstance();
        });

        byId("catalog-v2-game")?.addEventListener("change", async () => {
            updateInstanceOptions();
            await loadSelectedInstance();
        });

        byId("catalog-v2-instance")?.addEventListener("change", loadSelectedInstance);
        byId("catalog-v2-instance")?.addEventListener("change", loadConfigFiles);
        byId("catalog-v2-content")?.addEventListener("change", updateContentActions);
        byId("catalog-v2-refresh")?.addEventListener("click", loadRuntimeResources);
        byId("catalog-v2-environment-install")?.addEventListener("click", installExecutionEnvironment);
        byId("catalog-v2-instance-reinstall")?.addEventListener(
            "click",
            reinstallSelectedInstance
        );
        byId("catalog-v2-check")?.addEventListener("click", () => execute("compatibility"));
        byId("catalog-v2-plan")?.addEventListener("click", () => execute("plan"));
        byId("catalog-v2-install")?.addEventListener("click", () => execute("install"));
        byId("catalog-v2-verify")?.addEventListener("click", () => execute("verify"));
        byId("catalog-v2-rollback")?.addEventListener("click", () => execute("rollback"));
        byId("catalog-v2-installed")?.addEventListener("click", () => loadInstalled({ silent: false }));
        byId("catalog-v2-config-file")?.addEventListener("change", loadConfigFile);
        byId("catalog-v2-config-save")?.addEventListener("click", saveConfigFile);
    }

    document.addEventListener("DOMContentLoaded", () => {
        bind();
        loadRuntimeResources();
    });
})();
