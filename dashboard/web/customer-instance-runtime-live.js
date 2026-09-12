(()=>{"use strict";
const $=id=>document.getElementById(id),q=new URLSearchParams(location.search),iid=q.get("instance")||q.get("instance_id")||"",api="/api/customer/instance/workspace";
let overview=null,consoleBusy=false,overviewBusy=false,lifecyclePending="";
const lifecycleLabels={start:"Iniciando…",restart:"Reiniciando…",stop:"Parando…"},lifecycleActions=["start","restart","stop"],nativeFetch=window.fetch.bind(window);
const initialConsoleWrap=$("console-command-wrap");if(initialConsoleWrap){initialConsoleWrap.hidden=true;initialConsoleWrap.classList.add("hidden")}
function headers(){return {Accept:"application/json","X-Capivara-Auth-Area":"customer"}}
function lifecycleRequest(input,options={}){const method=String(options.method||((input&&input.method)||"GET")).toUpperCase();if(method!=="POST")return "";const raw=typeof input==="string"?input:(input&&input.url)||"";try{const path=new URL(raw,location.href).pathname;const match=path.match(/^\/api\/instance\/(start|restart|stop)$/);return match?match[1]:""}catch{return ""}}
function setLifecyclePending(action=""){lifecyclePending=action;lifecycleActions.forEach(name=>{const button=$(name);if(!button)return;if(!button.dataset.lifecycleLabel)button.dataset.lifecycleLabel=button.textContent||name;if(action){button.disabled=true;button.textContent=name===action?lifecycleLabels[action]:button.dataset.lifecycleLabel}else{button.textContent=button.dataset.lifecycleLabel}})}
async function get(path){const r=await fetch(path,{headers:headers(),credentials:"same-origin",cache:"no-store"});if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json()}
function permissions(){return new Set(overview?.permissions||[])}
function runtimeState(){return String($("state")?.textContent||overview?.instance?.status||"").trim().toLowerCase()}
function setConsoleInteractive(interactive){const consoleWrap=$("console-command-wrap");if(!consoleWrap)return;consoleWrap.hidden=!interactive;consoleWrap.classList.toggle("hidden",!interactive)}
function applyControls(){if(!overview)return;const p=permissions(),pr=!!overview.provision,state=runtimeState(),running=["running","online"].includes(state),stopped=["stopped","offline"].includes(state),busy=["starting","stopping","restarting"].includes(state),pending=!!lifecyclePending,start=$("start"),stop=$("stop"),restart=$("restart");if(start)start.disabled=pending||!p.has("instance.start")||pr||running||busy;if(stop)stop.disabled=pending||!p.has("instance.stop")||pr||stopped||busy;if(restart)restart.disabled=pending||!p.has("instance.restart")||pr||!running||busy;setConsoleInteractive(!!overview?.console?.supported&&p.has("console.execute"))}
async function refreshOverview(){if(!iid||overviewBusy)return;overviewBusy=true;try{overview=await get(`${api}?instance_id=${encodeURIComponent(iid)}`);applyControls()}catch{}finally{overviewBusy=false}}
async function refreshConsole(){if(!iid||consoleBusy||!overview)return;const view=$("view-console"),output=$("console-output");if(!view?.classList.contains("active")||!output||!permissions().has("console.read"))return;consoleBusy=true;try{const d=await get(`${api}/console?instance_id=${encodeURIComponent(iid)}&limit=400`),lines=(d.lines||[]).map(x=>typeof x==="string"?x:(x?.line||"")),nearBottom=output.scrollHeight-output.scrollTop-output.clientHeight<80;output.textContent=lines.join("\n")||"Nenhuma saída disponível.";if(nearBottom)output.scrollTop=output.scrollHeight}catch{}finally{consoleBusy=false}}
window.fetch=async function(input,options={}){const action=lifecycleRequest(input,options);if(!action)return nativeFetch(input,options);setLifecyclePending(action);applyControls();try{return await nativeFetch(input,options)}finally{try{await refreshOverview()}finally{setLifecyclePending("");applyControls()}}};
function rejectInvalidLifecycleClick(action,event){if(lifecyclePending){event.preventDefault();event.stopImmediatePropagation();return}const state=runtimeState(),running=["running","online"].includes(state),stopped=["stopped","offline"].includes(state),busy=["starting","stopping","restarting"].includes(state),invalid=busy||(action==="start"&&running)||(action==="stop"&&stopped)||(action==="restart"&&!running);if(invalid){event.preventDefault();event.stopImmediatePropagation()}}
if(!iid)return;
refreshOverview();
setInterval(refreshOverview,10000);
setInterval(applyControls,500);
setInterval(refreshConsole,3000);
document.querySelector('[data-view="console"]')?.addEventListener("click",()=>setTimeout(refreshConsole,100));
lifecycleActions.forEach(action=>$(action)?.addEventListener("click",event=>rejectInvalidLifecycleClick(action,event),true));
})();
