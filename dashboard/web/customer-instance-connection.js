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
 card.innerHTML='<div class="row"><div><span class="muted">ENDEREÇO DO SERVIDOR</span><h2 id="customer-connection-address">Disponível após a configuração</h2><p id="customer-connection-detail" class="muted">Aguardando endpoint público do Agent.</p></div><button id="customer-connection-copy" class="btn" type="button" disabled>Copiar endereço</button></div>';
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

function ensureVotifierCard(){
 let card=document.getElementById("customer-votifier-card");
 if(card)return card;
 const host=document.getElementById("view-overview");
 if(!host)return null;
 card=document.createElement("article");
 card.id="customer-votifier-card";
 card.className="card";
 card.hidden=true;
 const heading=document.createElement("h2");
 heading.textContent="Votifier · porta sob demanda";
 const status=document.createElement("p");
 status.id="customer-votifier-status";
 status.className="muted";
 const toggle=document.createElement("button");
 toggle.id="customer-votifier-toggle";
 toggle.className="btn";
 toggle.type="button";
 toggle.addEventListener("click", async()=>{
  if(toggle.disabled||toggle.dataset.canEditNow!=="true")return;
  const enabled=toggle.dataset.pendingAction==="enable" ? true
   :toggle.dataset.pendingAction==="disable" ? false
   :toggle.dataset.enabled!=="true";
  if(!enabled&&!confirm("Liberar a reserva do Votifier? Remova ou desative a configuração do mod/plugin antes de continuar."))return;
  toggle.disabled=true;
  status.textContent="Sincronizando reserva com o Agent…";
  try{
   const response=await fetch("/api/customer/instance/connection/votifier",{
    method:"POST",credentials:"same-origin",cache:"no-store",
    headers:{"Content-Type":"application/json","Accept":"application/json","X-Capivara-Auth-Area":"customer"},
    body:JSON.stringify({instance_id:iid,enabled})
   });
   const payload=await response.json().catch(()=>({}));
   if(!response.ok)throw new Error(payload.message||"A operação Votifier falhou.");
   status.textContent=payload.status==="pending_sync"
    ?"Reserva pendente de sincronização. Tente novamente com o servidor parado."
    :enabled?"Porta reservada. Configure o Votifier para escutá-la; inicie o servidor depois."
            :"Porta liberada para outras instâncias.";
   await load();
  }catch(error){
   status.textContent=error.message;
   toggle.disabled=toggle.dataset.canEditNow!=="true";
  }
 });
 card.append(heading,status,toggle);
 const connection=document.getElementById("customer-connection-card");
 if(connection?.parentNode)connection.after(card);else host.prepend(card);
 return card;
}
function renderVotifier(value, instanceStatus){
 const card=ensureVotifierCard();
 if(!card)return;
 const item=value||{};
 card.hidden=!(item.supported||item.reserved);
 if(card.hidden)return;
 const status=document.getElementById("customer-votifier-status");
 const button=document.getElementById("customer-votifier-toggle");
 const reserved=item.reserved===true;
 const port=item.port;
 // The backend also checks the managed systemd unit, protecting against stale UI state.
 const stopped=["stopped","offline"].includes(String(instanceStatus||"").trim().toLowerCase());
 status.textContent=item.pending
  ?item.pending_drop
   ?"Desativação pendente: a porta permanece protegida até o Agent confirmar."
   :"Ativação pendente: a reserva está protegida, mas o Agent ainda precisa sincronizar."
  :reserved
   ?`Reservada: ${port}/TCP. Configure manualmente o mod ou plugin Votifier para usar esta porta.`
   :"Nenhuma porta Votifier reservada. Habilite apenas quando for utilizar um mod ou plugin compatível.";
 if(!item.manageable&&!item.pending&&reserved)status.textContent+=" A alteração exige sincronização compatível do Agent.";
 if(item.manageable&&!stopped)status.textContent+=" Pare o servidor para ativar ou liberar a porta Votifier.";
 button.hidden=!item.manageable;
 button.disabled=!item.manageable||!stopped;
 button.dataset.canEditNow=String(item.manageable===true&&stopped);
 button.dataset.enabled=String(reserved);
 button.dataset.pendingAction=item.pending
  ?(item.pending_drop?"disable":"enable"):"";
 button.textContent=item.pending
  ?(item.pending_drop?"Concluir liberação":"Concluir ativação")
  :reserved?"Liberar reserva":"Reservar porta Votifier";
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
  renderVotifier(d.votifier,d.status);
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
  // A failed refresh must never leave a previously enabled action clickable.
  const toggle=document.getElementById("customer-votifier-toggle");
  if(toggle){toggle.disabled=true;toggle.dataset.canEditNow="false";}
  address.textContent="Endereço indisponível";
  address.dataset.address="";
  detail.textContent=e.message;
  copy.disabled=true;
 }
}
window.addEventListener("load",()=>{load();setInterval(load,30000)});
})();
