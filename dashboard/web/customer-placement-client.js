(function () {
  "use strict";

  const nativeFetch = window.fetch.bind(window);
  const PLACEMENT_TIMEOUT_MS = 8000;
  const CATALOG_TIMEOUT_MS = 10000;
  let coordinatesPromise = null;
  let placementStatusState = "idle";

  function setPlacementStatus(state, text) {
    placementStatusState = state;
    const node = document.getElementById("runtime-placement-status");
    if (!node) return;
    node.dataset.state = state;
    const target = node.querySelector("strong") || node;
    target.textContent = text;
  }

  function clientError(message, code, status) {
    const error = new Error(message);
    error.code = code;
    error.status = status;
    return error;
  }

  function coordinatesIfAlreadyAllowed() {
    if (coordinatesPromise) return coordinatesPromise;
    coordinatesPromise = Promise.resolve(null);
    if (!navigator.geolocation || !navigator.permissions?.query) return coordinatesPromise;

    coordinatesPromise = navigator.permissions
      .query({name: "geolocation"})
      .then(permission => {
        if (permission.state !== "granted") return null;
        return new Promise(resolve => {
          navigator.geolocation.getCurrentPosition(
            position => resolve({
              latitude: position.coords.latitude,
              longitude: position.coords.longitude,
            }),
            () => resolve(null),
            {maximumAge: 300000, timeout: 2500, enableHighAccuracy: false}
          );
        });
      })
      .catch(() => null);

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

  async function fetchJson(path, options = {}, timeoutMs, timeoutCode, timeoutMessage) {
    const controller = new AbortController();
    const upstreamSignal = options.signal;
    const abortFromUpstream = () => controller.abort();

    if (upstreamSignal) {
      if (upstreamSignal.aborted) controller.abort();
      else upstreamSignal.addEventListener("abort", abortFromUpstream, {once: true});
    }

    const timer = window.setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await nativeFetch(path, {
        ...options,
        headers: {
          Accept: "application/json",
          "X-Capivara-Auth-Area": "customer",
          ...(options.headers || {}),
        },
        credentials: "same-origin",
        cache: options.cache || "no-store",
        signal: controller.signal,
      });

      if (response.status === 401) {
        window.location.href = "/customer-login.html";
        throw clientError("Sessão encerrada.", "authentication_required", 401);
      }

      let data;
      try {
        data = await response.json();
      } catch (_error) {
        throw clientError(
          "O Controller retornou uma resposta inválida.",
          "invalid_json_response",
          502
        );
      }

      if (!response.ok) {
        throw clientError(
          data?.message || data?.error || `Erro HTTP ${response.status}`,
          data?.code || "request_failed",
          response.status
        );
      }

      return data;
    } catch (error) {
      if (error?.name === "AbortError" && !upstreamSignal?.aborted) {
        throw clientError(timeoutMessage, timeoutCode, 504);
      }
      throw error;
    } finally {
      window.clearTimeout(timer);
      upstreamSignal?.removeEventListener?.("abort", abortFromUpstream);
    }
  }

  async function loadRuntimes(game, options = {}) {
    try {
      return await fetchJson(
        `/api/catalog/runtimes?game=${encodeURIComponent(game)}`,
        options,
        CATALOG_TIMEOUT_MS,
        "runtime_catalog_timeout",
        "A consulta de ambientes excedeu o tempo limite. Tente novamente."
      );
    } catch (error) {
      if (error?.code === "runtime_catalog_timeout") {
        setPlacementStatus(
          "error",
          "A consulta de ambientes demorou demais. Tente novamente."
        );
      }
      throw error;
    }
  }

  async function loadRegions(context = {}, options = {}) {
    setPlacementStatus("checking", "Verificando servidores disponíveis...");

    const coords = await coordinatesIfAlreadyAllowed();
    const params = new URLSearchParams();
    const game = String(context.game || "").trim().toLowerCase();
    const contract = String(context.contract || context.contract_id || "").trim();

    if (game) params.set("game", game);
    if (contract) params.set("contract", contract);
    if (coords) {
      params.set("latitude", String(coords.latitude));
      params.set("longitude", String(coords.longitude));
    }

    const suffix = params.toString() ? `?${params}` : "";
    let data;

    try {
      data = await fetchJson(
        `/api/customer/placement/locations${suffix}`,
        options,
        PLACEMENT_TIMEOUT_MS,
        "placement_timeout",
        "A verificação dos servidores excedeu o tempo limite. Tente novamente."
      );
    } catch (error) {
      if (error?.code === "placement_timeout") {
        setPlacementStatus(
          "error",
          "Não foi possível concluir a verificação dos servidores. Tente novamente."
        );
      } else if (error?.code !== "authentication_required") {
        setPlacementStatus("error", "Falha ao verificar servidores disponíveis.");
      }
      throw error;
    }

    const locations = Array.isArray(data?.locations) ? data.locations : [];
    const available = locations.filter(item => item.availability === "available");

    if (!available.length) {
      const message = locations.length
        ? "Nenhum servidor está disponível para este jogo nesta região no momento."
        : "Nenhum servidor elegível foi localizado para este jogo no momento.";
      setPlacementStatus("unavailable", message);
      throw clientError(message, "placement_no_available_agent", 503);
    }

    const regions = available.map(publicRegion);
    setPlacementStatus(
      "available",
      `${regions.length} localização${regions.length === 1 ? "" : "ões"} disponível${regions.length === 1 ? "" : "is"}.`
    );

    return {regions};
  }

  window.CapivaraPlacementClient = Object.freeze({
    loadRuntimes,
    loadRegions,
    status() {
      return placementStatusState;
    },
  });
})();
