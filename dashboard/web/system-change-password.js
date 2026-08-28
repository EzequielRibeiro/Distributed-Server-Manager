(function(){
"use strict";
const byId=id=>document.getElementById(id);
const headers=()=>({Accept:"application/json","X-Capivara-Auth-Area":"controller"});
async function request(path,options={}){const requestHeaders={...headers()};if(options.body)requestHeaders["Content-Type"]="application/json";const response=await fetch(path,{...options,headers:requestHeaders,credentials:"same-origin",cache:"no-store"});if(response.status===401){location.replace("/login.html");throw new Error("Sessão encerrada");}const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.message||data.error||`HTTP ${response.status}`);return data}
async function change(){const next=byId("new-password").value;const confirm=byId("confirm-password").value;if(next.length<8)throw new Error("A nova senha deve ter pelo menos 8 caracteres.");if(next!==confirm)throw new Error("A confirmação da senha não corresponde.");await request("/api/system-users/change-password",{method:"POST",body:JSON.stringify({new_password:next})});try{await fetch("/api/auth/logout",{method:"POST",headers:headers(),credentials:"same-origin",cache:"no-store"});}finally{location.replace("/login.html")}}
async function init(){const response=await fetch("/api/auth/session",{headers:headers(),credentials:"same-origin",cache:"no-store"});if(!response.ok){location.replace("/login.html");return;}byId("change-password").addEventListener("click",()=>change().catch(error=>{byId("change-message").textContent=error.message}))}
document.addEventListener("DOMContentLoaded",()=>init().catch(error=>{byId("change-message").textContent=error.message}));
})();
