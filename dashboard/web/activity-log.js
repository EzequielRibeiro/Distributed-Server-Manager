(function () {
  "use strict";
  const byId = id => document.getElementById(id);
  const auth = sessionStorage.getItem("dsm_auth") || "";

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

  async function loadOptions() {
    const data = await request("/api/admin/activity-log/options");
    fillSelect("activity-user", data.users || []);
    fillSelect("activity-category", data.categories || []);
    fillSelect("activity-name", data.activities || []);
  }

  function isoLocal(value) {
    if (!value) return "";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : date.toISOString();
  }

  function params() {
    const query = new URLSearchParams();
    const pairs = [
      ["username", byId("activity-user").value],
      ["category", byId("activity-category").value],
      ["activity", byId("activity-name").value],
      ["result", byId("activity-result").value],
      ["start_at", isoLocal(byId("activity-start").value)],
      ["end_at", isoLocal(byId("activity-end").value)],
      ["limit", byId("activity-limit").value],
    ];
    pairs.forEach(([key, value]) => { if (value) query.set(key, value); });
    return query.toString();
  }

  function render(rows) {
    const body = byId("activity-table"); body.replaceChildren();
    rows.forEach(item => {
      const row = document.createElement("tr");
      const values = [
        item.created_at || "—",
        item.username || "—",
        item.activity || "—",
        item.category || "—",
        `${item.result || "—"}${item.status_code ? ` · ${item.status_code}` : ""}`,
        item.path || "—",
        item.remote_address || "—",
        item.session_id ? item.session_id.slice(0, 12) : "—",
      ];
      values.forEach(value => { const td = document.createElement("td"); td.textContent = value; row.appendChild(td); });
      body.appendChild(row);
    });
    byId("activity-message").textContent = `${rows.length} registro(s) exibido(s).`;
  }

  async function search() {
    const data = await request(`/api/admin/activity-log?${params()}`);
    render(data.activities || []);
  }

  function clearFilters() {
    ["activity-start", "activity-end", "activity-user", "activity-category", "activity-name", "activity-result"].forEach(id => { byId(id).value = ""; });
    byId("activity-limit").value = "200";
    search().catch(showError);
  }

  function showError(error) { byId("activity-message").textContent = error.message || String(error); }

  document.addEventListener("DOMContentLoaded", async () => {
    if (!auth) { location.replace("/login.html"); return; }
    try {
      await loadShell();
      await loadOptions();
      byId("activity-search").onclick = () => search().catch(showError);
      byId("activity-clear").onclick = clearFilters;
      await search();
    } catch (error) { showError(error); }
  });
})();
