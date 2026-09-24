(()=>{"use strict";
const q=new URLSearchParams(location.search),iid=q.get("instance")||q.get("instance_id")||"";

function ensureCard(){
 let card=document.getElementById("customer-connection-card");
 if(card)return card;
 const host=document.getElementById("view-overview");
 if(!host)return null;
 card=document.createElement("article");
 card.id="customer-connection-card";
 card.className="card";
 card.innerHTML='<div class="row"><div><span class="muted">ENDEREÇO DO SERVIDOR</span><h2 id="customer-connection-address">Disponível após a configuração</h2><p id="customer-connection-detail" class="muted">Aguardando endpoint público do Agent.</p></div><button id="customer-connection-copy" class="btn" type="button" disabled>Copiar endereço</button></div><div id="customer-query-check" class="row mt-12 hidden"><div><span class="muted">QUERY CHECK</span><strong id="customer-query-target">—</strong><p id="customer-query-detail" class="muted"></p><div id="customer-query-result" class="muted"></div></div><a id="customer-query-link" class="btn" href="#" target="_blank" rel="noopener noreferrer">Verificar publicamente</a><button id="customer-query-native" class="btn primary hidden" type="button">Testar Steam Query</button></div>';
 host.insertBefore(card,host.firstChild);
 document.getElementById("customer-connection-copy").addEventListener("click",async()=>{
  const value=document.getElementById("customer-connection-address").dataset.address||"";
  if(!value)return;
  try{
   await navigator.clipboard.writeText(value);
   const button=document.getElementById("customer-connection-copy");
   button.textContent="Copiado!";
   setTimeout(()=>button.textContent="Copiar endereço",1500);
  }catch(_){}
 });
 return card;
}

function renderPorts(rows){
 const box=document.getElementById("ports");
 if(!box)return;
 box.dataset.connectionEnhanced="1";
 box.replaceChildren(...(rows||[]).map(p=>{
  const d=document.createElement("div");
  d.className="row";
  const state=String(p.state||"unknown");
  const label=state==="listening"?"ONLINE":state==="reserved"?"RESERVADA":"DESCONHECIDA";
  const name=p.label||p.name||p.protocol;
  d.innerHTML=`<span>${name} · ${p.port}/${String(p.protocol||"udp").toUpperCase()}</span><strong class="${state==="listening"?"state ok":"muted"}">${label}</strong>`;
  return d;
 }));
}


async function runNativeQuery(){
 const button=document.getElementById("customer-query-native");
 const result=document.getElementById("customer-query-result");
 if(!button||!result||!iid)return;
 const original=button.textContent;
 button.disabled=true;button.textContent="Testando…";result.textContent="Consultando Steam Query pelo Capivara DSM…";
 try{
  const r=await fetch(`/api/customer/instance/connection/test?instance_id=${encodeURIComponent(iid)}`,{
   headers:{Accept:"application/json","X-Capivara-Auth-Area":"customer"},
   credentials:"same-origin",cache:"no-store"
  });
  if(r.status===401){location.replace("/customer-login.html");return}
  const d=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(d.message||`HTTP ${r.status}`);
  if(d.online!==true){
   if(d.listener_online){result.textContent=`ONLINE NO AGENT · acesso público não confirmado · ${d.message||"Steam Query pública não respondeu."}`;return}
   result.textContent=`SEM RESPOSTA · ${d.message||"Steam Query não respondeu."}`;return
  }
  const info=d.info||{},rules=d.rules||{};
  const parts=[
   "ONLINE",
   info.name||null,
   info.map?`Mapa ${info.map}`:null,
   Number.isFinite(Number(info.players))&&Number.isFinite(Number(info.max_players))?`${info.players}/${info.max_players} jogadores`:null,
   info.version?`v${info.version}`:null,
   rules.format==="key_value"?`${Object.keys(rules.rules||{}).length} regras`:rules.declared?`${rules.declared} regras/dados publicados`:null
  ].filter(Boolean);
  result.textContent=parts.join(" · ");
 }catch(e){result.textContent=`Falha no teste: ${e.message}`}
 finally{button.disabled=false;button.textContent=original}
}

function renderQuery(check){
 const wrap=document.getElementById("customer-query-check");
 const link=document.getElementById("customer-query-link");
 const nativeButton=document.getElementById("customer-query-native");
 const target=document.getElementById("customer-query-target");
 const detail=document.getElementById("customer-query-detail");
 const result=document.getElementById("customer-query-result");
 if(!wrap||!link||!nativeButton||!target||!detail||!result)return;
 if(!check){wrap.classList.add("hidden");return}
 wrap.classList.remove("hidden");
 target.textContent=check.target||"—";
 result.textContent="";
 if(check.native){
  link.classList.add("hidden");
  nativeButton.classList.remove("hidden");
  nativeButton.onclick=runNativeQuery;
  detail.textContent=`Teste nativo Steam Query pelo Capivara DSM · ${String(check.protocol||"A2S").toUpperCase()}${check.status==="conditional"?" · compatibilidade condicional":""}`;
 }else if(check.url){
  nativeButton.classList.add("hidden");
  link.classList.remove("hidden");
  link.href=check.url;
  detail.textContent=`Consulta pública via ${check.provider||"serviço externo"} · ${String(check.protocol||"").toUpperCase()}${check.status==="conditional"?" · compatibilidade condicional":""}`;
 }else{
  wrap.classList.add("hidden");
 }
}

async function load(){
 if(!iid||!ensureCard())return;
 const address=document.getElementById("customer-connection-address");
 const detail=document.getElementById("customer-connection-detail");
 const copy=document.getElementById("customer-connection-copy");
 try{
  const r=await fetch(`/api/customer/instance/connection?instance_id=${encodeURIComponent(iid)}`,{
   headers:{Accept:"application/json","X-Capivara-Auth-Area":"customer"},
   credentials:"same-origin",
   cache:"no-store"
  });
  if(r.status===401){location.replace("/customer-login.html");return}
  const d=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(d.message||`HTTP ${r.status}`);
  renderPorts(d.ports||[]);
  renderQuery(d.external_query);
  const c=d.connection;
  if(!c){
   address.textContent="Acesso público ainda não configurado";
   address.dataset.address="";
   detail.textContent="O administrador precisa configurar o hostname público ou IPv4 público do Agent.";
   copy.disabled=true;
   return;
  }
  address.textContent=c.address;
  address.dataset.address=c.address;
  copy.disabled=false;
  const source=c.source==="dns"?"Acesso por DNS":"Acesso por IPv4 público";
  detail.textContent=`${source} · ${String(c.protocol||"udp").toUpperCase()} · Agent ${String(d.agent_health||"unknown").toUpperCase()}`;
 }catch(e){
  address.textContent="Endereço indisponível";
  address.dataset.address="";
  detail.textContent=e.message;
  copy.disabled=true;
 }
}
window.addEventListener("load",()=>{load();setInterval(load,30000)});
})();
