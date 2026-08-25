(function(){
"use strict";
const $=id=>document.getElementById(id);const app=window.CapCustomerManagement;
const customerCode=(new URLSearchParams(location.search).get("customer_code")||"").trim().toUpperCase();
function empty(root,text){root.replaceChildren();const node=document.createElement("div");node.className="customer-empty";node.textContent=text;root.append(node);}
function renderUsers(items){
  const root=$("detail-users");root.replaceChildren();if(!items.length){empty(root,"Nenhum usuário vinculado.");return;}
  for(const item of items){const card=document.createElement("article");card.className="customer-list-item";const title=document.createElement("h3");title.textContent=item.username;const identity=document.createElement("p");identity.textContent=`E-mail: ${item.email||"—"} · Papel: ${item.account_role||"member"} · ${item.active?"ativo":"inativo"}`;const password=document.createElement("p");password.textContent=item.must_change_password?"Senha provisória: troca obrigatória no próximo acesso":"Senha definitiva configurada";card.append(title,identity,password);root.append(card);}
}
function renderContracts(items){
  const root=$("detail-contracts");root.replaceChildren();if(!items.length){empty(root,"Nenhum contrato cadastrado.");return;}
  for(const item of items){const card=document.createElement("article");card.className="customer-list-item";const title=document.createElement("h3");title.textContent=`${item.game_id} · ${item.id}`;const line=document.createElement("p");line.textContent=`Status: ${item.status} · Instâncias: ${item.instances_used||0}/${item.instance_limit} · Perfil: ${item.resource_profile_id||"—"}`;const dates=document.createElement("p");dates.textContent=`Início: ${item.starts_at||"—"} · Término: ${item.ends_at||"sem vencimento"}`;card.append(title,line,dates);root.append(card);}
}
function renderInstances(items){
  const root=$("detail-instances");root.replaceChildren();if(!items.length){empty(root,"Nenhuma instância criada.");return;}
  for(const item of items){const card=document.createElement("article");card.className="customer-list-item";const title=document.createElement("h3");title.textContent=item.name||item.id;const line=document.createElement("p");line.textContent=`${item.game_id} · ${item.status} · Runtime ${item.runtime_id||"—"} · Agent ${item.agent_id||"—"}`;const contract=document.createElement("p");contract.textContent=`Contrato: ${item.contract_id||"—"}`;card.append(title,line,contract);root.append(card);}
}
function renderCustomer(customer){
  $("detail-name").textContent=customer.name||customer.customer_code||customerCode;$("detail-meta").textContent=`${customer.customer_code||customerCode} · ${customer.status||"—"}`;
  const grid=$("detail-data");grid.replaceChildren(
    app.dataCell("Código do cliente",customer.customer_code),app.dataCell("Nome",customer.name),app.dataCell("Razão social / nome legal",customer.legal_name),
    app.dataCell("Documento",`${String(customer.document_type||"").toUpperCase()} ${app.formatDocument(customer.document_type,customer.document_number)}`.trim()),app.dataCell("E-mail",customer.account_email||customer.email),app.dataCell("Telefone",customer.phone),
    app.dataCell("Controller",customer.controller_id),app.dataCell("Status da conta",customer.status),app.dataCell("Status do cadastro",customer.registration_status),
    app.dataCell("E-mail verificado em",customer.email_verified_at),app.dataCell("Criado em",customer.created_at),app.dataCell("Atualizado em",customer.updated_at)
  );
  const billing=$("detail-billing");billing.replaceChildren(
    app.dataCell("Provider",customer.billing_provider),app.dataCell("Customer ID externo",customer.billing_customer_id),app.dataCell("Status",customer.billing_status),app.dataCell("Última sincronização",customer.billing_synced_at)
  );
  $("new-contract-link").href=`/customer-contract-create.html?customer_code=${encodeURIComponent(customer.customer_code||customerCode)}`;
}
async function load(){
  if(!customerCode)throw new Error("Código do cliente não informado.");
  const data=await app.request(`/api/admin/customer?customer_code=${encodeURIComponent(customerCode)}`);renderCustomer(data.customer||{});renderUsers(data.users||[]);renderContracts(data.contracts||[]);renderInstances(data.instances||[]);
}
async function init(){await app.loadShell("customers.html");await load();}
document.addEventListener("DOMContentLoaded",()=>init().catch(error=>{app.setNotice("detail-error",error.message,"error");$("detail-meta").textContent="Falha ao carregar cliente";}));
})();
