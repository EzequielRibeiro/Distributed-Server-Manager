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
        const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
        if (response.status === 401) { sessionStorage.removeItem("dsm_auth"); location.href = "/login.html"; throw new Error("Sessão encerrada"); }
        if (response.status === 403) { location.href = "/dashboard-v3.html"; throw new Error("Acesso exclusivo de administradores"); }
        if (response.status === 428) { location.href = "/system-change-password.html"; throw new Error("Troca de senha obrigatória"); }
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.message || data.error || `HTTP ${response.status}`);
        return data;
    }

    async function logoutSession() {
        try {
            if (auth) await fetch("/api/auth/logout", { method: "POST", headers: { Authorization: `Basic ${auth}`, Accept: "application/json" }, credentials: "same-origin", cache: "no-store" });
        } catch (_error) {
        } finally {
            sessionStorage.clear(); location.replace("/login.html");
        }
    }

    async function loadAdminShell() {
        const host = byId("sidebar-component");
        if (host) {
            const response = await fetch("/components/sidebar-v3.html");
            host.innerHTML = await response.text();
            host.querySelectorAll("nav a").forEach(a => a.classList.toggle("active", a.getAttribute("href") === "users.html"));
            const logout = byId("btn-logout");
            if (logout) logout.onclick = logoutSession;
        }
        const who = await request("/api/whoami");
        if (String(who.role || "").toLowerCase() !== "admin") {
            location.replace("/dashboard-v3.html");
            throw new Error("Acesso exclusivo de administradores");
        }
        byId("admin-user-name").textContent = who.username || "—";
        byId("admin-user-role").textContent = who.role || "—";
        document.querySelectorAll(".admin-only,.agent-manager-only,.instance-manager-only").forEach(x => x.style.display = "");
        const toggle = byId("admin-menu-toggle");
        if (toggle) toggle.onclick = () => { if (innerWidth <= 760) document.body.classList.toggle("sidebar-open"); else { document.body.classList.toggle("cap-sidebar-collapsed"); localStorage.setItem("cap_sidebar_collapsed", document.body.classList.contains("cap-sidebar-collapsed") ? "1" : "0"); } };
        if (localStorage.getItem("cap_sidebar_collapsed") === "1" && innerWidth > 760) document.body.classList.add("cap-sidebar-collapsed");
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
        const adminCount = users.filter(user => user.role === "admin").length;
        users.forEach(user => {
            const row = document.createElement("tr");
            const identity = document.createElement("td");
            const strong = document.createElement("strong"); strong.textContent = user.full_name || user.username;
            const meta = document.createElement("small"); meta.textContent = `${user.username}${user.corporate_email ? ` · ${user.corporate_email}` : ""}`;
            identity.append(strong, document.createElement("br"), meta);
            row.appendChild(identity);

            const functionCell = document.createElement("td");
            const functionParts = [user.job_title, user.department].filter(Boolean);
            functionCell.textContent = functionParts.length ? functionParts.join(" · ") : "-";
            row.appendChild(functionCell);

            [user.role, user.scope_id || "-", user.active ? "Ativo" : "Desativado", user.must_change_password ? "Temporária · troca obrigatória" : "Definida"].forEach(value => {
                const cell = document.createElement("td"); cell.textContent = value; row.appendChild(cell);
            });

            const actions = document.createElement("td");
            const edit = document.createElement("button"); edit.textContent = "Editar"; edit.addEventListener("click", () => editUser(user));
            const remove = document.createElement("button"); remove.textContent = "Remover"; remove.className = "catalog-v2-danger";
            const protectedAdmin = user.role === "admin" && (user.delete_allowed === false || adminCount <= 1);
            remove.disabled = protectedAdmin;
            remove.title = protectedAdmin ? "Este administrador é necessário para manter o sistema administrável." : "Remover usuário";
            remove.addEventListener("click", () => { if (!remove.disabled) deleteUser(user.username); });
            actions.append(edit, remove); row.appendChild(actions); body.appendChild(row);
        });
    }

    function editUser(user) {
        if (!SYSTEM_ROLES.has(user.role)) return;
        editing = user.username;
        byId("user-form-title").textContent = `Editar ${user.username}`;
        byId("user-save").textContent = "Salvar alterações";
        byId("user-full-name").value = user.full_name || "";
        byId("user-email").value = user.corporate_email || "";
        byId("user-phone").value = user.phone || "";
        byId("user-job-title").value = user.job_title || "";
        byId("user-department").value = user.department || "";
        byId("user-name").value = user.username; byId("user-name").disabled = true;
        byId("user-role").value = user.role; syncScope(); byId("user-scope").value = user.scope_id || "";
        byId("user-active").value = String(user.active); byId("user-cancel").hidden = false;
    }

    function resetForm() {
        editing = null;
        byId("user-form-title").textContent = "Novo usuário do sistema";
        byId("user-save").textContent = "Criar usuário";
        ["user-full-name", "user-email", "user-phone", "user-job-title", "user-department", "user-name"].forEach(id => { byId(id).value = ""; });
        byId("user-name").disabled = false;
        byId("user-role").value = "controller"; byId("user-active").value = "true"; syncScope(); byId("user-cancel").hidden = true;
    }

    async function load() {
        const data = await request("/api/users");
        users = (data.users || []).filter(user => SYSTEM_ROLES.has(user.role));
        scopes = { controllers: (data.scopes || {}).controllers || [] }; syncScope(); render();
        const security = data.security || {};
        if (byId("admin-protection-note")) byId("admin-protection-note").textContent = `${security.admin_count || users.filter(user => user.role === "admin").length} administrador(es) cadastrado(s), ${security.active_admin_count ?? users.filter(user => user.role === "admin" && user.active).length} ativo(s). O último Admin necessário para manter o sistema administrável é protegido.`;
    }

    async function save() {
        const role = byId("user-role").value;
        if (!SYSTEM_ROLES.has(role)) throw new Error("Perfil inválido para usuário do sistema.");
        const fullName = byId("user-full-name").value.trim();
        const corporateEmail = byId("user-email").value.trim().toLowerCase();
        if (!fullName) throw new Error("Informe o nome completo.");
        if (!corporateEmail) throw new Error("Informe o e-mail corporativo.");
        const payload = {
            username: editing || byId("user-name").value.trim(),
            full_name: fullName,
            corporate_email: corporateEmail,
            phone: byId("user-phone").value.trim(),
            job_title: byId("user-job-title").value.trim(),
            department: byId("user-department").value.trim(),
            role,
            scope_id: byId("user-scope").value,
            active: byId("user-active").value === "true"
        };
        const data = await request("/api/users/save", { method: "POST", body: JSON.stringify(payload) });
        if (data.created && data.temporary_password) {
            byId("users-message").textContent = `Usuário ${data.username} criado. Senha temporária: ${data.temporary_password} — copie agora; ela deve ser substituída no primeiro acesso.`;
        } else {
            byId("users-message").textContent = "Dados funcionais e permissões atualizados com sucesso.";
        }
        resetForm(); await load();
    }

    async function deleteUser(username) {
        if (!confirm(`Remover permanentemente o acesso de ${username}?`)) return;
        await request("/api/users/delete", { method: "POST", body: JSON.stringify({ username }) });
        byId("users-message").textContent = "Usuário removido."; resetForm(); await load();
    }

    async function init() {
        if (!auth) { location.href = "/login.html"; return; }
        await loadAdminShell();
        byId("user-role").addEventListener("change", syncScope);
        byId("user-save").addEventListener("click", () => save().catch(error => { byId("users-message").textContent = error.message; }));
        byId("user-cancel").addEventListener("click", resetForm);
        await load();
    }
    document.addEventListener("DOMContentLoaded", () => init().catch(error => { if (byId("users-message")) byId("users-message").textContent = error.message; }));
})();
