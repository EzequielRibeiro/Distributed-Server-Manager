/*
==================================================
 DSM Dashboard Enterprise
 Auth Module
==================================================
*/

function encodeBasicAuth(user, password) {
    const credentials = `${user}:${password}`;
    const bytes = new TextEncoder().encode(credentials);

    let binary = "";

    for (const byte of bytes) {
        binary += String.fromCharCode(byte);
    }

    return btoa(binary);
}


function saveSession(user, password) {
    sessionStorage.setItem(
        "dsm_auth",
        encodeBasicAuth(user, password)
    );
}


function getSession() {
    return sessionStorage.getItem("dsm_auth");
}


function clearSession() {
    sessionStorage.removeItem("dsm_auth");
}


function logout() {
    clearSession();
    window.location.href = "/login.html";
}


function destinationForRole(role) {
    if (role === "customer") {
        return "/customer.html";
    }

    if (["admin", "controller", "operator"].includes(role)) {
        return "/index.html";
    }

    return null;
}


async function loadAuthenticatedIdentity(token) {
    const response = await fetch(
        "/api/whoami",
        {
            method: "GET",
            headers: {
                "Authorization": `Basic ${token}`,
                "Accept": "application/json"
            },
            credentials: "same-origin",
            cache: "no-store"
        }
    );

    if (!response.ok) {
        throw new Error(`whoami HTTP ${response.status}`);
    }

    return await response.json();
}


async function login() {
    const usernameInput = document.getElementById("username");
    const passwordInput = document.getElementById("password");
    const loginButton = document.getElementById("login-button");

    const user = usernameInput.value.trim();
    const password = passwordInput.value;

    if (!user || !password) {
        showError(
            "Informe usuário e senha. | Enter username and password."
        );
        return;
    }

    loginButton.disabled = true;
    showError("");

    try {
        const token = encodeBasicAuth(user, password);

        const response = await fetch(
            "/api/auth/login",
            {
                method: "POST",
                headers: {
                    "Authorization": `Basic ${token}`,
                    "Accept": "application/json"
                },
                credentials: "same-origin",
                cache: "no-store"
            }
        );

        if (!response.ok) {
            if (response.status === 401) {
                showError(
                    "Usuário ou senha inválidos. | Invalid username or password."
                );
            } else if (response.status === 403) {
                showError(
                    "Usuário sem acesso ao Controller. | User cannot access Controller."
                );
            } else {
                showError(
                    `Erro HTTP ${response.status}.`
                );
            }
            return;
        }

        await response.json();

        // Compatibilidade temporária com APIs existentes que
        // ainda utilizam Basic Authentication.
        saveSession(user, password);

        const identity = await loadAuthenticatedIdentity(token);
        const destination = destinationForRole(identity?.role);

        if (!destination) {
            clearSession();
            showError(
                "Perfil de acesso não reconhecido. | Unknown access profile."
            );
            return;
        }

        window.location.replace(destination);

    } catch (error) {
        console.error("Login error:", error);
        clearSession();

        showError(
            "Erro de comunicação com servidor. | Server communication error."
        );
    } finally {
        loginButton.disabled = false;
    }
}

function showError(message) {
    const element = document.getElementById(
        "login-error"
    );

    if (element) {
        element.textContent = message;
    }
}


document.addEventListener(
    "DOMContentLoaded",
    () => {
        const loginButton =
            document.getElementById(
                "login-button"
            );

        const usernameInput =
            document.getElementById(
                "username"
            );

        const passwordInput =
            document.getElementById(
                "password"
            );

        const btnLogout =
            document.getElementById(
                "btn-logout"
            );

        if (loginButton) {
            loginButton.addEventListener(
                "click",
                login
            );
        }

        if (passwordInput) {
            passwordInput.addEventListener(
                "keydown",
                event => {
                    if (event.key === "Enter") {
                        event.preventDefault();
                        login();
                    }
                }
            );
        }

        if (usernameInput) {
            usernameInput.addEventListener(
                "keydown",
                event => {
                    if (event.key === "Enter") {
                        event.preventDefault();

                        if (passwordInput) {
                            passwordInput.focus();
                        }
                    }
                }
            );
        }

        if (btnLogout) {
            btnLogout.addEventListener(
                "click",
                logout
            );
        }
    }
);