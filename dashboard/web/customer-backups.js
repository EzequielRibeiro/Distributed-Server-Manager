(function () {
  "use strict";

  const $ = id => document.getElementById(id);

  async function request(path) {
    const response = await fetch(path, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
      cache: "no-store",
    });

    if (response.status === 401) {
      location.replace("/customer-login.html");
      throw new Error("Sessão encerrada.");
    }

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.message || data.error || `HTTP ${response.status}`);
    }
    return data;
  }

  function fmtBytes(value) {
    let n = Number(value || 0);
    if (!n) return "—";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let index = 0;
    while (n >= 1024 && index < units.length - 1) {
      n /= 1024;
      index += 1;
    }
    return `${n.toLocaleString("pt-BR", {maximumFractionDigits: 1})} ${units[index]}`;
  }

  function instanceUrl(item) {
    return "/customer-instance.html?" + new URLSearchParams({
      server: item.server || "",
      game: item.game || "",
      instance: item.instance || item.id || "",
    });
  }

  async function loadCard(item) {
    const instanceId = String(item.instance || item.id || "");
    const card = document.createElement("article");
    card.className = "integration-card";
    card.innerHTML = `<div class="integration-card-head"><div><span class="integration-badge">${item.game || "SERVIDOR"}</span><h3>${item.display_name || item.name || instanceId}</h3><p class="integration-muted">${instanceId}</p></div><span class="integration-status">Consultando</span></div><div class="integration-list"></div><div class="integration-actions" style="margin-top:14px"><a class="button" href="${instanceUrl(item)}">Gerenciar servidor</a></div>`;

    const status = card.querySelector(".integration-status");
    const list = card.querySelector(".integration-list");

    try {
      const [jobs, policy] = await Promise.all([
        request(`/api/customer/instance/workspace/backups?instance_id=${encodeURIComponent(instanceId)}`),
        request(`/api/customer/instance/workspace/backup-policy?instance_id=${encodeURIComponent(instanceId)}`),
      ]);
      const completed = (jobs.jobs || [])
        .filter(job => job.action === "create" && job.status === "completed")
        .slice(0, 1)[0];
      status.textContent = completed ? "Protegido" : "Sem backup";
      status.classList.add(completed ? "online" : "warning");
      list.innerHTML = `<div><strong>Último backup</strong><small class="integration-muted">${completed ? `${completed.backup_id || "backup"} · ${fmtBytes(completed.size_bytes)}` : "Nenhum backup operacional disponível"}</small></div><div><strong>Backup automático</strong><small class="integration-muted">${policy.enabled === false ? "Desabilitado" : `Ativo · ${policy.schedule_time || "04:00"} · ${policy.schedule_timezone || "UTC"}`}</small></div>`;
    } catch (error) {
      status.textContent = "Indisponível";
      status.classList.add("warning");
      list.innerHTML = `<div class="integration-notice">${error.message}</div>`;
    }
    return card;
  }

  async function load() {
    const grid = $("customer-backup-grid");
    try {
      await request("/api/customer/auth/session");
      const runtime = await request("/api/runtime/list");
      const instances = Array.isArray(runtime) ? runtime : (runtime.resources || []);
      if (!instances.length) {
        grid.innerHTML = '<div class="integration-empty">Nenhum servidor criado.</div>';
        return;
      }
      const cards = await Promise.all(instances.map(loadCard));
      grid.replaceChildren(...cards);
    } catch (error) {
      grid.innerHTML = `<div class="integration-notice">${error.message}</div>`;
    }
  }

  load();
})();
