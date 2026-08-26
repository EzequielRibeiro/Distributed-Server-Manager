(function(){
  "use strict";

  const auth=()=>sessionStorage.getItem("dsm_auth")||"";
  const $=id=>document.getElementById(id);
  const identity=Object.fromEntries(new URLSearchParams(location.search));
  const blockedViews=new Set(["logs","events","config","files","content","backups","danger"]);
  let timer=null;

  function query(){return new URLSearchParams(identity).toString()}

  async function request(path){
    const response=await fetch(path,{headers:{Authorization:`Basic ${auth()}`,Accept:"application/json"}});
    if(response.status===401){sessionStorage.removeItem("dsm_auth");location.href="/login.html";throw new Error("Sessão encerrada.")}
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(data.error||data.message||`HTTP ${response.status}`);
    return data;
  }

  function timestamp(value){
    if(value===null||value===undefined||value==="")return "";
    const date=typeof value==="number"?new Date(value*1000):new Date(value);
    return Number.isNaN(date.getTime())?String(value):date.toLocaleString();
  }

  function severity(value){
    const normalized=String(value||"info").toLowerCase();
    if(["critical","error","failed","fatal"].includes(normalized))return "error";
    if(["warning","warn","degraded"].includes(normalized))return "warning";
    if(["success","ok","completed"].includes(normalized))return "success";
    return "info";
  }

  function render(events){
    const container=$("instance-events-list");
    const counter=$("instance-events-count");
    if(!container)return;
    container.replaceChildren();
    if(counter)counter.textContent=`${events.length} evento(s)`;

    events.forEach(event=>{
      const row=document.createElement("article");
      row.className=`instance-event instance-event-${severity(event.severity||event.level||event.status)}`;
      const head=document.createElement("div");head.className="instance-event-head";
      const title=document.createElement("strong");title.textContent=event.title||event.type||event.action||event.code||"Evento";
      const time=document.createElement("time");time.textContent=timestamp(event.timestamp??event.time??event.created_at??event.occurred_at);
      const body=document.createElement("p");body.textContent=event.message||event.details||event.reason||event.data?.message||"";
      const meta=document.createElement("small");meta.textContent=[event.category||event.source,event.code,event.stage].filter(Boolean).join(" · ");
      head.append(title,time);row.append(head,body,meta);container.append(row);
    });

    if(!container.children.length){const empty=document.createElement("p");empty.className="instance-events-empty";empty.textContent="Nenhum evento registrado para esta instância.";container.append(empty)}
  }

  async function load(){
    if(!identity.server||!identity.game||!identity.instance)return;
    const summary=await request(`/api/runtime?${query()}`);
    const events=Array.isArray(summary.events)?summary.events:[];
    render([...events].sort((a,b)=>String(b.timestamp??b.time??b.created_at??"").localeCompare(String(a.timestamp??a.time??a.created_at??""))).slice(0,200));
  }

  function showOverview(){
    const overview=document.querySelector('[data-view="overview"]');
    if(!overview)return;
    document.querySelectorAll("[data-view]").forEach(button=>button.classList.toggle("active",button===overview));
    document.querySelectorAll(".view").forEach(view=>view.classList.toggle("active",view.id==="view-overview"));
  }

  function syncProvisionFailureTabs(){
    const provision=$("provision-progress");
    const blocked=Boolean(provision&&provision.classList.contains("provision-failed"));
    let blockedViewWasActive=false;

    document.querySelectorAll("[data-view]").forEach(button=>{
      const view=String(button.dataset.view||"");
      if(!blockedViews.has(view))return;
      if(blocked&&button.classList.contains("active"))blockedViewWasActive=true;
      button.disabled=blocked;
      button.setAttribute("aria-disabled",blocked?"true":"false");
      button.title=blocked?"Indisponível enquanto houver erro na instalação da instância.":"";
      button.style.cursor=blocked?"not-allowed":"";
      button.style.opacity=blocked?"0.45":"";
    });

    if(blocked&&blockedViewWasActive)showOverview();
  }

  function installProvisionFailureGuard(){
    const provision=$("provision-progress");
    if(!provision)return;
    new MutationObserver(syncProvisionFailureTabs).observe(provision,{attributes:true,attributeFilter:["class","hidden"],childList:true,subtree:true});
    syncProvisionFailureTabs();
  }

  function active(){return document.querySelector('[data-view="events"]')?.classList.contains("active")}
  function schedule(){
    if(timer)clearInterval(timer);
    timer=setInterval(()=>{if(active())load().catch(()=>{})},5000);
  }

  document.addEventListener("DOMContentLoaded",()=>{
    document.querySelector('[data-view="events"]')?.addEventListener("click",()=>load().catch(()=>{}));
    $("instance-events-refresh")?.addEventListener("click",()=>load().catch(()=>{}));
    installProvisionFailureGuard();
    schedule();
  });
})();
