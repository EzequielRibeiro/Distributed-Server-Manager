(function () {
    "use strict";

    const COMPAT_KEY = "dsm_auth";
    const COMPAT_VALUE = "cookie-session";
    const AREA_HEADER = "X-Capivara-Auth-Area";
    const customerPage = window.location.pathname.startsWith("/customer");
    const area = customerPage ? "customer" : "controller";
    const nativeFetch = window.fetch.bind(window);

    // Only the Controller keeps the temporary legacy sentinel. Customer pages
    // use the dedicated Customer cookie and must never inherit Admin auth state.
    if (area === "controller") {
        sessionStorage.setItem(COMPAT_KEY, COMPAT_VALUE);
    } else {
        sessionStorage.removeItem(COMPAT_KEY);
    }
    sessionStorage.removeItem("dsm_customer_auth");

    window.fetch = function (input, init) {
        const options = {...(init || {})};
        const headers = new Headers(options.headers || {});
        const authorization = headers.get("Authorization") || "";

        if (authorization === `Basic ${COMPAT_VALUE}`) {
            headers.delete("Authorization");
        }

        // The header only selects which already-valid HttpOnly cookie is
        // evaluated when Controller and Customer sessions coexist.
        if (!headers.has(AREA_HEADER)) {
            headers.set(AREA_HEADER, area);
        }

        options.headers = headers;
        if (!options.credentials) options.credentials = "same-origin";
        return nativeFetch(input, options);
    };

    async function logout(destination, requestedArea) {
        const logoutArea = requestedArea || area;
        const endpoint =
            logoutArea === "customer"
                ? "/api/customer/auth/logout"
                : "/api/auth/logout";

        try {
            await nativeFetch(endpoint, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    Accept: "application/json",
                    [AREA_HEADER]: logoutArea
                },
                cache: "no-store"
            });
        } catch (error) {
            console.warn("[Capivara Session] logout request failed", error);
        } finally {
            if (logoutArea === "controller") sessionStorage.removeItem(COMPAT_KEY);
            sessionStorage.removeItem("dsm_customer_auth");
            window.location.replace(
                destination ||
                (logoutArea === "customer" ? "/customer-login.html" : "/login.html")
            );
        }
    }

    document.addEventListener("click", function (event) {
        const button = event.target.closest(
            "#btn-logout,#customer-logout,#customer-team-logout,#logout,[data-capivara-logout]"
        );
        if (!button) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        const logoutArea = customerPage || button.id.startsWith("customer-")
            ? "customer"
            : "controller";
        logout(
            logoutArea === "customer" ? "/customer-login.html" : "/login.html",
            logoutArea
        );
    }, true);

    window.CapivaraBrowserSession = Object.freeze({logout, area});
})();