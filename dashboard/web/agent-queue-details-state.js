"use strict";

(() => {
    const params = new URLSearchParams(window.location.search);
    const agentId = params.get("agent_id") || "unknown";
    const storageKey = `capivara.agent.queue-details-open.${encodeURIComponent(agentId)}`;

    function readPreference() {
        try {
            return window.localStorage.getItem(storageKey);
        } catch (_error) {
            return null;
        }
    }

    function writePreference(open) {
        try {
            window.localStorage.setItem(storageKey, open ? "1" : "0");
        } catch (_error) {
            // Browsers may disable storage. The queue view must remain usable.
        }
    }

    function bindQueueDetails(root = document) {
        root.querySelectorAll(".cap-agent-queue-summary > details").forEach(details => {
            if (details.dataset.queueStateBound === "1") return;
            details.dataset.queueStateBound = "1";

            const preference = readPreference();
            if (preference === "1") details.open = true;
            if (preference === "0") details.open = false;

            details.addEventListener("toggle", () => writePreference(details.open));
        });
    }

    const container = document.getElementById("agent-view-content");
    if (container) {
        bindQueueDetails(container);
        const observer = new MutationObserver(() => bindQueueDetails(container));
        observer.observe(container, {childList: true, subtree: true});
    }
})();
