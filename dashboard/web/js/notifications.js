// =============================================================
// DSM Dashboard HUD
// web/js/notifications.js
// Versão | Version: v1.2.0
// Função: Renderização dos Alert Cards
// Function: Alert Cards Rendering
// =============================================================

const ALERT_REFRESH_MS = 10000;

// -------------------------------------------------------------
// Buscar notificações | Fetch notifications
// -------------------------------------------------------------
async function fetchNotifications() {
    try {
        const response = await fetch("/api/notifications");
        if (!response.ok) {
            throw new Error("Falha API notifications | API notifications failure");
        }
        return await response.json();
    } catch (error) {
        console.error("DSM notifications:", error);
        return {
            total: 0,
            critical: 0,
            warning: 0,
            alerts: []
        };
    }
}

// -------------------------------------------------------------
// Ícone por nível | Icon by level
// -------------------------------------------------------------
function alertIcon(level) {
    switch (level) {
        case "CRITICAL": return "🔴";
        case "WARNING": return "🟡";
        case "OK": return "🟢";
        default: return "⚪";
    }
}

// -------------------------------------------------------------
// Classe CSS | CSS Class
// -------------------------------------------------------------
function alertClass(level) {
    switch (level) {
        case "CRITICAL": return "critical";
        case "WARNING": return "warning";
        case "OK": return "ok";
        default: return "normal";
    }
}

// -------------------------------------------------------------
// Formatar data | Format date
// -------------------------------------------------------------
function formatAlertTime(date) {
    if (!date) return "-";
    try {
        return new Date(date).toLocaleString("pt-BR");
    } catch {
        return date;
    }
}

// -------------------------------------------------------------
// Criar card HUD | Create HUD card
// -------------------------------------------------------------
function createAlertCard(alert) {
    const div = document.createElement("div");
    div.className = "alert-card " + alertClass(alert.level);

    div.innerHTML = `
        <div class="alert-header">
            <span class="alert-level">${alertIcon(alert.level)} ${alert.level}</span>
            <span class="alert-time">${formatAlertTime(alert.created)}</span>
        </div>
        <div class="alert-title">${escapeHTML(alert.title)}</div>
        <div class="alert-message">${escapeHTML(alert.message)}</div>
        ${alert.ack ? '<div class="ack-status">✔ reconhecido | acknowledged</div>' : `<button class="btn acknowledge" data-alert-id="${alert.id}">RECONHECER | ACKNOWLEDGE</button>`}
    `;
    return div;
}

// -------------------------------------------------------------
// Proteção contra HTML | HTML protection
// -------------------------------------------------------------
function escapeHTML(text) {
    if (!text) return "";
    return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// -------------------------------------------------------------
// Renderizar alertas | Render alerts
// -------------------------------------------------------------
async function loadNotifications() {
    const data = await fetchNotifications();
    const container = document.getElementById("alerts-container");
    const counter = document.getElementById("alerts-total");

    if (counter) {
        counter.textContent = data.total;
    }

    if (!container) return;
    container.innerHTML = "";

    if (!data.alerts || data.alerts.length === 0) {
        container.innerHTML = '<div class="empty">nenhum alerta ativo | no active alerts</div>';
        return;
    }

    data.alerts.forEach(alert => {
        container.appendChild(createAlertCard(alert));
    });

    bindAcknowledgeButtons();
}

// -------------------------------------------------------------
// Botão reconhecer | Acknowledge button
// -------------------------------------------------------------
function bindAcknowledgeButtons() {
    document.querySelectorAll(".acknowledge").forEach(button => {
        button.addEventListener(
            "click",
            async function() {
            const id = this.dataset.alertId;
            this.disabled = true;
            this.textContent = "PROCESSANDO... | PROCESSING...";
            await acknowledgeAlert(id);
        });
    });
}

// -------------------------------------------------------------
// Enviar reconhecimento | Send acknowledgment
// -------------------------------------------------------------
async function acknowledgeAlert(id) {
    try {
        await fetch("/api/acknowledge?id=" + encodeURIComponent(id), {
            method: "POST"
        });
        await loadNotifications();
    } catch (error) {
        console.error("Erro acknowledge | Acknowledge error:", error);
    }
}

// -------------------------------------------------------------
// Inicialização automática | Automatic initialization
// -------------------------------------------------------------
let alertRefreshTimer = null;

window.initializeNotifications = async function() {
    await loadNotifications();

    if (alertRefreshTimer === null) {
        alertRefreshTimer = setInterval(
            loadNotifications,
            ALERT_REFRESH_MS
        );
    }
};
