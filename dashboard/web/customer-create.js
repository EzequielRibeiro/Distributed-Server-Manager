(function(){
"use strict";
const $=id=>document.getElementById(id);const app=window.CapCustomerManagement;
function option(value,label){const node=document.createElement("option");node.value=value;node.textContent=label;return node;}
async function loadOptions(){
  const data=await app.request("/api/admin/customers/options");
  const controllers=data.controllers||[],controller=$("customer-controller");controller.replaceChildren();
  if(controllers.length===1){controller.append(option(controllers[0].id,`${controllers[0].name} · ${controllers[0].id}`));controller.value=controllers[0].id;}
  else{controller.append(option("","Selecione o Controller"),...controllers.map(item=>option(item.id,`${item.name} · ${item.id}`)));}
  if(!controllers.length)controller.append(option("","Nenhum Controller ativo"));
  const billing=$("customer-billing-status");
  billing.replaceChildren(option("","Automático"),...(data.billing_statuses||[]).map(status=>option(status,status)));
}
function payload(){return{
  name:$("customer-name").value.trim(),legal_name:$("customer-legal-name").value.trim(),
  document_type:$("customer-document-type").value,document_number:$("customer-document-number").value.trim(),
  phone:$("customer-phone").value.trim(),controller_id:$("customer-controller").value,
  username:$("customer-username").value.trim(),email:$("customer-email").value.trim(),
  billing_provider:$("customer-billing-provider").value.trim(),billing_customer_id:$("customer-billing-id").value.trim(),
  billing_status:$("customer-billing-status").value
};}
async function createCustomer(){
  const form=$("customer-create-form");if(!form.reportValidity())return;
  const button=$("customer-create-button");button.disabled=true;app.setNotice("customer-create-result","Criando conta…");
  try{
    const data=await app.request("/api/admin/customers",{method:"POST",body:JSON.stringify(payload())});
    const delivery=data.delivered?"A senha provisória foi enviada ao e-mail cadastrado.":"O envio automático da senha não foi concluído; entregue-a ao cliente por um canal seguro.";
    app.setNotice("customer-create-result",`Cliente ${data.customer_code} criado com sucesso.\nUsuário: ${data.username}\nE-mail: ${data.email}\nSenha provisória: ${data.temporary_password}\n\n${delivery}\nNo primeiro acesso será obrigatória a criação de uma nova senha.`,"success");
    form.querySelectorAll("input").forEach(input=>{if(!["customer-controller"].includes(input.id))input.value="";});
  }catch(error){app.setNotice("customer-create-result",error.message,"error");}
  finally{button.disabled=false;}
}
async function init(){await app.loadShell("customer-create.html");await loadOptions();$("customer-create-button").addEventListener("click",createCustomer);}
document.addEventListener("DOMContentLoaded",()=>init().catch(error=>app.setNotice("customer-create-result",error.message,"error")));
})();
