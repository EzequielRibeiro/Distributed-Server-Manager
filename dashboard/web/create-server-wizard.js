(function () {
  "use strict";

  const STATUS_TEXT = {
    checking: "Verificando ambientes...",
    available: "Ambiente disponível",
    unavailable: "Nenhum ambiente disponível",
    creating: "Criando servidor...",
    provisioning: "Provisionando...",
    completed: "Concluído",
    failed: "Falha",
  };

  let placementReady = null;
  let currentState = "checking";

  const auth = () => sessionStorage.getItem("dsm_auth") || "";
  const $ = id => document.getElementById(id);

  function ensureStatusNode() {
    let node = $("runtime-placement-status");
    if (node) return node;

    const panel = $("create-instance-panel");
    const article = panel?.querySelector(".instance-panel");
    if (!article) return null;

    node = document.createElement("div");
    node.id = "runtime-placement-status";
    node.className = "runtime-placement-status";
    node.setAttribute("role", "status");
    node.setAttribute("aria-live", "polite");

    const heading = article.querySelector(".section-heading");
    if (heading?.nextSibling) {
      article.insertBefore(node, heading.nextSibling);
    } else {
      article.append(node);
    }
    return node;
  }

  function setState(state, detail = "") {
    currentState = state;
    const node = ensureStatusNode();
    if (!node) return;
    node.dataset.state = state;
    node.replaceChildren();

    const strong = document.createElement("strong");
    strong.textContent = STATUS_TEXT[state] || state;
    node.append(strong);

    if (detail) {
      const small = document.createElement("small");
      small.textContent = detail;
      node.append(small);
    }
  }

  function setOpeningCtasHidden(hidden) {
    document.querySelectorAll(
      ".server-card.contract .server-actions button"
    ).forEach(button => {
      button.hidden = Boolean(hidden);
    });
  }

  function syncFallbackSummary() {
    const checkbox = $("runtime-region-fallback");
    const summary = $("runtime-summary-region-fallback");
    if (checkbox && summary) {
      summary.textContent = checkbox.checked ? "Sim" : "Não";
    }
  }

  function enforceSubmitState() {
    const submit = $("create-instance-submit");
    if (submit && placementReady === false) {
      submit.disabled = true;
    }
  }

  async function checkReadiness() {
    setState("checking");
    placementReady = null;
    enforceSubmitState();

    const response = await fetch("/api/placement/readiness", {
      headers: {
        Authorization: `Basic ${auth()}`,
        Accept: "application/json",
      },
    });
    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      placementReady = false;
      setState(
        "unavailable",
        "Não foi possível confirmar a disponibilidade dos ambientes neste momento."
      );
      enforceSubmitState();
      return false;
    }

    placementReady = data.placement_ready === true;
    if (placementReady) {
      setState("available");
    } else {
      setState(
        "unavailable",
        "Nenhum ambiente está disponível para provisionamento neste momento."
      );
      enforceSubmitState();
    }
    return placementReady;
  }

  function installRuntimeSelectorWrapper() {
    const selector = window.CapivaraRuntimeSelector;
    if (!selector || typeof selector.open !== "function" || selector.__phase7Wrapped) {
      return false;
    }

    const originalOpen = selector.open.bind(selector);
    selector.open = async function (contract) {
      setOpeningCtasHidden(true);
      placementReady = null;
      setState("checking");

      try {
        const [, ready] = await Promise.all([
          originalOpen(contract),
          checkReadiness(),
        ]);
        syncFallbackSummary();
        if (!ready) enforceSubmitState();
      } catch (error) {
        setOpeningCtasHidden(false);
        setState("failed");
        throw error;
      }
    };
    selector.__phase7Wrapped = true;
    return true;
  }

  const originalFetch = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    const url = typeof input === "string" ? input : input?.url || "";
    const method = String(init?.method || input?.method || "GET").toUpperCase();
    const isCreate = method === "POST" && /\/api\/instance\/create(?:\?|$)/.test(url);

    if (isCreate) setState("creating");

    try {
      const response = await originalFetch(input, init);
      if (isCreate) {
        if (!response.ok) {
          setState("failed");
        } else {
          const data = await response.clone().json().catch(() => ({}));
          const provision = String(
            data?.provision?.status || data?.status || ""
          ).toLowerCase();
          if (["online", "offline", "completed", "complete", "ready"].includes(provision)) {
            setState("completed");
          } else {
            setState("provisioning");
          }
        }
      }
      return response;
    } catch (error) {
      if (isCreate) setState("failed");
      throw error;
    }
  };

  document.addEventListener("change", event => {
    if (event.target?.id === "runtime-region-fallback") {
      syncFallbackSummary();
    }
  }, true);

  document.addEventListener("click", event => {
    if (event.target?.id === "create-instance-close") {
      setOpeningCtasHidden(false);
      placementReady = null;
      return;
    }

    if (event.target?.id === "create-instance-submit") {
      syncFallbackSummary();
      if (placementReady === false) {
        event.preventDefault();
        event.stopImmediatePropagation();
        setState(
          "unavailable",
          "Nenhum ambiente está disponível para provisionamento neste momento."
        );
      }
    }
  }, true);

  const submitObserver = new MutationObserver(enforceSubmitState);

  function boot() {
    installRuntimeSelectorWrapper();
    syncFallbackSummary();
    const submit = $("create-instance-submit");
    if (submit) {
      submitObserver.observe(submit, { attributes: true, attributeFilter: ["disabled"] });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }

  window.CapivaraCreateServerWizard = {
    checkReadiness,
    setState,
    states: { ...STATUS_TEXT },
    get placementReady() { return placementReady; },
    get state() { return currentState; },
  };
})();
