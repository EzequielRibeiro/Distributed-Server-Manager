(function () {
    "use strict";

    const MOBILE_MAX = 760;
    const BODY_OPEN = "sidebar-open";
    const BODY_COLLAPSED = "cap-sidebar-collapsed";

    function mobile() {
        return window.innerWidth <= MOBILE_MAX;
    }

    function sidebarHost() {
        return document.getElementById("sidebar-component");
    }

    const TOGGLE_SELECTOR = [
        "#home-menu-toggle",
        "#agents-menu-toggle",
        "#add-agent-menu-toggle",
        "#agent-detail-menu-toggle",
        "#agent-context-menu-toggle",
        "#catalog-menu-toggle",
        "#admin-menu-toggle",
        "#profiles-menu-toggle",
        "#infra-menu-toggle",
        "#observability-menu-toggle",
        "#operations-menu-toggle",
        "#servers-menu-toggle",
        "#system-menu-toggle",
        "[id$='-menu-toggle']",
        ".cap-home-title > button:first-child"
    ].join(",");

    function menuToggle() {
        return document.querySelector(TOGGLE_SELECTOR);
    }

    function updateToggle(open) {
        const toggle = menuToggle();
        if (!toggle) return;

        toggle.setAttribute(
            "aria-expanded",
            mobile() && open ? "true" : "false"
        );

        toggle.setAttribute(
            "aria-label",
            mobile() && open
                ? "Fechar menu"
                : mobile()
                    ? "Abrir menu"
                    : "Abrir ou recolher menu"
        );
    }

    let normalizing = false;

    function normalizeMobileClasses() {
        if (!mobile() || normalizing) return;

        normalizing = true;
        document.body.classList.remove("cap-sidebar-open");
        document.body.classList.remove(BODY_COLLAPSED);
        normalizing = false;
    }

    function setMobileOpen(open) {
        const active = mobile() && Boolean(open);

        if (mobile()) {
            normalizeMobileClasses();
        }

        document.body.classList.toggle(BODY_OPEN, active);
        updateToggle(active);
    }

    function mobileOpen() {
        if (!mobile()) return false;

        return document.body.classList.contains(BODY_OPEN);
    }

    function toggleDesktop() {
        const collapsed =
            !document.body.classList.contains(BODY_COLLAPSED);

        document.body.classList.toggle(BODY_COLLAPSED, collapsed);

        localStorage.setItem(
            "cap_sidebar_collapsed",
            collapsed ? "1" : "0"
        );

        updateToggle(false);
    }

    function toggleMenu() {
        if (mobile()) {
            normalizeMobileClasses();
            setMobileOpen(!mobileOpen());
            return;
        }

        toggleDesktop();
    }

    /*
     * Captura o click antes dos listeners antigos de cada página.
     * Isso permite migrar o Dashboard progressivamente sem haver
     * dois toggles concorrendo.
     */
    document.addEventListener(
        "click",
        function (event) {
            const toggle = event.target.closest(TOGGLE_SELECTOR);

            if (toggle) {
                event.preventDefault();
                event.stopImmediatePropagation();
                toggleMenu();
                return;
            }

            const close = event.target.closest(".cap-sidebar-close");
            if (close) {
                event.preventDefault();
                event.stopImmediatePropagation();
                setMobileOpen(false);
                return;
            }

            const host = sidebarHost();

            if (
                mobile() &&
                document.body.classList.contains(BODY_OPEN) &&
                host &&
                !host.contains(event.target)
            ) {
                setMobileOpen(false);
                return;
            }

            if (
                mobile() &&
                event.target.closest("#sidebar-component a")
            ) {
                setMobileOpen(false);
            }
        },
        true
    );

    /*
     * pointerdown resolve especificamente o backdrop:
     * o usuário não precisa esperar o evento click.
     */
    document.addEventListener(
        "pointerdown",
        function (event) {
            if (
                !mobile() ||
                !document.body.classList.contains(BODY_OPEN)
            ) {
                return;
            }

            const host = sidebarHost();
            const toggle = menuToggle();

            if (
                host &&
                !host.contains(event.target) &&
                !(toggle && toggle.contains(event.target))
            ) {
                setMobileOpen(false);
            }
        },
        true
    );

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
            setMobileOpen(false);
        }
    });

    let touchStartX = null;
    let touchStartY = null;
    let touchStartedInSidebar = false;

    document.addEventListener(
        "touchstart",
        function (event) {
            const touch = event.changedTouches?.[0];
            if (!touch) return;

            const host = sidebarHost();

            touchStartedInSidebar =
                Boolean(host && host.contains(event.target));

            if (!touchStartedInSidebar) return;

            touchStartX = touch.clientX;
            touchStartY = touch.clientY;
        },
        { passive: true, capture: true }
    );

    document.addEventListener(
        "touchend",
        function (event) {
            if (
                !touchStartedInSidebar ||
                touchStartX === null ||
                touchStartY === null
            ) {
                return;
            }

            const touch = event.changedTouches?.[0];
            if (!touch) return;

            const dx = touch.clientX - touchStartX;
            const dy = touch.clientY - touchStartY;

            touchStartX = null;
            touchStartY = null;
            touchStartedInSidebar = false;

            if (
                mobile() &&
                dx < -60 &&
                Math.abs(dx) > Math.abs(dy) * 1.2
            ) {
                setMobileOpen(false);
            }
        },
        { passive: true, capture: true }
    );

    window.addEventListener("resize", function () {
        if (!mobile()) {
            document.body.classList.remove(BODY_OPEN);
            document.body.classList.remove("cap-sidebar-open");

            const saved =
                localStorage.getItem("cap_sidebar_collapsed") === "1";

            document.body.classList.toggle(
                BODY_COLLAPSED,
                saved
            );
        } else {
            document.body.classList.remove(BODY_COLLAPSED);
        }

        updateToggle(
            document.body.classList.contains(BODY_OPEN)
        );
    });

    document.addEventListener("DOMContentLoaded", function () {
        if (mobile()) {
            setMobileOpen(false);

            /*
             * Alguns scripts antigos também executam no DOMContentLoaded.
             * Normaliza novamente depois que toda a fila atual terminar.
             */
            window.setTimeout(function () {
                setMobileOpen(false);
            }, 0);
        } else {
            const saved =
                localStorage.getItem("cap_sidebar_collapsed") === "1";

            document.body.classList.toggle(
                BODY_COLLAPSED,
                saved
            );
        }

        updateToggle(false);
    });

    /*
     * Impede scripts legados de restaurarem cap-sidebar-collapsed
     * ou cap-sidebar-open no mobile após a inicialização.
     */
    const bodyClassObserver = new MutationObserver(function () {
        if (!mobile() || normalizing) return;

        if (
            document.body.classList.contains(BODY_COLLAPSED) ||
            document.body.classList.contains("cap-sidebar-open")
        ) {
            normalizeMobileClasses();
        }
    });

    bodyClassObserver.observe(document.body, {
        attributes: true,
        attributeFilter: ["class"]
    });

    window.CapivaraSidebar = {
        open: function () {
            setMobileOpen(true);
        },
        close: function () {
            setMobileOpen(false);
        },
        toggle: toggleMenu
    };
})();
