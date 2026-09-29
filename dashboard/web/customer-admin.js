(function(){
"use strict";
const $=id=>document.getElementById(id);const app=window.CapCustomerManagement;
const customerCode=(new URLSearchParams(location.search).get("customer_code")||"").trim().toUpperCase();let currentCustomer=null;
function empty(root,text){root.replaceChildren();const node=document.createElement("div");node.className="customer-empty";node.textContent=text;root.append(node);}
function renderUsers(items){const root=$("detail-users");root.replaceChildren();if(!items.length){empty(root,"Nenhum usuário vinculado.");return;}for(const item of items){const card=document.createElement("article");card.className="customer-list-item";const title=document.createElement("h3");title.textContent=item.username;const identity=document.createElement("p");identity.textContent=`E-mail: ${item.email||"—"} · Papel: ${item.account_role||"member"} · ${item.active?"ativo":"inativo"}`;const password=document.createElement("p");password.textContent=item.must_change_password?"Senha provisória: troca obrigatória no próximo acesso":"Senha definitiva configurada";card.append(title,identity,password);root.append(card);}}
let canEditAssets=false;
function actionButton(title,callback,kind=""){
  const button=document.createElement("button");
  button.type="button";button.textContent=title;button.className="customer-asset-action"+(kind?" "+kind:"");
  button.addEventListener("click",callback);return button;
}
function editor(title){
  const dialog=document.createElement("dialog");dialog.className="customer-asset-dialog";
  const form=document.createElement("form");form.className="customer-asset-form";
  const heading=document.createElement("h3");heading.textContent=title;
  const body=document.createElement("div");body.className="customer-asset-fields";
  const actions=document.createElement("div");actions.className="customer-asset-actions";
  const save=actionButton("Salvar alterações",()=>{});save.type="submit";save.classList.add("customer-primary");
  const cancel=actionButton("Cancelar",()=>dialog.close());actions.append(cancel,save);
  const notice=document.createElement("p");notice.className="customer-notice";notice.setAttribute("role","status");
  form.append(heading,body,notice,actions);dialog.append(form);document.body.append(dialog);
  dialog.addEventListener("close",()=>dialog.remove());dialog.showModal();
  return {dialog,form,body,notice,save};
}
function field(body,label,type,value,options=[]){
  const wrapper=document.createElement("label");wrapper.textContent=label;
  const input=options.length?document.createElement("select"):document.createElement("input");
  if(options.length)options.forEach(([v,text])=>input.append(new Option(text,v)));
  else input.type=type;
  input.value=value==null?"":String(value);wrapper.append(input);body.append(wrapper);
  return input;
}
async function editContract(item){
  const view=editor("Editar contrato · "+item.id);
  const status=field(view.body,"Status","",item.status,[
    ["pending","Pendente"],["active","Ativo"],["suspended","Suspenso"],
    ["cancelled","Cancelado"],["expired","Expirado"]
  ]);
  const used=Number(item.instances_used||0);
  if(used){for(const option of status.options)if(["cancelled","expired"].includes(option.value))option.disabled=true;}
  const limit=field(view.body,"Limite de instâncias","number",item.instance_limit);
  limit.min=String(Math.max(1,used));limit.max="1000";limit.required=true;
  const ends=field(view.body,"Término (opcional)","date",String(item.ends_at||"").slice(0,10));
  let profiles=null,products=null;
  if(!used){
    try{
      const data=await app.request("/api/catalog/resource-profiles?game="+encodeURIComponent(item.game_id));
      const list=data.profiles||[];
      if(list.length)profiles=field(view.body,"Perfil contratado","",item.resource_profile_id||"",list.map(x=>[x.id,x.name||x.id]));
      if(profiles&&!profiles.value&&item.resource_profile_id)profiles.value=item.resource_profile_id;
      const workspace=await app.request("/api/catalog/workspace-products?game="+encodeURIComponent(item.game_id));
      const choices=workspace.products||[];
      if(choices.length)products=field(view.body,"Produto / distribuições permitidas","",item.product_variant||workspace.default_product_id||"",choices.map(x=>[x.id,x.label||x.id]));
    }catch(error){view.notice.textContent="Não foi possível carregar todos os perfis/produtos: "+error.message;}
  }else{
    const hint=document.createElement("p");hint.textContent="Perfil e produto precisam de migração para contratos com instâncias vinculadas. Esta edição não interrompe servidores.";view.body.append(hint);
  }
  view.form.addEventListener("submit",async event=>{
    event.preventDefault();const changes={};const newLimit=Number(limit.value);
    if(!Number.isInteger(newLimit)||newLimit<Math.max(1,used)){view.notice.textContent="Limite inválido.";return;}
    if(status.value!==item.status)changes.status=status.value;
    if(newLimit!==Number(item.instance_limit))changes.instance_limit=newLimit;
    if(ends.value!==String(item.ends_at||"").slice(0,10))changes.ends_at=ends.value;
    if(profiles&&profiles.value&&profiles.value!==String(item.resource_profile_id||""))changes.resource_profile_id=profiles.value;
    if(products&&products.value&&products.value!==String(item.product_variant||""))changes.product_variant=products.value;
    if(!Object.keys(changes).length){view.dialog.close();return;}
    view.save.disabled=true;view.notice.textContent="Salvando contrato…";
    try{
      await app.request("/api/admin/customer/assets",{method:"POST",body:JSON.stringify({action:"edit_contract",customer_code:customerCode,id:item.id,changes})});
      view.dialog.close();await load();app.setNotice("detail-error","Contrato atualizado.","success");
    }catch(error){view.notice.textContent=error.message;}finally{view.save.disabled=false;}
  });
}
async function deleteEmptyContract(item){
  if(Number(item.instances_used||0)>0)return;
  const typed=prompt("Para remover um contrato sem instâncias, digite o identificador completo:\n"+item.id);
  if(typed!==item.id)return;
  try{
    await app.request("/api/admin/customer/assets",{method:"POST",body:JSON.stringify({action:"delete_contract",customer_code:customerCode,id:item.id})});
    await load();app.setNotice("detail-error","Contrato sem instâncias removido.","success");
  }catch(error){app.setNotice("detail-error",error.message,"error");}
}
function editInstance(item){
  const view=editor("Editar instância · "+item.id);
  const name=field(view.body,"Nome de exibição","text",item.name||item.id);
  name.maxLength=100;name.required=true;
  const hint=document.createElement("p");hint.textContent="Runtime, Agent, recursos e contrato não são alterados aqui. Migrações usam fluxos próprios.";view.body.append(hint);
  view.form.addEventListener("submit",async event=>{
    event.preventDefault();const newName=name.value.trim();
    if(newName===String(item.name||"")){view.dialog.close();return;}
    view.save.disabled=true;view.notice.textContent="Salvando instância…";
    try{
      await app.request("/api/admin/customer/assets",{method:"POST",body:JSON.stringify({action:"edit_instance",customer_code:customerCode,id:item.id,changes:{name:newName}})});
      view.dialog.close();await load();app.setNotice("detail-error","Nome da instância atualizado.","success");
    }catch(error){view.notice.textContent=error.message;}finally{view.save.disabled=false;}
  });
}
function renderContracts(items){
  const root=$("detail-contracts");root.replaceChildren();
  if(!items.length){empty(root,"Nenhum contrato cadastrado.");return;}
  for(const item of items){
    const card=document.createElement("article");card.className="customer-list-item";
    const title=document.createElement("h3");title.textContent=`${item.game_id} · ${item.id}`;
    const line=document.createElement("p");line.textContent=`Status: ${item.status} · Instâncias: ${item.instances_used||0}/${item.instance_limit} · Tipo: ${item.product_variant||"padrão"} · Perfil: ${item.resource_profile_id||"—"}`;
    const dates=document.createElement("p");dates.textContent=`Início: ${item.starts_at||"—"} · Término: ${item.ends_at||"sem vencimento"}`;
    card.append(title,line,dates);
    if(canEditAssets){
      const actions=document.createElement("div");actions.className="customer-asset-actions";
      actions.append(actionButton("Editar",()=>editContract(item)));
      if(Number(item.instances_used||0)===0)actions.append(actionButton("Remover",()=>deleteEmptyContract(item),"danger"));
      card.append(actions);
    }
    root.append(card);
  }
}
function renderInstances(items){
  const root=$("detail-instances");root.replaceChildren();
  if(!items.length){empty(root,"Nenhuma instância criada.");return;}
  for(const item of items){
    const card=document.createElement("article");card.className="customer-list-item";
    const title=document.createElement("h3");title.textContent=item.name||item.id;
    const line=document.createElement("p");line.textContent=`${item.game_id} · ${item.status} · Runtime ${item.runtime_id||"—"} · Agent ${item.agent_id||"—"}`;
    const contract=document.createElement("p");contract.textContent=`Contrato: ${item.contract_id||"—"}`;
    card.append(title,line,contract);
    const actions=document.createElement("div");actions.className="customer-asset-actions";
    if(canEditAssets)actions.append(actionButton("Editar",()=>editInstance(item)));
    if(item.node_id&&item.game_id) {
      const link=document.createElement("a");link.className="customer-asset-action";
      link.textContent="Administrar servidor";
      link.href="/controller-instance.html?"+new URLSearchParams({server:item.node_id,game:item.game_id,instance:item.id});
      actions.append(link);
    }
    card.append(actions);root.append(card);
  }
}
function value(id,v){const node=$(id);if(node)node.value=v===null||v===undefined?"":String(v);}
function fillEditor(customer){value("edit-name",customer.name);value("edit-legal-name",customer.legal_name);value("edit-phone",customer.phone);value("edit-document-type",customer.document_type||"other");value("edit-document-number",customer.document_number);value("edit-status",customer.status||"active");value("edit-registration-status",customer.registration_status||"active");value("edit-controller-id",customer.controller_id);value("edit-billing-provider",customer.billing_provider);value("edit-billing-customer-id",customer.billing_customer_id);value("edit-billing-status",customer.billing_status||"unlinked");value("edit-customer-code",customer.customer_code);value("edit-account-email",customer.account_email||customer.email);}
function renderCustomer(customer){currentCustomer=customer;$("detail-name").textContent=customer.name||customer.customer_code||customerCode;$("detail-meta").textContent=`${customer.customer_code||customerCode} · ${customer.status||"—"}`;const grid=$("detail-data");grid.replaceChildren(app.dataCell("Código do cliente",customer.customer_code),app.dataCell("Nome",customer.name),app.dataCell("Razão social / nome legal",customer.legal_name),app.dataCell("Documento",`${String(customer.document_type||"").toUpperCase()} ${app.formatDocument(customer.document_type,customer.document_number)}`.trim()),app.dataCell("E-mail",customer.account_email||customer.email),app.dataCell("Telefone",customer.phone),app.dataCell("Controller",customer.controller_id),app.dataCell("Status da conta",customer.status),app.dataCell("Status do cadastro",customer.registration_status),app.dataCell("E-mail verificado em",customer.email_verified_at),app.dataCell("Criado em",customer.created_at),app.dataCell("Atualizado em",customer.updated_at));const billing=$("detail-billing");billing.replaceChildren(app.dataCell("Provider",customer.billing_provider),app.dataCell("Customer ID externo",customer.billing_customer_id),app.dataCell("Status",customer.billing_status),app.dataCell("Última sincronização",customer.billing_synced_at));$("new-contract-link").href=`/customer-contract-create.html?customer_code=${encodeURIComponent(customer.customer_code||customerCode)}`;fillEditor(customer);}
function editChanges(){return {name:$("edit-name").value,legal_name:$("edit-legal-name").value,phone:$("edit-phone").value,document_type:$("edit-document-type").value,document_number:$("edit-document-number").value,status:$("edit-status").value,registration_status:$("edit-registration-status").value,controller_id:$("edit-controller-id").value,billing_provider:$("edit-billing-provider").value,billing_customer_id:$("edit-billing-customer-id").value,billing_status:$("edit-billing-status").value};}
async function saveProfile(event){event.preventDefault();const button=$("save-customer-profile");button.disabled=true;app.setNotice("profile-edit-notice","Salvando alterações…");try{const result=await app.request("/api/admin/customer/profile",{method:"POST",body:JSON.stringify({customer_code:customerCode,changes:editChanges()})});renderCustomer(result.customer||currentCustomer||{});app.setNotice("profile-edit-notice",result.updated?`Perfil atualizado. Campos: ${(result.changed_fields||[]).join(", ")}. Correlação: ${result.correlation_id}`:"Nenhuma alteração efetiva foi necessária.","success");}catch(error){app.setNotice("profile-edit-notice",error.message,"error");}finally{button.disabled=false;}}
async function load(){if(!customerCode)throw new Error("Código do cliente não informado.");const data=await app.request(`/api/admin/customer?customer_code=${encodeURIComponent(customerCode)}`);renderCustomer(data.customer||{});renderUsers(data.users||[]);renderContracts(data.contracts||[]);renderInstances(data.instances||[]);}
async function init(){const who=await app.loadShell("customers.html");canEditAssets=["admin","controller"].includes(who.role);$("customer-profile-form").addEventListener("submit",saveProfile);await load();}
document.addEventListener("DOMContentLoaded",()=>init().catch(error=>{app.setNotice("detail-error",error.message,"error");$("detail-meta").textContent="Falha ao carregar cliente";}));
})();
