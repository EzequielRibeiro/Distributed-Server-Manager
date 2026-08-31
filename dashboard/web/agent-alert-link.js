(function () {
  "use strict";

  const params = new URLSearchParams(location.search);
  const agentId = String(params.get("agent_id") || params.get("id") || "").trim();

  document.addEventListener("DOMContentLoaded", () => {
    const link = document.getElementById("agent-alerts-link");
    if (!link) return;
    link.href = agentId
      ? `alerts.html?agent_id=${encodeURIComponent(agentId)}`
      : "alerts.html";
  });
})();
