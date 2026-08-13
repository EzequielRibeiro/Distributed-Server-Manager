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
        const token = encodeBasicAuth(
            user,
            password
        );

        const response = await fetch(
            "/api/whoami",
            {
                method: "GET",

                headers: {
                    "Authorization": `Basic ${token}`,
                    "Accept": "application/json"
                },

                cache: "no-store"
            }
        );

        if (!response.ok) {
            if (response.status === 401) {
                showError(
                    "Usuário ou senha inválidos. | Invalid username or password."
                );
            } else {
                showError(
                    `Erro HTTP ${response.status}.`
                );
            }

            return;
        }

        const session = await response.json();

        saveSession(
            user,
            password
        );

        if (
            session.role === "client"
            || session.role === "customer"
        ) {
            window.location.replace(
                "/customer.html"
            );
        } else {
            window.location.replace(
                "/index.html"
            );
        }

    } catch (error) {
        console.error(
            "Login error:",
            error
        );

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