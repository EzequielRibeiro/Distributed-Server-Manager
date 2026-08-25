(function(){
"use strict";
const auth=()=>sessionStorage.getItem("dsm_auth")||"";
const byId=id=>document.getElementById(id);
async function request(path,options={}){const headers={Authorization:`Basic ${auth()}`,Accept:"application/json"};if(options.body)headers["Content-Type"]="application/json";const response=await fetch(path,{...options,headers});const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.message||data.error||`HTTP ${response.status}`);return data}
async function change(){const next=byId("new-password").value;const confirm=byId("confirm-password").value;if(next.length<8)throw new Error("A nova senha deve ter pelo menos 8 caracteres.");if(next!==confirm)throw new Error("A confirmação da senha não corresponde.");await request("/api/system-users/change-password",{method:"POST",body:JSON.stringify({new_password:next})});const encoded=auth();let username="";try{username=atob(encoded).split(":",1)[0]}catch(error){}if(!username)throw new Error("Não foi possível atualizar a sessão.");sessionStorage.setItem("dsm_auth",btoa(`${username}:${next}`));location.replace("/dashboard-v3.html")}
function init(){if(!auth()){location.replace("/login.html");return}byId("change-password").addEventListener("click",()=>change().catch(error=>{byId("change-message").textContent=error.message}))}
document.addEventListener("DOMContentLoaded",init);
})();
