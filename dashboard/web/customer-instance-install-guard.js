(function(){
  "use strict";

  const blockedViews = new Set([
    "logs",
    "events",
    "config",
    "files",
    "content",
    "backups",
    "danger",
  ]);

  function overviewButton() {
    return document.querySelector('[data-view="overview"]');
  }

  function showOverview() {
    const overview = overviewButton();
    if (!overview) return;

    document.querySelectorAll("[data-view]").forEach(button => {
      button.classList.toggle("active", button === overview);
    });

    document.querySelectorAll(".view").forEach(view => {
      view.classList.toggle("active", view.id === "view-overview");
    });
  }

  function installationFailed() {
    const provision = document.getElementById("provision-progress");
    return Boolean(provision && provision.classList.contains("provision-failed"));
  }

  function syncTabs() {
    const blocked = installationFailed();
    let activeViewWasBlocked = false;

    document.querySelectorAll("[data-view]").forEach(button => {
      const view = String(button.dataset.view || "");
      if (!blockedViews.has(view)) return;

      if (blocked && button.classList.contains("active")) {
        activeViewWasBlocked = true;
      }

      button.disabled = blocked;
      button.setAttribute("aria-disabled", blocked ? "true" : "false");
      button.title = blocked
        ? "Indisponível enquanto houver erro na instalação da instância."
        : "";
    });

    if (blocked && activeViewWasBlocked) {
      showOverview();
    }
  }

  const provision = document.getElementById("provision-progress");
  if (!provision) return;

  const observer = new MutationObserver(syncTabs);
  observer.observe(provision, {
    attributes: true,
    attributeFilter: ["class", "hidden"],
    childList: true,
    subtree: true,
  });

  syncTabs();
})();
