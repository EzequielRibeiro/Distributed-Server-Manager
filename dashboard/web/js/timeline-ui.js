(() => {
    "use strict";

    const TIMELINE_ENDPOINT = "/api/events/timeline";
    const DEFAULT_LIMIT = 50;
    const SENSITIVE_KEY = /(secret|token|password|credential|authorization|cookie)/i;

    let events = [];
    let activeFilter = "all";

    const filterDefinitions = [
        ["all", "Todos"],
        ["infrastructure", "Infraestrutura"],
        ["instance", "Instâncias"],
        ["content", "Conteúdo"],
        ["security", "Segurança"],
    ];

    const typeLabels = {
        AGENT_ONLINE: "Agent online",
        AGENT_OFFLINE: "Agent offline",
        AGENT_DISABLED: "Agent desabilitado",
        AGENT_REJECTED: "Agent rejeitado",
        AGENT_PAIRING_STARTED: "Pareamento do Agent iniciado",
        AGENT_PAIRING_FAILED: "Falha no pareamento do Agent",
        AGENT_UPDATE_AVAILABLE: "Atualização de Agent disponível",
        AGENT_UPDATE_STARTED: "Atualização do Agent iniciada",
        AGENT_UPDATE_COMPLETED: "Atualização do Agent concluída",
        AGENT_UPDATE_FAILED: "Falha na atualização do Agent",
        PLACEMENT_REQUESTED: "Placement solicitado",
        PLACEMENT_SELECTED: "Placement selecionado",
        PLACEMENT_UNAVAILABLE: "Placement indisponível",
        INSTANCE_CREATE_REQUESTED: "Criação de instância solicitada",
        INSTANCE_CREATED: "Instância criada",
        INSTANCE_INSTALL_STARTED: "Instalação da instância iniciada",
        INSTANCE_INSTALL_COMPLETED: "Instalação da instância concluída",
        INSTANCE_INSTALL_FAILED: "Falha na instalação da instância",
        INSTANCE_STARTED: "Instância iniciada",
        INSTANCE_STOPPED: "Instância parada",
        INSTANCE_RESTARTED: "Instância reiniciada",
        INSTANCE_FAILED: "Falha na instância",
        CONTENT_INSTALLED: "Conteúdo instalado",
        CONTENT_UPDATED: "Conteúdo atualizado",
        CONTENT_REMOVED: "Conteúdo removido",
        CONTENT_INSTALL_FAILED: "Falha na instalação de conteúdo",
        AUTH_LOGIN_FAILED: "Falha de autenticação",
        PERMISSION_DENIED: "Permissão negada",
    };

    function authHeader() {
        const auth = sessionStorage.getItem("dsm_auth") || "";
        return `Basic ${auth}`;
    }

    function eventCategory(event) {
        const type = String(event?.type || "").toUpperCase();
        const sourceType = String(event?.source?.type || "").toLowerCase();

        if (
            type.startsWith("AGENT_") ||
            type.startsWith("PLACEMENT_") ||
            type.startsWith("PORT_") ||
            type.startsWith("INFRASTRUCTURE_") ||
            sourceType === "agent" ||
            sourceType === "controller"
        ) {
            return "infrastructure";
        }
        if (type.startsWith("INSTANCE_") || sourceType === "instance") {
            return "instance";
        }
        if (
            type.startsWith("CONTENT_") ||
            type.startsWith("BACKUP_") ||
            type.startsWith("MOD_")
        ) {
            return "content";
        }
        if (
            type.startsWith("AUTH_") ||
            type.startsWith("PERMISSION_") ||
            type.includes("DENIED") ||
            sourceType === "audit"
        ) {
            return "security";
        }
        return "infrastructure";
    }

    function categoryLabel(category) {
        return {
            infrastructure: "INFRAESTRUTURA",
            instance: "INSTÂNCIA",
            content: "CONTEÚDO",
            security: "SEGURANÇA",
        }[category] || "EVENTO";
    }

    function categoryIcon(category) {
        return {
            infrastructure: "🖥️",
            instance: "🎮",
            content: "🧩",
            security: "🔒",
        }[category] || "📄";
    }

    function readableType(type) {
        const normalized = String(type || "EVENT").toUpperCase();
        return typeLabels[normalized] || normalized.replaceAll("_", " ");
    }

    function formatTimestamp(value) {
        const date = new Date(value || "");
        return Number.isNaN(date.getTime()) ? "-" : date.toLocaleString("pt-BR");
    }

    function compactData(data) {
        if (!data || typeof data !== "object" || Array.isArray(data)) {
            return "";
        }

        return Object.entries(data)
            .filter(([key, value]) => !SENSITIVE_KEY.test(key) && value !== null && value !== "")
            .slice(0, 4)
            .map(([key, value]) => {
                const printable = typeof value === "object"
                    ? JSON.stringify(value)
                    : String(value);
                return `${key}: ${printable.length > 80 ? `${printable.slice(0, 77)}…` : printable}`;
            })
            .join(" · ");
    }

    function appendText(parent, tag, className, text) {
        const node = document.createElement(tag);
        node.className = className;
        node.textContent = text;
        parent.appendChild(node);
        return node;
    }

    function createTimelineItem(event) {
        const category = eventCategory(event);
        const severity = String(event?.severity || "info").toLowerCase();
        const item = document.createElement("div");
        item.className = `timeline-item timeline-${severity}`;
        item.dataset.eventId = String(event?.id || "");
        item.dataset.category = category;

        appendText(item, "div", "timeline-icon", categoryIcon(category));

        const body = document.createElement("div");
        body.className = "timeline-body";
        item.appendChild(body);

        const header = document.createElement("div");
        header.className = "timeline-header";
        body.appendChild(header);
        appendText(header, "span", "timeline-title", readableType(event?.type));
        appendText(header, "span", `timeline-level level-${severity}`, severity.toUpperCase());

        const detail = compactData(event?.data);
        if (detail) {
            appendText(body, "div", "timeline-message", detail);
        }

        const footer = document.createElement("div");
        footer.className = "timeline-footer";
        body.appendChild(footer);
        appendText(footer, "span", "timeline-category", categoryLabel(category));
        appendText(footer, "span", "timeline-date", formatTimestamp(event?.timestamp));

        if (event?.correlation_id) {
            const correlation = appendText(
                body,
                "small",
                "timeline-correlation",
                `Fluxo: ${event.correlation_id}`,
            );
            correlation.title = event.causation_id
                ? `Causado por ${event.causation_id}`
                : "Evento raiz ou sem causação registrada";
        }

        return item;
    }

    function renderTimeline() {
        const container = document.getElementById("timeline-list");
        if (!container) return;

        container.replaceChildren();
        const visible = activeFilter === "all"
            ? events
            : events.filter((event) => eventCategory(event) === activeFilter);

        if (!visible.length) {
            appendText(container, "div", "timeline-empty", "Nenhum evento universal encontrado.");
            return;
        }

        visible.forEach((event) => container.appendChild(createTimelineItem(event)));
    }

    function setTimelineFilter(filter) {
        activeFilter = filterDefinitions.some(([value]) => value === filter)
            ? filter
            : "all";
        document.querySelectorAll(".timeline-toolbar button[data-timeline-filter]").forEach((button) => {
            button.classList.toggle("active", button.dataset.timelineFilter === activeFilter);
        });
        renderTimeline();
    }

    function rebuildToolbar() {
        const toolbar = document.querySelector(".timeline-toolbar");
        if (!toolbar) return;

        toolbar.replaceChildren();
        filterDefinitions.forEach(([value, label]) => {
            const button = document.createElement("button");
            button.type = "button";
            button.dataset.timelineFilter = value;
            button.textContent = label;
            button.addEventListener("click", () => setTimelineFilter(value));
            toolbar.appendChild(button);
        });
        setTimelineFilter(activeFilter);
    }

    async function loadTimeline(limit = DEFAULT_LIMIT) {
        const safeLimit = Math.max(1, Math.min(200, Number(limit) || DEFAULT_LIMIT));
        try {
            const response = await fetch(`${TIMELINE_ENDPOINT}?limit=${safeLimit}`, {
                headers: {
                    Authorization: authHeader(),
                    Accept: "application/json",
                },
            });

            if (response.status === 401) {
                sessionStorage.removeItem("dsm_auth");
                window.location.replace("login.html");
                return;
            }
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const payload = await response.json();
            events = Array.isArray(payload?.events) ? payload.events : [];
            renderTimeline();
        } catch (error) {
            const container = document.getElementById("timeline-list");
            if (container) {
                container.replaceChildren();
                appendText(container, "div", "timeline-empty", "Não foi possível carregar a linha do tempo.");
            }
            console.error("[Capivara][Timeline]", error);
        }
    }

    rebuildToolbar();

    // Compatibility boundary for app.js. refreshDashboard() keeps calling the
    // same public functions, but they now consume Universal Event Platform data.
    window.loadTimeline = loadTimeline;
    window.setTimelineFilter = setTimelineFilter;
    window.CapivaraTimeline = {
        load: loadTimeline,
        render: renderTimeline,
        setFilter: setTimelineFilter,
        categoryFor: eventCategory,
    };
})();
