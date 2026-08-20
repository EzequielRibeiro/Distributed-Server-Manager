(() => {
    "use strict";

    const byId = id => document.getElementById(id);

    async function api(path, options = {}) {
        const headers = {
            Authorization: "Basic " + (sessionStorage.getItem("dsm_auth") || ""),
            Accept: "application/json"
        };
        if (options.body) headers["Content-Type"] = "application/json";
        const response = await fetch(path, { ...options, headers });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.message || data.error || `HTTP ${response.status}`);
        return data;
    }

    function status(text, kind = "pending") {
        const element = byId("catalog-v2-status");
        if (element) {
            element.textContent = text;
            element.dataset.state = kind;
        }
    }

    function summary(text) {
        const element = byId("catalog-v2-summary");
        if (element) element.textContent = text;
    }

    function result(data) {
        const element = byId("catalog-v2-result");
        if (!element) return;
        element.textContent = JSON.stringify(data, null, 2);
        element.hidden = false;
    }

    async function agentForSelectedNode() {
        const nodeId = byId("catalog-v2-node")?.value || "";
        if (!nodeId) throw new Error("Selecione um Node / Agent.");
        const response = await api("/api/agents");
        const agents = Array.isArray(response) ? response : (response.agents || []);
        const agent = agents.find(item =>
            item?.node_id === nodeId && String(item?.status || "").toLowerCase() === "active"
        );
        if (!agent) throw new Error("O Node selecionado não possui Agent ativo.");
        return agent;
    }

    async function waitForJob(jobId, agentId) {
        for (let attempt = 0; attempt < 3600; attempt += 1) {
            const job = await api(`/api/agents/game-data/jobs?job_id=${encodeURIComponent(jobId)}`);
            const state = String(job.status || "").toLowerCase();
            const progress = Number(job.progress || 0);
            summary(`Agent ${agentId} · ${job.environment_id} · ${progress}% · ${state}`);
            if (state === "completed") {
                status("JOGO INSTALADO", "success");
                result(job);
                return;
            }
            if (state === "failed") {
                status("ERRO NA INSTALAÇÃO", "error");
                result(job);
                throw new Error(job.last_error || "A instalação falhou no Agent.");
            }
            status(state === "running" ? "INSTALANDO NO AGENT" : "AGUARDANDO AGENT", "pending");
            await new Promise(resolve => setTimeout(resolve, 2000));
        }
        throw new Error("A instalação continua no Agent; atualize a tela para consultar o estado.");
    }

    async function install(button) {
        const agent = await agentForSelectedNode();
        const environmentId = byId("catalog-v2-runtime")?.value || "";
        if (!environmentId) throw new Error("Selecione um Ambiente de Execução.");
        const version = byId("catalog-v2-version")?.value || "current";
        const build = byId("catalog-v2-loader-version")?.value || "";
        const selector = build ? `${version}@${build}` : version;

        button.disabled = true;
        status("ENFILEIRANDO", "pending");
        summary(`Solicitando instalação em ${agent.id}...`);
        const job = await api("/api/catalog/environment-install", {
            method: "POST",
            body: JSON.stringify({ agent_id: agent.id, environment_id: environmentId, selector })
        });
        result(job);
        try {
            await waitForJob(job.job_id, agent.id);
        } finally {
            button.disabled = false;
        }
    }

    document.addEventListener("click", event => {
        const button = event.target?.closest?.("#catalog-v2-environment-install");
        if (!button) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        install(button).catch(error => {
            button.disabled = false;
            status("ERRO NA INSTALAÇÃO", "error");
            summary(error.message || String(error));
        });
    }, true);
})();
