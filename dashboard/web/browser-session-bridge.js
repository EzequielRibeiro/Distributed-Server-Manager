(function () {
    "use strict";

    const COMPAT_KEY = "dsm_auth";
    const COMPAT_VALUE = "cookie-session";
    const nativeFetch = window.fetch.bind(window);

    // Compatibility only: legacy page modules still use the presence of
    // dsm_auth as a synchronous "session exists" signal. Never store the
    // username/password-derived Basic credential here again.
    sessionStorage.setItem(COMPAT_KEY, COMPAT_VALUE);
    sessionStorage.removeItem("dsm_customer_auth");

    window.fetch = function (input, init) {
        const options = {...(init || {})};
        const headers = new Headers(options.headers || {});
        const authorization = headers.get("Authorization") || "";

        if (authorization === `Basic ${COMPAT_VALUE}`) {
            headers.delete("Authorization");
        }

        options.headers = headers;
        if (!options.credentials) options.credentials = "same-origin";
        return nativeFetch(input, options);
    };

    async function logout(destination) {
        try {
            await nativeFetch("/api/auth/logout", {
                method: "POST",
                credentials: "same-origin",
                headers: {Accept: "application/json"},
                cache: "no-store"
            });
        } catch (error) {
            console.warn("[Capivara Session] logout request failed", error);
        } finally {
            sessionStorage.removeItem(COMPAT_KEY);
            sessionStorage.removeItem("dsm_customer_auth");
            window.location.replace(destination || "/login.html");
        }
    }

    document.addEventListener("click", function (event) {
        const button = event.target.closest("#btn-logout,#customer-logout,[data-capivara-logout]");
        if (!button) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        logout(button.id === "customer-logout" ? "/customer-login.html" : "/login.html");
    }, true);

    window.CapivaraBrowserSession = Object.freeze({logout});
})();
