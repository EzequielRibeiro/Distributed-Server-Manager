"use strict";

const HELP_REPOSITORY = "https://github.com/EzequielRibeiro/Distributed-Server-Manager/blob/main/";

const materials = [
    {
        category: "agents",
        tag: "Tutorial",
        title: "Instalar um Agent Linux remotamente via SSH",
        description: "Configure a chave do serviço da Dashboard, autorize o Agent, valide sudo não interativo e execute o bootstrap.",
        keywords: "ssh chave publica publickey sudo capivara mine controller agent datacenter host key permission denied",
        content: `
            <h3>1. Descubra a conta da Dashboard</h3>
            <pre>systemctl show dsm-dashboard.service -p User --value
getent passwd capivara</pre>
            <h3>2. Crie a chave da conta de serviço</h3>
            <pre>DSM_SERVICE_ACCOUNT="capivara"
DSM_SERVICE_HOME="$(getent passwd "$DSM_SERVICE_ACCOUNT" | cut -d: -f6)"
sudo install -d -m 700 -o "$DSM_SERVICE_ACCOUNT" -g "$DSM_SERVICE_ACCOUNT" "$DSM_SERVICE_HOME/.ssh"
sudo -u "$DSM_SERVICE_ACCOUNT" ssh-keygen -t ed25519 -f "$DSM_SERVICE_HOME/.ssh/id_ed25519" -N ""</pre>
            <h3>3. Autorize o acesso ao Agent</h3>
            <pre>sudo -u capivara ssh-copy-id -i "$DSM_SERVICE_HOME/.ssh/id_ed25519.pub" mine@192.168.15.55</pre>
            <h3>4. No Agent, autorize o preflight e bootstrap</h3>
            <pre>printf '%s\\n' 'mine ALL=(root) NOPASSWD: /usr/bin/true, /usr/bin/python3 -' | sudo tee /etc/sudoers.d/capivara-agent >/dev/null
sudo chmod 440 /etc/sudoers.d/capivara-agent
sudo visudo -cf /etc/sudoers.d/capivara-agent</pre>
            <h3>5. Valide a partir do Controller</h3>
            <pre>sudo -u capivara ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new mine@192.168.15.55 'sudo -n true &amp;&amp; echo SSH_OK'</pre>
            <p>Somente prossiga quando o resultado for <code>SSH_OK</code>. Depois, use <strong>Infraestrutura → Adicionar Agent → Instalar remotamente via SSH</strong>.</p>
            <p><a href="${HELP_REPOSITORY}docs/tutorial-instalacao-agent-via-ssh.md" target="_blank" rel="noopener">Abrir tutorial completo no GitHub</a></p>`
    },
    {
        category: "games",
        tag: "Tutorial",
        title: "Instalar servidor DayZ para um cliente em Agent remoto",
        description: "Crie Customer, contrato DayZ e instância vinculada ao Agent correto usando a CLI cap.",
        keywords: "dayz cliente customer contrato contract instance servidor remoto agent cap",
        content: `
            <h3>Fluxo administrativo</h3>
            <ol><li>Confirme que o Agent está ativo e possui localização/faixa de portas.</li><li>Crie o Customer e o login.</li><li>Crie o contrato DayZ.</li><li>Crie a instância selecionando explicitamente o Agent.</li></ol>
            <pre>cap customer create --id CLIENTE-001 --name "João" --username joao
cap contract create --customer CLIENTE-001 --game dayz --instances 1 --id CONTRACT-DAYZ-001
cap instance create --customer CLIENTE-001 --contract CONTRACT-DAYZ-001 --game dayz --agent AGENT-ID --name dayz-joao-01</pre>
            <p><a href="${HELP_REPOSITORY}docs/tutorial-instalacao-dayz-agent-remoto.md" target="_blank" rel="noopener">Abrir tutorial completo no GitHub</a></p>`
    },
    {
        category: "operations", tag: "Runbook", title: "Operações e recuperação Capivara 2.0",
        description: "Checklist operacional, saúde da infraestrutura, backup, recuperação e diagnóstico.",
        keywords: "operacao recovery doctor backup restore health runbook",
        content: `<p>Use este runbook para procedimentos de operação e recuperação do ambiente.</p><p><a href="${HELP_REPOSITORY}docs/runbooks/capivara-2.0-operations.md" target="_blank" rel="noopener">Abrir runbook no GitHub</a></p>`
    },
    {
        category: "reference", tag: "Referência", title: "Instalação SSH — arquitetura e segurança",
        description: "Contrato de segurança, limites do bootstrap SSH e ciclo de vida após enrollment.",
        keywords: "arquitetura ssh segurança enrollment pairing token",
        content: `<p>Referência técnica para entender as decisões de segurança do instalador remoto.</p><p><a href="${HELP_REPOSITORY}docs/architecture/agent-ssh-deploy.md" target="_blank" rel="noopener">Abrir referência no GitHub</a></p>`
    },
    {
        category: "reference", tag: "Referência", title: "Topologia geográfica e placement",
        description: "Como Controller, Região, Datacenter e Agent determinam elegibilidade e placement.",
        keywords: "regiao datacenter controller topology placement localização",
        content: `<p>Consulte a arquitetura da topologia antes de alterar localização ou políticas de placement.</p><p><a href="${HELP_REPOSITORY}docs/architecture/phase4-geographic-topology.md" target="_blank" rel="noopener">Abrir referência no GitHub</a></p>`
    },
    {
        category: "reference", tag: "Referência", title: "Acesso de clientes e equipes",
        description: "Contas, convites, funções, verificação de e-mail e recuperação de senha.",
        keywords: "customer cliente conta equipe convite senha email acesso",
        content: `<p>Referência dos fluxos de identidade e acesso do portal do cliente.</p><p><a href="${HELP_REPOSITORY}docs/customer-access-4.3E-4.3W.md" target="_blank" rel="noopener">Abrir referência no GitHub</a></p>`
    }
];

let selectedCategory = "all";

function normalized(value) {
    return String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function render() {
    const query = normalized(document.getElementById("help-search").value.trim());
    const visible = materials.filter(item => {
        const categoryMatches = selectedCategory === "all" || item.category === selectedCategory;
        const haystack = normalized(`${item.title} ${item.description} ${item.keywords} ${item.tag}`);
        return categoryMatches && (!query || haystack.includes(query));
    });
    const root = document.getElementById("help-results");
    root.replaceChildren(...visible.map(item => {
        const details = document.createElement("details");
        details.className = "help-card";
        const summary = document.createElement("summary");
        summary.innerHTML = `<span class="help-card-tag">${item.tag}</span><h2>${item.title}</h2><p>${item.description}</p>`;
        const article = document.createElement("article");
        article.className = "help-article";
        article.innerHTML = item.content;
        details.append(summary, article);
        return details;
    }));
    document.getElementById("help-count").textContent = `${visible.length} ${visible.length === 1 ? "material" : "materiais"}`;
    document.getElementById("help-empty").hidden = visible.length !== 0;
    document.getElementById("help-clear").hidden = !query && selectedCategory === "all";
}

async function initialize() {
    const sidebar = await fetch("/components/sidebar.html");
    document.getElementById("sidebar-component").innerHTML = await sidebar.text();
    document.querySelectorAll(".cap-sidebar-v2 nav a").forEach(link => link.classList.toggle("active", link.getAttribute("href") === "help.html"));
    const logout = document.getElementById("btn-logout");
    if (logout) logout.onclick = () => { sessionStorage.clear(); location.replace("/login.html"); };
    try {
        const response = await fetch("/api/whoami", {headers: {Authorization: `Basic ${sessionStorage.getItem("dsm_auth") || ""}`}});
        const user = await response.json();
        if (!response.ok) throw new Error(user.error || "authentication required");
        const current = document.getElementById("current-user");
        if (current) current.textContent = `${user.username} (${user.role})`;
        document.querySelectorAll(".admin-only").forEach(item => item.hidden = user.role !== "admin");
        document.querySelectorAll(".agent-manager-only").forEach(item => item.hidden = !["admin", "controller"].includes(user.role));
    } catch (_) {
        location.replace("/login.html");
        return;
    }
    document.getElementById("help-search").addEventListener("input", render);
    document.querySelectorAll("[data-help-category]").forEach(button => button.addEventListener("click", () => {
        selectedCategory = button.dataset.helpCategory;
        document.querySelectorAll("[data-help-category]").forEach(item => item.classList.toggle("active", item === button));
        render();
    }));
    document.getElementById("help-clear").addEventListener("click", () => {
        selectedCategory = "all";
        document.getElementById("help-search").value = "";
        document.querySelectorAll("[data-help-category]").forEach(item => item.classList.toggle("active", item.dataset.helpCategory === "all"));
        render();
    });
    render();
}

document.addEventListener("DOMContentLoaded", initialize);
