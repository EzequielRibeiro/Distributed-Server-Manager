"use strict";
(() => {
    const el = id => document.getElementById(id);
    let stepIndex = 0;
    let rowSeq = 0;
    const hosts = new Map();
    const steps = () => [...document.querySelectorAll("[data-batch-step]")];
    const indicators = () => [...document.querySelectorAll("[data-batch-step-indicator]")];

    function feedback(text, state = "") {
        const node = el("batch-feedback");
        node.textContent = text || "";
        node.dataset.state = state;
    }

    function topologyItems(value, type, out = []) {
        if (!value) return out;
        if (Array.isArray(value)) { value.forEach(x => topologyItems(x, type, out)); return out; }
        if (typeof value !== "object") return out;
        if (value.type === type && value.id) out.push(value);
        Object.values(value).forEach(x => { if (x && typeof x === "object") topologyItems(x, type, out); });
        return out;
    }

    function unique(items) {
        const map = new Map();
        items.forEach(x => map.set(String(x.id), x));
        return [...map.values()];
    }

    function populateTopology() {
        const region = el("batch-region");
        const dc = el("batch-datacenter");
        const controller = el("batch-controller");
        const wrapper = el("batch-controller-wrapper");
        const regions = unique(topologyItems(infrastructureTopology, "region"));
        const dcs = unique(topologyItems(infrastructureTopology, "datacenter"));
        const controllers = unique(topologyItems(infrastructureTopology, "controller"));
        region.replaceChildren(new Option("Selecione uma região", ""));
        regions.forEach(x => region.appendChild(new Option(x.name || x.id, x.id)));
        const renderDc = () => {
            dc.replaceChildren(new Option("Selecione um datacenter", ""));
            dcs.filter(x => !region.value || String(x.region_id || x.region?.id || "") === region.value)
                .forEach(x => dc.appendChild(new Option(x.name || x.id, x.id)));
        };
        region.addEventListener("change", renderDc);
        renderDc();
        if (currentUser.role === "admin") {
            wrapper.hidden = false;
            controller.replaceChildren(new Option("Selecione um Controller", ""));
            controllers.forEach(x => controller.appendChild(new Option(x.name || x.id, x.id)));
        }
    }

    async function loadReleases() {
        const platform = el("batch-platform").value;
        const select = el("batch-release");
        select.disabled = true;
        select.replaceChildren(new Option("Carregando releases...", ""));
        try {
            const r = await request(`/agents/releases?platform=${encodeURIComponent(platform)}&include_prereleases=0`);
            select.replaceChildren();
            (r.releases || []).forEach((x, index) => select.appendChild(new Option(`${x.tag}${index === 0 ? " · mais recente estável" : ""}`, x.tag)));
            if (!(r.releases || []).length) select.appendChild(new Option("Nenhuma release compatível", ""));
            else select.value = r.recommended || r.releases[0].tag;
        } catch (error) {
            select.replaceChildren(new Option("Falha ao consultar releases", ""));
            feedback(error.message, "error");
        } finally {
            select.disabled = false;
        }
    }

    function rowValue(row, field) {
        return row.querySelector(`[data-field="${field}"]`)?.value?.trim() || "";
    }

    function addHost(initial = {}) {
        const id = `batch-host-${++rowSeq}`;
        hosts.set(id, {id, preflight: "pending", preflightResult: null, preflightError: "", installationId: null, installState: "pending", installError: ""});
        const tr = document.createElement("tr");
        tr.dataset.hostId = id;
        tr.innerHTML = `
            <td><input data-field="host" type="text" required autocomplete="off" placeholder="192.168.15.56"></td>
            <td><input data-field="user" type="text" required autocomplete="off" placeholder="Administrator"></td>
            <td><input data-field="port" type="number" min="1" max="65535" value="22" required></td>
            <td><input data-field="password_file" type="text" autocomplete="off" placeholder="/etc/capivara/secrets/remote-deploy/node.secret"></td>
            <td><input data-field="name" type="text" maxlength="128" autocomplete="off" placeholder="Node 01"></td>
            <td><button type="button" data-remove-host aria-label="Remover host">×</button></td>`;
        el("batch-hosts").appendChild(tr);
        for (const [key, value] of Object.entries(initial)) {
            const input = tr.querySelector(`[data-field="${key}"]`);
            if (input) input.value = value;
        }
        tr.querySelector("[data-remove-host]").addEventListener("click", () => {
            hosts.delete(id); tr.remove(); renderPreflight(); renderInstall();
        });
    }

    function hostRows() { return [...el("batch-hosts").querySelectorAll("tr[data-host-id]")]; }

    function hostPayload(row) {
        return {
            platform: el("batch-platform").value,
            ssh_host: rowValue(row, "host"),
            ssh_user: rowValue(row, "user"),
            ssh_port: rowValue(row, "port") || "22",
            password_file: rowValue(row, "password_file") || undefined,
        };
    }

    function validateRows() {
        const rows = hostRows();
        if (!rows.length) { feedback("Adicione pelo menos um host ao lote.", "error"); return false; }
        for (const row of rows) {
            for (const input of row.querySelectorAll("input")) {
                if (!input.checkValidity()) { input.reportValidity(); input.focus(); return false; }
            }
        }
        return true;
    }

    function validateStep() {
        if (stepIndex === 0) {
            for (const input of steps()[0].querySelectorAll("input,select")) {
                if (!input.checkValidity()) { input.reportValidity(); input.focus(); return false; }
            }
        }
        if (stepIndex === 1 && !validateRows()) return false;
        feedback(""); return true;
    }

    function showStep(index) {
        const all = steps();
        stepIndex = Math.max(0, Math.min(index, all.length - 1));
        all.forEach((x, i) => { x.hidden = i !== stepIndex; });
        indicators().forEach((x, i) => {
            x.classList.toggle("active", i === stepIndex);
            x.classList.toggle("finish", i < stepIndex);
            x.setAttribute("aria-current", i === stepIndex ? "step" : "false");
        });
        el("batch-prev").hidden = stepIndex === 0;
        el("batch-next").hidden = stepIndex === all.length - 1;
        if (stepIndex === 2) renderPreflight();
        if (stepIndex === 3) { renderSummary(); renderInstall(); }
    }

    async function testOne(row) {
        const state = hosts.get(row.dataset.hostId);
        state.preflight = "testing"; state.preflightError = ""; state.preflightResult = null;
        renderPreflight();
        try {
            const result = await request("/agents/installations/test-connection", {method: "POST", body: JSON.stringify(hostPayload(row))});
            state.preflight = "ready"; state.preflightResult = result;
        } catch (error) {
            state.preflight = "failed"; state.preflightError = error.message;
        }
        renderPreflight(); renderSummary();
    }

    async function testMany(mode) {
        if (!validateRows()) return;
        const rows = hostRows().filter(row => mode !== "failed" || hosts.get(row.dataset.hostId)?.preflight === "failed");
        if (!rows.length) { feedback("Nenhum host elegível para esse teste."); return; }
        feedback(`Testando ${rows.length} host(s)...`, "working");
        el("batch-test-all").disabled = true; el("batch-retry-failed").disabled = true;
        try { await Promise.all(rows.map(testOne)); }
        finally { el("batch-test-all").disabled = false; el("batch-retry-failed").disabled = false; }
        const ready = [...hosts.values()].filter(x => x.preflight === "ready").length;
        const failed = [...hosts.values()].filter(x => x.preflight === "failed").length;
        feedback(`Preflight concluído: ${ready} pronto(s), ${failed} falha(s).`, failed ? "error" : "success");
    }

    function statusLabel(state) {
        return ({pending:"Pendente",testing:"Testando",ready:"Pronto",failed:"Falhou",installing:"Instalando",waiting:"Aguardando Agent",pairing:"Pareando",validating:"Validando",online:"Online"})[state] || state;
    }

    function renderPreflight() {
        const body = el("batch-preflight-results"); body.replaceChildren();
        for (const row of hostRows()) {
            const item = hosts.get(row.dataset.hostId); const result = item?.preflightResult || {};
            const tr = document.createElement("tr"); tr.innerHTML = `<td></td><td></td><td></td><td></td><td></td><td></td>`;
            tr.children[0].textContent = rowValue(row,"host") || "—";
            tr.children[1].textContent = result.platform || "—";
            tr.children[2].textContent = result.architecture || "—";
            tr.children[3].textContent = result.authentication || "—";
            tr.children[4].textContent = item?.preflight === "failed" ? `Falhou · ${item.preflightError}` : statusLabel(item?.preflight || "pending");
            const button = document.createElement("button"); button.type="button"; button.textContent="Testar"; button.disabled=item?.preflight==="testing"; button.addEventListener("click",()=>testOne(row)); tr.children[5].appendChild(button);
            body.appendChild(tr);
        }
    }

    function commonInstallPayload(row) {
        const controllerId = currentUser.role === "controller" ? currentUser.scope_id : el("batch-controller").value;
        return {
            ...hostPayload(row), method:"ssh", release_tag:el("batch-release").value,
            region_id:el("batch-region").value, datacenter_id:el("batch-datacenter").value,
            controller_id:controllerId, controller_url:el("batch-controller-url").value.trim(),
            agent_name:rowValue(row,"name"), port_protocol:el("batch-port-protocol").value,
            port_start:el("batch-port-start").value, port_end:el("batch-port-end").value,
        };
    }

    async function pollInstallation(item) {
        for (let attempt=0; attempt<120; attempt++) {
            await new Promise(resolve => setTimeout(resolve, 3000));
            try {
                const s = await request(`/agents/installations/status?installation_id=${encodeURIComponent(item.installationId)}`);
                item.installState = s.state || item.installState; renderInstall();
                if (item.installState === "online") return;
            } catch (error) { item.installError = error.message; renderInstall(); }
        }
        if (item.installState !== "online") { item.installState = "failed"; item.installError = "Tempo limite aguardando o Agent ficar online."; renderInstall(); }
    }

    async function installOne(row) {
        const item = hosts.get(row.dataset.hostId); item.installState="installing"; item.installError=""; renderInstall();
        try {
            const result = await request("/agents/installations", {method:"POST", body:JSON.stringify(commonInstallPayload(row))});
            item.installationId = result.installation_id; item.installState = result.state || "waiting"; renderInstall();
            await pollInstallation(item);
        } catch (error) { item.installState="failed"; item.installError=error.message; renderInstall(); }
    }

    async function installBatch() {
        const readyOnly = el("batch-ready-only").checked;
        const rows = hostRows().filter(row => !readyOnly || hosts.get(row.dataset.hostId)?.preflight === "ready");
        if (!rows.length) { feedback("Nenhum host aprovado para instalação.", "error"); return; }
        if (readyOnly && rows.some(row => hosts.get(row.dataset.hostId)?.preflight !== "ready")) return;
        el("batch-install").disabled = true; feedback(`Instalando ${rows.length} host(s) aprovados...`, "working");
        await Promise.all(rows.map(installOne));
        const online=[...hosts.values()].filter(x=>x.installState==="online").length;
        const failed=[...hosts.values()].filter(x=>x.installState==="failed").length;
        feedback(`Lote concluído: ${online} online, ${failed} falha(s).`, failed ? "error" : "success"); el("batch-install").disabled=false;
    }

    function renderSummary() {
        const ready=[...hosts.values()].filter(x=>x.preflight==="ready").length;
        const failed=[...hosts.values()].filter(x=>x.preflight==="failed").length;
        el("batch-summary").innerHTML=`<dl class="cap-agent-review-grid"><div><dt>Plataforma</dt><dd>${el("batch-platform").value}</dd></div><div><dt>Release</dt><dd>${el("batch-release").value||"—"}</dd></div><div><dt>Hosts</dt><dd>${hosts.size}</dd></div><div><dt>Preflight aprovado</dt><dd>${ready}</dd></div><div><dt>Preflight com falha</dt><dd>${failed}</dd></div><div><dt>Controller</dt><dd>${el("batch-controller-url").value||"—"}</dd></div></dl>`;
    }

    function renderInstall() {
        const body=el("batch-install-results"); body.replaceChildren();
        for (const row of hostRows()) {
            const item=hosts.get(row.dataset.hostId); const tr=document.createElement("tr"); tr.innerHTML="<td></td><td></td><td></td><td></td><td></td>";
            tr.children[0].textContent=rowValue(row,"host")||"—"; tr.children[1].textContent=rowValue(row,"name")||"—";
            tr.children[2].textContent=item?.installationId||"—"; tr.children[3].textContent=statusLabel(item?.installState||"pending"); tr.children[4].textContent=item?.installError||"—"; body.appendChild(tr);
        }
    }

    async function init() {
        for (let i=0;i<50&&(!currentUser||!infrastructureTopology);i++) await new Promise(r=>setTimeout(r,100));
        if (!currentUser||!infrastructureTopology) return;
        populateTopology(); await loadReleases(); addHost(); showStep(0);
        el("batch-platform").addEventListener("change", loadReleases);
        el("batch-add-host").addEventListener("click",()=>addHost());
        el("batch-clear-hosts").addEventListener("click",()=>{hosts.clear();el("batch-hosts").replaceChildren();addHost();renderPreflight();renderInstall();});
        el("batch-test-all").addEventListener("click",()=>testMany("all"));
        el("batch-retry-failed").addEventListener("click",()=>testMany("failed"));
        el("batch-install").addEventListener("click",installBatch);
        el("batch-next").addEventListener("click",()=>{if(validateStep())showStep(stepIndex+1);});
        el("batch-prev").addEventListener("click",()=>showStep(stepIndex-1));
        el("agent-batch-form").addEventListener("submit",event=>event.preventDefault());
    }
    window.addEventListener("load",init);
})();
