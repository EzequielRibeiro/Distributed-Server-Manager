(function () {
  "use strict";

  const auth = () => sessionStorage.getItem("dsm_auth") || "";
  const $ = id => document.getElementById(id);
  let discord = null;
  let instances = [];

  const EVENT_LABELS = {
    "server.started": "Servidor iniciado", "server.stopped": "Servidor desligado",
    "server.crashed": "Servidor caiu inesperadamente", "player.connected": "Jogador entrou",
    "player.disconnected": "Jogador saiu", "backup.completed": "Backup concluído",
    "backup.failed": "Falha no backup", "alert.critical": "Alerta crítico",
  };
  const COMMAND_LABELS = {
    status: "/status", players: "/players", start: "/start", stop: "/stop",
    restart: "/restart", backup: "/backup", serverinfo: "/serverinfo", events: "/events",
  };

  async function request(path, options = {}) {
    if (!auth()) { location.href = "/login.html"; throw new Error("Sessão encerrada."); }
    const headers = {Authorization: `Basic ${auth()}`, Accept: "application/json", ...(options.headers || {})};
    if (options.body) headers["Content-Type"] = "application/json";
    const response = await fetch(path, {...options, headers});
    if (response.status === 401) {
      sessionStorage.removeItem("dsm_auth"); location.href = "/login.html"; throw new Error("Sessão encerrada.");
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || data.error || `HTTP ${response.status}`);
    return data;
  }

  function message(text, kind = "success") {
    const node = $("discord-message");
    node.className = kind === "error" ? "integration-notice" : "integration-success";
    node.textContent = text;
    window.setTimeout(() => { node.className = ""; node.textContent = ""; }, 6000);
  }

  function instanceId(item) { return String(item.instance || item.id || ""); }
  function instanceLabel(item) {
    const id = instanceId(item);
    return String(item.display_name || item.name || id || "Servidor");
  }

  function activeConnections() {
    return (discord?.connections || []).filter(item => String(item.status) === "active");
  }

  function preference(type, key, instance) {
    const list = discord?.preferences || [];
    return list.find(item => String(item.preference_type) === type && String(item.preference_key) === key && String(item.instance_id) === String(instance));
  }

  function fillInstanceSelect(select) {
    const current = select.value;
    select.replaceChildren(new Option("Todos os servidores (padrão)", "*"));
    instances.forEach(item => select.add(new Option(instanceLabel(item), instanceId(item))));
    if ([...select.options].some(option => option.value === current)) select.value = current;
  }

  function renderSummary() {
    const connections = activeConnections();
    const status = $("discord-status");
    status.textContent = connections.length ? "Conectado" : "Não conectado";
    status.className = `integration-status ${connections.length ? "online" : "warning"}`;
    const summary = $("discord-summary");
    const defaultConnection = connections.find(item => Number(item.is_default) === 1);
    summary.innerHTML = connections.length
      ? `<div><strong>${connections.length} Discord(s) conectado(s)</strong><small class="integration-muted">Padrão: ${defaultConnection?.guild_name || "não definido"}</small></div>`
      : `<div class="integration-empty">Nenhum servidor Discord conectado.</div>`;
    const connect = $("discord-connect");
    if (discord?.oauth?.configured && discord.oauth.authorize_url) {
      connect.href = discord.oauth.authorize_url; connect.hidden = false;
    } else {
      connect.hidden = true;
      if (!connections.length) summary.insertAdjacentHTML("beforeend", '<div class="integration-notice">O administrador do Controller ainda precisa configurar o aplicativo Discord.</div>');
    }
  }

  function renderConnections() {
    const container = $("discord-connections");
    container.replaceChildren();
    const list = activeConnections();
    if (!list.length) { container.innerHTML = '<div class="integration-empty">Use “Conectar Discord” para adicionar uma comunidade.</div>'; return; }
    list.forEach(item => {
      const node = document.createElement("article");
      node.className = "integration-server";
      const isDefault = Number(item.is_default) === 1;
      node.innerHTML = `<div class="integration-row"><div><strong>${item.guild_name}</strong><small class="integration-muted">Guild ID ${item.guild_id}</small></div><div>${isDefault ? '<span class="integration-badge">PADRÃO</span>' : ''}</div></div><div class="integration-actions" style="margin-top:10px"></div>`;
      const actions = node.querySelector(".integration-actions");
      if (!isDefault) {
        const setDefault = document.createElement("button"); setDefault.type = "button"; setDefault.className = "button"; setDefault.textContent = "Tornar padrão";
        setDefault.onclick = () => update({action: "set_default", connection_id: item.id}, "Discord padrão atualizado."); actions.append(setDefault);
      }
      const disconnect = document.createElement("button"); disconnect.type = "button"; disconnect.className = "button"; disconnect.textContent = "Desconectar";
      disconnect.onclick = () => { if (confirm(`Desconectar ${item.guild_name}?`)) update({action: "disconnect", connection_id: item.id}, "Discord desconectado."); };
      actions.append(disconnect); container.append(node);
    });
  }

  function renderBindings() {
    const container = $("discord-bindings"); container.replaceChildren();
    if (!instances.length) { container.innerHTML = '<div class="integration-empty">Nenhuma instância do cliente encontrada.</div>'; return; }
    const connections = activeConnections();
    instances.forEach(item => {
      const id = instanceId(item); if (!id) return;
      const binding = (discord.bindings || []).find(row => String(row.instance_id) === id) || {mode: "inherit"};
      const node = document.createElement("article"); node.className = "integration-server";
      const form = document.createElement("div"); form.className = "integration-form";
      form.innerHTML = `<div><strong>${instanceLabel(item)}</strong><small class="integration-muted">${item.game || "Servidor"} · ${id}</small></div>`;
      const select = document.createElement("select");
      select.add(new Option("Usar Discord padrão da conta", "inherit"));
      connections.forEach(connection => select.add(new Option(`Usar ${connection.guild_name}`, `connection:${connection.id}`)));
      select.add(new Option("Não usar Discord", "disabled"));
      select.value = binding.mode === "connection" ? `connection:${binding.connection_id}` : binding.mode || "inherit";
      const channel = document.createElement("input"); channel.placeholder = "Canal padrão (ID, opcional)"; channel.value = binding.channel_id || "";
      const save = document.createElement("button"); save.type = "button"; save.className = "button"; save.textContent = "Salvar";
      save.onclick = () => {
        const [mode, connectionId] = select.value.split(":");
        update({action: "set_binding", instance_id: id, mode, connection_id: connectionId || null, channel_id: channel.value.trim() || null}, `Integração de ${instanceLabel(item)} atualizada.`);
      };
      form.append(select, channel, save); node.append(form); container.append(node);
    });
  }

  function renderPreferences(type) {
    const instanceSelect = $(type === "event" ? "discord-events-instance" : "discord-commands-instance");
    const container = $(type === "event" ? "discord-events" : "discord-commands");
    fillInstanceSelect(instanceSelect); container.replaceChildren();
    const selected = instanceSelect.value || "*";
    const keys = discord?.catalog?.[type === "event" ? "events" : "commands"] || [];
    keys.forEach(key => {
      const saved = preference(type, key, selected);
      const label = document.createElement("label"); label.className = "integration-option";
      const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.checked = saved ? Number(saved.enabled) === 1 : true;
      const text = document.createElement("span"); text.textContent = (type === "event" ? EVENT_LABELS : COMMAND_LABELS)[key] || key;
      checkbox.onchange = () => update({action: "set_preference", instance_id: selected, type, key, enabled: checkbox.checked, require_confirmation: type === "command" && ["stop", "restart"].includes(key)}, "Preferência atualizada.", false);
      label.append(checkbox, text);
      if (type === "command" && ["stop", "restart"].includes(key)) {
        const badge = document.createElement("small"); badge.className = "integration-badge"; badge.textContent = "CONFIRMAÇÃO"; label.append(badge);
      }
      container.append(label);
    });
  }

  function render() {
    renderSummary(); renderConnections(); renderBindings();
    renderPreferences("event"); renderPreferences("command");
  }

  async function update(payload, success, rerender = true) {
    try {
      discord = await request("/api/customer/integrations/discord", {method: "POST", body: JSON.stringify(payload)});
      if (rerender) render(); else { renderSummary(); renderConnections(); renderBindings(); }
      message(success);
    } catch (error) { message(error.message, "error"); await load().catch(() => {}); }
  }

  async function load() {
    try {
      const [snapshot, runtime] = await Promise.all([
        request("/api/customer/integrations/discord"), request("/api/runtime/list"),
      ]);
      discord = snapshot;
      instances = Array.isArray(runtime) ? runtime : (runtime.resources || []);
      render();
      if (new URLSearchParams(location.search).get("discord") === "connected") {
        message("Discord conectado com sucesso."); history.replaceState({}, "", "/customer-integrations.html");
      }
    } catch (error) { message(error.message, "error"); }
  }

  document.querySelectorAll("[data-tab]").forEach(button => button.addEventListener("click", () => {
    document.querySelectorAll("[data-tab]").forEach(item => item.classList.toggle("active", item === button));
    document.querySelectorAll("[data-panel]").forEach(panel => { panel.hidden = panel.dataset.panel !== button.dataset.tab; });
  }));
  $("discord-events-instance").addEventListener("change", () => renderPreferences("event"));
  $("discord-commands-instance").addEventListener("change", () => renderPreferences("command"));
  $("discord-refresh").addEventListener("click", load);
  load();
})();
