(function () {
  "use strict";

  const nativeFetch = window.fetch.bind(window);
  const PLACEMENT_TIMEOUT_MS = 8000;
  let coordinatesPromise = null;
  let placementContext = {};
  let placementAvailable = false;

  function submitButton() {
    return document.getElementById("create-instance-submit");
  }

  function syncCreateAvailability() {
    const button = submitButton();
    if (!button) return;
    button.dataset.placementAvailable = placementAvailable ? "true" : "false";
    if (!placementAvailable) button.disabled = true;
  }

  function setPlacementAvailability(available) {
    placementAvailable = available === true;
    syncCreateAvailability();
  }

  function setPlacementStatus(state, text) {
    const node = document.getElementById("runtime-placement-status");
    if (!node) return;
    node.dataset.state = state;
    const target = node.querySelector("strong") || node;
    target.textContent = text;
  }

  function jsonResponse(status, body, statusText = "") {
    return new Response(JSON.stringify(body), {
      status,
      statusText,
      headers: {"Content-Type": "application/json"},
    });
  }

  function placementUnavailable(message, code, details = {}) {
    setPlacementAvailability(false);
    return jsonResponse(200, {
      regions: [],
      placement_available: false,
      placement_state: "unavailable",
      message,
      code,
      ...details,
    }, "OK");
  }

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
    setPlacementAvailability(false);
    setPlacementStatus("checking", "Verificando servidores disponíveis...");

    const coords = await coordinatesIfAlreadyAllowed();
    const params = new URLSearchParams();
    if (placementContext.game) params.set("game", placementContext.game);
    if (placementContext.contract) params.set("contract", placementContext.contract);
    if (coords) {
      params.set("latitude", String(coords.latitude));
      params.set("longitude", String(coords.longitude));
    }

    const suffix = params.toString() ? `?${params}` : "";
    const controller = new AbortController();
    const upstreamSignal = options?.signal;
    const abortFromUpstream = () => controller.abort();
    if (upstreamSignal) {
      if (upstreamSignal.aborted) controller.abort();
      else upstreamSignal.addEventListener("abort", abortFromUpstream, {once: true});
    }
    const timer = window.setTimeout(() => controller.abort(), PLACEMENT_TIMEOUT_MS);

    let response;
    try {
      response = await nativeFetch(
        `/api/customer/placement/locations${suffix}`,
        {...options, signal: controller.signal}
      );
    } catch (error) {
      if (error?.name === "AbortError") {
        const message = "Não foi possível concluir a verificação dos servidores. Você pode continuar navegando e tentar novamente depois.";
        setPlacementStatus("error", message);
        return placementUnavailable(message, "placement_timeout", {retryable: true});
      }
      const message = "Não foi possível localizar servidores agora. Você pode continuar navegando normalmente.";
      setPlacementStatus("error", message);
      return placementUnavailable(message, "placement_unreachable", {retryable: true});
    } finally {
      window.clearTimeout(timer);
      upstreamSignal?.removeEventListener?.("abort", abortFromUpstream);
    }

    if (!response.ok) {
      const message = "Não foi possível verificar servidores disponíveis. A área do cliente continua disponível.";
      setPlacementStatus("error", message);
      return placementUnavailable(message, "placement_controller_error", {
        retryable: response.status >= 500,
        upstream_status: response.status,
      });
    }

    let data;
    try {
      data = await response.clone().json();
    } catch (_error) {
      const message = "Resposta inválida ao verificar servidores. A navegação continua disponível.";
      setPlacementStatus("error", message);
      return placementUnavailable(message, "placement_invalid_response", {retryable: true});
    }

    const locations = Array.isArray(data.locations) ? data.locations : [];
    const available = locations.filter(item => item.availability === "available");

    if (!available.length) {
      const message = locations.length
        ? "Nenhum servidor está disponível para este jogo nesta região no momento."
        : "Nenhum servidor elegível foi localizado para este jogo no momento.";
      setPlacementStatus("unavailable", message);
      return placementUnavailable(message, "placement_no_available_agent", {
        retryable: true,
        locations_found: locations.length,
      });
    }

    const regions = available.map(publicRegion);
    setPlacementAvailability(true);
    setPlacementStatus(
      "available",
      `${regions.length} localização${regions.length === 1 ? "" : "ões"} disponível${regions.length === 1 ? "" : "is"}.`
    );
    return jsonResponse(response.status, {
      regions,
      placement_available: true,
      placement_state: "available",
    }, response.statusText);
  }

  window.fetch = function (input, options) {
    const url = typeof input === "string" ? input : input?.url;
    if (url === "/api/customer/regions") return placementRegions(options || {});
    return nativeFetch(input, options);
  };

  document.addEventListener("click", event => {
    const button = event.target.closest?.("#create-instance-submit");
    if (!button || placementAvailable) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    setPlacementStatus(
      "unavailable",
      "A criação está indisponível porque nenhum servidor elegível foi localizado. Você pode continuar navegando normalmente."
    );
    syncCreateAvailability();
  }, true);

  document.addEventListener("DOMContentLoaded", () => {
    const button = submitButton();
    if (button && window.MutationObserver) {
      new MutationObserver(() => syncCreateAvailability()).observe(button, {
        attributes: true,
        attributeFilter: ["disabled"],
      });
    }
    syncCreateAvailability();

    const selector = window.CapivaraRuntimeSelector;
    if (!selector || typeof selector.open !== "function") return;
    const originalOpen = selector.open.bind(selector);
    selector.open = function (contract) {
      placementContext = {
        contract: String(contract?.id || contract?.contract_id || "").trim(),
        game: String(contract?.game_id || contract?.game || "").trim().toLowerCase(),
      };
      setPlacementAvailability(false);
      return originalOpen(contract);
    };
  });
})();
