(function () {
  "use strict";

  const $ = id => document.getElementById(id);
  const identity = Object.fromEntries(new URLSearchParams(location.search));
  let polling = false;

  async function api(path, options = {}) {
    const headers = {Accept: "application/json", "X-Capivara-Auth-Area": "customer"};
    if (options.body) headers["Content-Type"] = "application/json";
    const response = await fetch(path, {...options, headers, credentials: "same-origin", cache: options.cache || "no-store"});
    if (response.status === 401) {
      location.replace("/customer-login.html");
      throw new Error("Sessão encerrada");
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok && response.status !== 409) throw new Error(data.error || data.message || `HTTP ${response.status}`);
    return {status: response.status, data};
  }

  function formatBytes(value) {
    const bytes = Number(value) || 0;
    if (bytes < 1024) return `${bytes} B`;
    const units = ["KB", "MB", "GB", "TB"];
    let size = bytes / 1024;
    let unit = units[0];
    for (let i = 1; i < units.length && size >= 1024; i += 1) {
      size /= 1024;
      unit = units[i];
    }
    return `${size.toLocaleString("pt-BR", {maximumFractionDigits: 2})} ${unit}`;
  }

  function setControlsHidden(hidden) {
    const checkbox = $("delete-backup");
    const confirmation = $("delete-confirm");
    const button = $("instance-delete");
    if (checkbox?.parentElement) checkbox.parentElement.hidden = hidden;
    if (confirmation) confirmation.hidden = hidden;
    if (confirmation?.previousElementSibling) confirmation.previousElementSibling.hidden = hidden;
    if (button) button.hidden = hidden;
  }

  function render(operation) {
    const active = Boolean(operation?.active);
    if (!active) {
      if (operation?.state === "completed") {
        setControlsHidden(true);
        const box = $("delete-progress");
        box.hidden = false;
        $("delete-progress-label").textContent = "Instância excluída com sucesso.";
        $("delete-progress-value").textContent = "100%";
        $("delete-progress-bar").style.width = "100%";
        window.setTimeout(() => { location.replace("/customer.html"); }, 800);
      } else if (operation?.state === "failed") {
        setControlsHidden(false);
        $("delete-progress").hidden = true;
      }
      return;
    }

    setControlsHidden(true);
    const box = $("delete-progress");
    box.hidden = false;
    const value = Math.max(0, Math.min(100, Number(operation.progress) || 0));
    $("delete-progress-label").textContent = "Exclusão da instância em andamento\n\nCriando backup final…";
    $("delete-progress-value").textContent = `${value}%`;
    $("delete-progress-bar").style.width = `${value}%`;
    const small = box.querySelector("small");
    if (small) {
      const done = formatBytes(operation.processed_bytes);
      const total = formatBytes(operation.total_bytes);
      small.textContent = `${done} de ${total}\n\nVocê pode fechar esta página.\nA operação continuará sendo executada pelo Capivara.`;
      small.style.whiteSpace = "pre-line";
    }
  }

  async function status() {
    const params = new URLSearchParams(identity);
    const result = await api(`/api/instance/delete/status?${params}`);
    render(result.data);
    return result.data;
  }

  async function poll() {
    if (polling) return;
    polling = true;
    try {
      const current = await status();
      if (current.active) window.setTimeout(() => { polling = false; poll(); }, 1500);
      else polling = false;
    } catch (_) {
      polling = false;
      window.setTimeout(poll, 3000);
    }
  }

  async function start(event) {
    event.preventDefault();
    event.stopImmediatePropagation();
    if ($("delete-confirm").value !== identity.instance) return;
    setControlsHidden(true);
    const result = await api("/api/instance/delete", {
      method: "POST",
      body: JSON.stringify({...identity, confirmation: identity.instance, final_backup: $("delete-backup").checked})
    });
    render({...result.data, active: true});
    polling = false;
    poll();
  }

  const button = $("instance-delete");
  if (button) button.addEventListener("click", event => start(event).catch(() => { setControlsHidden(false); }), true);
  poll();
})();
