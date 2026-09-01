"use strict";

const API = "/api";
const BATCH_HISTORY_KEY = "capivara_agent_batch_history_v1";
const BATCH_HISTORY_LIMIT = 20;
let currentUser = null;
let infrastructureTopology = null;
let sidebarCollapsed = false;

function byId(id) { return document.getElementById(id); }
function authHeader() { return {Accept: "application/json", "X-Capivara-Auth-Area": "controller"}; }
async function request(endpoint, options = {}) {
    const headers = {...authHeader(), ...(options.headers || {})};
    if (options.body) headers["Content-Type"] = "application/json";
    const response = await fetch(`${API}${endpoint}`, {...options, headers, credentials: "same-origin", cache: options.cache || "no-store"});
    if (response.status === 401) { window.location.replace("/login.html"); return null; }
    const contentType = response.headers.get("content-type") || "";
    let body;
    if (contentType.includes("application/json")) body = await response.json();
    else {
        const text = await response.text();
        const preview = text.replace(/\s+/g, " ").trim().slice(0, 180);
        throw new Error(`API retornou conteúdo inesperado: HTTP ${response.status} (${contentType || "sem Content-Type"})${preview ? ` · ${preview}` : ""}`);
    }
    if (!response.ok) throw new Error(body.error || body.message || `HTTP ${response.status}`);
    return body;
}
function errorMessage(message = "") {
    const box = byId("agents-error");
    if (!box) return;
    box.hidden = !message;
    box.textContent = message;
}
function applySidebarState(collapsed) {
    sidebarCollapsed = collapsed;
    document.body.classList.toggle("cap-sidebar-collapsed", collapsed);
    localStorage.setItem("cap_sidebar_collapsed", collapsed ? "1" : "0");
}
function bindMenu() {
    byId("add-agent-menu-toggle")?.addEventListener("click", () => {
        if (window.innerWidth <= 760) { document.body.classList.toggle("sidebar-open"); return; }
        applySidebarState(!sidebarCollapsed);
    });
}
async function logout() {
    try { await fetch("/api/auth/logout", {method: "POST", headers: authHeader(), credentials: "same-origin", cache: "no-store"}); }
    finally { window.location.replace("/login.html"); }
}
async function loadSidebar() {
    const target = byId("sidebar-component");
    if (!target) return;
    const response = await fetch("/components/sidebar-v3.html", {credentials: "same-origin", cache: "no-store"});
    if (!response.ok) throw new Error(`sidebar HTTP ${response.status}`);
    target.innerHTML = await response.text();
    target.querySelectorAll("nav a").forEach(a => a.classList.toggle("active", a.getAttribute("href") === "add-agent.html"));
    target.querySelectorAll("a").forEach(a => a.addEventListener("click", () => document.body.classList.remove("sidebar-open")));
    byId("btn-logout")?.addEventListener("click", logout);
}
async function loadInfrastructure() { infrastructureTopology = await request("/infrastructure?active_only=true"); return infrastructureTopology; }
async function loadAgents() { return null; }

function parseCsv(text) {
    const rows = []; let row = []; let field = ""; let quoted = false;
    for (let i = 0; i < text.length; i += 1) {
        const ch = text[i];
        if (quoted) {
            if (ch === '"' && text[i + 1] === '"') { field += '"'; i += 1; }
            else if (ch === '"') quoted = false;
            else field += ch;
        } else if (ch === '"') quoted = true;
        else if (ch === ",") { row.push(field.trim()); field = ""; }
        else if (ch === "\n") { row.push(field.trim()); if (row.some(value => value !== "")) rows.push(row); row = []; field = ""; }
        else if (ch !== "\r") field += ch;
    }
    row.push(field.trim());
    if (row.some(value => value !== "")) rows.push(row);
    if (!rows.length) throw new Error("CSV vazio.");
    const headers = rows.shift().map(value => value.replace(/^\uFEFF/, "").trim());
    if (new Set(headers).size !== headers.length) throw new Error("CSV contém colunas duplicadas.");
    return rows.map((values, index) => {
        const item = {_line: index + 2};
        headers.forEach((header, position) => { item[header] = values[position] || ""; });
        return item;
    });
}
function normalizeBatchHost(value) { return String(value || "").trim().toLowerCase(); }
function validateUniqueBatchHosts(rows) {
    const seen = new Map();
    for (const row of rows) {
        const host = normalizeBatchHost(row.host);
        if (!host) continue;
        if (seen.has(host)) throw new Error(`Host duplicado no CSV: ${row.host} (linhas ${seen.get(host)} e ${row._line}).`);
        seen.set(host, row._line);
    }
}
async function batchFingerprint(text) {
    const normalized = String(text || "").replace(/\r\n/g, "\n").trim();
    if (window.crypto?.subtle && window.TextEncoder) {
        const digest = await window.crypto.subtle.digest("SHA-256", new TextEncoder().encode(normalized));
        return Array.from(new Uint8Array(digest)).map(value => value.toString(16).padStart(2, "0")).join("");
    }
    let hash = 2166136261;
    for (let i = 0; i < normalized.length; i += 1) { hash ^= normalized.charCodeAt(i); hash = Math.imul(hash, 16777619); }
    return `fallback-${(hash >>> 0).toString(16).padStart(8, "0")}`;
}
function readBatchHistory() {
    try {
        const parsed = JSON.parse(localStorage.getItem(BATCH_HISTORY_KEY) || "[]");
        return Array.isArray(parsed) ? parsed.filter(item => item && typeof item.fingerprint === "string") : [];
    } catch (_) { return []; }
}
function rememberBatchExecution(entry) {
    const history = readBatchHistory().filter(item => item.fingerprint !== entry.fingerprint);
    history.unshift(entry);
    localStorage.setItem(BATCH_HISTORY_KEY, JSON.stringify(history.slice(0, BATCH_HISTORY_LIMIT)));
}
function previousBatchExecution(fingerprint) { return readBatchHistory().find(item => item.fingerprint === fingerprint) || null; }
function batchPortRange(value) {
    const raw = String(value || "").trim();
    if (!raw) return ["", ""];
    const match = raw.match(/^(\d+)\s*-\s*(\d+)$/);
    if (!match) throw new Error("port_range deve usar o formato 24000-24999");
    return [match[1], match[2]];
}
async function recommendedRelease(platform) {
    const result = await request(`/agents/releases?platform=${encodeURIComponent(platform)}&include_prereleases=0`);
    if (!result?.recommended) throw new Error(`Nenhuma release compatível disponível para ${platform}.`);
    return result.recommended;
}
function validateBatchRow(row) {
    for (const name of ["host", "ssh_user", "region_id", "datacenter_id"]) if (!String(row[name] || "").trim()) throw new Error(`${name} é obrigatório`);
    if (row.password || row.ssh_password || row.winrm_password) throw new Error("senhas em texto puro não são aceitas; use password_file");
    if (row.identity_file) throw new Error("identity_file não é aceito pela Dashboard; configure a identidade SSH no Controller");
    const platform = String(row.platform || "linux").trim().toLowerCase();
    if (!["linux", "windows"].includes(platform)) throw new Error("platform deve ser linux ou windows");
    const method = String(row.method || "ssh").trim().toLowerCase();
    if (!["ssh", "winrm"].includes(method)) throw new Error("method deve ser ssh ou winrm no lote remoto");
    if (method === "winrm" && platform !== "windows") throw new Error("WinRM só pode ser usado com Windows");
    const packageFile = String(row.package_file || "").trim();
    if (packageFile && method !== "ssh") throw new Error("package_file só pode ser usado com method=ssh");
    if (packageFile && platform !== "linux") throw new Error("pacote local em lote está disponível somente para Agent Linux");
    if (packageFile && row.release_tag) throw new Error("use package_file ou release_tag, não os dois na mesma linha");
}
async function batchPayload(row, releaseCache) {
    validateBatchRow(row);
    const platform = String(row.platform || "linux").trim().toLowerCase();
    const method = String(row.method || "ssh").trim().toLowerCase();
    const packageFile = String(row.package_file || "").trim();
    const [portStart, portEnd] = batchPortRange(row.port_range);
    let releaseTag = String(row.release_tag || "").trim();
    if (!packageFile && !releaseTag) {
        if (!releaseCache[platform]) releaseCache[platform] = await recommendedRelease(platform);
        releaseTag = releaseCache[platform];
    }
    const controllerId = currentUser.role === "controller" ? currentUser.scope_id : String(row.controller_id || "").trim();
    if (!controllerId) throw new Error("controller_id é obrigatório para administrador");
    const payload = {
        platform, method,
        release_tag: releaseTag || undefined,
        package_file: packageFile || undefined,
        controller_id: controllerId,
        controller_url: String(row.controller_url || window.location.origin).trim(),
        region_id: String(row.region_id || "").trim(),
        datacenter_id: String(row.datacenter_id || "").trim(),
        agent_name: String(row.name || "").trim(),
        port_protocol: String(row.port_protocol || "both").trim().toLowerCase(),
        port_start: portStart,
        port_end: portEnd,
        bootstrap_timeout: String(row.bootstrap_timeout || "900").trim()
    };
    if (method === "ssh") {
        payload.ssh_host = String(row.host || "").trim();
        payload.ssh_user = String(row.ssh_user || "").trim();
        payload.ssh_port = String(row.ssh_port || "22").trim();
        payload.password_file = String(row.password_file || "").trim() || undefined;
    } else payload.winrm_host = String(row.host || "").trim();
    return payload;
}
function renderBatchResult(row, state, detail) {
    const body = byId("agent-batch-results-body"); const tr = document.createElement("tr");
    [row._line, row.host || "—", row.platform || "linux", state, detail || "—"].forEach(value => { const td = document.createElement("td"); td.textContent = String(value); tr.appendChild(td); });
    body.appendChild(tr);
}
function downloadBatchTemplate() {
    const content = [
        "host,ssh_user,platform,method,ssh_port,password_file,package_file,controller_id,controller_url,region_id,datacenter_id,name,port_range,port_protocol,release_tag,bootstrap_timeout",
        "192.168.15.60,admin,linux,ssh,22,/etc/capivara/secrets/remote-deploy/node60.secret,,,https://controller.exemplo,br,gru,Node60,24000-24999,both,,900",
        "192.168.15.61,admin,linux,ssh,22,/etc/capivara/secrets/remote-deploy/node61.secret,/var/lib/capivara/agent-packages/capivara-agent-linux-2.0.20.tar.gz,,https://controller.exemplo,br,gru,Node61,25000-25999,both,,900"
    ].join("\n");
    const blob = new Blob([content], {type: "text/csv;charset=utf-8"});
    const url = URL.createObjectURL(blob); const link = document.createElement("a");
    link.href = url; link.download = "capivara-agents-batch.csv"; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
}
async function runBatch(event) {
    event.preventDefault(); errorMessage();
    const file = byId("agent-batch-file")?.files?.[0]; if (!file) return;
    const submit = byId("agent-batch-submit"); const status = byId("agent-batch-status"); const results = byId("agent-batch-results"); const body = byId("agent-batch-results-body");
    const continueOnError = byId("agent-batch-continue")?.checked; const releaseCache = {};
    submit.disabled = true; submit.setAttribute("aria-busy", "true"); submit.textContent = "Instalação em andamento...";
    try {
        const text = await file.text(); const rows = parseCsv(text);
        if (!rows.length) throw new Error("CSV não contém linhas de Agents.");
        rows.forEach(validateBatchRow); validateUniqueBatchHosts(rows);
        const fingerprint = await batchFingerprint(text); const previous = previousBatchExecution(fingerprint);
        if (previous) {
            const when = previous.finished_at ? new Date(previous.finished_at).toLocaleString("pt-BR") : "data desconhecida";
            const confirmed = window.confirm(`Este mesmo CSV já foi executado em ${when}.\n\nReexecutar pode tentar instalar novamente nos mesmos hosts. O Controller recusará hosts onde o Agent já estiver presente.\n\nDeseja executar o lote novamente?`);
            if (!confirmed) { status.textContent = "Reexecução cancelada: este CSV já possui histórico de execução."; return; }
        }
        body.replaceChildren(); results.hidden = false;
        rememberBatchExecution({fingerprint,file_name:file.name,started_at:new Date().toISOString(),finished_at:null,state:"running",rows:rows.length,completed:0,failed:0});
        let completed = 0; let failed = 0;
        for (let index = 0; index < rows.length; index += 1) {
            const row = rows[index]; status.textContent = `Processando ${index + 1} de ${rows.length}: ${row.host || "host não informado"}...`;
            try {
                const payload = await batchPayload(row, releaseCache);
                const result = await request("/agents/installations", {method:"POST", body:JSON.stringify(payload)});
                completed += 1;
                const source = row.package_file ? "pacote local" : "release";
                renderBatchResult(row, "Iniciado", result?.installation_id ? `installation_id ${result.installation_id} · ${source}` : `Bootstrap solicitado · ${source}`);
            } catch (error) {
                failed += 1; renderBatchResult(row, "Falhou", error.message); if (!continueOnError) break;
            }
        }
        rememberBatchExecution({fingerprint,file_name:file.name,started_at:previousBatchExecution(fingerprint)?.started_at || new Date().toISOString(),finished_at:new Date().toISOString(),state:failed?"completed_with_errors":"completed",rows:rows.length,completed,failed});
        status.textContent = `Lote concluído: ${completed} iniciado(s), ${failed} falha(s).`; submit.textContent = "Executar novamente";
    } catch (error) { errorMessage(error.message); status.textContent = `Falha no lote: ${error.message}`; }
    finally { submit.disabled = false; submit.removeAttribute("aria-busy"); if (submit.textContent === "Instalação em andamento...") submit.textContent = "Instalar Agents em lote"; }
}
function bindBatchUi() {
    const link = byId("add-agent-batch-link"); const panel = byId("add-agent-batch");
    link?.addEventListener("click", event => { event.preventDefault(); panel.hidden = false; panel.scrollIntoView({behavior:"smooth",block:"start"}); });
    byId("agent-batch-template")?.addEventListener("click", downloadBatchTemplate);
    byId("agent-batch-file")?.addEventListener("change", () => { const submit = byId("agent-batch-submit"); if (submit) submit.textContent = "Instalar Agents em lote"; const status = byId("agent-batch-status"); if (status) status.textContent = ""; });
    byId("agent-batch-form")?.addEventListener("submit", runBatch);
}
async function initializeAddAgentPage() {
    try {
        bindMenu(); bindBatchUi(); await loadSidebar(); currentUser = await request("/whoami"); if (!currentUser) return;
        if (!["admin","controller"].includes(currentUser.role)) throw new Error("Você não possui permissão para adicionar Agents.");
        document.querySelectorAll(".admin-only").forEach(element => { element.style.display = currentUser.role === "admin" ? "" : "none"; });
        document.querySelectorAll(".agent-manager-only").forEach(element => { element.style.display = ["admin","controller"].includes(currentUser.role) ? "" : "none"; });
        document.querySelectorAll(".instance-manager-only").forEach(element => { element.style.display = ["admin","controller","operator"].includes(currentUser.role) ? "" : "none"; });
        const current = byId("current-user"); if (current) current.textContent = `${currentUser.username} (${currentUser.role})`;
        const name = byId("add-agent-user"); if (name) name.textContent = currentUser.username || "—";
        const role = byId("add-agent-role"); if (role) role.textContent = currentUser.role || "—";
        applySidebarState(localStorage.getItem("cap_sidebar_collapsed") === "1"); await loadInfrastructure();
    } catch (error) { errorMessage(error.message); }
}
document.addEventListener("DOMContentLoaded", initializeAddAgentPage);
