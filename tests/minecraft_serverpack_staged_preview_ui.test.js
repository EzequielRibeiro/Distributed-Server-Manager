"use strict";
// A future NeoForge ZIP may be uploaded and previewed, but may NEVER be
// finalized by the normal Server Pack upload path or mislabeled as a failure.
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../dashboard/web/customer-instance-v2.js"),"utf8");
const css=fs.readFileSync(path.join(__dirname,"../dashboard/web/customer-instance-v2.css"),"utf8");
assert(css.includes(".content-upload-outcome-preview_only{"),"read-only preview must have its own visual state");
const first=source.indexOf("async function previewOfficialServerpack(");
const last=source.indexOf("async function uploadManagedContent(",first);
assert(first>=0&&last>first);
const previewSource=source.slice(first,last);
assert(source.includes('outcome.status==="preview_only"?"ZIP validado: prévia de migração, sem instalação"'));
assert(source.includes('if(error.previewOnly){clearContentUploadInflight(contentUploadTransferId);return}'),
       "Both upload paths must retain previews without claiming upload failure");
assert.equal(source.split('if(error.previewOnly){clearContentUploadInflight(contentUploadTransferId);return}').length-1,2);
assert(source.includes('showContentUploadOutcome("failed",error.message||"Falha durante o envio ou validação."'));
assert(source.includes('showContentUploadOutcome("failed",error.message||"Falha durante a importação externa."'));
let requests=0;
let outcomes=[];
let confirmations=0;
const elements={
  "content-upload-cf-project":{value:"1148445"},
  "content-upload-cf-file":{value:"8916964"},
  "content-upload-loader-version":{value:"26.1.2.109"},
};
const context={
  $:name=>elements[name]||null,
  api:"/api/test",iid:"synthetic-minecraft",
  setManagedUploadUi:()=>{},
  bundleDiffText:diff=>"Added "+(diff.added||[]).length,
  showContentUploadOutcome:(state,message,transfer)=>outcomes.push({state,message,transfer}),
  confirm:()=>{confirmations++;return true},
  request:async (url,opts)=>{
    requests++;
    assert.equal(url,"/api/test/content/upload/preview");
    const body=JSON.parse(opts.body);
    assert.equal(body.transfer_id,"synthetic-transfer");
    return {serverpack:{
      kind:"CapivaraServerPackPreview",
      requires_stopped_instance:true,
      update_plan:{
        operation:"staged_loader_migration_preview",
        install_allowed:false,
        from_loader_version:"26.1.2.94",
        target_loader_version:"26.1.2.109",
        manifest_diff:{added:["a"],removed:[],updated:[],unchanged:[]},
      },
    }};
  },
};
const run=vm.runInNewContext(previewSource+"\npreviewOfficialServerpack",context);
(async()=>{
  let thrown;
  try{await run({transfer_id:"synthetic-transfer"},"atm11","modpack","ServerFiles-0.9.0-beta.zip","ATM11")}
  catch(error){thrown=error}
  assert(thrown&&thrown.previewOnly===true,
         "future loader preview must be explicitly distinguished from upload failure");
  assert.equal(requests,1);
  assert.equal(confirmations,0,"preview must never prompt to install incompatible ZIP");
  assert.equal(outcomes.length,1);
  assert.equal(outcomes[0].state,"preview_only");
  assert.match(outcomes[0].message,/NeoForge instalado: 26.1.2.94/);
  assert.match(outcomes[0].message,/NeoForge exigido: 26.1.2.109/);
  assert.match(outcomes[0].message,/instalação NÃO foi autorizada/);
  assert.equal(outcomes[0].transfer,"synthetic-transfer");
  console.log("PASS: client preserves staged loader ZIP evidence without finalization or misleading failure");
})().catch(error=>{console.error(error);process.exitCode=1});
