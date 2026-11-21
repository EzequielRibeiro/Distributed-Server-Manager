#!/usr/bin/env python3
"""One disposable Agent/browser DayZ navigation and usage-cache scenario."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

NODE = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const f = JSON.parse(fs.readFileSync(0, 'utf8'));
const src = fs.readFileSync(process.argv[1], 'utf8');
function segment(start, end) {
  const a=src.indexOf(start), b=src.indexOf(end,a+start.length);
  assert.ok(a>=0 && b>a, 'Missing production JS: '+start);
  return src.slice(a,b);
}
class Element {
  constructor(tag){this.tag=tag;this.textContent='';this.children=[];this.classList={add(){},remove(){}};}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=[...children];}
}
const nodes=new Map(), calls=[], usageWaiters=[], errors=[];
const context=vm.createContext({
  document:{createElement:tag=>new Element(tag)},
  $:id=>{if(!nodes.has(id))nodes.set(id,new Element(id));return nodes.get(id);},
  filePath:'.', api:'/fake', iid:'dayz-fake-001',
  overview:{storage:{limit_bytes:f.limit}},
  can:p=>p==='files.read', fmtBytes:v=>String(v)+' B',
  knownNumber:v=>v==null||!Number.isFinite(Number(v))?null:Number(v),
  setProgress:(element,value)=>{element.progress=value;},
  toast:message=>errors.push(message),
  request:async (url,options)=>{const id=String(calls.length);calls.push(JSON.parse(options.body));return {command_id:id};},
  waitAgentCommandStatus:async (url,id)=>{
    const cmd=calls[Number(id)];
    if(cmd.action==='list'){
      assert.ok(Object.hasOwn(f.listings,cmd.path),'Unexpected path '+cmd.path);
      return {result:f.listings[cmd.path]};
    }
    if(cmd.action==='usage')return new Promise(resolve=>usageWaiters.push(resolve));
    if(cmd.action==='write_text')return {result:{saved:true}};
    throw new Error('Unexpected Agent action '+cmd.action);
  }
});
vm.runInContext(segment('let fileUsagePending=','function saveDownloadedInstanceFile(')+'\n'+
                segment('async function loadFiles()','async function saveFile('),context);
const node=id=>nodes.get(id);
const countUsage=()=>calls.filter(x=>x.action==='usage').length;
const rows=()=>node('file-body').children;
function open(name){
  const row=rows().find(r=>r.children[0]?.textContent===name);
  assert.ok(row,'Missing entry '+name);
  const button=row.children[2].children.find(b=>b.textContent==='Abrir');
  assert.ok(button,'Missing open button '+name);
  return button.onclick();
}
async function scenario(){
  const tick=()=>new Promise(resolve=>setImmediate(resolve));
  assert.equal(await vm.runInContext('loadFiles()',context),true);
  assert.equal(node('file-path').textContent,'/');
  assert.ok(rows().some(r=>r.children[0].textContent==='mpmissions'));
  assert.ok(!rows().some(r=>r.children[0].textContent==='.dsm'));
  await tick();
  assert.equal(countUsage(),1,'First listing should issue one usage query');
  assert.equal(node('files-storage-label').textContent,'Calculando uso do armazenamento…');
  await open('mpmissions');
  assert.equal(node('file-path').textContent,'/mpmissions');
  await open('hardcore.namalsk');
  assert.equal(node('file-path').textContent,'/mpmissions/hardcore.namalsk');
  assert.ok(rows().some(r=>r.children[0].textContent==='serverDZ.cfg'));
  await tick();
  assert.equal(countUsage(),1,'Navigating must not duplicate full disk usage');
  const oldPromise=vm.runInContext('cachedFileUsage()',context);
  await vm.runInContext('fileCommand("write_text","mpmissions/hardcore.namalsk/serverDZ.cfg",null,{content:"updated"})',context);
  const freshPromise=vm.runInContext('cachedFileUsage()',context);
  await tick();
  assert.equal(countUsage(),2,'File write should invalidate pending usage');
  assert.equal(usageWaiters.length,2);
  usageWaiters[1]({result:{usage_bytes:f.newUsage,limit_bytes:f.limit}});
  assert.equal((await freshPromise).usage_bytes,f.newUsage);
  usageWaiters[0]({result:{usage_bytes:f.oldUsage,limit_bytes:f.limit}});
  assert.equal((await oldPromise).usage_bytes,f.newUsage);
  await tick();
  assert.equal(vm.runInContext('fileUsageSnapshot.usage_bytes',context),f.newUsage);
  assert.equal(node('files-storage-label').textContent,String(f.newUsage)+' B / '+f.limit+' B');
  assert.ok(node('files-storage-bar').progress>0);
  assert.equal(errors.length,0,errors.join('; '));
  console.log('DAYZ-FAKE-AGENT: Namalsk, uso unico e cache renovado - OK');
}
scenario().catch(error=>{console.error(error.stack);process.exitCode=1;});
"""


class CustomerDayzFakeAgentBrowserSmokeTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for browser execution")
    def test_disposable_dayz_navigation_and_usage_cache(self):
        path = ROOT / "agents/linux/runtime/instance_files_client.py"
        sys.path.insert(0, str(path.parent))
        try:
            spec = importlib.util.spec_from_file_location("dayz_disposable_agent_files", path)
            agent = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(agent)
        finally:
            sys.path.remove(str(path.parent))
        with tempfile.TemporaryDirectory(prefix="capivara-dayz-fake-") as temp:
            root=Path(temp)
            mission=root/"mpmissions/hardcore.namalsk"
            mission.mkdir(parents=True)
            (root/"mpmissions/regular.namalsk").mkdir()
            cfg=mission/"serverDZ.cfg"
            cfg.write_text('hostname="test";',encoding="utf-8")
            private=root/".dsm"
            private.mkdir()
            (private/"secret.key").write_bytes(b"x"*2048)
            policy={"_restricted_dayz_root":True,"storage_limit_bytes":10240}
            paths=(".","mpmissions","mpmissions/hardcore.namalsk")
            with patch.object(agent,"_usage",side_effect=AssertionError("unexpected tree scan")) as scan:
                listings={name:agent._list(root,name,policy) for name in paths}
            scan.assert_not_called()
            self.assertIsNone(listings["."]["usage_bytes"])
            self.assertEqual([r["name"] for r in listings["."]["entries"]],["mpmissions"])
            self.assertEqual([r["name"] for r in listings["mpmissions"]["entries"]],
                             ["hardcore.namalsk","regular.namalsk"])
            old_usage=agent._usage(root,policy)
            self.assertEqual(old_usage,cfg.stat().st_size)
            agent._write_text(root,"mpmissions/hardcore.namalsk/serverDZ.cfg",
                              {"content":"Namalsk test update "*5},policy)
            new_usage=agent._usage(root,policy)
            self.assertGreater(new_usage,old_usage)
            self.assertLess(new_usage,policy["storage_limit_bytes"])
            self.assertEqual((private/"secret.key").stat().st_size,2048)
            fixture={"listings":listings,"limit":policy["storage_limit_bytes"],
                     "oldUsage":old_usage,"newUsage":new_usage}
            result=subprocess.run(["node","-e",NODE,str(ROOT/"dashboard/web/customer-instance-v2.js")],
                                  input=json.dumps(fixture),capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+"\n"+result.stderr)
            self.assertIn("DAYZ-FAKE-AGENT:",result.stdout)


if __name__=="__main__":
    unittest.main()
