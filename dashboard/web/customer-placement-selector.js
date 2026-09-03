(function () {
  "use strict";

  let openingPromise = null;

  function placementClient() {
    const client = window.CapivaraPlacementClient;
    if (!client || typeof client.loadRegions !== "function") {
      throw new Error("O cliente de placement não está disponível.");
    }
    return client;
  }

  function contractContext(contract) {
    return {
      contract: String(contract?.id || contract?.contract_id || "").trim(),
      game: String(contract?.game_id || contract?.game || "").trim().toLowerCase(),
    };
  }

  document.addEventListener("DOMContentLoaded", () => {
    const selector = window.CapivaraRuntimeSelector;
    if (!selector || typeof selector.open !== "function") return;

    const originalOpen = selector.open.bind(selector);

    selector.open = function (contract) {
      if (openingPromise) {
        return openingPromise;
      }

      const context = contractContext(contract);

      openingPromise = Promise.resolve()
        .then(async () => {
          const client = placementClient();

          /*
           * Transitional preflight: availability is checked through the
           * explicit placement client before the legacy selector opens.
           * This removes the global fetch interception immediately while the
           * canonical selector is migrated to consume the client directly.
           */
          await client.loadRegions(context);
          return originalOpen(contract);
        })
        .finally(() => {
          openingPromise = null;
        });

      return openingPromise;
    };
  });
})();
