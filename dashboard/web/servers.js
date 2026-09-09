(function(){
"use strict";

const API="/api";
const state={instances:[],filter:"all",query:"",sidebarCollapsed:false};
const el=id=>document.getElementById(id);
const controllerHeaders=()=>({"X-Capivara-Auth-Area":"controller",Accept:"application/json"});

async function request(path,options={}){
    const headers={...controllerHeaders(),...(options.headers||{})};
    if(options.body&&!headers["Content-Type"])headers["Content-Type"]="application/json";
    const r=await fetch(path,{...options,headers,credentials:"same-origin",cache:"no-store"});
    if(r.status===401){
        location.replace("login.html");
        throw new Error("Sessão expirada");
    }
    const p=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(p.error||p.message||`HTTP ${r.status}`);
    return p;
}

function applySidebarState(c){
    state.sidebarCollapsed=c;
    document.body.classList.toggle("cap-sidebar-collapsed",c);
    localStorage.setItem("cap_sidebar_collapsed",c?"1":"0");
}

async function loadSidebar(){
    const host=el("sidebar-component");
    if(!host)return;
    const r=await fetch("components/sidebar-v3.html",{headers:controllerHeaders(),credentials:"same-origin",cache:"no-store"});
    if(r.status===401){
        location.replace("login.html");
        throw new Error("Sessão expirada");
    }
    if(!r.ok)throw new Error(`sidebar HTTP ${r.status}`);
    host.innerHTML=await r.text();
    host.querySelectorAll("nav a").forEach(a=>a.classList.toggle("active",a.getAttribute("href")==="servers.html"));
    el("btn-logout")?.addEventListener("click",()=>{location.replace("login.html")});
    const who=await request("/api/whoami");
    el("current-user").textContent=`${who.username} (${who.role})`;
    el("servers-user-name").textContent=who.username||"—";
    el("servers-user-role").textContent=who.role||"—";
    document.querySelectorAll(".admin-only").forEach(x=>x.style.display=who.role==="admin"?"":"none");
    document.querySelectorAll(".agent-manager-only").forEach(x=>x.style.display=["admin","controller"].includes(who.role)?"":"none");
    document.querySelectorAll(".instance-manager-only").forEach(x=>x.style.display=["admin","controller","operator"].includes(who.role)?"":"none");
    applySidebarState(localStorage.getItem("cap_sidebar_collapsed")==="1");
    el("servers-menu-toggle")?.addEventListener("click",()=>{
        if(window.innerWidth<=760){
            document.body.classList.toggle("sidebar-open");
            return;
        }
        applySidebarState(!state.sidebarCollapsed);
    });
    host.querySelectorAll("a").forEach(a=>a.addEventListener("click",()=>document.body.classList.remove("sidebar-open")));
}

function identity(i){
    return{
        server:i.server||i.node||i.node_id||"",
        game:i.game||"unknown",
        instance:i.instance||i.id||"unknown"
    };
}

function gameIcon(g){
    g=String(g).toLowerCase();
    if(g.includes("minecraft"))return"🧊";
    if(g.includes("dayz"))return"◈";
    if(g.includes("rust"))return"⬢";
    if(g.includes("arma"))return"◆";
    return"🎮";
}

function rawStatus(source){
    return String(
        source?.server_state?.status?.state??
        source?.status?.state??
        source?.state??
        source?.status??
        "unknown"
    ).trim().toLowerCase();
}

function normalizeStatus(source){
    const r=rawStatus(source);
    if(["online","running","started","active"].includes(r))return"online";
    if(["offline","stopped"].includes(r))return"offline";
    if(["starting","stopping","updating","installing","warning","degraded","failed","error"].includes(r))return"attention";
    return"unknown";
}

function number(v,f=0){
    const n=Number(v);
    return Number.isFinite(n)?n:f;
}

function normalize(resource,summary,agents){
    const id=identity(resource);
    const meta=summary?.instance_metadata||{};
    const metrics=summary?.metrics||{};
    const serverState=summary?.server_state||{};
    const summaryStatus=normalizeStatus(summary);
    const resourceStatus=normalizeStatus(resource);
    const status=summaryStatus==="unknown"?resourceStatus:summaryStatus;
    const players=number(serverState?.players??metrics?.players??summary?.players,0);
    const slots=number(serverState?.max_players??serverState?.slots??summary?.max_players,0);
    const ramMb=number(metrics?.instance?.memory_mb??metrics?.memory_mb??metrics?.ram_mb,0);
    const cpu=number(metrics?.instance?.cpu_pct??metrics?.cpu_pct??metrics?.cpu?.pct,0);
    const agentId=meta.agent_id||meta.agent||id.server;
    const agent=agents.find(a=>[a.id,a.agent_id,a.node_id,a.name].filter(Boolean).map(String).includes(String(agentId)));
    const location=agent?.location_name||agent?.location||agent?.datacenter_name||agent?.datacenter||meta.datacenter||"-";
    return{
        ...id,
        status,
        players,
        slots,
        ramMb,
        cpu,
        display:meta.display_name||id.instance,
        agent:agent?.name||agent?.id||agent?.agent_id||agentId||"-",
        location
    };
}

async function enrich(resources,agents){
    const result=new Array(resources.length);
    let cursor=0;
    async function worker(){
        while(cursor<resources.length){
            const i=cursor++;
            const r=resources[i];
            const id=identity(r);
            let summary=null;
            if(i<48&&id.server&&id.game&&id.instance){
                try{
                    summary=await request(`/api/runtime?${new URLSearchParams(id)}`);
                }catch(error){
                    console.warn("Runtime detail unavailable; preserving list projection",id,error);
                }
            }
            result[i]=normalize(r,summary,agents);
        }
    }
    await Promise.all(Array.from({length:Math.min(6,resources.length||1)},worker));
    return result;
}

function fmtRam(mb){
    return !mb?"-":mb>=1024?`${(mb/1024).toFixed(2)} GB`:`${Math.round(mb)} MB`;
}

function escapeHtml(v){
    return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function statusLabel(status){
    if(status==="online")return"Online";
    if(status==="offline")return"Offline";
    if(status==="attention")return"Atenção";
    return"Desconhecido";
}

function ensureManageDialog(){
    let dialog=el("instance-manage-dialog");
    if(dialog)return dialog;
    dialog=document.createElement("dialog");
    dialog.id="instance-manage-dialog";
    dialog.className="cap-manage-dialog";
    dialog.innerHTML=`<div class="cap-manage-shell"><header><div><span class="cap-manage-eyebrow">INSTÂNCIA</span><h2 id="manage-title">Gerenciar instância</h2><p id="manage-subtitle">Carregando...</p></div><button id="manage-close" class="cap-manage-close" type="button" aria-label="Fechar">×</button></header><div id="manage-message" class="cap-manage-message" hidden></div><section class="cap-manage-state"><div><span>Estado</span><strong id="manage-state">—</strong></div><div><span>Origem</span><strong id="manage-source">—</strong></div><div><span>Desejado</span><strong id="manage-desired">—</strong></div><div><span>Observado</span><strong id="manage-observed">—</strong></div></section><section class="cap-manage-actions" aria-label="Controles da instância"><button data-action="start" type="button">Iniciar</button><button data-action="restart" type="button">Reiniciar</button><button data-action="stop" class="danger" type="button">Parar</button></section><footer><a id="manage-console" class="cap-manage-link" href="console.html">Abrir console</a><button id="manage-refresh" type="button">Atualizar estado</button></footer></div>`;
    document.body.append(dialog);
    el("manage-close").addEventListener("click",()=>dialog.close());
    dialog.addEventListener("click",event=>{if(event.target===dialog)dialog.close();});
    el("manage-refresh").addEventListener("click",()=>refreshManage(dialog));
    dialog.querySelectorAll("[data-action]").forEach(button=>button.addEventListener("click",()=>controlManagedInstance(dialog,button.dataset.action)));
    return dialog;
}

function setManageBusy(dialog,busy){
    dialog.querySelectorAll("button").forEach(button=>button.disabled=busy);
}

function manageMessage(text,tone="info"){
    const box=el("manage-message");
    box.hidden=!text;
    box.dataset.tone=tone;
    box.textContent=text||"";
}

function manageProjection(summary){
    const serverState=summary?.server_state||{};
    const status=normalizeStatus(summary);
    return{
        status,
        source:serverState?.source??summary?.status_source??summary?.source??"—",
        desired:serverState?.desired_state??summary?.desired_state??"—",
        observed:serverState?.observed_state??summary?.observed_state??rawStatus(summary)??"—"
    };
}

async function refreshManage(dialog){
    const current=dialog._capInstance;
    if(!current)return;
    setManageBusy(dialog,true);
    manageMessage("");
    try{
        const id=identity(current);
        const summary=await request(`/api/runtime?${new URLSearchParams(id)}`);
        const projection=manageProjection(summary);
        el("manage-state").textContent=statusLabel(projection.status);
        el("manage-state").dataset.state=projection.status;
        el("manage-source").textContent=projection.source;
        el("manage-desired").textContent=projection.desired;
        el("manage-observed").textContent=projection.observed;
    }catch(error){
        manageMessage(`Não foi possível atualizar o estado: ${error.message}`,"error");
    }finally{
        setManageBusy(dialog,false);
    }
}

async function controlManagedInstance(dialog,action){
    const current=dialog._capInstance;
    if(!current)return;
    if(action!=="start"&&!confirm(`${action==="restart"?"Reiniciar":"Parar"} ${current.display}?`))return;
    setManageBusy(dialog,true);
    manageMessage(`Executando ${action}...`);
    try{
        const id=identity(current);
        await request(`/api/instance/${action}`,{method:"POST",body:JSON.stringify(id)});
        manageMessage("Operação concluída. Atualizando estado...","success");
        await new Promise(resolve=>setTimeout(resolve,700));
        await refreshManage(dialog);
        await load();
    }catch(error){
        manageMessage(error.message,"error");
    }finally{
        setManageBusy(dialog,false);
    }
}

async function openManage(instance){
    const dialog=ensureManageDialog();
    dialog._capInstance=instance;
    const id=identity(instance);
    el("manage-title").textContent=instance.display||id.instance;
    el("manage-subtitle").textContent=`${id.game} · ${instance.agent||id.server} · ${id.instance}`;
    el("manage-console").href=`console.html?${new URLSearchParams(id)}`;
    el("manage-state").textContent="Carregando...";
    el("manage-source").textContent="—";
    el("manage-desired").textContent="—";
    el("manage-observed").textContent="—";
    manageMessage("");
    if(!dialog.open)dialog.showModal();
    await refreshManage(dialog);
}

function card(i){
    const a=document.createElement("article");
    a.className="cap-instance-card";
    a.dataset.state=i.status;
    const label=statusLabel(i.status);
    const players=i.slots?`${i.players} / ${i.slots}`:String(i.players);
    const ramPct=Math.max(0,Math.min(100,i.ramMb?Math.min(100,(i.ramMb/16384)*100):0));
    const qs=new URLSearchParams({server:i.server,game:i.game,instance:i.instance});
    a.innerHTML=`<div class="cap-instance-head"><div class="cap-instance-title"><span class="cap-game-mark">${gameIcon(i.game)}</span><div><strong>${escapeHtml(i.display)}</strong><small>${escapeHtml(i.game)} · ${escapeHtml(i.agent)}</small></div></div><span class="cap-state ${i.status}">${label}</span></div><div class="cap-instance-meta"><div><span>Jogadores</span><strong>${players}</strong></div><div><span>CPU</span><strong>${i.cpu?i.cpu.toFixed(1)+"%":"-"}</strong></div><div><span>Agent</span><strong>${escapeHtml(i.agent)}</strong></div><div><span>Localização</span><strong>${escapeHtml(i.location)}</strong></div></div><div class="cap-meter"><div class="cap-meter-row"><span>RAM</span><strong>${fmtRam(i.ramMb)}</strong></div><div class="cap-meter-track"><div class="cap-meter-fill" style="width:${ramPct}%"></div></div></div><div class="cap-instance-actions"><a class="cap-action-primary" href="console.html?${qs}">Console</a><button class="cap-action-secondary" type="button">Gerenciar</button></div>`;
    a.querySelector(".cap-action-secondary").addEventListener("click",()=>openManage(i));
    return a;
}

function render(){
    const q=state.query.trim().toLowerCase();
    const visible=state.instances.filter(i=>(state.filter==="all"||i.status===state.filter)&&(!q||[i.display,i.game,i.instance,i.agent,i.server,i.location].some(v=>String(v).toLowerCase().includes(q))));
    el("instance-grid").replaceChildren(...visible.map(card));
    el("instance-empty").hidden=visible.length>0;
    el("instance-summary-text").textContent=`${visible.length} de ${state.instances.length} instância(s) exibida(s).`;
    el("fleet-total").textContent=state.instances.length;
    el("fleet-online").textContent=state.instances.filter(i=>i.status==="online").length;
    el("fleet-offline").textContent=state.instances.filter(i=>i.status==="offline").length;
    el("fleet-agents").textContent=new Set(state.instances.map(i=>i.agent).filter(v=>v&&v!=="-")).size;
}

async function load(){
    const btn=el("refresh-instances");
    if(btn)btn.disabled=true;
    el("instance-summary-text").textContent="Sincronizando Runtime...";
    try{
        const[r,a]=await Promise.all([
            request("/api/runtime/list"),
            request("/api/agents").catch(()=>({agents:[]}))
        ]);
        state.instances=await enrich(
            Array.isArray(r)?r:(r.resources||[]),
            Array.isArray(a)?a:(a.agents||[])
        );
        render();
    }catch(e){
        state.instances=[];
        render();
        el("instance-summary-text").textContent=`Não foi possível carregar as instâncias: ${e.message}`;
    }finally{
        if(btn)btn.disabled=false;
    }
}

function bind(){
    el("refresh-instances")?.addEventListener("click",load);
    el("instance-search")?.addEventListener("input",e=>{
        state.query=e.target.value;
        render();
    });
    document.querySelectorAll(".cap-filter").forEach(b=>b.addEventListener("click",()=>{
        document.querySelectorAll(".cap-filter").forEach(x=>x.classList.remove("active"));
        b.classList.add("active");
        state.filter=b.dataset.filter;
        render();
    }));
}

async function init(){
    try{
        await loadSidebar();
    }catch(e){
        console.error("Sidebar error",e);
    }
    bind();
    await load();
}

document.addEventListener("DOMContentLoaded",init);
})();
