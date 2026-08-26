(function () {
  "use strict";

  const nativeFetch = window.fetch.bind(window);
  let coordinatesPromise = null;
  let placementContext = {};

  function coordinatesIfAlreadyAllowed() {
    if (coordinatesPromise) return coordinatesPromise;
    coordinatesPromise = Promise.resolve(null);
    if (!navigator.geolocation || !navigator.permissions?.query) return coordinatesPromise;
    coordinatesPromise = navigator.permissions.query({name: "geolocation"}).then(permission => {
      if (permission.state !== "granted") return null;
      return new Promise(resolve => {
        navigator.geolocation.getCurrentPosition(
          position => resolve({latitude: position.coords.latitude, longitude: position.coords.longitude}),
          () => resolve(null),
          {maximumAge: 300000, timeout: 2500, enableHighAccuracy: false}
        );
      });
    }).catch(() => null);
    return coordinatesPromise;
  }

  function recommendationLabel(item) {
    if (item.recommended) return "★ Servidor recomendado";
    if (item.recommendation === "higher_latency") return "Latência maior";
    if (item.recommendation === "unavailable") return "Indisponível";
    return "Boa opção";
  }

  function publicRegion(item) {
    const latency = item.latency?.value_ms;
    const latencyText = Number.isFinite(latency) ? ` · ~${latency} ms` : "";
    return {
      id: item.region_id,
      name: `${item.name}${latencyText} · ${recommendationLabel(item)}`,
      country_code: item.country_code || "",
      availability: item.availability,
      recommended: item.recommended === true,
      latency_ms: Number.isFinite(latency) ? latency : null,
      latency_kind: "estimated",
    };
  }

  async function placementRegions(options) {
    const coords = await coordinatesIfAlreadyAllowed();
    const params = new URLSearchParams();
    if (placementContext.game) params.set("game", placementContext.game);
    if (placementContext.contract) params.set("contract", placementContext.contract);
    if (coords) {
      params.set("latitude", String(coords.latitude));
      params.set("longitude", String(coords.longitude));
    }
    const suffix = params.toString() ? `?${params}` : "";
    const response = await nativeFetch(`/api/customer/placement/locations${suffix}`, options);
    if (!response.ok) return response;
    const data = await response.clone().json();
    const regions = (Array.isArray(data.locations) ? data.locations : []).filter(item => item.availability === "available").map(publicRegion);
    return new Response(JSON.stringify({regions}), {status: response.status, statusText: response.statusText, headers: {"Content-Type": "application/json"}});
  }

  window.fetch = function (input, options) {
    const url = typeof input === "string" ? input : input?.url;
    if (url === "/api/customer/regions") return placementRegions(options || {});
    return nativeFetch(input, options);
  };

  document.addEventListener("DOMContentLoaded", () => {
    const selector = window.CapivaraRuntimeSelector;
    if (!selector || typeof selector.open !== "function") return;
    const originalOpen = selector.open.bind(selector);
    selector.open = function (contract) {
      placementContext = {
        contract: String(contract?.id || contract?.contract_id || "").trim(),
        game: String(contract?.game_id || contract?.game || "").trim().toLowerCase(),
      };
      return originalOpen(contract);
    };
  });
})();
