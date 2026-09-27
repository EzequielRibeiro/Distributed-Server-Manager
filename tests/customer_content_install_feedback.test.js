// Regression: the search-result Install action must never fail silently.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname,"..");
const source = fs.readFileSync(process.env.CAPIVARA_MAIN_SCRIPT ||
    path.join(root,"dashboard/web/customer-instance-v2.js"),"utf8");
const helpersStart=source.indexOf("function syncContentInstallLock(");
const helpersEnd=source.indexOf("function applyContentItems(",helpersStart);
const helpers=source.slice(helpersStart,helpersEnd);
const start = source.indexOf("async function installDiscoveredContent(");
const end = source.indexOf("async function mutateContent(",start);
assert(start > 0 && end > start,"install action must exist");
assert(source.includes("button.onclick=()=>installDiscoveredContent(item,button,feedback)"),
    "the rendered search result must wire button and inline feedback");
assert(source.includes("row.append(main,feedback,button)"),
    "feedback must be a full-width sibling, not trapped beside the title and thumbnail");
assert(!source.includes("body.append(feedback);row.append(main,button)"),
    "mobile feedback must not be nested in narrow result metadata");
assert(source.includes('if(!feedback)toast(error.message||"Não foi possível solicitar a instalação.");'),
    "an inline error must not also cover mobile cards as a global overlay");
const css=fs.readFileSync(path.join(root,"dashboard/web/customer-instance-v2.css"),"utf8");
assert(css.includes(".content-result > .content-install-status{grid-column:1/-1"),
    "feedback must span the full result card width");
assert(css.includes('.content-result-installing > .btn[aria-busy="true"]::before'),
    "pending Install buttons need a visible spinner");
function runFixture(request,loadContent) {
  const notices = [];
  const styles = new Set();
  const button = {disabled:false,textContent:"Instalar",attributes:new Map(),
    setAttribute(k,v){this.attributes.set(k,v)},
    removeAttribute(k){this.attributes.delete(k)}};
  const feedback = {textContent:"",classList:{
    add(k){styles.add(k)},remove(k){styles.delete(k)}
  }};
  const other={disabled:false,title:""},search={disabled:false},
    upload={disabled:false,dataset:{}},importUrl={disabled:false,dataset:{}},
    type={disabled:false,dataset:{}},query={disabled:false,dataset:{}},
    file={disabled:false,dataset:{}},preDisabled={disabled:true,dataset:{}};
  const resultRow={dataset:{contentId:"curseforge:123"},classList:{toggle(){}},querySelector:()=>({classList:{toggle(){}}})};
  const results={querySelectorAll:selector=>selector===".content-result"?[resultRow]:[button,other]};
  const elements={"content-search":search,"content-results":results,
    "content-upload-button":upload,"content-upload-url-button":importUrl,
    "content-type":type,"content-query":query,"content-upload-file":file,
    "content-upload-url":preDisabled};
  const context = {request,loadContent,api:"/api/test",iid:"minecraft-003",
    $:id=>elements[id],contentInstallLock:null,contentSearchResults:[{}],contentUploadActive:false,contentUploadTransferId:null,can:()=>true,setManagedUploadUi:()=>{},toast:text=>notices.push(text)};
  const install = vm.runInNewContext(helpers+source.slice(start,end)+
    "\ninstallDiscoveredContent",context);
  return {install,button,other,search,upload,importUrl,type,query,file,preDisabled,feedback,styles,notices,context};
}
const item={content_id:"curseforge:123",content_type:"mod",provider:"curseforge",
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
  assert.equal(fixture.other.disabled,true);
  assert.equal(fixture.search.disabled,true);
  assert.equal(fixture.upload.disabled,true);
  assert.equal(fixture.importUrl.disabled,true);
  assert.equal(fixture.type.disabled,true);
  assert.equal(fixture.query.disabled,true);
  assert.equal(fixture.file.disabled,true);
  assert.equal(fixture.button.textContent,"Verificando…");
  assert.match(fixture.feedback.textContent,/dependências/);
  assert.equal(requests,1,"second click must not send duplicate request");
  submit({});
  await Promise.all([first,second]);
  assert.equal(fixture.button.textContent,"Solicitado");
  assert.equal(fixture.context.contentInstallLock.stage,"processing");
  assert.equal(fixture.other.disabled,true);
  assert.match(fixture.feedback.textContent,/Solicitação aceita/);
  assert.equal(fixture.button.disabled,true);
  // The backend response is retained as customer-visible retryable feedback.
  fixture=runFixture(async()=>{throw new Error("Nenhuma versão compatível com 26.1.2")},async()=>{});
  await fixture.install(item,fixture.button,fixture.feedback);
  assert.equal(fixture.button.disabled,false);
  assert.equal(fixture.other.disabled,false);
  assert.equal(fixture.type.disabled,false);
  assert.equal(fixture.query.disabled,false);
  assert.equal(fixture.file.disabled,false);
  assert.equal(fixture.preDisabled.disabled,true,"previously disabled inputs must stay disabled");
  assert.equal(fixture.button.textContent,"Instalar");
  assert.match(fixture.feedback.textContent,/26.1.2/);
  assert(fixture.styles.has("content-search-error"));
  assert(!fixture.notices.some(x=>x.includes("26.1.2")),"mobile inline error must not overlap the card as a toast");
  // Never label a successful POST as failed if the follow-up refresh fails.
  fixture=runFixture(async()=>({ok:true}),async()=>{throw new Error("refresh offline")});
  await fixture.install(item,fixture.button,fixture.feedback);
  assert.equal(fixture.button.disabled,true);
  assert.match(fixture.feedback.textContent,/Solicitação aceita/);
  assert.match(fixture.feedback.textContent,/atualizar o painel/);
  assert(fixture.notices.some(x=>x.includes("Atualize a página")));
  console.log("PASS: mobile feedback layout, spinner, full content lock, duplicate protection, inline error, retry and refresh ambiguity");
}
main().catch(error=>{console.error(error);process.exitCode=1});
// The parent can report applied while Agent is still processing required children.
const summaryStart=source.indexOf('function contentBundlePending(');
const summaryEnd=source.indexOf('function applyContentItems(',summaryStart);
assert(summaryStart>0&&summaryEnd>summaryStart);
const {pending,failed}=vm.runInNewContext(source.slice(summaryStart,summaryEnd)+
  '\n({pending:contentBundlePending,failed:contentBundleFailed})', {
    contentInstallLock:null,contentReconcileState:v=>v.reconciliation.status,
    contentSecurityState:v=>v.security_state,$:()=>null,can:()=>true});
assert(pending({bundle_summary:{child_count:2,reconciliation_statuses:{applied:1,pending:1}}}),
  'a parent applied before children must retain the installation lock');
assert(!pending({bundle_summary:{child_count:2,reconciliation_statuses:{applied:2}}}));
assert(failed({bundle_summary:{child_count:2,reconciliation_statuses:{applied:1,failed:1}}}));


 
// Upload status must persist in this tab and distinguish acceptance from installation.
assert(source.includes('showContentUploadOutcome("failed",error.message||"Falha durante o envio ou validação."'),
  "Upload failures must be recorded in a persistent status panel");
assert(source.includes('showContentUploadOutcome("accepted","A solicitação foi registrada pelo Controller.'),
  "Controller acceptance must not be described as successful game installation");
assert(source.includes("box.append(uploadCard);renderContentUploadOutcome();"),
  "The status must be restored when the upload panel is rebuilt");
const outcomeStart=source.indexOf("const contentUploadOutcomeKey=");
const outcomeEnd=source.indexOf("function uploadFileWithProgress(",outcomeStart);
assert(outcomeStart>0&&outcomeEnd>outcomeStart);
const saved=new Map();
const storage={setItem:(k,v)=>saved.set(k,v),getItem:k=>saved.get(k)||null};
let panel={hidden:true,className:"",textContent:""};
const ctx={iid:"minecraft-003",$:id=>id==="content-upload-outcome"?panel:null,sessionStorage:storage};
const outcome=vm.runInNewContext(source.slice(outcomeStart,outcomeEnd)+String.fromCharCode(10)+
  "({show:showContentUploadOutcome,render:renderContentUploadOutcome})",ctx);
outcome.show("failed","ZIP recusado pelo Agent","transfer-test-123");
assert.equal(panel.hidden,false);
assert.match(panel.textContent,/ZIP recusado pelo Agent/);
assert.match(panel.textContent,/transfer-test-123/);
panel={hidden:true,className:"",textContent:""};
outcome.render();
assert.equal(panel.hidden,false,"last failure must survive UI re-render");
assert.match(panel.textContent,/não concluído/);
outcome.show("accepted","Controller registrou a solicitação","transfer-test-124");
assert.match(panel.textContent,/registrada/);
assert(!panel.textContent.includes("instalado com sucesso"));
console.log("PASS: persistent upload outcome survives re-render with correct failure and acceptance semantics");


// Interrupted upload recovery must not retry the 500 MiB body after refresh.
assert(source.includes('const contentUploadInflightKey="capivara:upload-inflight:"+iid'),
  "the active transfer reference must survive page refresh");
assert(source.includes('saveContentUploadInflight(transfer.transfer_id,file.name,"uploading")'),
  "the transfer ID must be saved before the browser starts uploading bytes");
assert(source.includes('reconcileInterruptedContentUpload().catch(console.warn)'),
  "content view must reconcile interrupted uploads after refresh");
assert(source.includes('latest.transfer?.status!=="staging"'),
  "discard must recheck server state before cancellation");
assert(source.includes('clearContentUploadInflight(transferId);'),
  "finished transfers must release client-side tracking");
assert(!source.includes('xhr.upload.onload=()=>request(api+"/content/upload"'),
  "recovery must not automatically duplicate the original upload");
console.log("PASS: interrupted transfer is recoverable with user-controlled discard");
