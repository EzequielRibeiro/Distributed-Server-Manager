(function () {
    "use strict";

    const AREA_HEADER = "X-Capivara-Auth-Area";
    const customerPage = window.location.pathname.startsWith("/customer");
    const area = customerPage ? "customer" : "controller";
    const nativeFetch = window.fetch.bind(window);

    window.fetch = function (input, init) {
        const options = {...(init || {})};
        const headers = new Headers(options.headers || {});
        if (!headers.has(AREA_HEADER)) headers.set(AREA_HEADER, area);
        options.headers = headers;
        if (!options.credentials) options.credentials = "same-origin";
        return nativeFetch(input, options);
    };

    async function logout(destination, requestedArea) {
        const logoutArea = requestedArea || area;
        const endpoint = logoutArea === "customer"
            ? "/api/customer/auth/logout"
            : "/api/auth/logout";
        try {
            await nativeFetch(endpoint, {
                method: "POST",
                credentials: "same-origin",
                headers: {Accept: "application/json", [AREA_HEADER]: logoutArea},
                cache: "no-store"
            });
        } catch (error) {
            console.warn("[Capivara Session] logout request failed", error);
        } finally {
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