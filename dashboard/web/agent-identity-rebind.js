(function () {
    "use strict";

    const params = new URLSearchParams(location.search);
    const agentId = params.get("agent_id") || params.get("id") || "";
    const el = id => document.getElementById(id);

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

    function text(id, value) {
        const node = el(id);
        if (node) node.textContent = value === null || value === undefined || value === "" ? "—" : String(value);
    }

    function setState(message, error = false) {
        const node = el("agent-identity-rebind-state");
        if (!node) return;
        node.textContent = message;
        node.classList.toggle("error", Boolean(error));
    }

    function render(identity) {
        const current = String(identity?.host_identity || "");
        text("agent-host-identity-current", current);
        text("agent-host-identity-incident", identity?.active_incident ? "CONFLITO ATIVO" : "Sem incidente ativo");
        const expected = el("agent-host-identity-expected");
        if (expected && document.activeElement !== expected) expected.value = current;
        const last = identity?.last_rebind;
        text("agent-host-identity-last-rebind", last ? `${last.at || "—"} · ${last.actor || "—"} · ${last.reason || "—"}` : "Nenhum rebind registrado");
    }

    async function refresh() {
        if (!agentId) return;
        const payload = await request(`/api/admin/agent/identity?agent_id=${encodeURIComponent(agentId)}`);
        render(payload.identity || {});
    }

    async function rebind() {
        const button = el("agent-host-identity-rebind");
        const expected = String(el("agent-host-identity-expected")?.value || "").trim();
        const next = String(el("agent-host-identity-new")?.value || "").trim();
        const reason = String(el("agent-host-identity-reason")?.value || "").trim();
        const confirmation = String(el("agent-host-identity-confirmation")?.value || "").trim();

        if (!expected || !next || !reason) {
            setState("Identidade atual, nova identidade e motivo são obrigatórios.", true);
            return;
        }
        if (confirmation !== agentId) {
            setState("Digite o Agent ID completo para confirmar o rebind.", true);
            return;
        }
        if (!window.confirm(`Revincular ${agentId} para a nova identidade física? Esta operação será auditada.`)) return;

        if (button) {
            button.disabled = true;
            button.textContent = "Revinculando…";
        }
        try {
            const result = await request("/api/admin/agent/identity/rebind", {
                method: "POST",
                body: JSON.stringify({
                    agent_id: agentId,
                    expected_identity: expected,
                    new_identity: next,
                    reason,
                    confirmation
                })
            });
            setState(`Rebind concluído: ${result.old_identity} → ${result.new_identity}. Incidente resolvido: ${result.incident_resolved ? "sim" : "não havia incidente ativo"}.`);
            if (el("agent-host-identity-new")) el("agent-host-identity-new").value = "";
            if (el("agent-host-identity-reason")) el("agent-host-identity-reason").value = "";
            if (el("agent-host-identity-confirmation")) el("agent-host-identity-confirmation").value = "";
            await refresh();
        } catch (error) {
            setState(error.message || String(error), true);
        } finally {
            if (button) {
                button.disabled = false;
                button.textContent = "Revincular identidade física";
            }
        }
    }

    function init() {
        el("agent-host-identity-refresh")?.addEventListener("click", () => refresh().catch(error => setState(error.message || String(error), true)));
        el("agent-host-identity-rebind")?.addEventListener("click", rebind);
        refresh().catch(error => setState(error.message || String(error), true));
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once: true});
    else init();
})();
