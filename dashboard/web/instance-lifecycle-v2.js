(function(){"use strict";
const $=id=>document.getElementById(id);
function identity(){return{server:$("catalog-v2-node")?.value||"",game:$("catalog-v2-game")?.value||"",instance:$("catalog-v2-instance")?.value||""}}
function provider(){const runtime=$("catalog-v2-runtime");const option=runtime?.selectedOptions?.[0];return option?.textContent||"Provedor definido pelo catálogo"}
function installed(){const state=String($("catalog-v2-runtime-state")?.textContent||"").toLowerCase();const pid=$("catalog-v2-runtime-pid")?.textContent;return Boolean(identity().instance)&&(state&&!state.includes("unknown")||pid&&pid!=="-")}
function decorate(){
 const card=$("catalog-v2-environment-install")?.closest(".catalog-v2-section"); if(!card)return;
 const title=card.querySelector("h3"); if(title)title.textContent="Instalação do servidor do jogo";
 const intro=card.querySelector(".catalog-v2-section-title p"); if(intro)intro.textContent="Prepara o servidor-base no Agent usando o provedor definido pelo catálogo. Ao provisionar uma instância, seus arquivos de servidor ficam isolados dos demais servidores.";
 const install=$("catalog-v2-environment-install"); if(install){install.textContent="Preparar servidor-base no Agent";install.title="Baixa/prepara os arquivos-base do jogo no Agent (game-data). Não reinstala automaticamente a instância selecionada."}
 const reinstall=$("catalog-v2-instance-reinstall"); if(reinstall){reinstall.textContent="Reinstalar servidor nesta instância";reinstall.title="Reinstala somente a instância selecionada usando o servidor-base disponível no Agent.";reinstall.disabled=!installed();}
 let note=$("catalog-v2-install-destination-note"); if(!note){note=document.createElement("p");note.id="catalog-v2-install-destination-note";note.className="catalog-v2-subtitle";card.querySelector(".catalog-v2-actions")?.before(note)}
 note.textContent=`Servidor-base: Agent / game-data · Instância selecionada: ${identity().instance||"nenhuma"} · Provedor: ${provider()}`;
}
function enhanceReinstall(){const old=$("catalog-v2-instance-reinstall");if(!old||old.dataset.lifecycleV2)return;old.dataset.lifecycleV2="1";old.addEventListener("click",async ev=>{
 ev.stopImmediatePropagation(); const id=identity(); if(!id.instance)return;
 const preserveConfig=confirm("Preservar os arquivos de configuração atuais?\n\nOK = preservar · Cancelar = reinstalação limpa das configurações.");
 const preserveMap=confirm("Preservar mapa/missão e dados persistentes atuais?\n\nOK = preservar · Cancelar = substituir os dados persistentes.");
 if(!preserveConfig&&!preserveMap&&!confirm("REINSTALAÇÃO LIMPA: configurações e persistência não serão preservadas. Deseja continuar?"))return;
 old.disabled=true; try{const r=await fetch("/api/instance/reinstall/v2",{method:"POST",headers:{"X-Capivara-Auth-Area":"controller","Content-Type":"application/json",Accept:"application/json"},body:JSON.stringify({...id,preserve_config:preserveConfig,preserve_map:preserveMap})});const data=await r.json();if(!r.ok)throw new Error(data.error||`HTTP ${r.status}`);alert("Reinstalação concluída.");location.reload()}catch(e){alert(`Não foi possível reinstalar: ${e.message}`)}finally{old.disabled=false}
 },true)}
const observer=new MutationObserver(()=>decorate());document.addEventListener("DOMContentLoaded",()=>{decorate();enhanceReinstall();observer.observe(document.body,{subtree:true,childList:true,characterData:true})});
})();