/* Cross-Agent relocation. Preview is read-only; execution needs typed confirmation. */
(() => {
    "use strict";
    if (!location.pathname.endsWith("/controller-instance.html")) return;
    const q = new URLSearchParams(location.search);
    const iid = q.get("instance") || q.get("instance_id") || "";
    if (!iid) return;
    const API = "/api/admin/instance/agent-relocation";
    const statusNames = {
        queued:"Aguardando parada da origem",
        stopping:"Parando servidor na origem",
        backing_up:"Gerando backup integral com servidor parado",
        exporting:"Transferindo e verificando backup",
        cutting_over:"Reservando portas e alterando localização",
        provisioning:"Preparando runtime no destino",
        importing:"Transferindo arquivo para o destino",
        restoring:"Restaurando os dados",
        starting:"Iniciando no destino",
        verifying:"Validando saúde do servidor",
        rolling_back:"Recuperando a origem",
        manual_recovery:"Intervenção administrativa necessária",
        failed:"Não concluída; origem recuperada",
        completed:"Migração concluída"
    };
    const el = id => document.getElementById(id);
    let target = "";
    let preflight = null;
    let tracking = "";
    let polling = false;
    let enabled = false;

    async function api(query = "", options = {}) {
        const response = await fetch(API + query, {
            ...options,
            headers: {
                Accept:"application/json",
                "Content-Type":"application/json",
                "X-Capivara-Auth-Area":"controller",
                ...(options.headers || {})
            },
            credentials:"same-origin", cache:"no-store"
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.message || body.error || "Falha ao consultar migração.");
        return body;
    }
    function message(text, warning = false) {
        const node = el("relocation-message");
        if (!node) return;
        node.textContent = text;
        node.style.color = warning ? "#f0ac83" : "";
    }
    function displayState(item) {
        if (!item) return;
        tracking = item.relocation_id;
        el("relocation-status").textContent = (statusNames[item.status] || item.status) +
            " · " + item.relocation_id;
        const locked = !["completed", "failed"].includes(item.status);
        el("relocation-start").disabled = locked || !preflight || !enabled;
        el("relocation-preview").disabled = locked;
        el("relocation-agent").disabled = locked;
        if (item.status === "manual_recovery") {
            message(
                "A recuperação automática foi interrompida para impedir dois servidores ativos. " +
                (item.last_error || "Verifique o destino antes de reativar a origem."),
                true
            );
        } else if (item.status === "failed") {
            message(item.last_error || "Migração não concluída. Consulte o histórico.", true);
        } else if (item.status === "completed") {
            message("Operação concluída. A origem permanece preservada e parada até a liberação administrativa.");
        } else {
            message("Operação em andamento. Não reinicie os Agents nem altere a instância durante a transferência.");
        }
    }
    async function refresh() {
        if (polling) return;
        polling = true;
        try {
            if (tracking) {
                const result = await api("?relocation_id=" + encodeURIComponent(tracking));
                displayState(result.relocation);
            } else {
                const result = await api("?instance_id=" + encodeURIComponent(iid));
                const current = (result.relocations || []).find(row =>
                    !["completed", "failed"].includes(row.status));
                if (current) displayState(current);
            }
        } catch (error) { message(error.message, true); }
        finally { polling = false; }
    }
    async function preview() {
        target = el("relocation-agent").value;
        preflight = null;
        el("relocation-start").disabled = true;
        if (!target) {message("Selecione o Agent de destino."); return;}
        message("Validando capacidade e portas do destino…");
        try {
            const result = await api(
                "?instance_id=" + encodeURIComponent(iid) +
                "&target_agent_id=" + encodeURIComponent(target)
            );
            preflight = result.preflight;
            enabled = result.enabled === true;
            const ports = (preflight.target_ports || [])
                .map(p => p.name + " " + p.protocol.toUpperCase() + "/" + p.port).join(", ");
            message("Destino compatível. Portas propostas: " + ports +
                ". A parada da origem e o backup completo são obrigatórios.");
            el("relocation-start").disabled = !enabled;
        } catch (error) {message(error.message, true);}
    }
    async function start() {
        if (!enabled || !preflight || target !== el("relocation-agent").value) return;
        const confirmation = prompt(
            "A migração pode causar indisponibilidade. Os jogadores devem sair antes da operação. " +
            "Digite o ID da instância para autorizar a parada e movimentação: " + iid
        );
        if (confirmation === null) return;
        if (confirmation !== iid) {message("O ID digitado não confere. Operação cancelada.", true); return;}
        el("relocation-start").disabled = true;
        try {
            const body = await api("", {
                method:"POST", body: JSON.stringify({
                    action:"start", instance_id:iid, target_agent_id:target,
                    confirmation
                })
            });
            displayState(body.relocation);
        } catch (error) {
            message(error.message, true);
            el("relocation-start").disabled = !enabled;
        }
    }
    async function init() {
        const overview = el("view-overview");
        if (!overview) return;
        const card = document.createElement("article");
        card.className = "card mt-14";
        card.innerHTML = `<h2>Mover instância para outro Agent</h2>
            <p class="muted">O servidor será parado. O Capivara verificará recursos e portas,
            criará backup integral, transferirá os dados e só iniciará o destino
            depois da restauração. Não existe migração sem interrupção.</p>
            <div class="form-grid">
            <label>Agent de destino <select id="relocation-agent">
                <option value="">Selecione outro Agent…</option>
            </select></label></div>
            <div class="actions mt-12">
                <button type="button" class="btn" id="relocation-preview">Verificar destino</button>
                <button type="button" class="btn primary" id="relocation-start" disabled>Confirmar migração</button>
            </div>
            <p id="relocation-message" class="muted" aria-live="polite"></p>
            <strong id="relocation-status" aria-live="polite"></strong>
            <p class="muted">A origem e suas portas permanecem reservadas após a conclusão
            para permitir recuperação administrativa. Não remova manualmente o backup.</p>`;
        overview.append(card);
        el("relocation-preview").onclick = preview;
        el("relocation-start").onclick = start;
        el("relocation-agent").onchange = () => {
            preflight = null;
            el("relocation-start").disabled = true;
            message("Clique em Verificar destino para validar os recursos.");
        };
        try {
            const result = await api("?instance_id=" + encodeURIComponent(iid));
            enabled = result.enabled === true;
            if (!enabled)
                message("Consulta disponível. Execução bloqueada até homologação entre dois Agents.", true);
            const select = el("relocation-agent");
            for (const item of result.agents || []) {
                if (item.status !== "active") continue;
                select.add(new Option(item.name + " (" + item.id + ")", item.id));
            }
            const current = (result.relocations || []).find(row =>
                !["completed", "failed"].includes(row.status));
            if (current) displayState(current);
            else if (!select.options.length || select.options.length === 1)
                message("Nenhum outro Agent ativo está cadastrado neste Controller.", true);
        } catch (error) {
            message(error.message, true);
        }
        setInterval(() => {
            if (document.visibilityState === "visible") refresh();
        }, 8000);
    }
    if (document.readyState === "loading")
        document.addEventListener("DOMContentLoaded", init);
    else init();
})();
