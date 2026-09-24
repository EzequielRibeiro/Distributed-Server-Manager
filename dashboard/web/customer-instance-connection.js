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
