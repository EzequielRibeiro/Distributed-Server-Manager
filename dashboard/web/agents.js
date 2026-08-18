
"use strict";

const API = "/api";

let currentUser = null;
let selectedAgent = null;


function authHeader() {
    const token =
        sessionStorage.getItem(
            "dsm_auth"
        );

    if (!token) {
        window.location.replace(
            "/login.html"
        );

        throw new Error(
            "authentication required"
        );
    }

    return {
        Authorization:
            `Basic ${token}`,
        Accept:
            "application/json"
    };
}


async function request(
    endpoint,
    options = {}
) {
    const headers = {
        ...authHeader(),
        ...(options.headers || {})
    };

    if (options.body) {
        headers[
            "Content-Type"
        ] = "application/json";
    }

    const response = await fetch(
        `${API}${endpoint}`,
        {
            ...options,
            headers
        }
    );

    if (response.status === 401) {
        sessionStorage.clear();

        window.location.replace(
            "/login.html"
        );

        return null;
    }

    const body = await response.json();

    if (!response.ok) {
        throw new Error(
            body.error
            || `HTTP ${response.status}`
        );
    }

    return body;
}


function errorMessage(message = "") {
    const box =
        document.getElementById(
            "agents-error"
        );

    if (!message) {
        box.hidden = true;
        box.textContent = "";
        return;
    }

    box.hidden = false;
    box.textContent = message;
}


async function loadSidebar() {
    const target =
        document.getElementById(
            "sidebar-component"
        );

    const response = await fetch(
        "/components/sidebar.html"
    );

    if (response.ok) {
        target.innerHTML =
            await response.text();
    }

    const logout =
        document.getElementById(
            "btn-logout"
        );

    if (logout) {
        logout.onclick = () => {
            sessionStorage.clear();

            window.location.replace(
                "/login.html"
            );
        };
    }
}


function applyRole() {
    document
        .querySelectorAll(
            ".admin-only"
        )
        .forEach(element => {
            element.style.display =
                currentUser.role
                === "admin"
                ? ""
                : "none";
        });

    document
        .querySelectorAll(
            ".agent-manager-only"
        )
        .forEach(element => {
            element.style.display =
                [
                    "admin",
                    "controller"
                ].includes(
                    currentUser.role
                )
                ? ""
                : "none";
        });

    const force =
        document.getElementById(
            "force-wrapper"
        );

    force.hidden =
        currentUser.role
        !== "admin";
}


function agentCard(agent) {
    const card =
        document.createElement(
            "article"
        );

    card.className =
        "agent-card";

    card.innerHTML = `
        <h2>${agent.name}</h2>
        <div class="agent-status">
            ${agent.status}
        </div>
        <p>Agent: ${agent.id}</p>
        <p>Node: ${agent.node_id}</p>
        <p>
            Instâncias:
            ${agent.instance_count || 0}
        </p>
    `;

    card.onclick = () =>
        loadAgent(
            agent.id
        );

    return card;
}


async function loadAgents() {
    errorMessage();

    try {
        const result =
            await request(
                "/agents"
            );

        const list =
            document.getElementById(
                "agents-list"
            );

        list.innerHTML = "";

        for (
            const agent
            of result.agents
        ) {
            list.appendChild(
                agentCard(agent)
            );
        }
    } catch (error) {
        errorMessage(
            error.message
        );
    }
}


function rangeCard(item) {
    const card =
        document.createElement(
            "article"
        );

    card.className =
        "range-card";

    if (
        item.near_exhaustion
    ) {
        card.classList.add(
            "near-exhaustion"
        );
    }

    card.innerHTML = `
        <h3>
            ${item.protocol.toUpperCase()}
            ${item.start_port}-${item.end_port}
        </h3>

        <div class="range-row">
            <span>Capacidade</span>
            <strong>${item.capacity}</strong>
        </div>

        <div class="range-row">
            <span>Reservadas</span>
            <strong>${item.reserved}</strong>
        </div>

        <div class="range-row">
            <span>Disponíveis</span>
            <strong>${item.available}</strong>
        </div>

        <div class="range-row">
            <span>Uso</span>
            <strong>
                ${item.usage_pct}%
            </strong>
        </div>
    `;

    return card;
}


async function loadAgent(
    agentId
) {
    errorMessage();

    try {
        const result =
            await request(
                `/agent/ports?agent_id=${
                    encodeURIComponent(
                        agentId
                    )
                }`
            );

        selectedAgent =
            result.agent.id;

        const detail =
            document.getElementById(
                "agent-detail"
            );

        detail.hidden = false;

        document.getElementById(
            "agent-detail-title"
        ).textContent =
            `${result.agent.name} · ${result.agent.id}`;

        const ranges =
            document.getElementById(
                "agent-ranges"
            );

        ranges.innerHTML = "";

        for (
            const item
            of result.ranges
        ) {
            ranges.appendChild(
                rangeCard(item)
            );
        }

        const conflicts =
            document.getElementById(
                "agent-conflicts"
            );

        if (
            result.conflict_count
        ) {
            conflicts.className =
                "conflict-box conflict-danger";

            conflicts.textContent =
                `${result.conflict_count} reserva(s) fora das faixas configuradas.`;
        } else {
            conflicts.className =
                "conflict-box";

            conflicts.textContent =
                "Nenhum conflito persistente detectado.";
        }

        const first =
            result.ranges[0];

        if (first) {
            document.getElementById(
                "range-start"
            ).value =
                first.start_port;

            document.getElementById(
                "range-end"
            ).value =
                first.end_port;
        }

    } catch (error) {
        errorMessage(
            error.message
        );
    }
}


async function saveRange(event) {
    event.preventDefault();

    if (!selectedAgent) {
        errorMessage(
            "Selecione um Agent."
        );
        return;
    }

    errorMessage();

    const payload = {
        agent_id:
            selectedAgent,

        protocol:
            document.getElementById(
                "range-protocol"
            ).value,

        start_port:
            Number(
                document.getElementById(
                    "range-start"
                ).value
            ),

        end_port:
            Number(
                document.getElementById(
                    "range-end"
                ).value
            ),

        force:
            document.getElementById(
                "range-force"
            ).checked
    };

    try {
        await request(
            "/agent/ports/set",
            {
                method: "POST",
                body:
                    JSON.stringify(
                        payload
                    )
            }
        );

        await loadAgent(
            selectedAgent
        );

        await loadAgents();

    } catch (error) {
        errorMessage(
            error.message
        );
    }
}


async function initialize() {
    try {
        await loadSidebar();

        currentUser =
            await request(
                "/whoami"
            );

        if (
            ![
                "admin",
                "controller"
            ].includes(
                currentUser.role
            )
        ) {
            throw new Error(
                "Você não possui permissão " +
                "para administrar Agents."
            );
        }

        const userBox =
            document.getElementById(
                "current-user"
            );

        if (userBox) {
            userBox.textContent =
                `${currentUser.username} (${currentUser.role})`;
        }

        applyRole();

        document.getElementById(
            "refresh-agents"
        ).onclick =
            loadAgents;

        document.getElementById(
            "agent-range-form"
        ).onsubmit =
            saveRange;

        await loadAgents();

    } catch (error) {
        errorMessage(
            error.message
        );
    }
}


document.addEventListener(
    "DOMContentLoaded",
    initialize
);
