"use strict";
(() => {
    const el = id => document.getElementById(id);
    const selectedMethod = () => document.querySelector('input[name="agent-method"]:checked')?.value || "github";

    function syncMethodNote() {
        const note = el("agent-manual-connectivity-note");
        if (note) note.hidden = ["ssh", "winrm"].includes(selectedMethod());
    }

    async function remoteCheck(event) {
        event?.preventDefault?.();

        const button = el("test-agent-connection");
        const out = el("agent-connection-result");
        const controllerUrl = el("agent-controller-url")?.value.trim() || "";
        if (!controllerUrl) {
            const message = "Informe a URL do Controller alcançável pelo Agent antes de testar a conexão.";
            out.textContent = `✕ ${message}`;
            el("agent-controller-url")?.focus();
            el("agent-controller-url")?.reportValidity();
            return;
        }

        button.disabled = true;
        out.textContent = "Testando SSH, privilégios e acesso HTTPS/TLS do Agent ao Controller...";
        const platform = document.body.dataset.agentPlatform || "linux";
        const payload = {
            platform,
            ssh_host: el("agent-ssh-host")?.value || "",
            ssh_user: el("agent-ssh-user")?.value || "",
            ssh_port: el("agent-ssh-port")?.value || 22,
            password_file: el("agent-password-file")?.value || undefined,
            controller_url: controllerUrl,
        };
        try {
            const r = await request("/agents/installations/test-connection", {
                method: "POST",
                body: JSON.stringify(payload),
            });
            out.textContent = `✓ SSH OK · ${r.platform} · ${r.architecture || "arquitetura desconhecida"}\n✓ Controller HTTPS/TLS OK · ${r.controller_url}`;
        } catch (e) {
            out.textContent = `✕ ${e.message}`;
        } finally {
            button.disabled = false;
        }
    }

    function ownConnectionButton() {
        const oldButton = el("test-agent-connection");
        if (!oldButton || oldButton.dataset.controllerProbeOwned === "true") return;

        const button = oldButton.cloneNode(true);
        button.dataset.controllerProbeOwned = "true";
        button.textContent = "Testar OpenSSH + Controller";
        oldButton.replaceWith(button);
        button.addEventListener("click", remoteCheck);
    }

    document.addEventListener("change", event => {
        if (event.target.matches?.('input[name="agent-method"]')) syncMethodNote();
    });

    window.addEventListener("load", () => {
        syncMethodNote();
        ownConnectionButton();
    });
})();
