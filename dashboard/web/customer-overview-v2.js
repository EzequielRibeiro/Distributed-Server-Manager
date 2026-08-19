(function(){"use strict";const $=id=>document.getElementById(id);
function value(...items){return items.find(v=>v!==undefined&&v!==null&&v!=="")}
function render(summary){const provision=summary?.provision||{};const completed=String(provision.stage||"").toLowerCase()==="completed"&&Number(provision.progress)>=100;if(completed){const p=$("provision-progress");if(p)p.hidden=true}
 const box=$("instance-overview");if(!box)return;const metadata=summary.instance_metadata||{},server=summary.server_state||{},status=server.status||{},metrics=summary.metrics||{},query=summary.steam_query||summary.query||server.steam_query||{};
 box.replaceChildren();const grid=document.createElement("div");grid.className="server-grid";
 const rows=[
 ["Servidor",value(metadata.display_name,new URLSearchParams(location.search).get("instance"),"-")],
 ["Jogo",String(new URLSearchParams(location.search).get("game")||metadata.game||"-").toUpperCase()],
 ["Estado",value(status.state,status,server.state,"Offline")],
 ["Endereço",value(server.public_address,server.address,metadata.public_address,"Não informado")],
 ["Jogadores",value(server.players?.current!==undefined?`${server.players.current} / ${server.players.max??"-"}`:null,metrics.players?.current,"-")],
 ["Mapa",value(server.map,metrics.map,metadata.map,"-")],
 ["Uptime",value(server.uptime,metrics.uptime,"-")],
 ["Versão",value(server.version,metadata.game_version,provision.version,"-")]
 ];
 const game=String(new URLSearchParams(location.search).get("game")||"").toLowerCase();if(["dayz","arma3","arma","rust"].includes(game)||Object.keys(query).length){const qstate=String(value(query.status,query.state,query.ok===true?"online":query.ok===false?"unavailable":"verificando")).toLowerCase();rows.splice(4,0,["Steam Query",qstate.includes("online")||qstate==="ok"?"● Online":qstate.includes("verif")?"● Verificando…":"● Indisponível"])}
 rows.forEach(([label,val])=>{const card=document.createElement("div");card.className="server-card";const strong=document.createElement("strong"),small=document.createElement("small");strong.textContent=label;small.textContent=String(val);card.append(strong,small);grid.append(card)});box.append(grid)}
async function refresh(){const q=new URLSearchParams(location.search);if(!q.get("server")||!q.get("game")||!q.get("instance"))return;try{const r=await fetch(`/api/runtime?${q}`,{headers:{Authorization:"Basic "+(sessionStorage.getItem("dsm_auth")||""),Accept:"application/json"}});if(r.ok)render(await r.json())}catch{}}
document.addEventListener("DOMContentLoaded",()=>{refresh();setInterval(refresh,10000)});})();