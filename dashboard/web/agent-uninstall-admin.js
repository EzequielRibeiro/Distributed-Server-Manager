(function () {
    "use strict";

    const params = new URLSearchParams(location.search);
    const agentId = params.get("agent_id") || params.get("id") || "";
    const el = id => document.getElementById(id);
    let polling = null;

    async function request(path, options = {}) {
        const headers = {
            "X-Capivara-Auth-Area": "controller",
            Accept: "application/json",
            ...(options.headers || {})
        };
        if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
        const response = await fetch(path, {
            ...options,
            headers,
            credentials: "same-origin",
            cache: "no-store"
        });
        if (response.status === 401) {
            location.replace("login.html");
            throw new Error("Sessão expirada");
        }
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.message || payload.error || `HTTP ${response.status}`);
        return payload;
    }

    function setBusy(node, busy, label, normalLabel) {
        if (!node) return;
        node.disabled = busy;
        node.textContent = busy ? label : normalLabel;
    }

    function statusLabel(state) {
        if (!state || typeof state !== "object") return "Nenhuma desinstalação remota solicitada.";
        const labels = {
            queued: "Solicitação registrada; aguardando entrega ao Agent.",
            delivered: "Preparação entregue; aguardando aceite do Agent.",
            accepted: "Preparação aceita; aguardando entrega do commit.",
            "commit-delivered": "Commit entregue; aguardando execução da remoção no host.",
            committed: "Remoção iniciada no host.",
            completed: "Desinstalação do host concluída.",
            failed: "Falha durante a desinstalação do host.",
            cancelled: "Desinstalação cancelada."
        };
        const status = String(state.status || "unknown");
        const mode = state.mode === "purge" ? "apagar dados" : state.mode === "preserve-data" ? "preservar dados" : "modo desconhecido";
        const requestId = state.request_id ? ` · ${state.request_id}` : "";
        const error = state.error ? ` · Erro: ${state.error}` : "";
        return `${labels[status] || `Estado: ${status}`} · ${mode}${requestId}${error}`;
    }

    function renderState(state) {
        const box = el("agent-uninstall-state");
        if (box) box.textContent = statusLabel(state);
        const terminal = ["completed", "failed", "cancelled"].includes(String(state?.status || ""));
        if (terminal && polling) {
            clearInterval(polling);
            polling = null;
        }
    }

    async function verifyDestructiveTarget() {
        if (!agentId) throw new Error("Agent ID ausente da URL.");

        const displayedAgentId = String(el("detail-agent-id")?.textContent || "").trim();
        if (!displayedAgentId || displayedAgentId === "—") {
            throw new Error("A identidade exibida do Agent ainda não foi carregada. Atualize a página antes de continuar.");
        }
        if (displayedAgentId !== agentId) {
            throw new Error(`Bloqueado: o Agent da URL (${agentId}) diverge do Agent exibido (${displayedAgentId}).`);
        }

        const detailResult = await request(`/api/admin/agent?agent_id=${encodeURIComponent(agentId)}`);
        const detail = detailResult.agent || {};
        const backendAgentId = String(detail.agent_id || "").trim();
        if (backendAgentId !== agentId) {
            throw new Error(`Bloqueado: o Controller retornou identidade divergente (${backendAgentId || "ausente"}).`);
        }

        const displayedNodeId = String(el("detail-node")?.textContent || "").trim();
        const backendNodeId = String(detail.node_id || "").trim();
        if (displayedNodeId && displayedNodeId !== "—" && backendNodeId && displayedNodeId !== backendNodeId) {
            throw new Error(`Bloqueado: o Node exibido (${displayedNodeId}) diverge do Node vinculado (${backendNodeId}).`);
        }

        return {agent_id: backendAgentId, node_id: backendNodeId};
    }

    function assertMutationResponse(result, expected) {
        const returnedAgentId = String(result?.agent_id || "").trim();
        const returnedNodeId = String(result?.node_id || "").trim();
        if (returnedAgentId !== expected.agent_id) {
            throw new Error(`Resposta rejeitada: o Controller confirmou outro Agent (${returnedAgentId || "ausente"}).`);
        }
        if (expected.node_id && returnedNodeId && returnedNodeId !== expected.node_id) {
            throw new Error(`Resposta rejeitada: o Controller confirmou outro Node (${returnedNodeId}).`);
        }
    }

    async function refreshState() {
        if (!agentId) return;
        try {
            const result = await request(`/api/admin/agent/uninstall?agent_id=${encodeURIComponent(agentId)}`);
            if (String(result.agent_id || "") !== agentId) {
                throw new Error("O estado de desinstalação retornou para outro Agent.");
            }
            renderState(result.uninstall);
        } catch (error) {
            const box = el("agent-uninstall-state");
            if (box) box.textContent = error.message || String(error);
        }
    }

    function ensurePolling() {
        if (!polling) polling = setInterval(refreshState, 3000);
    }

    async function uninstall(mode) {
        const confirmation = String(el("agent-uninstall-confirmation")?.value || "").trim();
        if (confirmation !== agentId) {
            window.alert("Digite o Agent ID completo para confirmar a desinstalação remota.");
            return;
        }

        let expected;
        try {
            expected = await verifyDestructiveTarget();
        } catch (error) {
            const box = el("agent-uninstall-state");
            if (box) box.textContent = error.message || String(error);
            return;
        }

        const purge = mode === "purge";
        const warning = purge
            ? `Desinstalar ${expected.agent_id} (${expected.node_id || "Node desconhecido"}) e apagar os dados gerenciados no host? Esta operação é irreversível.`
            : `Desinstalar ${expected.agent_id} (${expected.node_id || "Node desconhecido"}) preservando os dados das instâncias no host?`;
        if (!window.confirm(warning)) return;

        const button = el(purge ? "agent-uninstall-purge" : "agent-uninstall-preserve");
        const normalLabel = purge ? "Desinstalar host e apagar dados" : "Desinstalar host — preservar dados";
        setBusy(button, true, "Solicitando…", normalLabel);
        try {
            const result = await request("/api/admin/agent/uninstall", {
                method: "POST",
                body: JSON.stringify({agent_id: expected.agent_id, confirmation, mode})
            });
            assertMutationResponse(result, expected);
            renderState(result.uninstall);
            ensurePolling();
        } catch (error) {
            const box = el("agent-uninstall-state");
            if (box) box.textContent = error.message || String(error);
        } finally {
            setBusy(button, false, "Solicitando…", normalLabel);
        }
    }

    async function forceRemove() {
        const confirmation = String(el("agent-force-remove-confirmation")?.value || "").trim();
        if (confirmation !== agentId) {
            window.alert("Digite o Agent ID completo para confirmar a remoção forçada do Controller.");
            return;
        }

        let expected;
        try {
            expected = await verifyDestructiveTarget();
        } catch (error) {
            const box = el("agent-force-remove-state");
            if (box) box.textContent = error.message || String(error);
            return;
        }

        if (!window.confirm(`Remover somente o registro de ${expected.agent_id} (${expected.node_id || "Node desconhecido"}) do Controller? A máquina remota e seus arquivos NÃO serão desinstalados.`)) return;
        const button = el("agent-force-remove");
        setBusy(button, true, "Removendo…", "Remover somente registro do Controller");
        try {
            const result = await request("/api/admin/agent/remove", {
                method: "POST",
                body: JSON.stringify({agent_id: expected.agent_id, confirmation})
            });
            assertMutationResponse(result, expected);
            if (!result.controller_only || result.remote_host_removal !== false) {
                throw new Error("O Controller não confirmou a semântica de remoção somente do registro.");
            }
            const box = el("agent-force-remove-state");
            if (box) box.textContent = result.warning || `Agent ${result.agent_id} removido somente do Controller.`;
            window.setTimeout(() => location.replace("agents.html?removed=" + encodeURIComponent(result.agent_id)), 900);
        } catch (error) {
            const box = el("agent-force-remove-state");
            if (box) box.textContent = error.message || String(error);
            setBusy(button, false, "Removendo…", "Remover somente registro do Controller");
        }
    }

    function init() {
        if (!agentId || !el("agent-danger-zone")) return;
        el("agent-uninstall-preserve")?.addEventListener("click", () => uninstall("preserve-data"));
        el("agent-uninstall-purge")?.addEventListener("click", () => uninstall("purge"));
        el("agent-force-remove")?.addEventListener("click", forceRemove);
        refreshState();
    }

    document.addEventListener("DOMContentLoaded", init);
})();
