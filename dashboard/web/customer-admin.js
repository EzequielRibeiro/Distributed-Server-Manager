(function(){
"use strict";
const $=id=>document.getElementById(id);
const app=window.CapCustomerManagement;
const customerCode=(new URLSearchParams(location.search).get("customer_code")||"").trim().toUpperCase();
let currentCustomer=null;
let canEdit=false;

function empty(root,text){
  root.replaceChildren();
  const node=document.createElement("div");
  node.className="customer-empty";
  node.textContent=text;
  root.append(node);
}
function showNotice(message,type=""){
  app.setNotice("detail-error",message,type);
}
function editButton(label,form){
  const button=document.createElement("button");
  button.type="button";
  button.className="customer-secondary customer-card-edit";
  button.textContent=label;
  button.disabled=!canEdit;
  if(!canEdit)button.title="Edição disponível para administradores e controllers";
  button.setAttribute("aria-expanded","false");
  button.onclick=()=>{
    const opening=form.hidden;
    document.querySelectorAll(".customer-card-editor").forEach(item=>{item.hidden=true;});
    document.querySelectorAll(".customer-card-edit").forEach(item=>item.setAttribute("aria-expanded","false"));
    form.hidden=!opening;
    button.setAttribute("aria-expanded",String(opening));
    if(opening)form.querySelector("input")?.focus();
  };
  return button;
}
function field(title,input){
  const label=document.createElement("label");
  label.textContent=title;
  label.append(input);
  return label;
}
function renderUsers(items){
  const root=$("detail-users");
  root.replaceChildren();
  if(!items.length){empty(root,"Nenhum usuário vinculado.");return;}
  for(const item of items){
    const card=document.createElement("article");
    card.className="customer-list-item";
    const title=document.createElement("h3");
    title.textContent=item.username;
    const identity=document.createElement("p");
    identity.textContent=`E-mail: ${item.email||"—"} · Papel: ${item.account_role||"member"} · ${item.active?"ativo":"inativo"}`;
    const password=document.createElement("p");
    password.textContent=item.must_change_password?"Senha provisória: troca obrigatória no próximo acesso":"Senha definitiva configurada";
    card.append(title,identity,password);
    root.append(card);
  }
}
function renderContracts(items){
  const root=$("detail-contracts");
  root.replaceChildren();
  if(!items.length){empty(root,"Nenhum contrato cadastrado.");return;}
  for(const item of items){
    const card=document.createElement("article"),title=document.createElement("h3"),line=document.createElement("p"),dates=document.createElement("p");
    card.className="customer-list-item";
    title.textContent=`${item.game_id} · ${item.id}`;
    line.textContent=`Status: ${item.status} · Instâncias: ${item.instances_used||0}/${item.instance_limit} · Tipo: ${item.product_variant||"padrão"} · Perfil: ${item.resource_profile_id||"—"}`;
    dates.textContent=`Início: ${item.starts_at||"—"} · Término: ${item.ends_at||"sem vencimento"}`;
    const form=document.createElement("form"),actions=document.createElement("div");
    form.className="customer-card-editor customer-form";
    form.hidden=true;
    actions.className="customer-card-actions";
    const limit=document.createElement("input");
    limit.type="number";limit.min=String(Math.max(1,Number(item.instances_used)||0));
    limit.max="1000";limit.step="1";limit.required=true;limit.value=String(item.instance_limit);
    const expiry=document.createElement("input"),currentDate=String(item.ends_at||"").slice(0,10);
    expiry.type="date";expiry.value=currentDate;
    const note=document.createElement("p");
    note.className="wide customer-edit-help";
    note.textContent="Edite somente o limite e o vencimento. Perfil, produto e status seguem seus próprios fluxos. Vencimento definido para o fim do dia (UTC).";
    const footer=document.createElement("div"),submit=document.createElement("button"),cancel=document.createElement("button");
    footer.className="wide customer-actions";
    submit.type="submit";submit.className="customer-primary";submit.textContent="Salvar contrato";
    cancel.type="button";cancel.className="customer-secondary";cancel.textContent="Cancelar";cancel.onclick=()=>{form.hidden=true;};
    footer.append(submit,cancel);
    form.append(field("Limite de instâncias",limit),field("Vencimento (opcional)",expiry),note,footer);
    form.onsubmit=async event=>{
      event.preventDefault();submit.disabled=true;showNotice("Salvando contrato…");
      try{
        const changes={instance_limit:Number(limit.value)};
        if(expiry.value!==currentDate)changes.ends_at=expiry.value||null;
        const result=await app.request("/api/admin/customer/contract/update",{
          method:"POST",body:JSON.stringify({customer_code:customerCode,contract_id:item.id,changes})
        });
        renderContracts(result.detail.contracts);
        renderInstances(result.detail.instances);
        showNotice(result.updated?"Contrato atualizado.":"Nenhuma alteração foi necessária.","success");
      }catch(error){showNotice(error.message,"error");}
      finally{submit.disabled=false;}
    };
    actions.append(editButton("Editar",form));
    card.append(title,line,dates,actions,form);
    root.append(card);
  }
}
function renderInstances(items){
  const root=$("detail-instances");
  root.replaceChildren();
  if(!items.length){empty(root,"Nenhuma instância criada.");return;}
  for(const item of items){
    const card=document.createElement("article"),title=document.createElement("h3"),line=document.createElement("p"),contract=document.createElement("p");
    card.className="customer-list-item";
    title.textContent=item.name||item.id;
    line.textContent=`${item.game_id} · ${item.status} · Runtime ${item.runtime_id||"—"} · Agent ${item.agent_id||"—"}`;
    contract.textContent=`Contrato: ${item.contract_id||"—"}`;
    const form=document.createElement("form"),actions=document.createElement("div");
    form.className="customer-card-editor customer-form";form.hidden=true;
    actions.className="customer-card-actions";
    const name=document.createElement("input");
    name.type="text";name.maxLength=120;name.required=true;name.value=item.name||item.id;
    const note=document.createElement("p");note.className="wide customer-edit-help";
    note.textContent="Altera o nome de identificação no painel, sem reiniciar ou modificar o servidor de jogo.";
    const footer=document.createElement("div"),submit=document.createElement("button"),cancel=document.createElement("button");
    footer.className="wide customer-actions";
    submit.type="submit";submit.className="customer-primary";submit.textContent="Salvar instância";
    cancel.type="button";cancel.className="customer-secondary";cancel.textContent="Cancelar";cancel.onclick=()=>{form.hidden=true;};
    footer.append(submit,cancel);form.append(field("Nome da instância",name),note,footer);
    form.onsubmit=async event=>{
      event.preventDefault();submit.disabled=true;showNotice("Salvando instância…");
      try{
        const result=await app.request("/api/admin/customer/instance/update",{
          method:"POST",body:JSON.stringify({customer_code:customerCode,instance_id:item.id,name:name.value})
        });
        renderContracts(result.detail.contracts);
        renderInstances(result.detail.instances);
        showNotice(result.updated?"Instância atualizada.":"Nenhuma alteração foi necessária.","success");
      }catch(error){showNotice(error.message,"error");}
      finally{submit.disabled=false;}
    };
    actions.append(editButton("Editar",form));
    if(item.node_id&&item.game_id){
      const link=document.createElement("a");link.className="customer-secondary";
      link.textContent="Gerenciar instância";
      link.href="/controller-instance.html?"+new URLSearchParams({server:item.node_id,game:item.game_id,instance:item.id});
      actions.append(link);
    }
    card.append(title,line,contract,actions,form);root.append(card);
  }
}
function value(id,v){const node=$(id);if(node)node.value=v===null||v===undefined?"":String(v);}
function fillEditor(customer){
  value("edit-name",customer.name);value("edit-legal-name",customer.legal_name);
  value("edit-phone",customer.phone);value("edit-document-type",customer.document_type||"other");
  value("edit-document-number",customer.document_number);value("edit-status",customer.status||"active");
  value("edit-registration-status",customer.registration_status||"active");
  value("edit-controller-id",customer.controller_id);value("edit-billing-provider",customer.billing_provider);
  value("edit-billing-customer-id",customer.billing_customer_id);value("edit-billing-status",customer.billing_status||"unlinked");
  value("edit-customer-code",customer.customer_code);value("edit-account-email",customer.account_email||customer.email);
}
function renderCustomer(customer){
  currentCustomer=customer;
  $("detail-name").textContent=customer.name||customer.customer_code||customerCode;
  $("detail-meta").textContent=`${customer.customer_code||customerCode} · ${customer.status||"—"}`;
  $("detail-data").replaceChildren(
    app.dataCell("Código do cliente",customer.customer_code),app.dataCell("Nome",customer.name),
    app.dataCell("Razão social / nome legal",customer.legal_name),
    app.dataCell("Documento",`${String(customer.document_type||"").toUpperCase()} ${app.formatDocument(customer.document_type,customer.document_number)}`.trim()),
    app.dataCell("E-mail",customer.account_email||customer.email),app.dataCell("Telefone",customer.phone),
    app.dataCell("Controller",customer.controller_id),app.dataCell("Status da conta",customer.status),
    app.dataCell("Status do cadastro",customer.registration_status),
    app.dataCell("E-mail verificado em",customer.email_verified_at),
    app.dataCell("Criado em",customer.created_at),app.dataCell("Atualizado em",customer.updated_at)
  );
  $("detail-billing").replaceChildren(
    app.dataCell("Provider",customer.billing_provider),
    app.dataCell("Customer ID externo",customer.billing_customer_id),
    app.dataCell("Status",customer.billing_status),
    app.dataCell("Última sincronização",customer.billing_synced_at)
  );
  $("new-contract-link").href=`/customer-contract-create.html?customer_code=${encodeURIComponent(customer.customer_code||customerCode)}`;
  fillEditor(customer);
}
function editChanges(){
  return {name:$("edit-name").value,legal_name:$("edit-legal-name").value,phone:$("edit-phone").value,
    document_type:$("edit-document-type").value,document_number:$("edit-document-number").value,
    status:$("edit-status").value,registration_status:$("edit-registration-status").value,
    controller_id:$("edit-controller-id").value,billing_provider:$("edit-billing-provider").value,
    billing_customer_id:$("edit-billing-customer-id").value,billing_status:$("edit-billing-status").value};
}
async function saveProfile(event){
  event.preventDefault();
  const button=$("save-customer-profile");button.disabled=true;
  app.setNotice("profile-edit-notice","Salvando alterações…");
  try{
    const result=await app.request("/api/admin/customer/profile",{
      method:"POST",body:JSON.stringify({customer_code:customerCode,changes:editChanges()})
    });
    renderCustomer(result.customer||currentCustomer||{});
    app.setNotice("profile-edit-notice",result.updated?
      `Perfil atualizado. Campos: ${(result.changed_fields||[]).join(", ")}. Correlação: ${result.correlation_id}`:
      "Nenhuma alteração efetiva foi necessária.","success");
  }catch(error){app.setNotice("profile-edit-notice",error.message,"error");}
  finally{button.disabled=false;}
}
async function load(){
  if(!customerCode)throw new Error("Código do cliente não informado.");
  const data=await app.request(`/api/admin/customer?customer_code=${encodeURIComponent(customerCode)}`);
  renderCustomer(data.customer||{});renderUsers(data.users||[]);
  renderContracts(data.contracts||[]);renderInstances(data.instances||[]);
}
async function init(){
  const user=await app.loadShell("customers.html");
  canEdit=["admin","controller"].includes(user.role);
  $("customer-profile-form").addEventListener("submit",saveProfile);
  await load();
}
document.addEventListener("DOMContentLoaded",()=>init().catch(error=>{
  showNotice(error.message,"error");$("detail-meta").textContent="Falha ao carregar cliente";
}));
})();
