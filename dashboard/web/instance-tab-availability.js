(function () {
  "use strict";

  const OPERATIONAL_VIEWS = new Set([
    "logs",
    "events",
    "config",
    "files",
    "content",
    "backups",
    "danger",
  ]);

  const LOCKED_STATUSES = new Set([
    "queued",
    "provisioning",
    "pending_steam_auth",
    "pending_install",
    "installing",
    "failed",
    "error",
  ]);

  function normalize(value) {
    return String(value || "").trim().toLowerCase();
  }

  function installationCompleted(provision) {
    return (
      normalize(provision?.stage) === "completed" &&
      Number(provision?.progress) >= 100
    );
  }

  function blocksOperationalViews(provision) {
    if (installationCompleted(provision)) {
      return false;
    }

    const status = normalize(provision?.status);

    return (
      LOCKED_STATUSES.has(status) ||
      status.includes("fail") ||
      status.includes("error")
    );
  }

  function lockReason(provision) {
    const status = normalize(provision?.status);

    if (status.includes("fail") || status.includes("error")) {
      return "Indisponível porque a instalação da instância falhou.";
    }

    if (status === "pending_steam_auth") {
      return "Disponível após a autenticação Steam e a conclusão da instalação.";
    }

    return "Disponível após a conclusão da instalação.";
  }

  function activateOverview() {
    const overviewButton = document.querySelector('[data-view="overview"]');

    if (!overviewButton) {
      return;
    }

    document.querySelectorAll("[data-view]").forEach(button => {
      button.classList.toggle("active", button === overviewButton);
    });

    document.querySelectorAll(".view").forEach(view => {
      view.classList.toggle("active", view.id === "view-overview");
    });
  }

  function setOperationalViewsLocked(locked, reason) {
    const buttons = Array.from(document.querySelectorAll("[data-view]"))
      .filter(button => OPERATIONAL_VIEWS.has(button.dataset.view));

    buttons.forEach(button => {
      button.disabled = locked;
      button.setAttribute("aria-disabled", String(locked));

      if (locked) {
        button.title = reason;
      } else {
        button.removeAttribute("title");
      }
    });

    document.body?.classList.toggle("instance-operations-locked", locked);

    if (
      locked &&
      document.querySelector('[data-view].active:not([data-view="overview"])')
    ) {
      activateOverview();
    }
  }

  function applyProvisionState(provision) {
    const locked = blocksOperationalViews(provision || {});
    setOperationalViewsLocked(locked, lockReason(provision || {}));
  }

  /*
   * Fail closed until the first authoritative /api/runtime response arrives.
   * This avoids a short interval where an operational tab could be opened
   * before the provision state is known.
   */
  function lockUntilRuntimeIsKnown() {
    setOperationalViewsLocked(
      true,
      "Verificando o estado da instalação da instância…"
    );
  }

  const nativeFetch = window.fetch.bind(window);

  window.fetch = async function (...args) {
    const response = await nativeFetch(...args);

    try {
      const input = args[0];
      const rawUrl = input instanceof Request ? input.url : String(input || "");
      const url = new URL(rawUrl, window.location.href);

      if (url.pathname === "/api/runtime" && response.ok) {
        response
          .clone()
          .json()
          .then(data => applyProvisionState(data?.provision || {}))
          .catch(() => {});
      }
    } catch (_) {
      /* The original request must never fail because of UI availability. */
    }

    return response;
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", lockUntilRuntimeIsKnown, {
      once: true,
    });
  } else {
    lockUntilRuntimeIsKnown();
  }
})();
