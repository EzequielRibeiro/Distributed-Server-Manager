"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");

const source=fs.readFileSync(path.join(__dirname,"../dashboard/web/customer-instance-v2.js"),"utf8");
const first=source.indexOf("async function previewOfficialServerpack(");
const last=source.indexOf("async function uploadManagedContent(",first);
assert(first>=0&&last>first);
const previewSource=source.slice(first,last);

let calls=[];
let confirmationText="";
let outcome;
const elements={
  "content-upload-cf-project":{value:"1148445"},
  "content-upload-cf-file":{value:"8916964"},
  "content-upload-loader-version":{value:"26.1.2.109"},
};
const context={
  $:name=>elements[name]||null,
  api:"/api/test",
  iid:"cli-production-test",
  setManagedUploadUi:()=>{},
  bundleDiffText:()=>"",
  showContentUploadOutcome:(state,message,transfer)=>{outcome={state,message,transfer}},
  toast:()=>{},
  confirm:text=>{confirmationText=text;return true},
  request:async(url,opts)=>{
    calls.push(url);
    const body=JSON.parse(opts.body);
    if(url==="/api/test/content/upload/preview"){
      return {serverpack:{
        kind:"CapivaraServerPackPreview",
        requires_stopped_instance:true,
        update_plan:{
          operation:"staged_loader_migration_preview",
          install_allowed:false,
          migration_plan_sha256:"f".repeat(64),
          from_loader_version:"26.1.2.94",
          target_loader_version:"26.1.2.109",
          manifest_diff:{added:[],removed:[],updated:[],unchanged:[]},
        },
      }};
    }
    if(url==="/api/test/content/upload/migration/revalidate"){
      return {migration:{
        valid:true,
        install_allowed:false,
        migration_plan_sha256:"f".repeat(64),
        provisioning_migration_available:true,
        migration_execution_mode:"production",
        provisioning_homologation_available:false,
      }};
    }
    if(url==="/api/test/content/upload/migration/enqueue"){
      assert.equal(body.migration_plan_sha256,"f".repeat(64));
      return {migration:{
        accepted:true,
        execution_mode:"production",
        homologation_only:false,
        production_authorized:true,
        provisioning_id:"instance-provision-production",
        migration:{migration_plan_sha256:"f".repeat(64)},
        pending_bundle:{publish_allowed:false,candidate_bundle_revision:8},
      }};
    }
    throw new Error("unexpected request "+url);
  },
};

const run=vm.runInNewContext(previewSource+"\npreviewOfficialServerpack",context);
(async()=>{
  let thrown;
  try{
    await run(
      {transfer_id:"transfer-production"},
      "atm11",
      "modpack",
      "ServerFiles.zip",
      "ATM11",
    );
  }catch(error){thrown=error}
  assert(thrown&&thrown.migrationQueued===true);
  assert.match(confirmationText,/MIGRAÇÃO EM PRODUÇÃO/);
  assert.match(confirmationText,/parar temporariamente o servidor/);
  assert.deepEqual(calls,[
    "/api/test/content/upload/preview",
    "/api/test/content/upload/migration/revalidate",
    "/api/test/content/upload/migration/enqueue",
  ]);
  assert.equal(outcome.state,"accepted");
  assert.match(outcome.message,/Migração transacional enfileirada/);
  assert.match(outcome.message,/PENDENTE/);
  console.log("PASS: production UI requires explicit warning and exact production mode confirmation");
})().catch(error=>{console.error(error);process.exitCode=1});
