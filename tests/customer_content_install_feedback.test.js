// Regression: the search-result Install action must never fail silently.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname,"..");
const source = fs.readFileSync(process.env.CAPIVARA_MAIN_SCRIPT ||
    path.join(root,"dashboard/web/customer-instance-v2.js"),"utf8");
const helpersStart = source.indexOf("function syncContentInstallLock(");
const helpersEnd = source.indexOf("function applyContentItems(",helpersStart);
const helpers = source.slice(helpersStart,helpersEnd);
const start = source.indexOf("async function installDiscoveredContent(");
const end = source.indexOf("async function mutateContent(",start);
assert(start > 0 && end > start,"install action must exist");
assert(source.includes("button.onclick=()=>installDiscoveredContent(item,button,feedback)"),
    "the rendered search result must wire button and inline feedback");
assert(source.includes("body.append(feedback);row.append(main,button)"),
    "mobile feedback must render under content metadata instead of overlapping heading");
const css = fs.readFileSync(path.join(root,"dashboard/web/customer-instance-v2.css"),"utf8");
assert(css.includes(".content-install-wait::before"),"reload shows animated pending banner");
assert(source.includes("if(!contentSearchResults.length){if(contentInstallLock)"),"reload does not display empty search while installing");
assert(css.includes(".content-result .content-install-status{display:block"),
    "installation feedback must wrap as a block on narrow screens");
function runFixture(request,loadContent) {
  const notices = [];
  const styles = new Set();
  const button = {disabled:false,textContent:"Instalar",attributes:new Map(),
    setAttribute(k,v){this.attributes.set(k,v)},
    removeAttribute(k){this.attributes.delete(k)}};
  const feedback = {textContent:"",classList:{
    add(k){styles.add(k)},remove(k){styles.delete(k)}
  }};
  const other = {disabled:false,title:""};
  const search={disabled:false};
  const upload={disabled:false};const importUrl={disabled:false};
  const resultRow={dataset:{contentId:"curseforge:123"},classList:{toggle(){}},
    querySelector:()=>({classList:{toggle(){}}})};
  const contentResult={querySelectorAll:selector=>selector===".content-result"?[resultRow]:[button,other]};
  const managedButton={textContent:"Atualizar",disabled:false,title:""};
  const viewButton={textContent:"Ver conteúdo",disabled:false,title:""};
  const managed={querySelectorAll:()=>[managedButton,viewButton]};
  const elements={"content-search":search,"content-results":contentResult,
    "content-upload-button":upload,"content-upload-url-button":importUrl,
    "content-installed":managed};
  const context = {request,loadContent,api:"/api/test",iid:"minecraft-003",
    contentSearchResults:[{}],contentInstallLock:null,can:()=>true,
    $:id=>elements[id],toast:text=>notices.push(text)};
  const install = vm.runInNewContext(helpers+source.slice(start,end)+
    "\ninstallDiscoveredContent",context);
  return {install,button,other,search,upload,importUrl,managedButton,viewButton,feedback,styles,notices,context};
}
const item={content_id:"curseforge:123",content_type:"modpack",provider:"curseforge",
    project_ref:"123",name:"All the Mods 11"};
async function main(){
  // User should immediately see progress, and two clicks must never enqueue twice.
  let submit;let requests=0;
  const pending = new Promise(resolve=>{submit=resolve});
  let fixture = runFixture(async (url,options)=>{
    requests++;
    assert.equal(url,"/api/test/content");
    assert.equal(JSON.parse(options.body).artifact.project_id,"123");
    return pending;
  },async()=>{});
  const first=fixture.install(item,fixture.button,fixture.feedback);
  const second=fixture.install(item,fixture.button,fixture.feedback);
  assert.equal(fixture.button.disabled,true);
  assert.equal(fixture.other.disabled,true,"other install buttons blocked while submitting");
  assert.equal(fixture.search.disabled,true,"search blocked while submitting");
  assert.equal(fixture.upload.disabled,true,"upload blocked");
  assert.equal(fixture.importUrl.disabled,true,"URL import blocked");
  assert.equal(fixture.managedButton.disabled,true,"managed modifications blocked");
  assert.equal(fixture.viewButton.disabled,false,"read-only details remain available");
  assert.equal(fixture.button.textContent,"Verificando…");
  assert.match(fixture.feedback.textContent,/dependências/);
  assert.equal(requests,1,"second click must not send duplicate request");
  submit({});
  await Promise.all([first,second]);
  assert.equal(fixture.button.textContent,"Solicitado");
  assert.equal(fixture.other.disabled,true,"accepted request must retain lock");
  assert.equal(fixture.context.contentInstallLock.stage,"processing");
  // Backend terminal states, not HTTP acceptance, release the other actions.
  // Completion is exercised in a shared context to observe lock state.
  const terminalContext={contentInstallLock:{contentId:item.content_id,stage:"processing"},
    contentReconcileState:v=>v.reconciliation.status,contentSecurityState:v=>v.security_state,
    $:fixture.context.$,can:()=>true};
  const terminal = vm.runInNewContext(helpers+"\ncheckContentInstallCompletion",terminalContext);
  terminal([{content_id:item.content_id,reconciliation:{status:"pending"},security_state:"clean"}]);
  assert(terminalContext.contentInstallLock,"pending reconciliation retains the lock");
  terminal([{content_id:item.content_id,reconciliation:{status:"failed"},security_state:"clean"}]);
  assert.equal(terminalContext.contentInstallLock,null,"backend failure releases the lock");
  assert.equal(fixture.other.disabled,false);
  assert.equal(fixture.search.disabled,false);
  assert.equal(fixture.upload.disabled,false);
  assert.equal(fixture.importUrl.disabled,false);
  assert.equal(fixture.managedButton.disabled,false);

  assert.match(fixture.feedback.textContent,/Solicitação aceita/);
  assert.equal(fixture.button.disabled,false,"terminal backend failure unlocks primary button");
  // The backend response is retained as customer-visible retryable feedback.
  fixture=runFixture(async()=>{throw new Error("Nenhuma versão compatível com 26.1.2")},async()=>{});
  await fixture.install(item,fixture.button,fixture.feedback);
  assert.equal(fixture.button.disabled,false);
  assert.equal(fixture.other.disabled,false,"submission failure unlocks other buttons");
  assert.equal(fixture.search.disabled,false);
  assert.equal(fixture.upload.disabled,false);
  assert.equal(fixture.importUrl.disabled,false);
  assert.equal(fixture.managedButton.disabled,false);
  assert.equal(fixture.button.textContent,"Instalar");
  assert.match(fixture.feedback.textContent,/26.1.2/);
  assert(fixture.styles.has("content-search-error"));
  assert(fixture.notices.some(x=>x.includes("26.1.2")));
  // A pending modpack reported by the Controller must restore the lock after reload.
  const restored={contentInstallLock:null,contentReconcileState:v=>v.reconciliation.status,
    $:fixture.context.$,can:()=>true};
  const restore=vm.runInNewContext(helpers+"\n"+
    source.slice(source.indexOf("function restoreContentInstallLock("),
      source.indexOf("function applyContentItems("))+"\nrestoreContentInstallLock",restored);
  restore([{content_id:item.content_id,content_type:"modpack",desired_state:"installed",
    reconciliation:{status:"pending"}}]);
  assert.equal(restored.contentInstallLock.contentId,item.content_id);
  restored.contentInstallLock=null;
  restore([{content_id:item.content_id,content_type:"modpack",desired_state:"installed",
    reconciliation:{status:"applied"}}]);
  assert.equal(restored.contentInstallLock,null,"completed items do not restore the lock");
  // Never label a successful POST as failed if the follow-up refresh fails.
  fixture=runFixture(async()=>({ok:true}),async()=>{throw new Error("refresh offline")});
  await fixture.install(item,fixture.button,fixture.feedback);
  assert.equal(fixture.button.disabled,true);
  assert.match(fixture.feedback.textContent,/Solicitação aceita/);
  assert.match(fixture.feedback.textContent,/atualizar o painel/);
  assert(fixture.notices.some(x=>x.includes("Atualize a página")));
  console.log("PASS: progress, duplicate protection, explicit API error, retry and refresh ambiguity");
}
main().catch(error=>{console.error(error);process.exitCode=1});
