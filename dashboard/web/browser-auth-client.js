(function () {
  "use strict";

  const AREAS = Object.freeze({
    controller: {
      session: "/api/auth/session",
      logout: "/api/auth/logout",
      login: "/login.html",
      roles: new Set(["admin", "controller", "operator"]),
    },
    customer: {
      session: "/api/customer/auth/session",
      logout: "/api/customer/auth/logout",
      login: "/customer-login.html",
      roles: new Set(["customer"]),
    },
  });

  function config(area) {
    const value = AREAS[String(area || "").toLowerCase()];
    if (!value) throw new Error(`Unknown authentication area: ${area}`);
    return value;
  }

  function headersFor(area, headers) {
    const result = new Headers(headers || {});
    result.delete("Authorization");
    result.set("X-Capivara-Auth-Area", area);
    if (!result.has("Accept")) result.set("Accept", "application/json");
    return result;
  }

  async function fetchWithSession(area, input, init) {
    const options = {...(init || {})};
    options.headers = headersFor(area, options.headers);
    options.credentials = "same-origin";
    if (!options.cache) options.cache = "no-store";
    return window.fetch(input, options);
  }

  async function session(area) {
    const cfg = config(area);
    const response = await fetchWithSession(area, cfg.session, {method: "GET"});
    if (!response.ok) return null;
    const identity = await response.json().catch(() => null);
    if (!identity || identity.authenticated !== true) return null;
    if (!cfg.roles.has(String(identity.role || "").toLowerCase())) return null;
    return identity;
  }

  async function requireSession(area, roles) {
    const identity = await session(area);
    const allowed = roles ? new Set(roles.map(role => String(role).toLowerCase())) : null;
    if (!identity || (allowed && !allowed.has(String(identity.role || "").toLowerCase()))) {
      window.location.replace(config(area).login);
      throw new Error("authentication required");
    }
    return identity;
  }

  async function logout(area, destination) {
    const cfg = config(area);
    try {
      await fetchWithSession(area, cfg.logout, {method: "POST"});
    } finally {
      window.location.replace(destination || cfg.login);
    }
  }

  async function json(area, input, init) {
    const response = await fetchWithSession(area, input, init);
    if (response.status === 401) {
      window.location.replace(config(area).login);
      throw new Error("Sessão encerrada");
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || data.error || `HTTP ${response.status}`);
    return data;
  }

  window.CapivaraAuth = Object.freeze({
    fetch: fetchWithSession,
    headers: headersFor,
    json,
    logout,
    require: requireSession,
    session,
  });
})();
