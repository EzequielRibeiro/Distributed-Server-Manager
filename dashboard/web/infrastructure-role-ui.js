"use strict";

(function () {
    const ROLE_API = "/api/infrastructure/role";

    function authHeaders() {
        return {Accept: "application/json", "X-Capivara-Auth-Area": "controller"};
    }

    async function api(path, options = {}) {
        const headers = {...authHeaders(), ...(options.headers || {})};
        if (options.body) headers["Content-Type"] = "application/json";
        const response = await fetch(path, {...options, headers, credentials: "same-origin", cache: options.cache || "no-store"});
        if (response.status === 401) {
            location.replace("/login.html");
            throw new Error("Sessão encerrada");
        }
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.error || body.message || `HTTP ${response.status}`);
        return body;
    }

    function ensurePanel() {
        let panel = document.getElementById("local-role-panel");
        if (panel) return panel;
        panel = document.createElement("section");
        panel.id = "local-role-panel";
        panel.className = "agent-detail agent-manager-only";
        panel.innerHTML = `
            <h2>Este Node</h2>
            <div class="range-grid">
                <article class="range-card"><span>Node</span><strong id="local-role-node">—</strong></article>
                <article class="range-card"><span>Papel</span><strong id="local-role-name">—</strong></article>
                <article class="range-card"><span>Agent local</span><strong id="local-role-agent">—</strong></article>
                <article class="range-card"><span>Health</span><strong id="local-role-health">—</strong></article>
                <article class="range-card"><span>Placement</span><strong id="local-role-placement">—</strong></article>
            </div>
            <div id="local-role-activate" hidden>
                <p>Este host possui Controller, mas não possui o papel Agent local. Ativar o modo híbrido preserva o Node e o Controller existentes e adiciona um Agent local.</p>
                <button id="promote-local-hybrid" type="button">Ativar Agent local · modo híbrido</button>
            </div>
            <div id="local-role-deactivate" hidden>
                <p>Este host opera em modo híbrido. Desativar o Agent local preserva o mesmo Node e Controller e retorna este host ao papel Controller.</p>
                <button id="demote-local-controller" type="button">Desativar Agent local · voltar a Controller</button>
            </div>
            <p id="local-role-message" aria-live="polite"></p>
        `;
        const error = document.getElementById("agents-error");
        if (error && error.parentNode) error.parentNode.insertBefore(panel, error.nextSibling);
        return panel;
    }

    function render(status, user) {
        ensurePanel();
        document.getElementById("local-role-node").textContent = status.node_id || "—";
        document.getElementById("local-role-name").textContent = status.role || "—";
        document.getElementById("local-role-agent").textContent = status.agent_id || "Nenhum";
        document.getElementById("local-role-health").textContent = status.health_status || "—";
        document.getElementById("local-role-placement").textContent = status.placement_ready ? "Pronto" : `Bloqueado · ${status.placement_reason || "não elegível"}`;
        const isAdmin = user.role === "admin";
        document.getElementById("local-role-activate").hidden = !(isAdmin && status.role === "controller" && !status.agent_id);
        document.getElementById("local-role-deactivate").hidden = !(isAdmin && status.role === "hybrid" && status.agent_id);
    }

    async function load() {
        const user = await api("/api/whoami");
        const status = await api(ROLE_API);
        render(status, user);
        return {user, status};
    }

    async function promote() {
        const button = document.getElementById("promote-local-hybrid");
        const message = document.getElementById("local-role-message");
        if (!window.confirm("Ativar o modo híbrido neste Node? O Controller e o Node existentes serão preservados e um Agent local será criado.")) return;
        button.disabled = true;
        message.textContent = "Promovendo Controller para Hybrid e reconciliando o Agent local…";
        try {
            const result = await api(ROLE_API, {method: "POST", body: JSON.stringify({role: "hybrid"})});
            message.textContent = result.placement_ready ? "Modo híbrido ativado. Agent local online e placement disponível." : `Modo híbrido ativado. Placement ainda bloqueado: ${result.placement_reason || "verifique os requisitos técnicos"}.`;
            await load();
            if (typeof window.loadAgents === "function") await window.loadAgents();
        } catch (error) {
            message.textContent = `Falha: ${error.message}`;
        } finally {
            button.disabled = false;
        }
    }

    async function demote() {
        const button = document.getElementById("demote-local-controller");
        const message = document.getElementById("local-role-message");
        if (!window.confirm("Desativar o Agent local deste Node? Instâncias locais impedem a operação. O Node e o Controller serão preservados.")) return;
        button.disabled = true;
        message.textContent = "Desativando Agent local e retornando o Node ao papel Controller…";
        try {
            await api(ROLE_API, {method: "POST", body: JSON.stringify({role: "controller"})});
            message.textContent = "Agent local desativado. O Node continua como Controller e pode ser promovido novamente a Hybrid.";
            await load();
            if (typeof window.loadAgents === "function") await window.loadAgents();
        } catch (error) {
            message.textContent = `Falha: ${error.message}`;
        } finally {
            button.disabled = false;
        }
    }

    document.addEventListener("DOMContentLoaded", async () => {
        try {
            ensurePanel();
            document.getElementById("promote-local-hybrid").addEventListener("click", promote);
            document.getElementById("demote-local-controller").addEventListener("click", demote);
            await load();
        } catch (error) {
            const message = ensurePanel().querySelector("#local-role-message");
            message.textContent = `Não foi possível carregar o papel deste Node: ${error.message}`;
        }
    });
})();
