"use strict";

const API = "/api";
let currentUser = null;
let infrastructureTopology = null;
let sidebarCollapsed = false;

function byId(id) { return document.getElementById(id); }
function authHeader() { const token=sessionStorage.getItem("dsm_auth"); if(!token){window.location.replace("/login.html");throw new Error("authentication required");} return {Authorization:`Basic ${token}`,Accept:"application/json"}; }
async function request(endpoint,options={}){const headers={...authHeader(),...(options.headers||{})};if(options.body)headers["Content-Type"]="application/json";const response=await fetch(`${API}${endpoint}`,{...options,headers});if(response.status===401){sessionStorage.clear();window.location.replace("/login.html");return null;}const body=await response.json();if(!response.ok)throw new Error(body.error||`HTTP ${response.status}`);return body;}
function errorMessage(message=""){const box=byId("agents-error");if(!box)return;box.hidden=!message;box.textContent=message;}
function applySidebarState(collapsed){sidebarCollapsed=collapsed;document.body.classList.toggle("cap-sidebar-collapsed",collapsed);localStorage.setItem("cap_sidebar_collapsed",collapsed?"1":"0");}
function bindMenu(){byId("add-agent-menu-toggle")?.addEventListener("click",()=>{if(window.innerWidth<=760){document.body.classList.toggle("sidebar-open");return;}applySidebarState(!sidebarCollapsed);});}
async function loadSidebar(){const target=byId("sidebar-component");if(!target)return;const response=await fetch("/components/sidebar-v3.html");if(!response.ok)throw new Error(`sidebar HTTP ${response.status}`);target.innerHTML=await response.text();target.querySelectorAll("nav a").forEach(a=>a.classList.toggle("active",a.getAttribute("href")==="add-agent.html"));target.querySelectorAll("a").forEach(a=>a.addEventListener("click",()=>document.body.classList.remove("sidebar-open")));byId("btn-logout")?.addEventListener("click",()=>{sessionStorage.clear();window.location.replace("/login.html");});}
async function loadInfrastructure(){infrastructureTopology=await request("/infrastructure?active_only=true");return infrastructureTopology;}
async function loadAgents(){return null;}
async function initializeAddAgentPage(){try{bindMenu();await loadSidebar();currentUser=await request("/whoami");if(!currentUser)return;if(!["admin","controller"].includes(currentUser.role))throw new Error("Você não possui permissão para adicionar Agents.");document.querySelectorAll(".admin-only").forEach(element=>{element.style.display=currentUser.role==="admin"?"":"none";});document.querySelectorAll(".agent-manager-only").forEach(element=>{element.style.display=["admin","controller"].includes(currentUser.role)?"":"none";});document.querySelectorAll(".instance-manager-only").forEach(element=>{element.style.display=["admin","controller","operator"].includes(currentUser.role)?"":"none";});const current=byId("current-user");if(current)current.textContent=`${currentUser.username} (${currentUser.role})`;const name=byId("add-agent-user");if(name)name.textContent=currentUser.username||"—";const role=byId("add-agent-role");if(role)role.textContent=currentUser.role||"—";applySidebarState(localStorage.getItem("cap_sidebar_collapsed")==="1");await loadInfrastructure();}catch(error){errorMessage(error.message);}}
document.addEventListener("DOMContentLoaded",initializeAddAgentPage);
