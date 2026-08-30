(function () {
    "use strict";

    const params = new URLSearchParams(location.search);
    const agentId = params.get("agent_id") || params.get("id") || "";

    function value(raw, fallback = "—") {
        return raw === null || raw === undefined || raw === "" ? fallback : String(raw);
    }

    function list(raw) {
        return Array.isArray(raw) && raw.length ? raw.join(", ") : "—";
    }

    async function request() {
        const response = await fetch(`/api/agent/ports?agent_id=${encodeURIComponent(agentId)}`, {
            headers: {"X-Capivara-Auth-Area": "controller", Accept: "application/json"},
            credentials: "same-origin",
            cache: "no-store"
        });
        if (response.status === 401) {
            location.replace("login.html");
            throw new Error("Sessão expirada");
        }
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.message || payload.error || `HTTP ${response.status}`);
        return payload;
    }

    function fact(term, description) {
        const box = document.createElement("div");
        const dt = document.createElement("dt");
        const dd = document.createElement("dd");
        dt.textContent = term;
        dd.textContent = description;
        box.append(dt, dd);
        return box;
    }

    function interfaceCard(item) {
        const card = document.createElement("div");
        card.className = "cap-range-card";
        const strong = document.createElement("strong");
        strong.textContent = `${value(item.name, "Interface")} · ${value(item.status, "unknown")}`;
        const span = document.createElement("span");
        const details = [
            `IPv4 ${list(item.ipv4)}`,
            `IPv6 ${list(item.ipv6)}`,
            `MAC ${value(item.mac)}`,
            `MTU ${value(item.mtu)}`
        ];
        span.textContent = details.join(" · ");
        card.append(strong, span);
        return card;
    }

    function preflightCard(protocol, report) {
        const card = document.createElement("div");
        card.className = "cap-range-card";
        const strong = document.createElement("strong");
        strong.textContent = `${protocol.toUpperCase()} · ${report?.ready ? "apto" : "indisponível"}`;
        const span = document.createElement("span");
        const best = Math.max(0, ...(report?.ranges || []).map(item => Number(item.largest_contiguous_available || 0)));
        span.textContent = `${value(report?.eligible_range_count, 0)} faixa(s) elegível(is) · maior bloco livre ${best} · ${value(report?.observed_conflict_count, 0)} conflito(s) de socket`;
        card.append(strong, span);
        return card;
    }

    function ensurePanel() {
        let panel = document.getElementById("agent-network-panel");
        if (panel) return panel;
        panel = document.createElement("section");
        panel.id = "agent-network-panel";
        panel.className = "cap-detail-panel";
        panel.innerHTML = `
            <div class="cap-detail-heading"><div><h2>Rede do Host e Conectividade</h2><p>Inventário reportado pelo Agent, estado do heartbeat e prontidão do Port Pool.</p></div></div>
            <dl id="agent-network-facts" class="cap-detail-list"></dl>
            <h3>Interfaces</h3><div id="agent-network-interfaces" class="cap-range-grid"></div>
            <h3>Preflight do Port Pool</h3><div id="agent-port-preflight" class="cap-range-grid"></div>
            <div id="agent-network-note" class="cap-detail-note"></div>`;
        const telemetry = document.getElementById("agent-telemetry");
        if (telemetry) telemetry.insertAdjacentElement("afterend", panel);
        else document.querySelector(".cap-agent-detail-content")?.appendChild(panel);
        return panel;
    }

    function render(payload) {
        ensurePanel();
        const agent = payload.agent || {};
        const network = agent.network || {};
        const health = String(agent.health_status || "offline").toLowerCase();
        const connected = health === "online" || health === "degraded";
        const facts = document.getElementById("agent-network-facts");
        facts?.replaceChildren(
            fact("Hostname / FQDN", `${value(network.hostname || agent.hostname)} / ${value(network.fqdn)}`),
            fact("Interface principal", value(network.primary_interface)),
            fact("IPv4 principal", value(network.primary_ipv4 || agent.address)),
            fact("IPv6 principal", value(network.primary_ipv6)),
            fact("Gateway IPv4", value(network.gateway_ipv4)),
            fact("Gateway IPv6", value(network.gateway_ipv6)),
            fact("DNS", list(network.dns_servers)),
            fact("Heartbeat com este Controller", connected ? `conectado (${health})` : `sem conectividade (${health})`),
            fact("Último heartbeat", value(agent.last_seen)),
            fact("Inventário de rede", network.complete === false ? "parcial" : network.complete === true ? "completo" : "não informado")
        );

        const interfaces = document.getElementById("agent-network-interfaces");
        const cards = Array.isArray(network.interfaces) ? network.interfaces.map(interfaceCard) : [];
        interfaces?.replaceChildren(...cards);
        if (interfaces && !cards.length) {
            const empty = document.createElement("div");
            empty.className = "cap-detail-note";
            empty.textContent = "Nenhuma interface detalhada foi reportada pelo Agent.";
            interfaces.appendChild(empty);
        }

        document.getElementById("agent-port-preflight")?.replaceChildren(
            preflightCard("tcp", payload.preflight?.tcp),
            preflightCard("udp", payload.preflight?.udp)
        );
        const note = document.getElementById("agent-network-note");
        if (note) {
            note.textContent = "Diagnóstico DNS/TCP/TLS/HTTP do endpoint configurado permanece disponível localmente em: cap agent controller test --json.";
        }
    }

    async function refresh() {
        if (!agentId) return;
        try {
            render(await request());
        } catch (error) {
            ensurePanel();
            const note = document.getElementById("agent-network-note");
            if (note) note.textContent = `Não foi possível carregar o inventário de rede: ${error?.message || error}`;
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        refresh();
        document.getElementById("refresh-agent-detail")?.addEventListener("click", () => setTimeout(refresh, 0));
    });
})();
