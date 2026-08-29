(function () {
    "use strict";

    const AREA_HEADER = {"X-Capivara-Auth-Area": "controller"};

    function bindMobileSidebar(host) {
        const toggle = document.getElementById("agent-detail-menu-toggle");
        if (!host || !toggle) return;

        const isMobile = () => window.innerWidth <= 760;
        const setOpen = open => {
            const active = Boolean(open) && isMobile();
            document.body.classList.toggle("sidebar-open", active);
            toggle.setAttribute("aria-expanded", active ? "true" : "false");
            toggle.setAttribute("aria-label", active ? "Fechar menu" : "Abrir menu");
        };

        host.querySelector(".cap-sidebar-close")?.addEventListener("click", () => setOpen(false));
        host.querySelectorAll("a").forEach(link => link.addEventListener("click", () => setOpen(false)));

        document.addEventListener("pointerdown", event => {
            if (!isMobile() || !document.body.classList.contains("sidebar-open")) return;
            if (host.contains(event.target) || toggle.contains(event.target)) return;
            setOpen(false);
        });

        document.addEventListener("keydown", event => {
            if (event.key === "Escape") setOpen(false);
        });

        let startX = null;
        let startY = null;
        host.addEventListener("touchstart", event => {
            const touch = event.changedTouches?.[0];
            if (!touch) return;
            startX = touch.clientX;
            startY = touch.clientY;
        }, {passive: true});
        host.addEventListener("touchend", event => {
            if (startX === null || startY === null) return;
            const touch = event.changedTouches?.[0];
            if (!touch) return;
            const dx = touch.clientX - startX;
            const dy = touch.clientY - startY;
            startX = null;
            startY = null;
            if (isMobile() && dx < -60 && Math.abs(dx) > Math.abs(dy) * 1.2) setOpen(false);
        }, {passive: true});

        window.addEventListener("resize", () => {
            if (!isMobile()) setOpen(false);
        });
    }

    async function ensureSidebar() {
        const host = document.getElementById("sidebar-component");
        if (!host) return;

        if (!host.children.length) {
            const response = await fetch("/components/sidebar-v3.html", {
                headers: AREA_HEADER,
                credentials: "same-origin",
                cache: "no-store"
            });

            if (response.status === 401) {
                location.replace("login.html");
                return;
            }
            if (!response.ok) throw new Error(`sidebar HTTP ${response.status}`);

            host.innerHTML = await response.text();
        }

        host.querySelectorAll("nav a").forEach(link => {
            link.classList.toggle("active", link.getAttribute("href") === "agents.html");
        });
        bindMobileSidebar(host);

        const logout = host.querySelector("#btn-logout");
        if (logout && !logout.dataset.agentDetailsBound) {
            logout.dataset.agentDetailsBound = "1";
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
