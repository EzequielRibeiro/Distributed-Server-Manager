"use strict";

const API = "/api";
let currentUser = null;
let infrastructureTopology = null;

function byId(id) {
    return document.getElementById(id);
}

function authHeader() {
    const token = sessionStorage.getItem("dsm_auth");
    if (!token) {
        window.location.replace("/login.html");
        throw new Error("authentication required");
    }
    return {
        Authorization: `Basic ${token}`,
        Accept: "application/json"
    };
}

async function request(endpoint, options = {}) {
    const headers = {...authHeader(), ...(options.headers || {})};
    if (options.body) headers["Content-Type"] = "application/json";

    const response = await fetch(`${API}${endpoint}`, {...options, headers});
    if (response.status === 401) {
        sessionStorage.clear();
        window.location.replace("/login.html");
        return null;
    }

    const body = await response.json();
    if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
    return body;
}

function errorMessage(message = "") {
    const box = byId("agents-error");
    if (!box) return;
    box.hidden = !message;
    box.textContent = message;
}

async function loadSidebar() {
    const target = byId("sidebar-component");
    if (!target) return;
    const response = await fetch("/components/sidebar.html");
    if (response.ok) target.innerHTML = await response.text();

    const logout = byId("btn-logout");
    if (logout) {
        logout.addEventListener("click", () => {
            sessionStorage.clear();
            window.location.replace("/login.html");
        });
    }
}

async function loadInfrastructure() {
    infrastructureTopology = await request("/infrastructure?active_only=true");
    return infrastructureTopology;
}

async function loadAgents() {
    return null;
}

async function initializeAddAgentPage() {
    try {
        await loadSidebar();
        currentUser = await request("/whoami");
        if (!currentUser) return;
        if (!["admin", "controller"].includes(currentUser.role)) {
            throw new Error("Você não possui permissão para adicionar Agents.");
        }

        document.querySelectorAll(".admin-only").forEach(element => {
            element.style.display = currentUser.role === "admin" ? "" : "none";
        });

        await loadInfrastructure();

        const back = byId("back-to-agents");
        if (back) back.addEventListener("click", () => window.location.assign("/agents.html"));
    } catch (error) {
        errorMessage(error.message);
    }
}

document.addEventListener("DOMContentLoaded", initializeAddAgentPage);
