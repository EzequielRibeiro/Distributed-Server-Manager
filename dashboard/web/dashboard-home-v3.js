"use strict";

const HOME_API = "/api";
const $ = id => document.getElementById(id);
const controllerHeaders = () => ({Accept: "application/json", "X-Capivara-Auth-Area": "controller"});

async function get(path) {
    try {
        const response = await fetch(`${HOME_API}${path}`, {
            headers: controllerHeaders(), credentials: "same-origin", cache: "no-store",
        });
        if (response.status === 401) { window.location.replace("/login.html"); return null; }
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        console.warn("[Capivara Home]", path, error); return null;
    }
}

async function post(path, payload) {
    const response = await fetch(`${HOME_API}${path}`, {
        method: "POST",
        headers: {...controllerHeaders(), "Content-Type": "application/json"},
        credentials: "same-origin",
        cache: "no-store",
        body: JSON.stringify(payload || {}),
    });
    if (response.status === 401) { window.location.replace("/login.html"); return null; }
    let data = {};
    try { data = await response.json(); } catch (_) { data = {}; }
    if (!response.ok) throw new Error(data?.error || `Falha HTTP ${response.status}`);
    return data;
}

function text(id, value, fallback = "—") { const element = $(id); if (element) element.textContent = value ?? fallback; }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char])); }
function isOnline(agent) { return ["online","healthy","ok","active","running"].includes(String(agent?.health_status || agent?.health || agent?.status || "").toLowerCase()); }
function formatTime(value) { if (!value) return "—"; const date = typeof value === "number" ? new Date(value * 1000) : new Date(value); return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleTimeString("pt-BR", {hour:"2-digit",minute:"2-digit"}); }
function formatDateTime(value) { if (!value) return "—"; const date = typeof value === "number" ? new Date(value * 1000) : new Date(value); return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("pt-BR", {dateStyle:"short",timeStyle:"medium"}); }
function eventText(event) { const type=String(event?.type||event?.action||event?.event_type||"Evento").replaceAll("_"," ").toLowerCase(); const message=event?.message||event?.details||event?.data?.message||""; return message?`${type} · ${message}`:type; }
function eventSeverity(event) { return String(event?.severity || event?.level || "").trim().toLowerCase(); }
function agentPlatform(agent) { return agent?.platform || agent?.system || agent?.os_name || agent?.os || "—"; }
function agentLocation(agent) { const region=agent?.region_id||agent?.region||""; const dc=agent?.datacenter_id||agent?.datacenter||""; return [region,dc].filter(Boolean).join(" / ") || "—"; }
function agentState(agent) { return String(agent?.health_status || agent?.health || agent?.status || "unknown"); }
function agentIp(agent) { return agent?.ip || agent?.address || agent?.public_ip || agent?.private_ip || agent?.public_host || "—"; }
function agentHostname(agent) { return agent?.hostname || agent?.node_id || agent?.name || "—"; }
function compactAgentId(value) {
    const id = String(value || "");
    if (!id || id.length <= 18) return id || "—";
    if (id.startsWith("agent-")) {
        const body = id.slice(6);
        return `agent-${body.slice(0,4)}…${body.slice(-4)}`;
    }
    return `${id.slice(0,8)}…${id.slice(-5)}`;
}

function renderAgentTable(agents) {
    const body = $("home-agent-table-body");
    if (!body) return;
    if (!agents.length) {
        body.innerHTML = '<tr><td colspan="8" class="cap-agent-table-empty">Nenhum Agent registrado.</td></tr>';
        return;
    }
    body.innerHTML = agents.map(agent => {
        const id = String(agent.id || "");
        const state = agentState(agent);
        const online = isOnline(agent);
        const heartbeat = agent.last_heartbeat || agent.heartbeat_at || agent.last_seen || agent.updated_at;
        const detailsUrl = `agent-details.html?agent_id=${encodeURIComponent(id)}`;
        return `<tr>
            <td class="cap-agent-id-cell"><a class="cap-agent-name" href="${detailsUrl}" title="${escapeHtml(id)}">${escapeHtml(compactAgentId(id))}</a></td>
            <td class="cap-agent-hostname-cell">${escapeHtml(agentHostname(agent))}</td>
            <td class="cap-agent-ip-cell">${escapeHtml(agentIp(agent))}</td>
            <td>${escapeHtml(agentPlatform(agent))}</td>
            <td>${escapeHtml(agentLocation(agent))}</td>
            <td><span class="cap-agent-state ${online ? "online" : "offline"}"><i></i>${escapeHtml(state)}</span></td>
            <td class="cap-agent-number">${escapeHtml(Number(agent.instance_count || 0))}</td>
            <td>${escapeHtml(formatDateTime(heartbeat))}</td>
        </tr>`;
    }).join("");
}

function renderAgents(result) {
    const agents = Array.isArray(result?.agents) ? result.agents : [];
    const online = agents.filter(isOnline).length;
    const instances = agents.reduce((total, agent) => total + Number(agent.instance_count || 0), 0);
    const running = agents.reduce((total, agent) => total + Number(agent.running_instance_count || agent.instances_running || 0), 0);
    text("home-agent-total", agents.length); text("home-agent-online", `${online} online`); text("home-agent-offline", `${Math.max(0, agents.length-online)} offline`); text("home-instance-total", instances); text("home-instance-total-copy", instances); text("home-running-total", running); text("home-infra-agents", agents.length); text("home-infra-online", online);
    renderAgentTable(agents);
    const list=$("home-agent-bars"); if(list){const maxInstances=Math.max(1,...agents.map(agent=>Number(agent.instance_count||0)));list.innerHTML=agents.slice(0,7).map(agent=>{const count=Number(agent.instance_count||0);const pct=Math.round((count/maxInstances)*100);return `<div class="cap-bar-row"><span>${escapeHtml(agent.name||agent.id)}</span><div class="cap-bar"><i style="width:${pct}%"></i></div><b>${count}</b></div>`}).join("")||'<div class="cap-empty">Nenhum Agent registrado.</div>'}
    const health=$("home-health-agents"); if(health){health.textContent=agents.length?`${online} / ${agents.length} online`:"Nenhum Agent";health.className=online===agents.length&&agents.length?"cap-good":"cap-warn"}
}

function renderInfrastructure(data) { let regions=0,datacenters=0; function walk(value){if(!value)return;if(Array.isArray(value)){value.forEach(walk);return}if(typeof value!=="object")return;if(value.type==="region")regions++;if(value.type==="datacenter")datacenters++;Object.values(value).forEach(walk)} walk(data); text("home-infra-regions",regions); text("home-infra-datacenters",datacenters); }

function renderTimeline(result) {
    const events=Array.isArray(result)?result:(result?.events||[]);
    const list=$("home-events");
    if(list){list.innerHTML=events.slice(0,5).map(event=>`<div class="cap-event"><time>${escapeHtml(formatTime(event.timestamp||event.time))}</time><i class="cap-event-dot"></i><div><p>${escapeHtml(eventText(event))}</p><small>${escapeHtml(event.category||event.source||"Sistema")}</small></div></div>`).join("")||'<div class="cap-empty">Nenhuma atividade recente.</div>'}
}

function renderActiveAlerts(result, alertResult) {
    const summary = result?.summary || {};
    const alertsSummary = summary?.alerts || {};
    const recentAlerts = Array.isArray(alertResult?.alerts)
        ? alertResult.alerts
        : Array.isArray(result?.recent?.alerts) ? result.recent.alerts : [];
    const active = Number(alertsSummary.active ?? alertResult?.count ?? recentAlerts.length ?? 0);
    text("home-alert-total", active);
    const target = $("home-alerts");
    if (!target) return;
    if (active <= 0) {
        target.innerHTML = '<div class="cap-empty">Nenhum alerta ativo.</div>';
        return;
    }
    const activeAlerts = recentAlerts.filter(alert => !["RESOLVED","CLOSED","CLEARED","SUPPRESSED"].includes(String(alert?.status || alert?.state || "").toUpperCase()));
    if (!activeAlerts.length) {
        target.innerHTML = `<article class="cap-alert warning"><strong class="cap-warn">${escapeHtml(active)} ATIVO(S)</strong><p>Existem alertas ativos, mas o resumo não retornou detalhes recentes.</p></article>`;
        return;
    }
    target.innerHTML = activeAlerts.slice(0, 3).map(alert => {
        const severity = String(alert?.severity || alert?.level || "warning").toLowerCase();
        const critical = ["critical","error","fatal"].includes(severity);
        const alertId = String(alert?.id || alert?.alert_id || "");
        const code = alert?.code || alert?.rule_id || alert?.event_type || alert?.type || "Alerta";
        const ruleId = String(alert?.rule_id || "").trim();
        const scope = alert?.agent_id || alert?.instance_id || alert?.customer_id || alert?.scope || "Sistema";
        const status = String(alert?.status || alert?.state || "OPEN").toUpperCase();
        const message = alert?.message || alert?.description || "";
        const agentId = String(alert?.agent_id || "");
        const viewAgent = agentId ? `<a class="cap-alert-action" href="agent-details.html?agent_id=${encodeURIComponent(agentId)}">Ver Agent</a>` : "";
        const acknowledge = alertId && status === "OPEN" ? `<button type="button" class="cap-alert-action" data-alert-action="acknowledge" data-alert-id="${escapeHtml(alertId)}">Reconhecer</button>` : "";
        const note = alertId ? `<button type="button" class="cap-alert-action" data-alert-action="note" data-alert-id="${escapeHtml(alertId)}">Adicionar nota</button>` : "";
        const resolve = alertId && ruleId !== "agent.identity_collision" ? `<button type="button" class="cap-alert-action cap-alert-resolve" data-alert-action="resolve" data-alert-id="${escapeHtml(alertId)}">Resolver</button>` : "";
        return `<article class="cap-alert ${critical ? "" : "warning"}">
            <strong class="${critical ? "cap-bad" : "cap-warn"}">${escapeHtml(severity.toUpperCase())} · ${escapeHtml(status)}</strong>
            ${message ? `<p class="cap-alert-message">${escapeHtml(message)}</p>` : ""}
            <p class="cap-alert-meta"><b>${escapeHtml(code)}</b><br>${escapeHtml(scope)}</p>
            <div class="cap-alert-actions">${viewAgent}${acknowledge}${note}${resolve}</div>
        </article>`;
    }).join("");
}

async function handleAlertAction(button) {
    const alertId = String(button?.dataset?.alertId || "").trim();
    const action = String(button?.dataset?.alertAction || "").trim();
    if (!alertId || !["acknowledge","note","resolve"].includes(action)) return;
    let note = "";
    if (action === "note") {
        note = String(window.prompt("Adicione uma nota administrativa a este alerta:") || "").trim();
        if (!note) return;
    }
    if (action === "resolve") {
        note = String(window.prompt("Descreva o que foi feito para resolver este alerta:") || "").trim();
        if (!note) return;
    }
    const original = button.textContent;
    button.disabled = true;
    button.textContent = action === "resolve" ? "Resolvendo..." : action === "note" ? "Salvando..." : "Reconhecendo...";
    try {
        await post("/admin/alert/action", {id: alertId, action, note});
        await refresh();
    } catch (error) {
        window.alert(`Não foi possível alterar o alerta:\n${error.message}`);
        button.disabled = false;
        button.textContent = original;
    }
}

function renderHealth(result) { const data=result?.data||result||{};const status=String(data.status||"").toLowerCase();const failed=["failed","critical","offline","error"].includes(status);text("home-controller-health",data.status||"Operacional");const dot=$("home-controller-dot");if(dot)dot.classList.toggle("off",failed);const top=document.querySelector(".cap-controller-state");if(top){top.classList.toggle("cap-controller-failed",failed);const label=top.querySelector("span");if(label)label.textContent=failed?"Controller com falha":"Controller Online"}}
function renderUser(user) { const role=user?.role||"";text("home-user-name",user?.username||"Usuário");text("home-user-role",role);text("current-user",user?.username||"Sessão ativa");document.querySelectorAll(".admin-only").forEach(element=>element.style.display=role==="admin"?"":"none");document.querySelectorAll(".agent-manager-only").forEach(element=>element.style.display=["admin","controller"].includes(role)?"":"none");document.querySelectorAll(".instance-manager-only").forEach(element=>element.style.display=["admin","controller","client","customer"].includes(role)?"":"none"); }
function renderControllerTelemetry(result){if(!result)return;window.CapivaraTelemetry?.render($("controller-telemetry"),result.current||{},result.history||[],{label:"Controller",processKey:"controller",description:"Telemetria do host do Control Plane e consumo exclusivo do processo da Dashboard/Controller."})}

async function refresh() {
    const [user,agents,infrastructure,timeline,health,controllerTelemetry,observability,activeAlertDetails]=await Promise.all([get("/whoami"),get("/agents"),get("/infrastructure?active_only=true"),get("/timeline?limit=30"),get("/health"),get("/controller/telemetry?window_seconds=3600"),get("/admin/observability"),get("/admin/alerts?active=true&limit=3")]);
    if(user)renderUser(user);renderAgents(agents);renderInfrastructure(infrastructure);renderTimeline(timeline);renderHealth(health);renderControllerTelemetry(controllerTelemetry);renderActiveAlerts(observability,activeAlertDetails);text("home-last-refresh",new Date().toLocaleTimeString("pt-BR"));
}

function bindMobileSidebar(target,toggle){
    if(!target||!toggle)return;
    const isMobile=()=>window.innerWidth<=760;
    const setOpen=open=>{document.body.classList.toggle("sidebar-open",Boolean(open)&&isMobile());toggle.setAttribute("aria-expanded",Boolean(open)&&isMobile()?"true":"false");toggle.setAttribute("aria-label",Boolean(open)&&isMobile()?"Fechar menu":"Abrir menu");};
    toggle.addEventListener("click",event=>{event.stopPropagation();if(isMobile()){setOpen(!document.body.classList.contains("sidebar-open"));return;}document.body.classList.toggle("cap-sidebar-collapsed");});
    target.querySelector(".cap-sidebar-close")?.addEventListener("click",()=>setOpen(false));
    target.querySelectorAll("a").forEach(link=>link.addEventListener("click",()=>setOpen(false)));
    document.addEventListener("pointerdown",event=>{if(!isMobile()||!document.body.classList.contains("sidebar-open"))return;if(target.contains(event.target)||toggle.contains(event.target))return;setOpen(false);});
    document.addEventListener("keydown",event=>{if(event.key==="Escape")setOpen(false);});
    let startX=null,startY=null;
    target.addEventListener("touchstart",event=>{const touch=event.changedTouches?.[0];if(!touch)return;startX=touch.clientX;startY=touch.clientY;},{passive:true});
    target.addEventListener("touchend",event=>{if(startX===null||startY===null)return;const touch=event.changedTouches?.[0];if(!touch)return;const dx=touch.clientX-startX,dy=touch.clientY-startY;startX=null;startY=null;if(isMobile()&&dx<-60&&Math.abs(dx)>Math.abs(dy)*1.2)setOpen(false);},{passive:true});
    window.addEventListener("resize",()=>{if(!isMobile())setOpen(false);});
}

async function loadSidebar(){
    const target=$("sidebar-component");if(!target)return;
    const response=await fetch("/components/sidebar-v3.html",{headers:controllerHeaders(),credentials:"same-origin",cache:"no-store"});
    if(response.ok)target.innerHTML=await response.text();
    const logout=$("btn-logout");if(logout)logout.onclick=async()=>{try{await fetch("/api/auth/logout",{method:"POST",headers:controllerHeaders(),credentials:"same-origin",cache:"no-store"});}finally{window.location.replace("/login.html")}};
    bindMobileSidebar(target,$("home-menu-toggle"));
}

document.addEventListener("click", event => {
    const button = event.target.closest("[data-alert-action]");
    if (!button) return;
    event.preventDefault();
    handleAlertAction(button);
});

document.addEventListener("DOMContentLoaded",async()=>{
    await loadSidebar();
    $("home-refresh")?.addEventListener("click",refresh);
    await refresh();
    window.setInterval(refresh,30000);
});