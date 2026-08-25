(function () {
  "use strict";

  const auth = () => sessionStorage.getItem("dsm_auth") || "";

  function formatBytes(value) {
    const bytes = Number(value) || 0;
    if (bytes < 1024) return `${bytes} B`;
    const units = ["KB", "MB", "GB", "TB"];
    let size = bytes / 1024;
    let unit = units[0];
    for (let index = 1; index < units.length && size >= 1024; index += 1) {
      size /= 1024;
      unit = units[index];
    }
    return `${size.toLocaleString("pt-BR", {maximumFractionDigits: 2})} ${unit}`;
  }

  async function json(path) {
    const response = await fetch(path, {headers: {Authorization: `Basic ${auth()}`, Accept: "application/json"}});
    if (!response.ok) return null;
    return response.json();
  }

  function insertSection(section) {
    const main = document.querySelector(".customer-main");
    if (!main) return;
    const message = document.getElementById("customer-message");
    main.insertBefore(section, message || null);
  }

  async function loadSharedInstances() {
    const data = await json("/api/customer/shared-instances");
    const instances = Array.isArray(data?.instances) ? data.instances : [];
    if (!instances.length) return;
    const section = document.createElement("section");
    section.className = "customer-section";
    const heading = document.createElement("div");
    heading.className = "section-heading";
    heading.innerHTML = "<div><p class=\"customer-label\">EQUIPE</p><h2>Servidores compartilhados comigo</h2><p>Instâncias que você pode administrar conforme as permissões concedidas pelo proprietário.</p></div>";
    const grid = document.createElement("div");
    grid.className = "server-grid";
    instances.forEach(item => {
      const card = document.createElement("article");
      card.className = "server-card";
      const label = document.createElement("span"); label.className = "game"; label.textContent = String(item.game_id || "Servidor").toUpperCase();
      const title = document.createElement("h3"); title.textContent = item.name || item.id;
      const detail = document.createElement("p"); detail.textContent = `${item.status || "desconhecido"} · ${(item.permissions || []).length} permissão(ões)`;
      const actions = document.createElement("div"); actions.className = "server-actions";
      const open = document.createElement("button"); open.type = "button"; open.textContent = "Administrar instância";
      open.addEventListener("click", () => { location.href = `/customer-instance.html?${new URLSearchParams({instance: item.id, game: item.game_id || ""})}`; });
      actions.append(open); card.append(label, title, detail, actions); grid.append(card);
    });
    section.append(heading, grid); insertSection(section);
  }

  async function loadDeletedBackups() {
    const data = await json("/api/instance/delete/backups");
    const backups = Array.isArray(data?.backups) ? data.backups : [];
    if (!backups.length) return;
    const section = document.createElement("section");
    section.className = "customer-section";
    const heading = document.createElement("div");
    heading.className = "section-heading";
    heading.innerHTML = "<div><p class=\"customer-label\">BACKUPS PENDENTES</p><h2>Backups de instâncias excluídas</h2><p>Baixe os arquivos preservados antes da expiração.</p></div>";
    const grid = document.createElement("div"); grid.className = "server-grid";
    backups.forEach(item => {
      const card = document.createElement("article"); card.className = "server-card";
      const label = document.createElement("span"); label.className = "game"; label.textContent = "BACKUP DISPONÍVEL";
      const title = document.createElement("h3"); title.textContent = item.instance_id || "Instância excluída";
      const detail = document.createElement("p"); detail.textContent = `${item.game || "Servidor"} · ${formatBytes(item.backup_size)}${item.expires_at ? ` · expira ${item.expires_at}` : ""}`;
      const actions = document.createElement("div"); actions.className = "server-actions";
      const download = document.createElement("button"); download.type = "button"; download.textContent = "Baixar backup";
      download.addEventListener("click", () => {
        const link = document.createElement("a"); link.href = `/api/instance/delete/backup?${new URLSearchParams({instance: item.instance_id})}`; link.style.display = "none"; document.body.append(link); link.click(); link.remove();
      });
      actions.append(download); card.append(label, title, detail, actions); grid.append(card);
    });
    section.append(heading, grid); insertSection(section);
  }

  Promise.allSettled([loadSharedInstances(), loadDeletedBackups()]);
})();
