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

function text(id, value, fallback = "—") { const element = $(id); if (element) element.textContent = value ?? fallback; }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char])); }
function isOnline(agent) { return ["online","healthy","ok","active","running"].includes(String(agent?.health_status || agent?.health || agent?.status || "").toLowerCase()); }
function formatTime(value) { if (!value) return "—"; const date = typeof value === "number" ? new Date(value * 1000) : new Date(value); return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleTimeString("pt-BR", {hour:"2-digit",minute:"2-digit"}); }
function formatDateTime(value) { if (!value) return "—"; const date = typeof value === "number" ? new Date(value * 1000) : new Date(value); return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("pt-BR", {dateStyle:"short",timeStyle:"medium"}); }
function eventText(event) { const type=String(event?.type||event?.action||"Evento").replaceAll("_"," ").toLowerCase(); const message=event?.message||event?.details||event?.data?.message||""; return message?`${type} · ${message}`:type; }
function agentHost(agent) { return agent?.hostname || agent?.address || agent?.ip || agent?.public_host || agent?.node_id || "—"; }
function agentPlatform(agent) { return agent?.platform || agent?.system || agent?.os_name || agent?.os || "—"; }
function agentLocation(agent) { const region=agent?.region_id||agent?.region||""; const dc=agent?.datacenter_id||agent?.datacenter||""; return [region,dc].filter(Boolean).join(" / ") || "—"; }
function agentState(agent) { return String(agent?.health_status || agent?.health || agent?.status || "unknown"); }
function compactAgentId(value) {
    const id = String(value || "");
    if (!id || id.length <= 18) return id || "—";
    if (id.startsWith("agent-")) {
        const body = id.slice(6);
        return `agent-${body.slice(0,4)}…${body.slice(-4)}`;
    }
    return `${id.slice(0,8)}…${id.slice(-5)}`;
}

function closeAgentMenus(except = null) {
    document.querySelectorAll(".cap-agent-action-menu.is-open").forEach(menu => {
        if (menu !== except) menu.classList.remove("is-open");
    });
    document.querySelectorAll(".cap-agent-action-toggle[aria-expanded='true']").forEach(button => {
        if (!except || button.nextElementSibling !== except) button.setAttribute("aria-expanded", "false");
    });
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
        const instancesUrl = `servers.html?agent=${encodeURIComponent(id)}`;
        return `<tr>
            <td><a class="cap-agent-name" href="${detailsUrl}">${escapeHtml(agent.name || agent.id || "Agent")}</a><small title="${escapeHtml(agent.id || "—")}">${escapeHtml(compactAgentId(agent.id))}</small></td>
            <td>${escapeHtml(agentHost(agent))}</td>
            <td>${escapeHtml(agentPlatform(agent))}</td>
            <td>${escapeHtml(agentLocation(agent))}</td>
            <td><span class="cap-agent-state ${online ? "online" : "offline"}"><i></i>${escapeHtml(state)}</span></td>
            <td class="cap-agent-number">${escapeHtml(Number(agent.instance_count || 0))}</td>
            <td>${escapeHtml(formatDateTime(heartbeat))}</td>
            <td class="cap-agent-actions-cell">
                <div class="cap-agent-action-wrap">
                    <button class="cap-agent-action-toggle" type="button" aria-label="Ações de ${escapeHtml(agent.name || id || "Agent")}" aria-haspopup="menu" aria-expanded="false">⋮</button>
                    <div class="cap-agent-action-menu" role="menu">
                        <a role="menuitem" href="${detailsUrl}">Gerenciar Agent</a>
                        <a role="menuitem" href="${instancesUrl}">Ver instâncias</a>
                    </div>
                </div>
            </td>
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
function renderTimeline(result) { const events=Array.isArray(result)?result:(result?.events||[]); const list=$("home-events"); if(list){list.innerHTML=events.slice(0,5).map(event=>`<div class="cap-event"><time>${escapeHtml(formatTime(event.timestamp||event.time))}</time><i class="cap-event-dot"></i><div><p>${escapeHtml(eventText(event))}</p><small>${escapeHtml(event.category||event.source||"Sistema")}</small></div></div>`).join("")||'<div class="cap-empty">Nenhuma atividade recente.</div>'} const important=events.filter(event=>["warning","warn","error","critical","fatal"].includes(String(event.level||"").toLowerCase())); const alerts=$("home-alerts"); if(alerts){alerts.innerHTML=important.slice(0,3).map(event=>{const critical=["error","critical","fatal"].includes(String(event.level||"").toLowerCase());return `<article class="cap-alert ${critical?"":"warning"}"><strong class="${critical?"cap-bad":"cap-warn"}">${escapeHtml(String(event.level||"WARNING").toUpperCase())}</strong><p>${escapeHtml(eventText(event))}</p><time>${escapeHtml(formatTime(event.timestamp||event.time))}</time></article>`}).join("")||'<div class="cap-empty">Nenhum alerta importante no período.</div>'} text("home-alert-total",important.length); }
function renderHealth(result) { const data=result?.data||result||{};const status=String(data.status||"").toLowerCase();const failed=["failed","critical","offline","error"].includes(status);text("home-controller-health",data.status||"Operacional");const dot=$("home-controller-dot");if(dot)dot.classList.toggle("off",failed);const top=document.querySelector(".cap-controller-state");if(top){top.classList.toggle("cap-controller-failed",failed);const label=top.querySelector("span");if(label)label.textContent=failed?"Controller com falha":"Controller Online"}}
function renderUser(user) { const role=user?.role||"";text("home-user-name",user?.username||"Usuário");text("home-user-role",role);text("current-user",user?.username||"Sessão ativa");document.querySelectorAll(".admin-only").forEach(element=>element.style.display=role==="admin"?"":"none");document.querySelectorAll(".agent-manager-only").forEach(element=>element.style.display=["admin","controller"].includes(role)?"":"none");document.querySelectorAll(".instance-manager-only").forEach(element=>element.style.display=["admin","controller","client","customer"].includes(role)?"":"none"); }
function renderControllerTelemetry(result){if(!result)return;window.CapivaraTelemetry?.render($("controller-telemetry"),result.current||{},result.history||[],{label:"Controller",processKey:"controller",description:"Telemetria do host do Control Plane e consumo exclusivo do processo da Dashboard/Controller."})}

async function refresh() {
    const [user,agents,infrastructure,timeline,health,controllerTelemetry]=await Promise.all([get("/whoami"),get("/agents"),get("/infrastructure?active_only=true"),get("/timeline?limit=30"),get("/health"),get("/controller/telemetry?window_seconds=3600")]);
    if(user)renderUser(user);renderAgents(agents);renderInfrastructure(infrastructure);renderTimeline(timeline);renderHealth(health);renderControllerTelemetry(controllerTelemetry);text("home-last-refresh",new Date().toLocaleTimeString("pt-BR"));
}

function bindMobileSidebar(target,toggle){
    if(!target||!toggle)return;
    const isMobile=()=>window.innerWidth<=760;
    const setOpen=open=>{document.body.classList.toggle("sidebar-open",Boolean(open)&&isMobile());toggle.setAttribute("aria-expanded",Boolean(open)&&isMobile()?"true":"false");toggle.setAttribute("aria-label",Boolean(open)&&isMobile()?"Fechar menu":"Abrir menu");};
    toggle.addEventListener("click",event=>{event.stopPropagation();if(isMobile()){setOpen(!document.body.classList.contains("sidebar-open"));return;}document.body.classList.toggle("cap-sidebar-collapsed");});
    target.querySelector(".cap-sidebar-close")?.addEventListener("click",()=>setOpen(false));
    target.querySelectorAll("a").forEach(link=>link.addEventListener("click",()=>setOpen(false)));
    document.addEventListener("pointerdown",event=>{if(!isMobile()||!document.body.classList.contains("sidebar-open"))return;if(target.contains(event.target)||toggle.contains(event.target))return;setOpen(false);});
    let startX=null,startY=null;
    target.addEventListener("touchstart",event=>{const touch=event.changedTouches?.[0];if(!touch)return;startX=touch.clientX;startY=touch.clientY;},{passive:true});
    target.addEventListener("touchend",event=>{if(startX===null||startY===null)return;const touch=event.changedTouches?.[0];if(!touch)return;const dx=touch.clientX-startX,dy=touch.clientY-startY;startX=null;startY=null;if(isMobile()&&dx<-60&&Math.abs(dx)>Math.abs(dy)*1.2)setOpen(false);},{passive:true});
    window.addEventListener("resize",()=>{if(!isMobile())setOpen(false);});
}

function bindAgentTableScroll(){
    const viewport=document.querySelector(".cap-agent-table-scroll");
    if(!viewport)return;
    let active=false,startX=0,startY=0,startLeft=0,startTop=0;
    viewport.addEventListener("touchstart",event=>{
        if(event.touches.length!==1)return;
        const touch=event.touches[0];
        active=true;
        startX=touch.clientX;
        startY=touch.clientY;
        startLeft=viewport.scrollLeft;
        startTop=viewport.scrollTop;
    },{passive:true});
    viewport.addEventListener("touchmove",event=>{
        if(!active||event.touches.length!==1)return;
        const touch=event.touches[0];
        const dx=touch.clientX-startX;
        const dy=touch.clientY-startY;
        if(Math.abs(dx)<3&&Math.abs(dy)<3)return;
        event.preventDefault();
        viewport.scrollLeft=startLeft-dx;
        viewport.scrollTop=startTop-dy;
    },{passive:false});
    const stop=()=>{active=false;};
    viewport.addEventListener("touchend",stop,{passive:true});
    viewport.addEventListener("touchcancel",stop,{passive:true});
}

function bindAgentActionMenus(){
    const table=$("home-agent-table-body");
    if(!table)return;
    table.addEventListener("click",event=>{
        const button=event.target.closest(".cap-agent-action-toggle");
        if(!button)return;
        event.preventDefault();event.stopPropagation();
        const menu=button.nextElementSibling;
        const opening=!menu.classList.contains("is-open");
        closeAgentMenus(menu);
        menu.classList.toggle("is-open",opening);
        button.setAttribute("aria-expanded",opening?"true":"false");
    });
    document.addEventListener("click",event=>{if(!event.target.closest(".cap-agent-action-wrap"))closeAgentMenus();});
    document.addEventListener("keydown",event=>{if(event.key==="Escape")closeAgentMenus();});
}

async function loadSidebar(){
    const target=$("sidebar-component");if(!target)return;
    const response=await fetch("/components/sidebar-v3.html",{headers:controllerHeaders(),credentials:"same-origin",cache:"no-store"});
    if(response.ok)target.innerHTML=await response.text();
    const logout=$("btn-logout");if(logout)logout.onclick=async()=>{try{await fetch("/api/auth/logout",{method:"POST",headers:controllerHeaders(),credentials:"same-origin",cache:"no-store"});}finally{window.location.replace("/login.html")}};
    bindMobileSidebar(target,$("home-menu-toggle"));
}

document.addEventListener("DOMContentLoaded",async()=>{
    await loadSidebar();
    bindAgentTableScroll();
    bindAgentActionMenus();
    $("home-refresh")?.addEventListener("click",refresh);
    await refresh();
    window.setInterval(refresh,30000);
});
