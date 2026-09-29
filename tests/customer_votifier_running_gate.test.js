#!/usr/bin/env node
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const source=fs.readFileSync(
 process.env.CAPIVARA_VOTIFIER_UI_SCRIPT ||
 path.join(__dirname,"../dashboard/web/customer-instance-connection.js"),"utf8"
);
function fixture(initialStatus,options={}){
 let state=initialStatus,fail=false;
 const requests=[],events={},nodes={},intervals=[];
 function node(tag="div"){
  const result={tag,dataset:{},hidden:false,disabled:false,textContent:"",children:[],
   append(...items){this.children.push(...items)},
   prepend(...items){this.children.unshift(...items)},
   replaceChildren(...items){this.children=items},
   addEventListener(type,callback){this[type]=callback},
   after(){}
  };
  Object.defineProperty(result,"id",{set(v){this._id=v;nodes[v]=this},get(){return this._id}});
  return result;
 }
 nodes["view-overview"]=node();
 nodes["customer-connection-card"]=node();
 nodes["customer-connection-address"]=node();
 nodes["customer-connection-detail"]=node();
 nodes["customer-connection-copy"]=node();
 nodes.ports=node();
 const document={
  getElementById(id){return nodes[id]||null},
  createElement:node
 };
 const window={addEventListener(name,fn){events[name]=fn}};
 const context={window,document,URLSearchParams,
  location:{search:"?instance=mc-003",replace(){}},
  setInterval(fn){intervals.push(fn)},
  setTimeout(fn){return 1},
  confirm(){return true},
  async fetch(url,settings={}){
   requests.push({url,settings});
   if(fail)throw new Error("Conexão perdida");
   if(settings.method==="POST")return {ok:true,async json(){return {status:"completed"}}};
   return {ok:true,async json(){return {
    status:state,ports:[],connection:null,
    votifier:{supported:true,reserved:true,port:24015,
      manageable:options.manageable!==false,pending:!!options.pending}
   }}};
  }
 };
 vm.runInNewContext(source,context,{filename:"customer-instance-connection.js"});
 async function settle(){for(let i=0;i<5;i++)await new Promise(resolve=>setImmediate(resolve))}
 return {nodes,requests,events,intervals,settle,
  setState(next){state=next},fail(){fail=true}};
}
async function test(){
 for(const state of ["running","online","active","starting","stopping","restarting","unknown",""]){
  const app=fixture(state);
  app.events.load();await app.settle();
  const button=app.nodes["customer-votifier-toggle"];
  assert.ok(button, "Votifier button rendered");
  assert.equal(button.disabled,true,`No changes allowed in ${state}`);
  assert.equal(button.dataset.canEditNow,"false");
  assert.match(app.nodes["customer-votifier-status"].textContent,/Pare o servidor/);
  const before=app.requests.filter(x=>x.settings.method==="POST").length;
  await button.click();await app.settle();
  assert.equal(app.requests.filter(x=>x.settings.method==="POST").length,before);
 }
 for(const state of ["stopped","offline"]){
  const app=fixture(state);
  app.events.load();await app.settle();
  const button=app.nodes["customer-votifier-toggle"];
  assert.equal(button.disabled,false,`Changes allowed in ${state}`);
  assert.equal(button.dataset.canEditNow,"true");
  await button.click();await app.settle();
  const posts=app.requests.filter(x=>x.settings.method==="POST");
  assert.equal(posts.length,1);
  assert.equal(JSON.parse(posts[0].settings.body).enabled,false);
 }
 const restricted=fixture("stopped",{manageable:false});
 restricted.events.load();await restricted.settle();
 assert.equal(restricted.nodes["customer-votifier-toggle"].hidden,true);
 assert.equal(restricted.nodes["customer-votifier-toggle"].disabled,true);
 const stale=fixture("stopped");
 stale.events.load();await stale.settle();
 const staleButton=stale.nodes["customer-votifier-toggle"];
 assert.equal(staleButton.disabled,false);
 stale.fail();
 stale.intervals[0]();await stale.settle();
 assert.equal(staleButton.disabled,true);
 assert.equal(staleButton.dataset.canEditNow,"false");
 await staleButton.click();
 assert.equal(stale.requests.filter(x=>x.settings.method==="POST").length,0);
 console.log("PASS: Votifier UI blocks active/unknown states, handles stopped states and failed refresh.");
}
test().catch(err=>{console.error(err);process.exitCode=1});
