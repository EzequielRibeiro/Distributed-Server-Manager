(function(){
"use strict";

const auth=()=>sessionStorage.getItem("dsm_auth")||"";
const params=new URLSearchParams(location.search);
const agentId=params.get("agent_id")||params.get("id")||"";
const el=id=>document.getElementById(id);

function bytes(value){
  const n=Number(value);
  if(!Number.isFinite(n)||n<0)return "—";
  const units=["B","KiB","MiB","GiB","TiB","PiB"];
  let v=n,i=0;
  while(v>=1024&&i<units.length-1){v/=1024;i+=1;}
  return `${v>=100||i===0?v.toFixed(0):v.toFixed(1)} ${units[i]}`;
}

function pct(usable,total){
  const u=Number(usable),t=Number(total);
  if(!Number.isFinite(u)||!Number.isFinite(t)||t<=0)return null;
  return Math.max(0,Math.min(100,(u/t)*100));
}

function value(v,f="—"){return v===null||v===undefined||v===""?f:String(v);}

function poolCard(pool){
  const card=document.createElement("div");
  card.className="cap-range-card cap-storage-pool-card";
  const health=String(pool.health||"unknown").toLowerCase();
  card.dataset.health=health;

  const title=document.createElement("strong");
  title.textContent=`${value(pool.id,"pool")}${pool.default?" · padrão":""}`;

  const meta=document.createElement("span");
  meta.textContent=`${value(pool.storage_class,"standard")} · prioridade ${value(pool.priority,0)} · ${pool.enabled===false?"desabilitado":health}`;

  const path=document.createElement("code");
  path.textContent=value(pool.root_path);

  const capacity=document.createElement("span");
  capacity.textContent=`Utilizável ${bytes(pool.usable_bytes)} · Livre ${bytes(pool.free_bytes)} · Reserva ${bytes(pool.reserve_bytes)} · Total ${bytes(pool.total_bytes)}`;

  const ratio=pct(pool.usable_bytes,pool.total_bytes);
  const progress=document.createElement("div");
  progress.className="cap-storage-pool-progress";
  progress.setAttribute("role","progressbar");
  progress.setAttribute("aria-label",`Capacidade utilizável do pool ${value(pool.id,"pool")}`);
  progress.setAttribute("aria-valuemin","0");
  progress.setAttribute("aria-valuemax","100");
  progress.setAttribute("aria-valuenow",ratio===null?"0":ratio.toFixed(1));
  const fill=document.createElement("i");
  fill.style.width=`${ratio===null?0:ratio}%`;
  progress.append(fill);

  card.append(title,meta,path,capacity,progress);
  return card;
}

function render(pools){
  const box=el("agent-storage-pools");
  const summary=el("agent-storage-pools-summary");
  if(!box)return;
  const list=Array.isArray(pools)?pools:[];
  box.replaceChildren();
  if(!list.length){
    const empty=document.createElement("div");
    empty.className="cap-detail-note";
    empty.textContent="Este Agent ainda não publicou inventário de Storage Pools. Agents legados continuam usando o diretório de armazenamento único.";
    box.append(empty);
    if(summary)summary.textContent="Sem inventário de pools no último heartbeat.";
    return;
  }
  list.forEach(pool=>box.append(poolCard(pool)));
  const online=list.filter(p=>String(p.health||"").toLowerCase()==="online"&&p.enabled!==false).length;
  const usable=list.reduce((sum,p)=>sum+(Number.isFinite(Number(p.usable_bytes))?Number(p.usable_bytes):0),0);
  if(summary)summary.textContent=`${list.length} pool(s) publicado(s) · ${online} disponível(is) · ${bytes(usable)} utilizáveis no total.`;
}

async function refresh(){
  if(!agentId||!auth())return;
  try{
    const r=await fetch(`/api/agent/ports?agent_id=${encodeURIComponent(agentId)}`,{headers:{Authorization:"Basic "+auth(),Accept:"application/json"},cache:"no-store"});
    if(!r.ok)return;
    const payload=await r.json();
    const telemetry=payload.telemetry||payload.agent?.telemetry||{};
    render(telemetry.storage_pools||payload.agent?.metadata?.telemetry?.storage_pools||[]);
  }catch(_){/* main page owns global error reporting */}
}

document.addEventListener("DOMContentLoaded",()=>{refresh();setInterval(refresh,30000);});
})();
