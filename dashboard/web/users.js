(function () {
    "use strict";
    const byId = id => document.getElementById(id);
    const auth = sessionStorage.getItem("dsm_auth") || "";
    let users = [];
    let scopes = { controllers: [] };
    let editing = null;
    const SYSTEM_ROLES = new Set(["admin", "controller", "operator"]);

    async function request(path, options = {}) {
        const headers = { Authorization: `Basic ${auth}`, Accept: "application/json" };
        if (options.body) headers["Content-Type"] = "application/json";
        const response = await fetch(path, { ...options, headers });
        if (response.status === 401) { sessionStorage.removeItem("dsm_auth"); location.href = "/login.html"; throw new Error("Sessão encerrada"); }
        if (response.status === 403) { location.href = "/index.html"; throw new Error("Acesso exclusivo do administrador"); }
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        return data;
    }

    function syncScope() {
        const role = byId("user-role").value;
        const select = byId("user-scope");
        const items = role === "controller" ? (scopes.controllers || []) : [];
        select.replaceChildren(new Option(items.length ? "Selecione o vínculo" : "Não aplicável", ""), ...items.map(item => new Option(`${item.name} · ${item.id}`, item.id)));
        select.disabled = !items.length;
    }

    function render() {
        const body = byId("users-table"); body.replaceChildren();
        users.forEach(user => {
            const row = document.createElement("tr");
            [user.username, user.role, user.scope_id || "-", user.active ? "Ativo" : "Desativado"].forEach(value => { const cell = document.createElement("td"); cell.textContent = value; row.appendChild(cell); });
            const actions = document.createElement("td");
            const edit = document.createElement("button"); edit.textContent = "Editar"; edit.addEventListener("click", () => editUser(user));
            const remove = document.createElement("button"); remove.textContent = "Remover"; remove.className = "catalog-v2-danger"; remove.addEventListener("click", () => deleteUser(user.username));
            actions.append(edit, remove); row.appendChild(actions); body.appendChild(row);
        });
    }

    function editUser(user) {
        if (!SYSTEM_ROLES.has(user.role)) return;
        editing = user.username; byId("user-form-title").textContent = `Editar ${user.username}`;
        byId("user-name").value = user.username; byId("user-name").disabled = true;
        byId("user-role").value = user.role; syncScope(); byId("user-scope").value = user.scope_id || "";
        byId("user-password").value = ""; byId("user-active").value = String(user.active); byId("user-cancel").hidden = false;
    }

    function resetForm() {
        editing = null; byId("user-form-title").textContent = "Novo usuário do sistema";
        byId("user-name").disabled = false; byId("user-name").value = ""; byId("user-password").value = "";
        byId("user-role").value = "controller"; byId("user-active").value = "true"; syncScope(); byId("user-cancel").hidden = true;
    }

    async function load() {
        const data = await request("/api/users");
        users = (data.users || []).filter(user => SYSTEM_ROLES.has(user.role));
        scopes = { controllers: (data.scopes || {}).controllers || [] }; syncScope(); render();
    }

    async function save() {
        const role = byId("user-role").value;
        if (!SYSTEM_ROLES.has(role)) throw new Error("Perfis de cliente devem ser administrados na página Clientes.");
        const payload = { username: editing || byId("user-name").value.trim(), role, scope_id: byId("user-scope").value, password: byId("user-password").value, active: byId("user-active").value === "true" };
        await request("/api/users/save", { method: "POST", body: JSON.stringify(payload) });
        byId("users-message").textContent = "Usuário do sistema salvo com sucesso."; resetForm(); await load();
    }

    async function deleteUser(username) {
        if (!confirm(`Remover o acesso de ${username}?`)) return;
        await request("/api/users/delete", { method: "POST", body: JSON.stringify({ username }) });
        byId("users-message").textContent = "Usuário removido."; resetForm(); await load();
    }

    byId("user-role").addEventListener("change", syncScope);
    byId("user-save").addEventListener("click", () => save().catch(error => { byId("users-message").textContent = error.message; }));
    byId("user-cancel").addEventListener("click", resetForm);
    byId("users-logout").addEventListener("click", () => { sessionStorage.removeItem("dsm_auth"); location.href = "/login.html"; });
    if (!auth) location.href = "/login.html"; else load().catch(error => { byId("users-message").textContent = error.message; });
})();
