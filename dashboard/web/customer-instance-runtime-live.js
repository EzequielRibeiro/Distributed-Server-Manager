(()=>{"use strict";
const $=id=>document.getElementById(id),q=new URLSearchParams(location.search),iid=q.get("instance")||q.get("instance_id")||"",api="/api/customer/instance/workspace";
let overview=null,consoleBusy=false,overviewBusy=false;
const initialConsoleWrap=$("console-command-wrap");if(initialConsoleWrap){initialConsoleWrap.hidden=true;initialConsoleWrap.classList.add("hidden")}
function headers(){return {Accept:"application/json","X-Capivara-Auth-Area":"customer"}}
async function get(path){const r=await fetch(path,{headers:headers(),credentials:"same-origin",cache:"no-store"});if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json()}
function permissions(){return new Set(overview?.permissions||[])}
function runtimeState(){return String($("state")?.textContent||overview?.instance?.status||"").trim().toLowerCase()}
function setConsoleInteractive(interactive){const consoleWrap=$("console-command-wrap");if(!consoleWrap)return;consoleWrap.hidden=!interactive;consoleWrap.classList.toggle("hidden",!interactive)}
function applyControls(){if(!overview)return;const p=permissions(),pr=!!overview.provision,state=runtimeState(),running=["running","online"].includes(state),stopped=["stopped","offline"].includes(state),busy=["starting","stopping","restarting"].includes(state),start=$("start"),stop=$("stop"),restart=$("restart");if(start)start.disabled=!p.has("instance.start")||pr||running||busy;if(stop)stop.disabled=!p.has("instance.stop")||pr||stopped||busy;if(restart)restart.disabled=!p.has("instance.restart")||pr||!running||busy;setConsoleInteractive(!!overview?.console?.supported&&p.has("console.execute"))}
async function refreshOverview(){if(!iid||overviewBusy)return;overviewBusy=true;try{overview=await get(`${api}?instance_id=${encodeURIComponent(iid)}`);applyControls()}catch{}finally{overviewBusy=false}}
async function refreshConsole(){if(!iid||consoleBusy||!overview)return;const view=$("view-console"),output=$("console-output");if(!view?.classList.contains("active")||!output||!permissions().has("console.read"))return;consoleBusy=true;try{const d=await get(`${api}/console?instance_id=${encodeURIComponent(iid)}&limit=400`),lines=(d.lines||[]).map(x=>typeof x==="string"?x:(x?.line||"")),nearBottom=output.scrollHeight-output.scrollTop-output.clientHeight<80;output.textContent=lines.join("\n")||"Nenhuma saída disponível.";if(nearBottom)output.scrollTop=output.scrollHeight}catch{}finally{consoleBusy=false}}
if(!iid)return;
refreshOverview();
setInterval(refreshOverview,10000);
setInterval(applyControls,500);
setInterval(refreshConsole,3000);
document.querySelector('[data-view="console"]')?.addEventListener("click",()=>setTimeout(refreshConsole,100));
$("start")?.addEventListener("click",event=>{if(["running","online","starting","restarting"].includes(runtimeState())){event.preventDefault();event.stopImmediatePropagation()}},true);
})();