"use strict";

(() => {
    let lastAgent = null;

    function text(id, value) {
        const element = document.getElementById(id);
        if (element) element.textContent = value || "—";
    }

    async function loadUpdateStatus() {
        if (!selectedAgent || selectedAgent === lastAgent && document.getElementById("agent-update-status")?.dataset.loaded === "true") return;
        lastAgent = selectedAgent;
        const status = await request(`/agents/updates/status?agent_id=${encodeURIComponent(selectedAgent)}`);
        text("agent-installed-version", status.installed_version);
        text("agent-available-version", status.available_version);
        text("agent-update-status", status.update_status);
        text("agent-last-update", status.last_update);
        document.getElementById("agent-update-status").dataset.loaded = "true";
        document.getElementById("agent-update-channel").value = status.update_channel || "stable";
        document.getElementById("agent-rollout-channel").value = status.update_channel || "stable";
        document.getElementById("agent-rollout-agents").value = selectedAgent;
    }

    async function saveChannel(event) {
        event.preventDefault();
        if (!selectedAgent) return;
        try {
            const result = await request("/agents/updates/channel", {
                method: "POST",
                body: JSON.stringify({
                    agent_id: selectedAgent,
                    update_channel: document.getElementById("agent-update-channel").value
                })
            });
            document.getElementById("agent-update-channel").value = result.update_channel;
            errorMessage();
        } catch (error) {
            errorMessage(error.message);
        }
    }

    async function createRollout(event) {
        event.preventDefault();
        const ids = document.getElementById("agent-rollout-agents").value
            .split(/[\s,;]+/)
            .map(value => value.trim())
            .filter(Boolean);
        try {
            const rollout = await request("/agents/updates/rollouts", {
                method: "POST",
                body: JSON.stringify({
                    agent_ids: ids,
                    desired_version: document.getElementById("agent-rollout-version").value.trim(),
                    update_channel: document.getElementById("agent-rollout-channel").value,
                    batch_size: Number(document.getElementById("agent-rollout-batch-size").value)
                })
            });
            errorMessage();
            document.getElementById("agent-available-version").textContent = rollout.desired_version;
            document.getElementById("agent-update-status").textContent = "planned";
            document.getElementById("agent-update-status").dataset.loaded = "false";
            await loadUpdateStatus();
        } catch (error) {
            errorMessage(error.message);
        }
    }

    function watchSelection() {
        const title = document.getElementById("agent-detail-title");
        if (!title) return;
        new MutationObserver(() => {
            if (selectedAgent) {
                document.getElementById("agent-update-status").dataset.loaded = "false";
                loadUpdateStatus().catch(error => errorMessage(error.message));
            }
        }).observe(title, {childList: true, characterData: true, subtree: true});
    }

    window.addEventListener("load", () => {
        document.getElementById("agent-update-channel-form")?.addEventListener("submit", saveChannel);
        document.getElementById("agent-rollout-form")?.addEventListener("submit", createRollout);
        watchSelection();
    });
})();
