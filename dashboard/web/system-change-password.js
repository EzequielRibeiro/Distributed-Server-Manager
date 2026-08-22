(function () {
    "use strict";
    const auth = sessionStorage.getItem("dsm_auth") || "";
    const message = document.getElementById("system-password-message");
    async function request(path, options = {}) {
        const headers = { Authorization: `Basic ${auth}`, Accept: "application/json" };
        if (options.body) headers["Content-Type"] = "application/json";
        const response = await fetch(path, { ...options, headers });
        if (response.status === 401) {
            sessionStorage.removeItem("dsm_auth");
            location.href = "/login.html";
            throw new Error("Sessão encerrada");
        }
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        return data;
    }
    async function changePassword() {
        const password = document.getElementById("system-new-password").value;
        const confirmation = document.getElementById("system-confirm-password").value;
        if (password.length < 8) throw new Error("A nova senha deve ter pelo menos 8 caracteres.");
        if (password !== confirmation) throw new Error("A confirmação da senha não corresponde.");
        await request("/api/system/auth/change-password", { method: "POST", body: JSON.stringify({ password }) });
        message.textContent = "Senha alterada. Redirecionando para o painel…";
        setTimeout(() => { location.href = "/index.html"; }, 300);
    }
    document.getElementById("system-change-password").addEventListener("click", () => changePassword().catch(error => { message.textContent = error.message; }));
    document.getElementById("system-password-logout").addEventListener("click", () => {
        sessionStorage.removeItem("dsm_auth");
        location.href = "/login.html";
    });
    if (!auth) location.href = "/login.html";
})();
