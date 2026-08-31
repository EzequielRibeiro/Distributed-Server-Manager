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

  function labelAlertHeading(card) {
    let heading = card.querySelector(":scope > .cap-alert-heading");
    const status = heading?.querySelector(":scope > strong") || card.querySelector(":scope > strong");
    if (!status) return;

    if (!heading) {
      heading = document.createElement("div");
      heading.className = "cap-alert-heading";
      status.replaceWith(heading);
      heading.append(status);
    }

    const id = alertIdFromCard(card);
    if (!id) return;
    let label = heading.querySelector(":scope > .cap-alert-id");
    if (!label) {
      label = document.createElement("small");
      label.className = "cap-alert-id";
      heading.append(label);
    }
    const desired = `ID do alerta: ${id}`;
    if (label.textContent !== desired) label.textContent = desired;
  }

  function convertViewAgentToButton(main) {
    const controls = main?.querySelector(":scope > .cap-alert-controls");
    if (!controls) return null;

    const existingButton = controls.querySelector("button[data-agent-href]");
    if (existingButton) return existingButton;

    const link = controls.querySelector('a[href*="agent-details.html?agent_id="]');
    if (!link) return null;

    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Ver Agent";
    button.className = "cap-alert-control-link";
    button.dataset.agentHref = link.getAttribute("href") || "";
    link.replaceWith(button);
    return button;
  }

  function labelAlertScope(card) {
    const main = card.querySelector(":scope > .cap-alert-item-main");
    const scope = main?.querySelector(":scope > small");
    if (!scope) return;

    const viewAgent = convertViewAgentToButton(main);
    if (scope.dataset.capIdentifiersLabeled === "1") return;

    const original = String(scope.textContent || "").trim();
    if (viewAgent) {
      let currentAgentId = "";
      try {
        currentAgentId = new URL(viewAgent.dataset.agentHref || "", location.href).searchParams.get("agent_id") || "";
      } catch (_) {
        currentAgentId = "";
      }
      const parts = original.split(" · ").map(value => value.trim()).filter(Boolean);
      const instanceId = parts.length > 1 ? parts[1] : "";
      const desired = currentAgentId
        ? `ID do Agent: ${currentAgentId}${instanceId ? ` · ID da instância: ${instanceId}` : ""}`
        : `Escopo: ${original}`;
      if (scope.textContent !== desired) scope.textContent = desired;
    } else if (original) {
      const desired = `Escopo: ${original}`;
      if (scope.textContent !== desired) scope.textContent = desired;
    }
    scope.dataset.capIdentifiersLabeled = "1";
  }

  function decorateAlertCards() {
    document.querySelectorAll("#observability-alerts .cap-alert-item").forEach(card => {
      labelAlertHeading(card);
      labelAlertScope(card);
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

  document.addEventListener("click", event => {
    const button = event.target.closest("button[data-agent-href]");
    if (!button) return;
    const href = String(button.dataset.agentHref || "").trim();
    if (href) location.href = href;
  });

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
      new MutationObserver(decorateAlertCards).observe(list, {childList: true, subtree: true});
      decorateAlertCards();
    }
  });
})();
