"use strict";

(() => {
    let lastAgent = null;
    let telemetryTimer = null;
    const histories = new Map();
    const HISTORY_LIMIT = 60;

    function text(id, value) {
        const element = document.getElementById(id);
        if (element) element.textContent = value ?? "—";
    }

    function number(value) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
    }

    function bytes(value) {
        const n = number(value);
        if (n === null) return "—";
        const units = ["B", "KB", "MB", "GB", "TB"];
        let current = Math.max(0, n);
        let unit = 0;
        while (current >= 1024 && unit < units.length - 1) {
            current /= 1024;
            unit += 1;
        }
        return `${current.toFixed(unit === 0 ? 0 : current >= 10 ? 1 : 2)} ${units[unit]}`;
    }

    function duration(seconds) {
        const total = number(seconds);
        if (total === null) return "—";
        const days = Math.floor(total / 86400);
        const hours = Math.floor((total % 86400) / 3600);
        const minutes = Math.floor((total % 3600) / 60);
        return `${days ? `${days}d ` : ""}${hours}h ${minutes}m`;
    }

    function telemetryFrom(result) {
        if (result?.telemetry && typeof result.telemetry === "object") return result.telemetry;
        if (result?.agent?.telemetry && typeof result.agent.telemetry === "object") return result.agent.telemetry;
        const metadata = result?.agent?.metadata;
        if (metadata?.telemetry && typeof metadata.telemetry === "object") return metadata.telemetry;
        return null;
    }

    function history(key, value) {
        if (!histories.has(key)) histories.set(key, []);
        const values = histories.get(key);
        const numeric = number(value);
        if (numeric !== null) values.push(numeric);
        if (values.length > HISTORY_LIMIT) values.splice(0, values.length - HISTORY_LIMIT);
        return values;
    }

    function draw(canvasId, values, {min = null, max = null} = {}) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !values.length) return;
        const rect = canvas.getBoundingClientRect();
        const width = Math.max(120, Math.floor(rect.width || canvas.clientWidth || 240));
        const height = Math.max(48, Math.floor(rect.height || canvas.clientHeight || 72));
        const ratio = window.devicePixelRatio || 1;
        canvas.width = Math.floor(width * ratio);
        canvas.height = Math.floor(height * ratio);
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        ctx.clearRect(0, 0, width, height);

        let low = min === null ? Math.min(...values) : min;
        let high = max === null ? Math.max(...values) : max;
        if (high <= low) high = low + 1;
        const pad = 5;
        ctx.beginPath();
        values.forEach((value, index) => {
            const x = values.length === 1 ? width - pad : pad + (index / (values.length - 1)) * (width - pad * 2);
            const y = height - pad - ((value - low) / (high - low)) * (height - pad * 2);
            if (index === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.lineWidth = 2;
        ctx.strokeStyle = getComputedStyle(canvas.closest(".telemetry-card") || canvas).color || "#7dd3fc";
        ctx.stroke();
    }

    function renderProcesses(items) {
        const body = document.getElementById("agent-process-table-body");
        if (!body) return;
        body.replaceChildren();
        const rows = Array.isArray(items) ? items.slice(0, 5) : [];
        if (!rows.length) {
            const row = document.createElement("tr");
            row.className = "empty-row";
            const cell = document.createElement("td");
            cell.colSpan = 5;
            cell.textContent = "Aguardando telemetria do Agent.";
            row.appendChild(cell);
            body.appendChild(row);
            return;
        }
        rows.forEach(item => {
            const row = document.createElement("tr");
            [
                item.name || "—",
                item.pid ?? "—",
                number(item.cpu_usage_pct) === null ? "—" : `${number(item.cpu_usage_pct).toFixed(1)}%`,
                bytes(item.memory_rss_bytes),
                item.threads ?? "—"
            ].forEach(value => {
                const cell = document.createElement("td");
                cell.textContent = String(value);
                row.appendChild(cell);
            });
            body.appendChild(row);
        });
    }

    function renderTelemetry(telemetry) {
        if (!telemetry || typeof telemetry !== "object") return;
        const host = telemetry.host && typeof telemetry.host === "object" ? telemetry.host : {};
        const memory = host.memory && typeof host.memory === "object" ? host.memory : {};
        const disk = host.disk && typeof host.disk === "object" ? host.disk : {};
        const load = host.load_average && typeof host.load_average === "object" ? host.load_average : {};
        const network = host.network && typeof host.network === "object" ? host.network : {};
        const agent = telemetry.agent && typeof telemetry.agent === "object" ? telemetry.agent : {};

        const cpu = number(host.cpu_usage_pct);
        const memoryUsed = number(memory.used_bytes);
        const memoryTotal = number(memory.total_bytes);
        const diskPct = number(disk.usage_pct);
        const load1 = number(load["1m"]);
        const load5 = number(load["5m"]);
        const load15 = number(load["15m"]);
        const rx = number(network.rx_bytes_per_second);
        const tx = number(network.tx_bytes_per_second);
        const temperature = number(host.temperature_c);
        const agentCpu = number(agent.cpu_usage_pct);
        const agentMemory = number(agent.memory_rss_bytes);
        const agentThreads = number(agent.threads);
        const agentPid = number(agent.pid);

        text("agent-host-cpu", cpu === null ? "Coletando…" : `${cpu.toFixed(1)}%`);
        text("agent-host-memory", memoryTotal === null ? "—" : `${bytes(memoryUsed)} / ${bytes(memoryTotal)}`);
        text("agent-host-disk", diskPct === null ? "—" : `${diskPct.toFixed(1)}%`);
        text("agent-host-load", [load1, load5, load15].every(v => v !== null) ? `${load1.toFixed(2)} / ${load5.toFixed(2)} / ${load15.toFixed(2)}` : "—");
        text("agent-host-uptime", duration(host.uptime_seconds));
        text("agent-host-network-in", rx === null ? "Coletando…" : `${bytes(rx)}/s`);
        text("agent-host-network-out", tx === null ? "Coletando…" : `${bytes(tx)}/s`);
        text("agent-host-temperature", temperature === null ? "N/D" : `${temperature.toFixed(1)} °C`);
        text("agent-process-cpu", agentCpu === null ? "Coletando…" : `${agentCpu.toFixed(1)}%`);
        text("agent-process-memory", bytes(agentMemory));
        text("agent-process-threads", agentThreads === null ? "—" : Math.round(agentThreads));
        text("agent-process-pid", agentPid === null ? "—" : Math.round(agentPid));

        draw("agent-host-cpu-chart", history("host.cpu", cpu), {min: 0, max: 100});
        draw("agent-host-memory-chart", history("host.memory", number(memory.usage_pct)), {min: 0, max: 100});
        draw("agent-host-disk-chart", history("host.disk", diskPct), {min: 0, max: 100});
        draw("agent-host-load-chart", history("host.load", load1), {min: 0});
        draw("agent-host-uptime-chart", history("host.uptime", number(host.uptime_seconds)), {min: 0});
        draw("agent-host-network-in-chart", history("host.network.rx", rx), {min: 0});
        draw("agent-host-network-out-chart", history("host.network.tx", tx), {min: 0});
        draw("agent-host-temperature-chart", history("host.temperature", temperature), {min: 0});
        draw("agent-process-cpu-chart", history("agent.cpu", agentCpu), {min: 0, max: 100});
        draw("agent-process-memory-chart", history("agent.memory", agentMemory), {min: 0});
        draw("agent-process-threads-chart", history("agent.threads", agentThreads), {min: 0});
        draw("agent-process-pid-chart", history("agent.pid", agentPid), {min: 0});
        renderProcesses(telemetry.top_processes);
    }

    async function loadTelemetry() {
        if (!selectedAgent) return;
        const result = await request(`/agent/ports?agent_id=${encodeURIComponent(selectedAgent)}`);
        renderTelemetry(telemetryFrom(result));
    }

    function scheduleTelemetry() {
        if (telemetryTimer) clearInterval(telemetryTimer);
        loadTelemetry().catch(error => errorMessage(error.message));
        telemetryTimer = setInterval(() => {
            if (selectedAgent) loadTelemetry().catch(error => console.warn("[Capivara][Telemetry]", error));
        }, 30000);
    }

    async function loadUpdateStatus() {
        if (!selectedAgent || selectedAgent === lastAgent && document.getElementById("agent-update-status")?.dataset.loaded === "true") return;
        lastAgent = selectedAgent;
        const status = await request(`/agents/updates/status?agent_id=${encodeURIComponent(selectedAgent)}`);
        text("agent-installed-version", status.installed_version);
        text("agent-available-version", status.available_version);
        text("agent-update-status", status.update_status);
        text("agent-last-update", status.last_update);
        const statusElement = document.getElementById("agent-update-status");
        if (statusElement) statusElement.dataset.loaded = "true";
        const channel = document.getElementById("agent-update-channel");
        if (channel) channel.value = status.update_channel || "stable";
        const rolloutChannel = document.getElementById("agent-rollout-channel");
        if (rolloutChannel) rolloutChannel.value = status.update_channel || "stable";
        const rolloutAgents = document.getElementById("agent-rollout-agents");
        if (rolloutAgents) rolloutAgents.value = selectedAgent;
    }

    async function saveChannel(event) {
        event.preventDefault();
        if (!selectedAgent) return;
        try {
            const result = await request("/agents/updates/channel", {
                method: "POST",
                body: JSON.stringify({
                    agent_id: selectedAgent,
                    update_channel: document.getElementById("agent-update-channel").value
                })
            });
            document.getElementById("agent-update-channel").value = result.update_channel;
            errorMessage();
        } catch (error) {
            errorMessage(error.message);
        }
    }

    async function createRollout(event) {
        event.preventDefault();
        const ids = document.getElementById("agent-rollout-agents").value
            .split(/[\s,;]+/)
            .map(value => value.trim())
            .filter(Boolean);
        try {
            const rollout = await request("/agents/updates/rollouts", {
                method: "POST",
                body: JSON.stringify({
                    agent_ids: ids,
                    desired_version: document.getElementById("agent-rollout-version").value.trim(),
                    update_channel: document.getElementById("agent-rollout-channel").value,
                    batch_size: Number(document.getElementById("agent-rollout-batch-size").value)
                })
            });
            errorMessage();
            document.getElementById("agent-available-version").textContent = rollout.desired_version;
            document.getElementById("agent-update-status").textContent = "planned";
            document.getElementById("agent-update-status").dataset.loaded = "false";
            await loadUpdateStatus();
        } catch (error) {
            errorMessage(error.message);
        }
    }

    function watchSelection() {
        const title = document.getElementById("agent-detail-title");
        if (!title) return;
        new MutationObserver(() => {
            if (selectedAgent) {
                const status = document.getElementById("agent-update-status");
                if (status) status.dataset.loaded = "false";
                loadUpdateStatus().catch(error => errorMessage(error.message));
                scheduleTelemetry();
            }
        }).observe(title, {childList: true, characterData: true, subtree: true});
    }

    window.addEventListener("resize", () => {
        if (selectedAgent) loadTelemetry().catch(() => {});
    });

    window.addEventListener("load", () => {
        document.getElementById("agent-update-channel-form")?.addEventListener("submit", saveChannel);
        document.getElementById("agent-rollout-form")?.addEventListener("submit", createRollout);
        watchSelection();
        if (selectedAgent) scheduleTelemetry();
    });
})();
