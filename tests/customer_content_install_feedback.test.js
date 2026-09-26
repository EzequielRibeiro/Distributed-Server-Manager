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
function runFixture(request,loadContent) {
  const notices = [];
  const styles = new Set();
  const button = {disabled:false,textContent:"Instalar",attributes:new Map(),
    setAttribute(k,v){this.attributes.set(k,v)},
    removeAttribute(k){this.attributes.delete(k)}};
  const feedback = {textContent:"",classList:{
    add(k){styles.add(k)},remove(k){styles.delete(k)}
  }};
  const other={disabled:false,title:""},search={disabled:false},upload={disabled:false},importUrl={disabled:false};
  const resultRow={dataset:{contentId:"curseforge:123"},classList:{toggle(){}},querySelector:()=>({classList:{toggle(){}}})};
  const results={querySelectorAll:selector=>selector===".content-result"?[resultRow]:[button,other]};
  const elements={"content-search":search,"content-results":results,"content-upload-button":upload,"content-upload-url-button":importUrl};
  const context = {request,loadContent,api:"/api/test",iid:"minecraft-003",
    $:id=>elements[id],contentInstallLock:null,contentSearchResults:[{}],contentUploadActive:false,contentUploadTransferId:null,can:()=>true,setManagedUploadUi:()=>{},toast:text=>notices.push(text)};
  const install = vm.runInNewContext(helpers+source.slice(start,end)+
    "\ninstallDiscoveredContent",context);
  return {install,button,other,search,upload,feedback,styles,notices,context};
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
  assert.equal(fixture.button.textContent,"Instalar");
  assert.match(fixture.feedback.textContent,/26.1.2/);
  assert(fixture.styles.has("content-search-error"));
  assert(fixture.notices.some(x=>x.includes("26.1.2")));
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
