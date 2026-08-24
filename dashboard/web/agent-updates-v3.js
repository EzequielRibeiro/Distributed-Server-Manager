"use strict";

(() => {
    const el = id => document.getElementById(id);
    const auth = () => sessionStorage.getItem("dsm_auth") || "";
    const ACTIVE_STATES = new Set(["planned", "updating", "verifying"]);
    const PROGRESS = {
        planned: [15, "Rollout planejado", "Aguardando o Agent receber a atualização."],
        updating: [55, "Atualizando o Agent", "O pacote está sendo aplicado. O Agent pode reiniciar durante esta etapa."],
        verifying: [85, "Verificando a atualização", "Aguardando o Agent retornar online na versão solicitada."],
        completed: [100, "Atualização concluída", "O Agent retornou online na versão esperada."],
        failed: [100, "Falha na atualização", "A atualização não foi concluída. Consulte os detalhes e tente novamente."],
    };
    let pollTimer = null;

    async function request(path, options = {}) {
        const response = await fetch(`/api${path}`, {
            ...options,
            headers: {
                Authorization: `Basic ${auth()}`,
                Accept: "application/json",
                ...(options.body ? {"Content-Type": "application/json"} : {}),
                ...(options.headers || {})
            }
        });
        if (response.status === 401) {
            sessionStorage.clear();
            location.replace("login.html");
            throw new Error("Sessão expirada");
        }
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.error || payload.message || `HTTP ${response.status}`);
        return payload;
    }

    function showError(message = "") {
        const box = el("agent-update-error");
        if (!box) return;
        box.hidden = !message;
        box.textContent = message;
    }

    function setText(id, value) {
        const target = el(id);
        if (target) target.textContent = value || "—";
    }

    function setRolloutBusy(busy) {
        const button = el("agent-rollout-submit");
        if (!button) return;
        button.disabled = busy;
        button.textContent = busy ? "Atualização em andamento…" : "Criar rollout";
        button.setAttribute("aria-busy", String(busy));
    }

    function renderErrorDetails(status, state) {
        const details = el("agent-update-error-details");
        const content = el("agent-update-error-detail-content");
        if (!details || !content) return;
        const failed = state === "failed";
        details.hidden = !failed;
        if (!failed) {
            details.open = false;
            content.textContent = "";
            return;
        }
        const values = [
            ["Erro", status.last_error || "O Controller não forneceu detalhes adicionais."],
            ["Agent", status.agent_id || el("agent-update-selector")?.value],
            ["Rollout", status.rollout_id],
            ["Versão instalada", status.installed_version],
            ["Versão desejada", status.desired_version || status.available_version],
            ["Canal", status.update_channel],
            ["Lote", status.batch_number],
            ["Solicitado em", status.requested_at],
            ["Atualizado em", status.updated_at || status.last_update],
        ];
        content.textContent = values
            .filter(([, value]) => value !== null && value !== undefined && value !== "")
            .map(([label, value]) => `${label}: ${value}`)
            .join("\n");
    }

    function renderProgress(status = {}) {
        const state = String(status.update_status || "idle").toLowerCase();
        const progress = el("agent-update-progress");
        const statusCard = el("agent-update-status-card");
        if (statusCard) statusCard.setAttribute("data-state", state);
        setRolloutBusy(ACTIVE_STATES.has(state));
        if (!progress) return;
        const presentation = PROGRESS[state];
        progress.hidden = !presentation;
        progress.setAttribute("data-state", state);
        renderErrorDetails(status, state);
        if (!presentation) return;
        const [value, title, message] = presentation;
        setText("agent-update-progress-title", title);
        setText("agent-update-progress-value", `${value}%`);
        setText("agent-update-progress-message", status.last_error || message);
        const track = progress.querySelector('[role="progressbar"]');
        const bar = el("agent-update-progress-bar");
        if (track) track.setAttribute("aria-valuenow", String(value));
        if (bar) bar.style.width = `${value}%`;
    }

    function schedulePoll(status) {
        clearTimeout(pollTimer);
        pollTimer = null;
        if (ACTIVE_STATES.has(String(status?.update_status || "").toLowerCase())) {
            pollTimer = setTimeout(loadStatus, 2000);
        }
    }

    async function loadAgents() {
        const selector = el("agent-update-selector");
        if (!selector) return;
        const result = await request("/agents");
        const agents = Array.isArray(result) ? result : (result.agents || []);
        agents.forEach(agent => selector.add(new Option(agent.name || agent.id, agent.id)));
        if (location.hash === "#agent-update-panel" && agents.length === 1) {
            selector.value = agents[0].id;
            await loadStatus();
        }
    }

    async function loadStatus() {
        const agentId = el("agent-update-selector")?.value || "";
        if (!agentId) {
            clearTimeout(pollTimer);
            renderProgress({update_status: "idle"});
            return;
        }
        try {
            const status = await request(`/agents/updates/status?agent_id=${encodeURIComponent(agentId)}`);
            setText("agent-installed-version", status.installed_version);
            setText("agent-available-version", status.available_version);
            setText("agent-update-status", status.update_status);
            setText("agent-last-update", status.last_update);
            el("agent-update-channel").value = status.update_channel || "stable";
            el("agent-rollout-channel").value = status.update_channel || "stable";
            el("agent-rollout-agents").value = agentId;
            renderProgress(status);
            schedulePoll(status);
            showError();
        } catch (error) {
            showError(error.message);
            pollTimer = setTimeout(loadStatus, 5000);
        }
    }

    async function saveChannel(event) {
        event.preventDefault();
        const agentId = el("agent-update-selector")?.value || "";
        if (!agentId) return showError("Selecione um Agent.");
        try {
            const result = await request("/agents/updates/channel", {
                method: "POST",
                body: JSON.stringify({agent_id: agentId, update_channel: el("agent-update-channel").value})
            });
            el("agent-update-channel").value = result.update_channel;
            el("agent-rollout-channel").value = result.update_channel;
            showError();
        } catch (error) {
            showError(error.message);
        }
    }

    async function createRollout(event) {
        event.preventDefault();
        const agentIds = el("agent-rollout-agents").value.split(/[\s,;]+/).map(value => value.trim()).filter(Boolean);
        setRolloutBusy(true);
        renderProgress({update_status: "planned"});
        try {
            const rollout = await request("/agents/updates/rollouts", {
                method: "POST",
                body: JSON.stringify({
                    agent_ids: agentIds,
                    desired_version: el("agent-rollout-version").value.trim(),
                    update_channel: el("agent-rollout-channel").value,
                    batch_size: Number(el("agent-rollout-batch-size").value)
                })
            });
            setText("agent-available-version", rollout.desired_version);
            setText("agent-update-status", "planned");
            showError();
            await loadStatus();
        } catch (error) {
            renderProgress({
                update_status: "failed",
                last_error: error.message,
                agent_id: el("agent-update-selector")?.value,
                desired_version: el("agent-rollout-version")?.value,
                update_channel: el("agent-rollout-channel")?.value,
            });
            setRolloutBusy(false);
            showError(error.message);
        }
    }

    document.addEventListener("DOMContentLoaded", async () => {
        el("agent-update-selector")?.addEventListener("change", () => {
            clearTimeout(pollTimer);
            loadStatus();
        });
        el("agent-update-channel-form")?.addEventListener("submit", saveChannel);
        el("agent-rollout-form")?.addEventListener("submit", createRollout);
        try { await loadAgents(); } catch (error) { showError(error.message); }
    });
})();
