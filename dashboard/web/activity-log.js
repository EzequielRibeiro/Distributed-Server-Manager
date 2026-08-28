(function () {
  "use strict";
  const byId = id => document.getElementById(id);
  const auth = sessionStorage.getItem("dsm_auth") || "";
  const actorState = { offset: 0, hasMore: false, showAll: false, query: "" };
  const roleLabels = {
    admin: "Administrador",
    controller: "Controlador",
    operator: "Operador",
    customer: "Cliente",
  };

  async function request(path) {
    const response = await fetch(path, {
      headers: { Authorization: `Basic ${auth}`, Accept: "application/json" },
      credentials: "same-origin",
      cache: "no-store",
    });
    if (response.status === 401) { sessionStorage.clear(); location.replace("/login.html"); throw new Error("Sessão encerrada"); }
    if (response.status === 403) { location.replace("/dashboard-v3.html"); throw new Error("Acesso exclusivo de administradores"); }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || data.error || `HTTP ${response.status}`);
    return data;
  }

  async function loadShell() {
    const sidebar = byId("sidebar-component");
    if (sidebar) {
      const response = await fetch("/components/sidebar-v3.html");
      sidebar.innerHTML = await response.text();
      sidebar.querySelectorAll("nav a").forEach(a => a.classList.toggle("active", a.getAttribute("href") === "activity-log.html"));
      const logout = byId("btn-logout");
      if (logout) logout.onclick = async () => {
        try { await fetch("/api/auth/logout", { method: "POST", headers: { Authorization: `Basic ${auth}` }, credentials: "same-origin" }); } catch (_) {}
        sessionStorage.clear(); location.replace("/login.html");
      };
    }
    const who = await request("/api/whoami");
    if (String(who.role || "").toLowerCase() !== "admin") throw new Error("Acesso exclusivo de administradores");
    byId("admin-user-name").textContent = who.username || "—";
    byId("admin-user-role").textContent = who.role || "—";
    const toggle = byId("admin-menu-toggle");
    if (toggle) toggle.onclick = () => document.body.classList.toggle("cap-sidebar-collapsed");
  }

  function fillSelect(id, values) {
    const select = byId(id);
    const first = select.options[0];
    select.replaceChildren(first, ...values.map(value => new Option(value, value)));
  }

  function fillRoles(values) {
    const select = byId("activity-role");
    const first = select.options[0];
    const normalized = [...new Set((values || []).map(value => String(value || "").trim().toLowerCase()).filter(Boolean))];
    select.replaceChildren(
      first,
      ...normalized.map(value => new Option(roleLabels[value] || value, value))
    );
  }

  async function loadOptions() {
    const data = await request("/api/admin/activity-log/options");
    fillRoles(data.actor_roles || ["admin", "controller", "operator", "customer"]);
    fillSelect("activity-category", data.categories || []);
    fillSelect("activity-name", data.actions || []);
  }

  function resetActors(message) {
    const select = byId("activity-user");
    select.replaceChildren(new Option("Qualquer usuário da categoria", ""));
    actorState.offset = 0;
    actorState.hasMore = false;
    actorState.showAll = false;
    actorState.query = "";
    byId("activity-more-users").hidden = true;
    if (message) byId("activity-user-message").textContent = message;
  }

  function actorLabel(actor) {
    const name = String(actor.actor_name || actor.actor_id || "Usuário");
    const parts = [];
    if (actor.email) parts.push(String(actor.email));
    if (actor.customer_code) parts.push(String(actor.customer_code));
    else if (actor.document_number) parts.push(String(actor.document_number));
    if (actor.actor_id && actor.actor_id !== name) parts.push(String(actor.actor_id));
    if (actor.historical) parts.push("histórico");
    return parts.length ? `${name} · ${parts.join(" · ")}` : name;
  }

  function appendActors(actors, append) {
    const select = byId("activity-user");
    const previous = append ? select.value : "";
    if (!append) select.replaceChildren(new Option("Qualquer usuário da categoria", ""));
    const existing = new Set(Array.from(select.options).map(option => option.value));
    (actors || []).forEach(actor => {
      const id = String(actor.actor_id || "").trim();
      if (!id || existing.has(id)) return;
      const option = new Option(actorLabel(actor), id);
      option.dataset.role = String(actor.actor_role || "");
      select.appendChild(option);
      existing.add(id);
    });
    if (append && previous && existing.has(previous)) select.value = previous;
  }

  async function loadActors({ append = false, showAll = false } = {}) {
    const term = String(byId("activity-user-query").value || "").trim();
    if (!showAll && !term) {
      resetActors("Informe nome, e-mail, documento, login ou ID, ou use “Mostrar lista completa”.");
      return;
    }
    const offset = append ? actorState.offset : 0;
    const query = new URLSearchParams();
    const role = byId("activity-role").value;
    if (role) query.set("role", role);
    if (term) query.set("q", term);
    if (showAll) query.set("show_all", "true");
    query.set("limit", "100");
    query.set("offset", String(offset));

    byId("activity-user-message").textContent = append ? "Carregando mais usuários…" : "Buscando usuários…";
    const data = await request(`/api/admin/activity-log/actors?${query.toString()}`);
    appendActors(data.actors || [], append);
    actorState.offset = Number(data.next_offset || 0);
    actorState.hasMore = Boolean(data.has_more);
    actorState.showAll = showAll;
    actorState.query = term;
    byId("activity-more-users").hidden = !actorState.hasMore;
    const total = Number(data.total || 0);
    const shown = Math.min(actorState.offset, total);
    if (!total) {
      byId("activity-user-message").textContent = "Nenhum usuário encontrado para os filtros informados.";
    } else if (actorState.hasMore) {
      byId("activity-user-message").textContent = `${shown} de ${total} usuário(s) carregado(s). Use “Carregar mais” para continuar.`;
    } else {
      byId("activity-user-message").textContent = `${total} usuário(s) encontrado(s). Selecione um usuário ou mantenha “Qualquer usuário da categoria”.`;
    }
  }

  function isoLocal(value) {
    if (!value) return "";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : date.toISOString();
  }

  function params() {
    const query = new URLSearchParams();
    const pairs = [
      ["actor_role", byId("activity-role").value],
      ["actor_id", byId("activity-user").value],
      ["category", byId("activity-category").value],
      ["action", byId("activity-name").value],
      ["result", byId("activity-result").value],
      ["start_at", isoLocal(byId("activity-start").value)],
      ["end_at", isoLocal(byId("activity-end").value)],
      ["limit", byId("activity-limit").value],
    ];
    pairs.forEach(([key, value]) => { if (value) query.set(key, value); });
    return query.toString();
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("pt-BR");
  }

  function render(rows) {
    const body = byId("activity-table");
    body.replaceChildren();
    rows.forEach(item => {
      const row = document.createElement("tr");
      const values = [
        formatDate(item.occurred_at),
        item.actor_name || item.actor_id || "—",
        item.summary || "—",
        item.category || "—",
        item.result || "—",
        item.target_name || item.target_id || "—",
      ];
      values.forEach(value => {
        const td = document.createElement("td");
        td.textContent = value;
        row.appendChild(td);
      });
      body.appendChild(row);
    });
    byId("activity-message").textContent = `${rows.length} registro(s) exibido(s).`;
  }

  async function search() {
    const data = await request(`/api/admin/activity-log?${params()}`);
    render(data.activities || []);
  }

  function clearFilters() {
    ["activity-start", "activity-end", "activity-role", "activity-user-query", "activity-user", "activity-category", "activity-name", "activity-result"].forEach(id => { byId(id).value = ""; });
    byId("activity-limit").value = "200";
    resetActors("Selecione uma categoria de acesso e pesquise por nome, e-mail, documento, login ou ID. Também é possível mostrar a lista completa.");
    search().catch(showError);
  }

  function showError(error) {
    const message = error.message || String(error);
    byId("activity-message").textContent = message;
    if (byId("activity-user-message")) byId("activity-user-message").textContent = message;
  }

  document.addEventListener("DOMContentLoaded", async () => {
    if (!auth) { location.replace("/login.html"); return; }
    try {
      await loadShell();
      await loadOptions();
      byId("activity-search").onclick = () => search().catch(showError);
      byId("activity-clear").onclick = clearFilters;
      byId("activity-find-user").onclick = () => loadActors({ showAll: false }).catch(showError);
      byId("activity-show-users").onclick = () => loadActors({ showAll: true }).catch(showError);
      byId("activity-more-users").onclick = () => loadActors({ append: true, showAll: actorState.showAll }).catch(showError);
      byId("activity-role").onchange = () => resetActors("Categoria alterada. Pesquise um usuário ou use “Mostrar lista completa”.");
      byId("activity-user-query").oninput = () => {
        if (byId("activity-user").value) byId("activity-user").value = "";
      };
      byId("activity-user-query").onkeydown = event => {
        if (event.key === "Enter") {
          event.preventDefault();
          loadActors({ showAll: false }).catch(showError);
        }
      };
      await search();
    } catch (error) { showError(error); }
  });
})();
