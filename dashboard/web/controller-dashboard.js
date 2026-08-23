(function(){
  "use strict";

  const auth=()=>sessionStorage.getItem("dsm_auth")||"";
  const $=id=>document.getElementById(id);

  async function request(path){
    const response=await fetch(path,{headers:{Authorization:`Basic ${auth()}`,Accept:"application/json"}});
    if(response.status===401){sessionStorage.removeItem("dsm_auth");location.replace("/login.html");throw new Error("Sessão encerrada.")}
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(data.error||data.message||`HTTP ${response.status}`);
    return data;
  }

  function text(id,value){const node=$(id);if(node)node.textContent=value??"-"}
  function progress(id,value){const node=$(id);if(node)node.style.width=`${Math.max(0,Math.min(100,Number(value)||0))}%`}
  function percent(value){return `${(Number(value)||0).toFixed(1)}%`}

  async function loadMetrics(){
    const response=await request("/api/metrics");
    const data=response.data??response;
    const cpu=Number(data.cpu?.host_pct)||0;
    const ram=100-(Number(data.memory?.free_pct)||100);
    const disk=Number(data.disk?.used_pct)||0;
    progress("cpu-bar",cpu);progress("ram-bar",ram);progress("disk-bar",disk);
    text("cpu-value",percent(cpu));text("ram-value",percent(ram));text("disk-value",percent(disk));
    text("host-name",data.system?.hostname);text("kernel",data.system?.kernel);text("uptime",data.system?.uptime);
  }

  async function loadHealth(){
    const response=await request("/api/health");
    const data=response.data??response;
    text("health-score",`${Number(data.score)||0}%`);text("health-status",data.status||"-");text("system-status",String(data.status||"online").toUpperCase());
  }

  function eventTimestamp(event){
    const value=event.timestamp??event.time??event.created_at??null;
    if(!value)return "";
    const date=typeof value==="number"?new Date(value*1000):new Date(value);
    return Number.isNaN(date.getTime())?String(value):date.toLocaleString();
  }

  async function loadTimeline(){
    const container=$("timeline-list");
    const response=await request("/api/timeline?limit=40");
    const events=Array.isArray(response)?response:(response.events||[]);
    container.replaceChildren();
    events.slice(0,40).forEach(event=>{
      const row=document.createElement("div");row.className="controller-event";
      const copy=document.createElement("div");const title=document.createElement("strong");const detail=document.createElement("span");const time=document.createElement("small");
      title.textContent=event.title||event.type||event.action||"Evento";
      detail.textContent=event.message||event.details||event.data?.message||"";
      time.textContent=eventTimestamp(event);
      copy.append(title,document.createElement("br"),detail);row.append(copy,time);container.append(row);
    });
    if(!container.children.length){const empty=document.createElement("p");empty.textContent="Nenhum evento global disponível.";container.append(empty)}
  }

  async function loadScheduler(){
    const container=$("scheduler-list");
    const response=await request("/api/scheduler");
    const data=response.data??response;const jobs=Array.isArray(data.jobs)?data.jobs:[];
    container.replaceChildren();
    jobs.forEach(job=>{const row=document.createElement("div");row.className="job-item";const name=document.createElement("div");name.className="job-name";name.textContent=job.name||"Job";const status=document.createElement("div");status.className="job-status";status.textContent=job.schedule||job.status||"-";row.append(name,status);container.append(row)});
    if(!container.children.length){const empty=document.createElement("div");empty.className="job-item";empty.textContent="Nenhum job agendado.";container.append(empty)}
  }

  async function loadLogs(){
    const container=$("controller-logs");
    const params=new URLSearchParams({source:"controller",limit:"400"});
    const response=await request(`/api/log-viewer?${params}`);const data=response.data??response;const logs=Array.isArray(data.logs)?data.logs:[];
    container.replaceChildren();
    logs.forEach(line=>{const row=document.createElement("div");row.className="log-line";row.textContent=line;container.append(row)});
    if(!container.children.length){const empty=document.createElement("div");empty.textContent=data.message||"Nenhum log disponível.";container.append(empty)}
  }

  async function loadSidebar(){
    const host=$("sidebar-component");if(!host)return;
    const response=await fetch("/components/sidebar.html");if(!response.ok)return;host.innerHTML=await response.text();
    const logout=$("btn-logout");if(logout)logout.addEventListener("click",()=>{sessionStorage.clear();location.replace("/login.html")});
  }

  async function refresh(){
    const tasks=[loadMetrics(),loadHealth(),loadTimeline(),loadScheduler(),loadLogs()];
    const results=await Promise.allSettled(tasks);
    if(results.every(item=>item.status==="rejected"))text("system-status","ERRO");
  }

  document.addEventListener("DOMContentLoaded",async()=>{
    if(!auth()){location.replace("/login.html");return}
    await loadSidebar();
    $("timeline-refresh")?.addEventListener("click",()=>loadTimeline().catch(console.error));
    $("controller-log-refresh")?.addEventListener("click",()=>loadLogs().catch(console.error));
    await refresh();
    window.setInterval(()=>{loadMetrics().catch(()=>{});loadHealth().catch(()=>{})},5000);
    window.setInterval(()=>{loadTimeline().catch(()=>{});loadScheduler().catch(()=>{});loadLogs().catch(()=>{})},15000);
  });
})();
