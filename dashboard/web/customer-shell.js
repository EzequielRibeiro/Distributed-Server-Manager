(function () {
  "use strict";

  function load(src) {
    const script = document.createElement("script");
    script.src = src;
    script.async = false;
    document.head.appendChild(script);
  }

  async function bootstrap() {
    let response;
    try {
      response = await fetch("/api/customer/auth/session", {
        headers: {Accept: "application/json"},
        credentials: "same-origin",
        cache: "no-store",
      });
    } catch (error) {
      location.replace("/customer-login.html");
      return;
    }

    const session = await response.json().catch(() => ({}));
    if (!response.ok || session.authenticated !== true || session.role !== "customer") {
      location.replace("/customer-login.html");
      return;
    }

    // Customer pages use only the dedicated Customer cookie session.
    // The Controller compatibility bridge is intentionally not loaded here.
    load("/customer-navigation.js?v=3");
    load("/customer-core.js?v=3");
  }

  bootstrap();
})();
