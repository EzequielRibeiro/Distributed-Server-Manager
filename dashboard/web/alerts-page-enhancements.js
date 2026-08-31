(function () {
  "use strict";

  const params = new URLSearchParams(location.search);
  const agentId = String(params.get("agent_id") || "").trim();
  const nativeFetch = window.fetch.bind(window);
  let searchTimer = null;

  function searchValue() {
    return String(document.getElementById("alert-search")?.value || "").trim();
  }

  function enhanceAlertsRequest(input) {
    const raw = typeof input === "string" ? input : input?.url;
    if (!raw) return input;
    const url = new URL(raw, location.href);
    if (url.pathname !== "/api/admin/alerts") return input;
    if (url.searchParams.get("active") !== "false") return input;
    if (agentId) url.searchParams.set("agent_id", agentId);
    const query = searchValue();
    if (query) url.searchParams.set("q", query);
    else url.searchParams.delete("q");
    return url.pathname + url.search;
  }

  window.fetch = function (input, init) {
    return nativeFetch(enhanceAlertsRequest(input), init);
  };

  function alertIdFromCard(card) {
    return String(
      card.querySelector("[data-alert-id]")?.dataset?.alertId
      || card.querySelector("[data-alert-history]")?.dataset?.alertHistory
      || ""
    ).trim();
  }

  function decorateAlertIds() {
    document.querySelectorAll("#observability-alerts .cap-alert-item").forEach(card => {
      if (card.querySelector(":scope > .cap-alert-heading")) return;
      const status = card.querySelector(":scope > strong");
      if (!status) return;
      const id = alertIdFromCard(card);
      if (!id) return;
      const heading = document.createElement("div");
      heading.className = "cap-alert-heading";
      const label = document.createElement("small");
      label.className = "cap-alert-id";
      label.textContent = `ID: ${id}`;
      status.replaceWith(heading);
      heading.append(status, label);
    });
  }

  function refreshAlerts() {
    const button = document.getElementById("observability-refresh");
    if (button) button.click();
  }

  function runSearch() {
    clearTimeout(searchTimer);
    const button = document.getElementById("alert-search-button");
    if (button) {
      button.disabled = true;
      button.textContent = "Pesquisando…";
      setTimeout(() => {
        button.disabled = false;
        button.textContent = "Pesquisar";
      }, 500);
    }
    refreshAlerts();
  }

  function configureAgentScope() {
    const box = document.getElementById("alert-agent-scope");
    const value = document.getElementById("alert-agent-scope-value");
    const clear = document.getElementById("alert-agent-scope-clear");
    if (!agentId) {
      if (box) box.hidden = true;
      return;
    }
    if (box) box.hidden = false;
    if (value) value.textContent = agentId;
    clear?.addEventListener("click", event => {
      event.preventDefault();
      location.href = "alerts.html";
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    configureAgentScope();

    const input = document.getElementById("alert-search");
    const button = document.getElementById("alert-search-button");

    button?.addEventListener("click", runSearch);
    input?.addEventListener("keydown", event => {
      if (event.key === "Enter") {
        event.preventDefault();
        runSearch();
      }
    });
    input?.addEventListener("search", runSearch);
    input?.addEventListener("input", () => {
      clearTimeout(searchTimer);
      if (!searchValue()) searchTimer = setTimeout(refreshAlerts, 150);
    });

    const list = document.getElementById("observability-alerts");
    if (list) {
      new MutationObserver(decorateAlertIds).observe(list, {childList: true, subtree: true});
      decorateAlertIds();
    }
  });
})();
