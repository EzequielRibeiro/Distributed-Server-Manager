/*
==================================================
 Capivara DSM
 Controller Browser Authentication
==================================================
*/

function encodeBasicAuth(user, password) {
    const credentials = `${user}:${password}`;
    const bytes = new TextEncoder().encode(credentials);
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary);
}

async function logout() {
    try {
        await fetch("/api/auth/logout", {
            method: "POST",
            credentials: "same-origin",
            headers: {Accept: "application/json"},
            cache: "no-store"
        });
    } catch (error) {
        console.warn("Logout request failed:", error);
    } finally {
        sessionStorage.removeItem("dsm_auth");
        sessionStorage.removeItem("dsm_customer_auth");
        window.location.replace("/login.html");
    }
}

function destinationForRole(role) {
    if (["admin", "controller", "operator"].includes(role)) {
        return "/dashboard-v3.html";
    }
    return null;
}

async function loadBrowserSession() {
    const response = await fetch("/api/auth/session", {
        method: "GET",
        credentials: "same-origin",
        headers: {Accept: "application/json"},
        cache: "no-store"
    });
    if (!response.ok) return null;
    return await response.json();
}

async function login() {
    const usernameInput = document.getElementById("username");
    const passwordInput = document.getElementById("password");
    const loginButton = document.getElementById("login-button");
    const user = usernameInput.value.trim();
    const password = passwordInput.value;

    if (!user || !password) {
        showError("Informe usuário e senha. | Enter username and password.");
        return;
    }

    loginButton.disabled = true;
    showError("");

    try {
        const token = encodeBasicAuth(user, password);
        const response = await fetch("/api/auth/login", {
            method: "POST",
            headers: {
                "Authorization": `Basic ${token}`,
                "Accept": "application/json"
            },
            credentials: "same-origin",
            cache: "no-store"
        });

        if (!response.ok) {
            if (response.status === 401) {
                showError("Usuário ou senha inválidos. | Invalid username or password.");
            } else if (response.status === 429) {
                showError("Muitas tentativas. Aguarde e tente novamente. | Too many attempts.");
            } else {
                showError(`Erro HTTP ${response.status}.`);
            }
            return;
        }

        const identity = await response.json();
        const destination = destinationForRole(identity?.role);
        if (!destination) {
            await logout();
            return;
        }

        // Remove every legacy credential copy. The Basic value existed only
        // during this request; normal navigation now relies on the HttpOnly
        // Controller session cookie.
        sessionStorage.removeItem("dsm_auth");
        sessionStorage.removeItem("dsm_customer_auth");
        window.location.replace(destination);
    } catch (error) {
        console.error("Login error:", error);
        showError("Erro de comunicação com servidor. | Server communication error.");
    } finally {
        loginButton.disabled = false;
    }
}

function showError(message) {
    const element = document.getElementById("login-error");
    if (element) element.textContent = message;
}

async function redirectEstablishedControllerSession() {
    try {
        const identity = await loadBrowserSession();
        const destination = destinationForRole(identity?.role);
        if (destination) window.location.replace(destination);
    } catch (_) {
        // Login form remains available when there is no valid session.
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const loginButton = document.getElementById("login-button");
    const usernameInput = document.getElementById("username");
    const passwordInput = document.getElementById("password");
    const btnLogout = document.getElementById("btn-logout");

    if (loginButton) loginButton.addEventListener("click", login);
    if (passwordInput) {
        passwordInput.addEventListener("keydown", event => {
            if (event.key === "Enter") {
                event.preventDefault();
                login();
            }
        });
    }
    if (usernameInput) {
        usernameInput.addEventListener("keydown", event => {
            if (event.key === "Enter") {
                event.preventDefault();
                if (passwordInput) passwordInput.focus();
            }
        });
    }
    if (btnLogout) btnLogout.addEventListener("click", logout);
    if (loginButton) redirectEstablishedControllerSession();
});
