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

  async function load() {
    const response = await fetch("/api/instance/delete/backups", {
      headers: {Authorization: `Basic ${auth()}`, Accept: "application/json"},
    });
    if (!response.ok) return;
    const data = await response.json();
    const backups = Array.isArray(data.backups) ? data.backups : [];
    if (!backups.length) return;

    const main = document.querySelector(".customer-main");
    if (!main) return;
    const section = document.createElement("section");
    section.className = "customer-section";
    const heading = document.createElement("div");
    heading.className = "section-heading";
    heading.innerHTML = "<div><p class=\"customer-label\">BACKUPS PENDENTES</p><h2>Backups de instâncias excluídas</h2><p>Baixe os arquivos preservados. O backup será removido do servidor somente após a transferência ser concluída com sucesso.</p></div>";
    const grid = document.createElement("div");
    grid.className = "server-grid";

    backups.forEach(item => {
      const card = document.createElement("article");
      card.className = "server-card";
      const label = document.createElement("span");
      label.className = "game";
      label.textContent = "BACKUP DISPONÍVEL";
      const title = document.createElement("h3");
      title.textContent = item.instance_id || "Instância excluída";
      const detail = document.createElement("p");
      detail.textContent = `${item.game || "Servidor"} · ${formatBytes(item.backup_size)}`;
      const actions = document.createElement("div");
      actions.className = "server-actions";
      const download = document.createElement("button");
      download.type = "button";
      download.textContent = "Baixar backup";
      download.addEventListener("click", () => {
        const url = `/api/instance/delete/backup?${new URLSearchParams({instance: item.instance_id})}`;
        const link = document.createElement("a");
        link.href = url;
        link.style.display = "none";
        document.body.append(link);
        link.click();
        link.remove();
        window.setTimeout(() => location.reload(), 2000);
      });
      actions.append(download);
      card.append(label, title, detail, actions);
      grid.append(card);
    });
    section.append(heading, grid);
    const message = document.getElementById("customer-message");
    main.insertBefore(section, message || null);
  }

  load().catch(() => {});
})();
