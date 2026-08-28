(function(){
"use strict";
const controllerHeaders=()=>({Accept:"application/json","X-Capivara-Auth-Area":"controller"});
async function request(path,options={}){
  const headers={...controllerHeaders(),...(options.headers||{})};
  if(options.body)headers["Content-Type"]="application/json";
  const response=await fetch(path,{...options,headers,cache:options.cache||"no-store",credentials:"same-origin"});
  if(response.status===401){location.replace("/login.html");throw new Error("Sessão encerrada");}
  const data=await response.json().catch(()=>({}));
  if(!response.ok)throw new Error(data.message||data.error||`HTTP ${response.status}`);
  return data;
}
async function logout(){
  try{await fetch("/api/auth/logout",{method:"POST",headers:controllerHeaders(),credentials:"same-origin",cache:"no-store"});}
  catch(_error){}
  finally{location.replace("/login.html");}
}
async function loadShell(activeHref){
  const host=document.getElementById("sidebar-component");
  if(host){
    const response=await fetch("/components/sidebar-v3.html",{cache:"no-store",credentials:"same-origin"});
    host.innerHTML=await response.text();
    host.querySelectorAll("nav a").forEach(a=>a.classList.toggle("active",a.getAttribute("href")===activeHref));
    const logoutButton=document.getElementById("btn-logout");
    if(logoutButton)logoutButton.onclick=logout;
  }
  const who=await request("/api/whoami");
  const name=document.getElementById("admin-user-name"),role=document.getElementById("admin-user-role");
  if(name)name.textContent=who.username||"—";
  if(role)role.textContent=who.role||"—";
  document.querySelectorAll(".admin-only").forEach(x=>x.style.display=who.role==="admin"?"":"none");
  document.querySelectorAll(".agent-manager-only").forEach(x=>x.style.display=["admin","controller"].includes(who.role)?"":"none");
  document.querySelectorAll(".instance-manager-only").forEach(x=>x.style.display=["admin","controller","operator"].includes(who.role)?"":"none");
  const toggle=document.getElementById("admin-menu-toggle");
  if(toggle)toggle.onclick=()=>{
    if(innerWidth<=760)document.body.classList.toggle("sidebar-open");
    else{
      document.body.classList.toggle("cap-sidebar-collapsed");
      localStorage.setItem("cap_sidebar_collapsed",document.body.classList.contains("cap-sidebar-collapsed")?"1":"0");
    }
  };
  if(localStorage.getItem("cap_sidebar_collapsed")==="1"&&innerWidth>760)document.body.classList.add("cap-sidebar-collapsed");
  return who;
}
function setNotice(id,message,type=""){
  const node=typeof id==="string"?document.getElementById(id):id;
  if(!node)return;
  node.className=`customer-notice${type?` ${type}`:""}`;
  node.textContent=message||"";
}
function dataCell(label,value){
  const node=document.createElement("div");node.className="customer-data";
  const small=document.createElement("small");small.textContent=label;
  const strong=document.createElement("strong");strong.textContent=value===null||value===undefined||value===""?"—":String(value);
  node.append(small,strong);return node;
}
function formatDocument(type,value){
  const raw=String(value||"");
  if(type==="cpf"&&/^\d{11}$/.test(raw))return raw.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/,"$1.$2.$3-$4");
  if(type==="cnpj"&&/^\d{14}$/.test(raw))return raw.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/,"$1.$2.$3/$4-$5");
  return raw||"—";
}
window.CapCustomerManagement={request,loadShell,logout,setNotice,dataCell,formatDocument};
})();
