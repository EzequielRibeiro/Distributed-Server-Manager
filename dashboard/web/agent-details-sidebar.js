(function () {
    "use strict";

    const AREA_HEADER = {"X-Capivara-Auth-Area": "controller"};

    async function ensureSidebar() {
        const host = document.getElementById("sidebar-component");
        if (!host || host.children.length) return;

        const response = await fetch("/components/sidebar-v3.html", {
            headers: AREA_HEADER,
            credentials: "same-origin",
            cache: "no-store"
        });

        if (response.status === 401) {
            location.replace("login.html");
            return;
        }
        if (!response.ok) {
            throw new Error(`sidebar HTTP ${response.status}`);
        }

        host.innerHTML = await response.text();
        host.querySelectorAll("nav a").forEach(link => {
            link.classList.toggle("active", link.getAttribute("href") === "agents.html");
        });

        const logout = host.querySelector("#btn-logout");
        if (logout) {
            logout.addEventListener("click", async event => {
                event.preventDefault();
                try {
                    await fetch("/api/auth/logout", {
                        method: "POST",
                        headers: AREA_HEADER,
                        credentials: "same-origin",
                        cache: "no-store"
                    });
                } finally {
                    location.replace("login.html");
                }
            });
        }
    }

    function start() {
        ensureSidebar().catch(error => {
            const host = document.getElementById("sidebar-component");
            if (host && !host.children.length) {
                host.innerHTML = `<div class="cap-sidebar-error">Menu indisponível: ${String(error.message || error)}</div>`;
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start, {once: true});
    } else {
        start();
    }
})();
