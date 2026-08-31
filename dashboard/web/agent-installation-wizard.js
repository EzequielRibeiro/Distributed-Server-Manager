"use strict";
(() => {
    let installationId = null;
    let pollTimer = null;
    let currentStep = 0;

    const platform = document.body.dataset.agentPlatform || document.querySelector('input[name="agent-platform"]:checked')?.value || "linux";
    const el = id => document.getElementById(id);
    const steps = () => [...document.querySelectorAll(".cap-agent-step")];
    const indicators = () => [...document.querySelectorAll("[data-agent-step-indicator]")];

    function selectedMethod() {
        return document.querySelector('input[name="agent-method"]:checked')?.value || "github";
    }

    function collectType(value, type, result = []) {
        if (!value) return result;
        if (Array.isArray(value)) {
            value.forEach(v => collectType(v, type, result));
            return result;
        }
        if (typeof value !== "object") return result;
        if (value.type === type && value.id) result.push(value);
        Object.values(value).forEach(v => {
            if (v && typeof v === "object") collectType(v, type, result);
        });
        return result;
    }

    function unique(items) {
        const map = new Map();
        items.forEach(x => map.set(String(x.id), x));
        return [...map.values()];
    }

    function addOption(select, item) {
        select.appendChild(new Option(item.name || String(item.id), String(item.id)));
    }

    function populateTopology() {
        const region = el("agent-install-region");
        const dc = el("agent-install-datacenter");
        const controller = el("agent-install-controller");
        const wrapper = el("agent-controller-wrapper");
        const regions = unique(collectType(infrastructureTopology, "region"));
        const dcs = unique(collectType(infrastructureTopology, "datacenter"));
        const controllers = unique(collectType(infrastructureTopology, "controller"));

        region.replaceChildren(new Option("Selecione uma região", ""));
        regions.forEach(x => addOption(region, x));
        const render = () => {
            dc.replaceChildren(new Option("Selecione um datacenter", ""));
            dcs.filter(x => !region.value || String(x.region_id || x.region?.id || "") === region.value).forEach(x => addOption(dc, x));
        };
        region.addEventListener("change", render);
        render();

        if (currentUser.role === "admin") {
            wrapper.hidden = false;
            controller.replaceChildren(new Option("Selecione um Controller", ""));
            controllers.forEach(x => addOption(controller, x));
        }
    }

    function ensureReleaseUi() {
        if (el("agent-release-options")) return;
        const fieldset = document.createElement("fieldset");
        fieldset.id = "agent-release-options";
        fieldset.innerHTML = '<legend>Versão do Agent</legend><label>GitHub Release<select id="agent-release-tag" required><option value="">Carregando releases...</option></select></label><label class="inline-option"><input id="agent-release-prereleases" type="checkbox"> Mostrar pré-lançamentos</label><p id="agent-release-status" class="location-safety-note" role="status"></p>';
        const anchor = el("agent-release-anchor");
        if (anchor) anchor.appendChild(fieldset);
        else el("agent-ssh-options").parentNode.insertBefore(fieldset, el("agent-ssh-options"));
        el("agent-release-prereleases").addEventListener("change", loadReleases);
    }

    async function loadReleases() {
        ensureReleaseUi();
        const method = selectedMethod();
        const wrap = el("agent-release-options");
        const select = el("agent-release-tag");
        const status = el("agent-release-status");
        wrap.hidden = method === "local";
        select.required = method !== "local";
        select.disabled = method === "local";
        if (method === "local") return;

        select.disabled = true;
        select.replaceChildren(new Option("Carregando releases...", ""));
        status.textContent = "Consultando GitHub Releases...";
        try {
            const r = await request(`/agents/releases?platform=${encodeURIComponent(platform)}&include_prereleases=${el("agent-release-prereleases").checked ? "1" : "0"}`);
            select.replaceChildren();
            (r.releases || []).forEach((x, i) => select.appendChild(new Option(`${x.tag}${i === 0 && !x.prerelease ? " · mais recente estável" : ""}${x.prerelease ? " · pré-lançamento" : ""}`, x.tag)));
            if (!(r.releases || []).length) {
                select.appendChild(new Option(`Nenhuma release compatível para ${platform}`, ""));
                status.textContent = "Nenhuma release compatível encontrada.";
            } else {
                select.value = r.recommended || r.releases[0].tag;
                status.textContent = `${r.releases.length} release(s) compatível(is).`;
            }
        } catch (e) {
            select.replaceChildren(new Option("Falha ao consultar releases", ""));
            status.textContent = e.message;
        } finally {
            select.disabled = false;
        }
    }

    function updateUi() {
        const method = selectedMethod();
        const ssh = method === "ssh";
        const winrm = method === "winrm";
        el("agent-ssh-options").hidden = !ssh;
        el("agent-winrm-options").hidden = !winrm;

        const sshHost = el("agent-ssh-host");
        const sshUser = el("agent-ssh-user");
        const sshUrl = el("agent-controller-url");
        const winrmHost = el("agent-winrm-host");
        const winrmUrl = el("agent-winrm-controller-url");
        if (sshHost) sshHost.required = ssh;
        if (sshUser) sshUser.required = ssh;
        if (sshUrl) sshUrl.required = ssh;
        if (winrmHost) winrmHost.required = winrm;
        if (winrmUrl) winrmUrl.required = winrm;

        const release = el("agent-release-options");
        const releaseSelect = el("agent-release-tag");
        if (release) release.hidden = method === "local";
        if (releaseSelect) {
            releaseSelect.required = method !== "local";
            releaseSelect.disabled = method === "local";
        }
        renderReview();
    }

    function feedback(text, state = "") {
        el("agent-install-feedback").textContent = text;
        el("agent-install-feedback").dataset.state = state;
    }

    function sshPayload() {
        return {
            platform,
            ssh_host: el("agent-ssh-host").value,
            ssh_user: el("agent-ssh-user").value,
            ssh_port: el("agent-ssh-port").value,
            password_file: el("agent-password-file")?.value || undefined,
        };
    }

    async function testConnection() {
        const button = el("test-agent-connection");
        const out = el("agent-connection-result");
        button.disabled = true;
        out.textContent = "Testando conectividade, autenticação, plataforma e privilégios...";
        try {
            const r = await request("/agents/installations/test-connection", {method: "POST", body: JSON.stringify(sshPayload())});
            out.textContent = `✓ SSH OK · ${r.platform} · ${r.architecture || "arquitetura desconhecida"}\nAutenticação: ${r.authentication} · ${r.host}:${r.ssh_port}`;
        } catch (e) {
            out.textContent = `✕ ${e.message}`;
        } finally {
            button.disabled = false;
        }
    }

    function validateStep(index) {
        const step = steps()[index];
        if (!step) return true;
        const controls = [...step.querySelectorAll("input,select,textarea")].filter(x => !x.disabled && !x.closest("[hidden]") && x.type !== "hidden");
        for (const control of controls) {
            if (!control.checkValidity()) {
                control.reportValidity();
                control.focus();
                return false;
            }
        }
        if (index === 1) {
            const method = selectedMethod();
            const field = method === "ssh" ? el("agent-controller-url") : method === "winrm" ? el("agent-winrm-controller-url") : null;
            if ((method === "ssh" || method === "winrm") && !field?.value.trim()) {
                const message = "Informe a URL do Controller alcançável pelo Agent. Ela deve ser acessível pelo host remoto e corresponder ao certificado TLS.";
                feedback(message, "error");
                field?.focus();
                return false;
            }
        }
        feedback("");
        return true;
    }

    function showStep(index) {
        const all = steps();
        currentStep = Math.max(0, Math.min(index, all.length - 1));
        all.forEach((step, i) => {
            step.hidden = i !== currentStep;
            step.setAttribute("aria-hidden", i === currentStep ? "false" : "true");
        });
        indicators().forEach((indicator, i) => {
            indicator.classList.toggle("active", i === currentStep);
            indicator.classList.toggle("finish", i < currentStep);
            indicator.setAttribute("aria-current", i === currentStep ? "step" : "false");
        });
        const prev = el("agent-step-prev");
        const next = el("agent-step-next");
        const submit = el("generate-agent-install");
        if (prev) prev.hidden = currentStep === 0;
        if (next) next.hidden = currentStep === all.length - 1;
        if (submit) submit.hidden = currentStep !== all.length - 1;
        if (currentStep === all.length - 1) renderReview();
        const first = all[currentStep]?.querySelector("input:not([type=hidden]),select,textarea,button");
        first?.focus({preventScroll: true});
    }

    function nextStep() {
        if (!validateStep(currentStep)) return;
        showStep(currentStep + 1);
    }

    function previousStep() {
        showStep(currentStep - 1);
    }

    function textValue(id, fallback = "—") {
        const node = el(id);
        if (!node) return fallback;
        if (node.tagName === "SELECT") return node.selectedOptions?.[0]?.textContent?.trim() || fallback;
        return node.value?.trim() || fallback;
    }

    function renderReview() {
        const review = el("agent-install-review");
        if (!review) return;
        const method = selectedMethod();
        const methodLabel = document.querySelector('input[name="agent-method"]:checked')?.parentElement?.textContent?.trim() || method;
        const remoteUrl = method === "ssh" ? textValue("agent-controller-url") : method === "winrm" ? textValue("agent-winrm-controller-url") : window.location.origin;
        const remoteHost = method === "ssh" ? textValue("agent-ssh-host") : method === "winrm" ? textValue("agent-winrm-host") : "Não se aplica";
        review.innerHTML = `
            <dl class="cap-agent-review-grid">
                <div><dt>Plataforma</dt><dd>${platform === "windows" ? "Windows" : "Linux"}</dd></div>
                <div><dt>Método</dt><dd>${methodLabel}</dd></div>
                <div><dt>Release</dt><dd>${method === "local" ? "Pacote local" : textValue("agent-release-tag")}</dd></div>
                <div><dt>Host remoto</dt><dd>${remoteHost}</dd></div>
                <div><dt>Controller alcançável</dt><dd>${remoteUrl}</dd></div>
                <div><dt>Região</dt><dd>${textValue("agent-install-region")}</dd></div>
                <div><dt>Datacenter</dt><dd>${textValue("agent-install-datacenter")}</dd></div>
                <div><dt>Nome administrativo</dt><dd>${textValue("agent-preconfig-name")}</dd></div>
                <div><dt>Faixa de portas</dt><dd>${textValue("agent-preconfig-port-start")}–${textValue("agent-preconfig-port-end")} / ${textValue("agent-preconfig-protocol")}</dd></div>
                <div><dt>Endpoint público</dt><dd>${textValue("agent-public-hostname", textValue("agent-public-ipv4", "Não configurado"))}</dd></div>
            </dl>`;
    }

    function progress(state) {
        const root = el("agent-install-progress");
        const order = ["waiting", "pairing", "validating", "online"];
        const current = Math.max(0, order.indexOf(state));
        root.dataset.state = state;
        root.querySelectorAll("[data-step]").forEach((x, i) => {
            x.dataset.complete = i <= current ? "true" : "false";
            x.setAttribute("aria-current", i === current ? "step" : "false");
        });
    }

    function renderPreconfiguration(p) {
        const t = el("agent-preconfiguration-status");
        if (!p) { t.textContent = ""; return; }
        if (p.apply_error) { t.textContent = `Pré-configuração pendente com erro: ${p.apply_error}`; return; }
        const endpoint = p.public_hostname || p.public_ipv4 || "não configurado";
        if (p.applied_at) { t.textContent = `Pré-configuração aplicada em ${p.applied_at}. Endpoint público: ${endpoint}.`; return; }
        t.textContent = `Pré-configuração aguardando enrollment. Endpoint público: ${endpoint}.`;
    }

    async function poll() {
        if (!installationId) return;
        try {
            const s = await request(`/agents/installations/status?installation_id=${encodeURIComponent(installationId)}`);
            progress(s.state);
            renderPreconfiguration(s.preconfiguration);
            if (s.state === "online") {
                clearInterval(pollTimer);
                pollTimer = null;
            }
        } catch (e) {
            errorMessage(e.message);
        }
    }

    async function copyCommand() {
        const t = el("agent-install-command");
        try {
            await navigator.clipboard.writeText(t.value);
            el("copy-agent-install").textContent = "Copiado!";
            setTimeout(() => el("copy-agent-install").textContent = "Copiar instrução", 1500);
        } catch (_) {
            t.focus();
            t.select();
            feedback("Use Ctrl+C para copiar a instrução.", "error");
        }
    }

    async function generate(event) {
        event.preventDefault();
        errorMessage();
        if (!validateStep(currentStep)) return;

        const method = selectedMethod();
        const releaseTag = method === "local" ? "" : el("agent-release-tag")?.value;
        if (method !== "local" && !releaseTag) {
            errorMessage("Nenhuma GitHub Release compatível está disponível.");
            return;
        }
        const remoteUrl = method === "ssh" ? el("agent-controller-url")?.value.trim() : method === "winrm" ? el("agent-winrm-controller-url")?.value.trim() : "";
        if ((method === "ssh" || method === "winrm") && !remoteUrl) {
            const field = method === "ssh" ? el("agent-controller-url") : el("agent-winrm-controller-url");
            const message = "Informe a URL do Controller alcançável pelo Agent. Ela deve ser acessível pelo host remoto e corresponder ao certificado TLS.";
            errorMessage(message);
            feedback(message, "error");
            field?.focus();
            field?.reportValidity();
            return;
        }

        const payload = {
            platform,
            method,
            release_tag: releaseTag || undefined,
            region_id: el("agent-install-region").value,
            datacenter_id: el("agent-install-datacenter").value,
            controller_id: currentUser.role === "controller" ? currentUser.scope_id : el("agent-install-controller").value,
            controller_url: remoteUrl || window.location.origin,
            agent_name: el("agent-preconfig-name").value,
            port_protocol: el("agent-preconfig-protocol").value,
            port_start: el("agent-preconfig-port-start").value,
            port_end: el("agent-preconfig-port-end").value,
            public_hostname: el("agent-public-hostname")?.value || "",
            public_ipv4: el("agent-public-ipv4")?.value || "",
        };
        if (method === "ssh") Object.assign(payload, sshPayload());
        if (method === "winrm") payload.winrm_host = el("agent-winrm-host").value;

        const submit = el("generate-agent-install");
        submit.disabled = true;
        feedback(method === "ssh" || method === "winrm" ? "Executando preflight e bootstrap remoto..." : "Preparando instalação...", "working");
        try {
            const r = await request("/agents/installations", {method: "POST", body: JSON.stringify(payload)});
            installationId = r.installation_id;
            el("agent-install-result").hidden = false;
            el("agent-install-expiry").textContent = `Token válido até ${r.expires_at}. Uso único. Release: ${r.release_tag}.`;
            if (r.instruction) {
                el("agent-install-result-title").textContent = "Instruções de instalação";
                el("agent-install-command").hidden = false;
                el("copy-agent-install").hidden = false;
                el("agent-install-command").value = r.instruction;
                el("agent-remote-bootstrap-status").hidden = true;
            } else {
                el("agent-install-result-title").textContent = "Instalação remota iniciada";
                el("agent-install-command").hidden = true;
                el("copy-agent-install").hidden = true;
                const remote = r.remote_bootstrap || {};
                el("agent-remote-bootstrap-status").hidden = false;
                el("agent-remote-bootstrap-status").textContent = `Bootstrap ${remote.transport || method} concluído em ${remote.host}. Aguardando enrollment e heartbeat.`;
            }
            renderPreconfiguration(r.preconfiguration);
            feedback("Instalação preparada. Aguardando o Agent.", "success");
            progress("waiting");
            if (pollTimer) clearInterval(pollTimer);
            pollTimer = setInterval(poll, 3000);
            await poll();
        } catch (e) {
            errorMessage(e.message);
            feedback(`Falha: ${e.message}`, "error");
        } finally {
            submit.disabled = false;
            updateUi();
        }
    }

    async function init() {
        for (let i = 0; i < 50 && (!currentUser || !infrastructureTopology); i++) await new Promise(r => setTimeout(r, 100));
        if (!currentUser || !infrastructureTopology) return;
        populateTopology();
        ensureReleaseUi();
        document.querySelectorAll('input[name="agent-method"]').forEach(x => x.addEventListener("change", async () => {
            updateUi();
            await loadReleases();
        }));
        document.querySelectorAll("input,select,textarea").forEach(x => x.addEventListener("change", renderReview));
        el("agent-install-form").addEventListener("submit", generate);
        el("agent-step-next")?.addEventListener("click", nextStep);
        el("agent-step-prev")?.addEventListener("click", previousStep);
        el("copy-agent-install").addEventListener("click", copyCommand);
        el("test-agent-connection")?.addEventListener("click", testConnection);
        updateUi();
        await loadReleases();
        showStep(0);
    }

    window.addEventListener("load", init);
})();
