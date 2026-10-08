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
let outcomes=[];
let confirmations=0;
const elements={
  "content-upload-cf-project":{value:"1148445"},
  "content-upload-cf-file":{value:"8916964"},
  "content-upload-loader-version":{value:"26.1.2.109"},
};
const context={
  $:name=>elements[name]||null,
  api:"/api/test",
  iid:"pr855-customer-flow",
  setManagedUploadUi:()=>{},
  bundleDiffText:diff=>"Added "+(diff.added||[]).length,
  showContentUploadOutcome:(state,message,transfer)=>outcomes.push({state,message,transfer}),
  toast:()=>{},
  confirm:()=>{confirmations++;return true},
  request:async(url,opts)=>{
    calls.push(url);
    const body=JSON.parse(opts.body);
    assert.equal(body.instance_id,"pr855-customer-flow");
    assert.equal(body.transfer_id,"synthetic-transfer");
    if(url==="/api/test/content/upload/preview"){
      return {serverpack:{
        kind:"CapivaraServerPackPreview",
        requires_stopped_instance:true,
        update_plan:{
          operation:"staged_loader_migration_preview",
          install_allowed:false,
          migration_plan_sha256:"b".repeat(64),
          from_loader_version:"26.1.2.94",
          target_loader_version:"26.1.2.109",
          manifest_diff:{added:["a"],removed:[],updated:[],unchanged:[]},
        },
      }};
    }
    if(url==="/api/test/content/upload/migration/revalidate"){
      assert.equal(body.migration_plan_sha256,"b".repeat(64));
      return {migration:{
        valid:true,
        install_allowed:false,
        migration_plan_sha256:"b".repeat(64),
        provisioning_migration_available:true,
        migration_execution_mode:"homologation",
        provisioning_homologation_available:true,
      }};
    }
    if(url==="/api/test/content/upload/migration/enqueue"){
      assert.equal(body.migration_plan_sha256,"b".repeat(64));
      return {migration:{
        accepted:true,
        execution_mode:"homologation",
        homologation_only:true,
        production_authorized:false,
        provisioning_id:"instance-provision-pr855",
        migration:{migration_plan_sha256:"b".repeat(64)},
        pending_bundle:{publish_allowed:false,candidate_bundle_revision:5},
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
      {transfer_id:"synthetic-transfer"},
      "atm11",
      "modpack",
      "ServerFiles-0.9.0-beta.zip",
      "ATM11",
    );
  }catch(error){thrown=error}
  assert(thrown&&thrown.previewOnly===true);
  assert.equal(thrown.migrationQueued,true);
  assert.deepEqual(calls,[
    "/api/test/content/upload/preview",
    "/api/test/content/upload/migration/revalidate",
    "/api/test/content/upload/migration/enqueue",
  ]);
  assert.equal(confirmations,1,"lab enqueue requires explicit customer confirmation");
  assert.equal(outcomes.length,1);
  assert.equal(outcomes[0].state,"accepted");
  assert.match(outcomes[0].message,/instance-provision-pr855/);
  assert.match(outcomes[0].message,/PENDENTE/);
  assert.equal(outcomes[0].transfer,"synthetic-transfer");
  console.log("PASS: revalidated PR855 preview enqueues exactly once and never reaches normal finalize");
})().catch(error=>{console.error(error);process.exitCode=1});
