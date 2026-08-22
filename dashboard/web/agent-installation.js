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

    function selectedMethod() {
        return document.querySelector('input[name="agent-method"]:checked')?.value || "github";
    }

    function ensureReleaseUi() {
        if (document.getElementById("agent-release-options")) return;
        const fieldset = document.createElement("fieldset");
        fieldset.id = "agent-release-options";
        fieldset.innerHTML = `
            <legend>Versão do Agent</legend>
            <label>GitHub Release
                <select id="agent-release-tag" required>
                    <option value="">Carregando releases...</option>
                </select>
            </label>
            <label class="inline-option">
                <input id="agent-release-prereleases" type="checkbox"> Mostrar pré-lançamentos
            </label>
            <p id="agent-release-status" class="location-safety-note" role="status" aria-live="polite"></p>`;
        const sshOptions = document.getElementById("agent-ssh-options");
        sshOptions.parentNode.insertBefore(fieldset, sshOptions);
        document.getElementById("agent-release-prereleases").addEventListener("change", loadReleases);
    }

    async function loadReleases() {
        ensureReleaseUi();
        const method = selectedMethod();
        const wrapper = document.getElementById("agent-release-options");
        const select = document.getElementById("agent-release-tag");
        const status = document.getElementById("agent-release-status");
        const platform = document.querySelector('input[name="agent-platform"]:checked')?.value || "linux";
        const includePrereleases = document.getElementById("agent-release-prereleases").checked;

        wrapper.hidden = method === "local";
        if (method === "local") return;

        select.disabled = true;
        select.replaceChildren(new Option("Carregando releases...", ""));
        status.textContent = "Consultando GitHub Releases e validando os pacotes disponíveis...";
        try {
            const result = await request(
                `/agents/releases?platform=${encodeURIComponent(platform)}&include_prereleases=${includePrereleases ? "1" : "0"}`
            );
            select.replaceChildren();
            const releases = result.releases || [];
            releases.forEach((release, index) => {
                const label = `${release.tag}${index === 0 && !release.prerelease ? " · mais recente estável" : ""}${release.prerelease ? " · pré-lançamento" : ""}`;
                select.appendChild(new Option(label, release.tag));
            });
            if (!releases.length) {
                select.appendChild(new Option(`Nenhuma release compatível para ${platform}`, ""));
                status.textContent = "Nenhuma release publicada possui o pacote e o checksum exigidos para esta plataforma.";
            } else {
                select.value = result.recommended || releases[0].tag;
                status.textContent = `${releases.length} release(s) compatível(is). A mais recente estável é selecionada por padrão.`;
            }
        } catch (error) {
            select.replaceChildren(new Option("Falha ao consultar releases", ""));
            status.textContent = `Falha ao consultar GitHub Releases: ${error.message}`;
        } finally {
            select.disabled = false;
        }
    }

    function updateMethodUi() {
        const method = selectedMethod();
        const ssh = method === "ssh";
        const linux = document.querySelector('input[name="agent-platform"][value="linux"]');
        const windows = document.querySelector('input[name="agent-platform"][value="windows"]');
        const button = document.getElementById("generate-agent-install");
        document.getElementById("agent-ssh-options").hidden = !ssh;
        const releaseOptions = document.getElementById("agent-release-options");
        if (releaseOptions) releaseOptions.hidden = method === "local";
        windows.disabled = ssh;
        if (ssh) linux.checked = true;
        button.textContent = ssh ? "Instalar Agent via SSH" : "Gerar instalação";
        if (ssh && !document.getElementById("agent-controller-url").value) {
            document.getElementById("agent-controller-url").value = window.location.origin;
        }
    }

    function installationFeedback(message, state = "") {
        const feedback = document.getElementById("agent-install-feedback");
        feedback.textContent = message;
        feedback.dataset.state = state;
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

    function renderPreconfiguration(preconfiguration) {
        const target = document.getElementById("agent-preconfiguration-status");
        if (!preconfiguration) {
            target.textContent = "";
            return;
        }
        if (preconfiguration.apply_error) {
            target.textContent = `Pré-configuração pendente com erro: ${preconfiguration.apply_error}`;
            return;
        }
        if (preconfiguration.applied_at) {
            target.textContent = `Pré-configuração aplicada em ${preconfiguration.applied_at}.`;
            return;
        }
        const name = preconfiguration.requested_name || preconfiguration.agent_name;
        const range = preconfiguration.port_start
            ? `${preconfiguration.port_protocol} ${preconfiguration.port_start}-${preconfiguration.port_end}`
            : "sem alteração de faixa";
        target.textContent = `Pré-configuração aguardando enrollment${name ? ` · nome ${name}` : ""} · ${range}.`;
    }

    async function poll() {
        if (!installationId) return;
        try {
            const status = await request(`/agents/installations/status?installation_id=${encodeURIComponent(installationId)}`);
            progress(status.state);
            renderPreconfiguration(status.preconfiguration);
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
        errorMessage();
        const platform = document.querySelector('input[name="agent-platform"]:checked').value;
        const method = selectedMethod();
        const releaseTag = method === "local" ? "" : document.getElementById("agent-release-tag")?.value;
        if (method !== "local" && !releaseTag) {
            errorMessage("Nenhuma GitHub Release compatível está disponível para a plataforma selecionada.");
            return;
        }
        const regionId = document.getElementById("agent-install-region").value;
        const datacenterId = document.getElementById("agent-install-datacenter").value;
        const controllerId = currentUser.role === "controller"
            ? currentUser.scope_id
            : document.getElementById("agent-install-controller").value;
        const portStart = document.getElementById("agent-preconfig-port-start").value;
        const portEnd = document.getElementById("agent-preconfig-port-end").value;
        const submit = document.getElementById("generate-agent-install");

        const payload = {
            platform,
            method,
            release_tag: releaseTag || undefined,
            region_id: regionId,
            datacenter_id: datacenterId,
            controller_id: controllerId,
            controller_url: method === "ssh"
                ? document.getElementById("agent-controller-url").value
                : window.location.origin,
            agent_name: document.getElementById("agent-preconfig-name").value,
            port_protocol: document.getElementById("agent-preconfig-protocol").value,
            port_start: portStart,
            port_end: portEnd
        };
        if (method === "ssh") {
            payload.ssh_host = document.getElementById("agent-ssh-host").value;
            payload.ssh_user = document.getElementById("agent-ssh-user").value;
            payload.ssh_port = document.getElementById("agent-ssh-port").value;
        }

        submit.disabled = true;
        submit.setAttribute("aria-busy", "true");
        submit.textContent = method === "ssh" ? "Executando bootstrap SSH..." : "Gerando...";
        installationFeedback(
            method === "ssh"
                ? `Conectando ao Agent e preparando ${releaseTag}...`
                : "Preparando a instalação...",
            "working"
        );
        try {
            const result = await request("/agents/installations", {
                method: "POST",
                body: JSON.stringify(payload)
            });
            installationId = result.installation_id;
            const resultRoot = document.getElementById("agent-install-result");
            const command = document.getElementById("agent-install-command");
            const copy = document.getElementById("copy-agent-install");
            const remoteStatus = document.getElementById("agent-remote-bootstrap-status");
            resultRoot.hidden = false;
            document.getElementById("agent-install-expiry").textContent = `Token válido até ${result.expires_at}. Uso único. Release: ${result.release_tag}.`;

            if (result.instruction) {
                document.getElementById("agent-install-result-title").textContent = "Instruções de instalação";
                command.hidden = false;
                copy.hidden = false;
                command.value = result.instruction;
                remoteStatus.hidden = true;
            } else {
                document.getElementById("agent-install-result-title").textContent = "Instalação remota iniciada";
                command.hidden = true;
                copy.hidden = true;
                remoteStatus.hidden = false;
                const remote = result.remote_bootstrap || {};
                remoteStatus.textContent = `Bootstrap SSH de ${remote.release_tag || result.release_tag} concluído em ${remote.host || payload.ssh_host}. Aguardando enrollment e heartbeat do Agent.`;
            }

            renderPreconfiguration(result.preconfiguration);
            installationFeedback(
                method === "ssh"
                    ? "Bootstrap SSH concluído. Aguardando enrollment do Agent."
                    : "Instrução de instalação gerada.",
                "success"
            );
            progress("waiting");
            if (pollTimer) clearInterval(pollTimer);
            pollTimer = setInterval(poll, 3000);
            await poll();
        } catch (error) {
            errorMessage(error.message);
            installationFeedback(`Falha: ${error.message}`, "error");
        } finally {
            submit.disabled = false;
            submit.removeAttribute("aria-busy");
            updateMethodUi();
        }
    }

    async function initializePhase14() {
        for (let i = 0; i < 50 && (!currentUser || !infrastructureTopology); i += 1) {
            await new Promise(resolve => setTimeout(resolve, 100));
        }
        if (!currentUser || !infrastructureTopology) return;
        populateTopology();
        ensureReleaseUi();
        document.querySelectorAll('input[name="agent-method"]').forEach(input => {
            input.addEventListener("change", async () => {
                updateMethodUi();
                await loadReleases();
            });
        });
        document.querySelectorAll('input[name="agent-platform"]').forEach(input => {
            input.addEventListener("change", async () => {
                updateMethodUi();
                await loadReleases();
            });
        });
        updateMethodUi();
        await loadReleases();
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
