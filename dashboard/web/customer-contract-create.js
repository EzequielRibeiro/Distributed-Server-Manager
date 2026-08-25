(function(){
"use strict";
const $=id=>document.getElementById(id);const app=window.CapCustomerManagement;let profiles=[],defaultProfile="";
function option(value,label){const node=document.createElement("option");node.value=value;node.textContent=label;return node;}
async function verifyCustomer(){
  const code=$("contract-customer-code").value.trim().toUpperCase();if(!code){app.setNotice("contract-customer-summary","Informe o código do cliente.","error");return false;}
  try{const data=await app.request(`/api/admin/customer?customer_code=${encodeURIComponent(code)}`),customer=data.customer||{};app.setNotice("contract-customer-summary",`${customer.customer_code} · ${customer.name} · ${customer.status} · ${customer.account_email||customer.email||"sem e-mail"}`,"success");return customer.status==="active";}
  catch(error){app.setNotice("contract-customer-summary",error.message,"error");return false;}
}
async function loadGames(){
  const data=await app.request("/api/catalog/runtimes");const runtimes=Array.isArray(data)?data:(data.runtimes||[]);const games=[...new Set(runtimes.map(item=>String(item.game||"").toLowerCase()).filter(Boolean))].sort();
  const select=$("contract-game");select.replaceChildren(option("","Selecione um jogo"),...games.map(game=>option(game,game)));
}
function profileLabel(profile){const ram=(Number(profile.memory_mb||0)/1024).toFixed(1).replace(".0","");const storage=(Number(profile.storage_mb||0)/1024).toFixed(1).replace(".0","");return `${profile.name||profile.id} · ${profile.cpu_cores} CPU · ${ram} GB RAM · ${storage} GB disco`;}
function renderProfile(){const id=$("contract-profile").value||defaultProfile,profile=profiles.find(item=>String(item.id)===id);$("contract-profile-summary").textContent=profile?`${profile.name||profile.id}: ${profile.description||"Sem descrição"} · ${profileLabel(profile)}${id===defaultProfile?" · perfil padrão do jogo":""}.`:"Nenhum perfil disponível para este jogo.";}
async function loadProfiles(){
  const game=$("contract-game").value,select=$("contract-profile");select.replaceChildren();profiles=[];defaultProfile="";
  if(!game){select.append(option("","Selecione o jogo primeiro"));select.disabled=true;renderProfile();return;}
  try{const data=await app.request(`/api/catalog/resource-profiles?game=${encodeURIComponent(game)}`);profiles=data.profiles||[];defaultProfile=String(data.default_profile_id||"");if(!profiles.length){select.append(option("","Nenhum perfil configurado"));select.disabled=true;renderProfile();return;}select.append(...profiles.map(profile=>option(profile.id,profileLabel(profile))));select.value=defaultProfile||profiles[0].id;select.disabled=false;renderProfile();}
  catch(error){select.append(option("","Falha ao carregar perfis"));select.disabled=true;app.setNotice("contract-result",error.message,"error");}
}
async function createContract(){
  const form=$("contract-create-form");if(!form.reportValidity())return;if(!(await verifyCustomer()))return;
  const button=$("contract-create-button");button.disabled=true;app.setNotice("contract-result","Criando contrato…");
  try{const payload={customer_code:$("contract-customer-code").value.trim().toUpperCase(),game_id:$("contract-game").value,resource_profile_id:$("contract-profile").value,instance_limit:Number($("contract-limit").value||1),ends_at:$("contract-ends").value.trim()};const data=await app.request("/api/admin/customer/contracts",{method:"POST",body:JSON.stringify(payload)});app.setNotice("contract-result",`Contrato ${data.id} criado com sucesso.\nCliente: ${data.customer_code}\nJogo: ${data.game_id}\nPerfil: ${data.resource_profile_id}\nStatus: ${data.status}\nLimite de instâncias: ${data.instance_limit}`,"success");}
  catch(error){app.setNotice("contract-result",error.message,"error");}
  finally{button.disabled=false;}
}
async function init(){
  await app.loadShell("customer-contract-create.html");await loadGames();const preset=(new URLSearchParams(location.search).get("customer_code")||"").trim().toUpperCase();if(preset){$("contract-customer-code").value=preset;await verifyCustomer();}
  $("contract-customer-code").addEventListener("blur",verifyCustomer);$("contract-game").addEventListener("change",loadProfiles);$("contract-profile").addEventListener("change",renderProfile);$("contract-create-button").addEventListener("click",createContract);
}
document.addEventListener("DOMContentLoaded",()=>init().catch(error=>app.setNotice("contract-result",error.message,"error")));
})();
