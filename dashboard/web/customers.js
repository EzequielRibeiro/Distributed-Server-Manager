(function(){
"use strict";
const $=id=>document.getElementById(id);const app=window.CapCustomerManagement;
function render(items){
  const root=$("customer-results");root.replaceChildren();
  if(!items.length){const empty=document.createElement("div");empty.className="customer-empty";empty.textContent="Nenhum cliente encontrado.";root.append(empty);return;}
  for(const item of items){
    const card=document.createElement("article");card.className="customer-result";
    const body=document.createElement("div");
    const title=document.createElement("h3");title.textContent=item.name||item.customer_code;
    const identity=document.createElement("p");identity.innerHTML=`<span class="customer-code"></span> · ${item.document_type?String(item.document_type).toUpperCase():"Documento"} ${app.formatDocument(item.document_type,item.document_number)}`;identity.querySelector(".customer-code").textContent=item.customer_code||"—";
    const contact=document.createElement("p");contact.textContent=`${item.email||"Sem e-mail"}${item.phone?` · ${item.phone}`:""}`;
    const state=document.createElement("small");state.textContent=`Conta ${item.status||"—"} · Cadastro ${item.registration_status||"—"} · Billing ${item.billing_status||"não vinculado"}`;
    body.append(title,identity,contact,state);
    const open=document.createElement("button");open.type="button";open.className="customer-secondary";open.textContent="Ver dados completos";open.onclick=()=>location.href=`/customer-admin.html?customer_code=${encodeURIComponent(item.customer_code)}`;
    card.append(body,open);root.append(card);
  }
}
async function search(){
  const field=$("customer-search-field").value,q=$("customer-search").value.trim();
  if(!q){app.setNotice("customer-search-message","Informe um valor para localizar o cliente.","error");render([]);return;}
  app.setNotice("customer-search-message","Consultando…");
  try{
    const data=await app.request(`/api/admin/customers?field=${encodeURIComponent(field)}&q=${encodeURIComponent(q)}`);
    app.setNotice("customer-search-message",`${(data.customers||[]).length} cliente(s) encontrado(s).`,"success");render(data.customers||[]);
  }catch(error){app.setNotice("customer-search-message",error.message,"error");render([]);}
}
async function init(){
  await app.loadShell("customers.html");
  $("customer-search-button").addEventListener("click",search);
  $("customer-search").addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();search();}});
}
document.addEventListener("DOMContentLoaded",()=>init().catch(error=>app.setNotice("customer-search-message",error.message,"error")));
})();
