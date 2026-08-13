/*
=============================================================
 Capivara DSM Dashboard - Installation Events UI
=============================================================
*/

"use strict";

(function () {
    const INSTALLATION_TYPES = new Set([
        "INSTALL_STARTED", "INSTALL_COMPLETED", "INSTALL_FAILED", "INSTALL_VALIDATION_FAILED",
        "UPDATE_STARTED", "UPDATE_COMPLETED", "UPDATE_FAILED",
        "ROLLBACK_STARTED", "ROLLBACK_COMPLETED", "ROLLBACK_FAILED"
    ]);

    const EVENT_META = {
        INSTALL_STARTED: { icon: "📦", label: "Instalação iniciada", state: "running" },
        INSTALL_COMPLETED: { icon: "✅", label: "Instalação concluída", state: "success" },
        INSTALL_FAILED: { icon: "❌", label: "Falha na instalação", state: "error" },
        INSTALL_VALIDATION_FAILED: { icon: "🧪", label: "Falha na validação", state: "error" },
        UPDATE_STARTED: { icon: "⬆️", label: "Atualização iniciada", state: "running" },
        UPDATE_COMPLETED: { icon: "✅", label: "Atualização concluída", state: "success" },
        UPDATE_FAILED: { icon: "❌", label: "Falha na atualização", state: "error" },
        ROLLBACK_STARTED: { icon: "↩️", label: "Rollback iniciado", state: "warning" },
        ROLLBACK_COMPLETED: { icon: "✅", label: "Rollback concluído", state: "success" },
        ROLLBACK_FAILED: { icon: "🚨", label: "Falha no rollback", state: "critical" }
    };

    const OPERATION_TYPE_META = {
        install: { icon: "📦", label: "Instalação" },
        installation: { icon: "📦", label: "Instalação" },
        update: { icon: "⬆️", label: "Atualização" },
        rollback: { icon: "↩️", label: "Rollback" }
    };

    const STAGE_LABELS = {
        queued: "Na fila",
        preparing: "Preparando operação",
        staging: "Preparando staging",
        downloading: "Baixando arquivos",
        downloaded: "Download concluído",
        validating: "Validando arquivos",
        installing: "Instalando arquivos",
        updating: "Aplicando atualização",
        activating: "Ativando versão",
        finalizing: "Finalizando operação",
        rollback: "Executando rollback",
        restoring: "Restaurando versão anterior",
        processing: "Processando operação",
        completed: "Operação concluída",
        failed: "Operação encerrada com falha"
    };

    let operationRefreshTimer = null;

    function isInstallationEvent(event) {
        const category = String(event?.category ?? event?.source ?? "").toLowerCase();
        const type = String(event?.type ?? event?.action ?? "").toUpperCase();
        return category === "installation" || INSTALLATION_TYPES.has(type);
    }

    function valueOrDash(value) {
        return value === undefined || value === null || value === "" ? "-" : String(value);
    }

    function formatTimestamp(value) {
        if (!value) return "-";
        const numeric = Number(value);
        if (Number.isFinite(numeric)) {
            const millis = numeric > 9999999999 ? numeric : numeric * 1000;
            return new Date(millis).toLocaleString();
        }
        const parsed = new Date(value);
        return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
    }

    function eventTimestamp(event) {
        return formatTimestamp(event?.timestamp ?? event?.time);
    }

    function setText(id, value) {
        const element = document.getElementById(id);
        if (element) element.textContent = valueOrDash(value);
    }

    function appendInfo(container, label, value) {
        if (value === undefined || value === null || value === "") return;
        const item = document.createElement("div");
        item.className = "installation-event-info";
        const key = document.createElement("span");
        key.className = "installation-event-key";
        key.textContent = label;
        const text = document.createElement("strong");
        text.className = "installation-event-value";
        text.textContent = valueOrDash(value);
        item.append(key, text);
        container.appendChild(item);
    }

    function createInstallationTimelineItem(event) {
        const type = String(event?.type ?? event?.action ?? "EVENT").toUpperCase();
        const meta = EVENT_META[type] ?? { icon: "📦", label: type, state: "neutral" };
        const data = event?.data && typeof event.data === "object" ? event.data : {};
        const resource = event?.resource && typeof event.resource === "object" ? event.resource : {};
        const level = String(event?.level ?? event?.severity ?? "INFO").toUpperCase();

        const item = document.createElement("div");
        item.className = `timeline-item installation-event installation-${meta.state}`;
        item.dataset.eventType = type;

        const icon = document.createElement("div");
        icon.className = "timeline-icon installation-event-icon";
        icon.textContent = meta.icon;

        const body = document.createElement("div");
        body.className = "timeline-body installation-event-body";

        const header = document.createElement("div");
        header.className = "timeline-header installation-event-header";

        const title = document.createElement("div");
        title.className = "installation-event-title-wrap";
        const titleText = document.createElement("span");
        titleText.className = "timeline-title installation-event-title";
        titleText.textContent = meta.label;
        const code = document.createElement("span");
        code.className = "installation-event-code";
        code.textContent = type;
        title.append(titleText, code);

        const badge = document.createElement("span");
        badge.className = `timeline-level level-${level.toLowerCase()} installation-event-badge`;
        badge.textContent = level;
        header.append(title, badge);

        const context = document.createElement("div");
        context.className = "installation-event-context";
        appendInfo(context, "Node", resource.server ?? resource.node ?? event?.node_id);
        appendInfo(context, "Jogo", resource.game ?? event?.game_id);
        appendInfo(context, "Instância", resource.instance ?? event?.instance_id);
        appendInfo(context, "Provider", data.provider);
        appendInfo(context, "Versão", data.version ?? data.current_version);
        appendInfo(context, "Anterior", data.previous_version);
        if (typeof data.rollback_available === "boolean") {
            appendInfo(context, "Rollback", data.rollback_available ? "disponível" : "indisponível");
        }

        const reason = data.reason ?? event?.message ?? event?.details;
        let reasonBox = null;
        if (reason) {
            reasonBox = document.createElement("div");
            reasonBox.className = "installation-event-reason";
            reasonBox.textContent = `${meta.state === "error" || meta.state === "critical" ? "Motivo" : "Detalhe"}: ${reason}`;
        }

        const footer = document.createElement("div");
        footer.className = "timeline-footer installation-event-footer";
        const category = document.createElement("span");
        category.className = "timeline-category";
        category.textContent = "INSTALLATION";
        const date = document.createElement("span");
        date.className = "timeline-date";
        date.textContent = eventTimestamp(event);
        footer.append(category, date);

        body.append(header, context);
        if (reasonBox) body.appendChild(reasonBox);
        body.appendChild(footer);
        item.append(icon, body);
        return item;
    }

    function installTimelineRenderer() {
        const original = window.createTimelineItem;
        if (typeof original !== "function") return false;
        if (original.__installationEventsWrapped) return true;
        const wrapped = function (event) {
            return isInstallationEvent(event) ? createInstallationTimelineItem(event) : original(event);
        };
        wrapped.__installationEventsWrapped = true;
        window.createTimelineItem = wrapped;
        return true;
    }

    function addInstallationFilter() {
        const toolbar = document.querySelector(".timeline-toolbar");
        if (!toolbar || toolbar.querySelector('[data-timeline-filter="installation"]')) return;
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.timelineFilter = "installation";
        button.className = "timeline-filter-installation";
        button.textContent = "📦 Instalação";
        button.addEventListener("click", () => {
            if (typeof window.setTimelineFilter === "function") window.setTimelineFilter("installation");
        });
        toolbar.appendChild(button);
    }

    function normalizeOperationResponse(payload) {
        if (!payload || typeof payload !== "object") return null;
        if (payload.status === "idle" && payload.operation == null) return null;
        if (payload.operation && typeof payload.operation === "object") return payload.operation;
        return payload;
    }

    function clampProgress(value) {
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) return 0;
        return Math.max(0, Math.min(100, Math.round(numeric)));
    }

    function operationVisualState(status) {
        const normalized = String(status ?? "idle").toLowerCase();
        if (["running", "starting", "queued", "pending"].includes(normalized)) return "running";
        if (["completed", "success", "succeeded"].includes(normalized)) return "success";
        if (["failed", "error", "critical"].includes(normalized)) return "error";
        return "idle";
    }

    function operationStatusLabel(status) {
        const normalized = String(status ?? "idle").toLowerCase();
        if (["running", "starting", "queued", "pending"].includes(normalized)) return "EM ANDAMENTO";
        if (["completed", "success", "succeeded"].includes(normalized)) return "CONCLUÍDA";
        if (["failed", "error", "critical"].includes(normalized)) return "FALHOU";
        return "SEM OPERAÇÃO";
    }

    function operationStageLabel(stage, status) {
        const normalized = String(stage ?? "").toLowerCase();
        if (normalized && STAGE_LABELS[normalized]) return STAGE_LABELS[normalized];
        const visualState = operationVisualState(status);
        if (visualState === "success") return "Operação concluída";
        if (visualState === "error") return "Operação encerrada com falha";
        if (visualState === "running") return "Operação em andamento";
        return "Nenhuma operação ativa";
    }

    function renderCurrentOperation(operation) {
        const card = document.getElementById("current-operation-card");
        const empty = document.getElementById("current-operation-empty");
        const content = document.getElementById("current-operation-content");
        if (!card || !empty || !content) return;

        if (!operation) {
            card.className = "card current-operation-card operation-idle";
            empty.hidden = false;
            content.hidden = true;
            setText("current-operation-status", "SEM OPERAÇÃO");
            return;
        }

        const type = String(operation.type ?? "operation").toLowerCase();
        const typeMeta = OPERATION_TYPE_META[type] ?? { icon: "📦", label: valueOrDash(operation.type) };
        const visualState = operationVisualState(operation.status);
        const progress = clampProgress(operation.progress);
        const bar = document.getElementById("current-operation-progress-bar");
        const detail = document.getElementById("current-operation-detail");

        card.className = `card current-operation-card operation-${visualState}`;
        empty.hidden = true;
        content.hidden = false;

        setText("current-operation-status", operationStatusLabel(operation.status));
        setText("current-operation-title", `${typeMeta.icon} ${typeMeta.label}`);
        setText("current-operation-code", String(operation.operation_id ?? operation.id ?? type).toUpperCase());
        setText("current-operation-time", formatTimestamp(operation.updated_at ?? operation.started_at));
        setText("current-operation-node", operation.server ?? operation.node);
        setText("current-operation-game", operation.game);
        setText("current-operation-instance", operation.instance);
        setText("current-operation-provider", operation.provider);
        setText("current-operation-version", operation.version ?? operation.target_version);
        setText("current-operation-previous", operation.previous_version ?? operation.from_version);
        setText("current-operation-progress-text", operationStageLabel(operation.stage, operation.status));
        setText("current-operation-progress-value", `${progress}%`);

        if (bar) {
            bar.style.width = `${progress}%`;
            bar.className = `current-operation-progress-bar progress-${visualState}`;
        }

        const reason = operation.reason ?? operation.message ?? operation.error;
        if (detail) {
            if (reason) {
                detail.hidden = false;
                detail.textContent = String(reason);
            } else {
                detail.hidden = true;
                detail.textContent = "";
            }
        }
    }

    async function refreshCurrentOperation() {
        try {
            let payload = null;

            if (typeof window.apiGet === "function") {
                payload = await window.apiGet("operations/current");
            } else {
                const auth = sessionStorage.getItem("dsm_auth");
                const result = await fetch("/api/operations/current", {
                    headers: auth
                        ? { Authorization: `Basic ${auth}`, Accept: "application/json" }
                        : { Accept: "application/json" }
                });

                if (!result.ok) {
                    throw new Error(`GET /api/operations/current retornou HTTP ${result.status}`);
                }

                payload = await result.json();
            }

            renderCurrentOperation(normalizeOperationResponse(payload));
        } catch (error) {
            if (window.Logger?.error) window.Logger.error("Current Operation UI", error);
        }
    }

    function initialize() {
        const rendererInstalled = installTimelineRenderer();
        addInstallationFilter();
        refreshCurrentOperation();

        if (operationRefreshTimer) clearInterval(operationRefreshTimer);
        operationRefreshTimer = setInterval(refreshCurrentOperation, 5000);

        if (rendererInstalled && typeof window.renderTimeline === "function") window.renderTimeline();
        if (window.Logger?.info) window.Logger.info("Installation Events UI carregada | loaded.");
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, { once: true });
    } else {
        initialize();
    }
})();
