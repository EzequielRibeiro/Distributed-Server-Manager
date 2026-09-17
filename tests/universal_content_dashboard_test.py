#!/usr/bin/env python3
from __future__ import annotations
import sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/'core',ROOT/'database',ROOT/'dashboard'):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from backend import DatabaseConfig
from backend_factory import create_backend
from content_repository import ContentRepository
from minecraft_content_resolver import discover_curseforge,discover_modrinth
from runtime_workspace_catalog import runtime_workspace_capabilities
from customer_content_workspace import CustomerContentWorkspaceService

class UniversalContentDashboardTest(unittest.TestCase):
 def test_runtime_capabilities_drive_provider_surface(self):
  paper=runtime_workspace_capabilities(ROOT,'minecraft','minecraft.java.paper')
  neo=runtime_workspace_capabilities(ROOT,'minecraft','minecraft.java.neoforge')
  arclight=runtime_workspace_capabilities(ROOT,'minecraft','minecraft.java.arclight')
  self.assertEqual(paper['providers'],{'plugin':['modrinth']});self.assertFalse(paper['modpacks'])
  self.assertEqual(neo['providers']['mod'],['curseforge','modrinth']);self.assertEqual(neo['providers']['modpack'],['curseforge','modrinth']);self.assertTrue(neo['modpacks'])
  self.assertNotIn('mod',arclight['providers']);self.assertEqual(arclight['providers']['plugin'],['modrinth'])
 def test_modrinth_discovery_filters_by_runtime(self):
  seen=[]
  def requester(url,headers):
   seen.append(url);return {'hits':[{'project_id':'abc123','slug':'sodium','project_type':'mod','title':'Sodium','description':'Fast','author':'dev','downloads':42,'icon_url':'https://cdn.modrinth.com/icon.png'}]}
  rows=discover_modrinth('sodium','1.21.1',{'loader':'fabric'},'mod',requester=requester)
  self.assertEqual(rows[0]['content_id'],'modrinth:abc123');self.assertEqual(rows[0]['project_ref'],'sodium')
  self.assertIn('project_type%3Amod',seen[0]);self.assertIn('versions%3A1.21.1',seen[0]);self.assertIn('categories%3Afabric',seen[0])
 def test_curseforge_discovery_uses_controller_key_only(self):
  seen=[]
  def requester(url,headers):
   seen.append((url,dict(headers)));self.assertEqual(headers.get('x-api-key'),'secret')
   if '/categories?' in url:return {'data':[{'id':6,'gameId':432,'name':'Mods','slug':'mc-mods','isClass':True}]}
   return {'data':[{'id':123,'gameId':432,'name':'Example','slug':'example','summary':'Summary','downloadCount':99,'logo':{'thumbnailUrl':'https://example.invalid/icon.png'}}]}
  rows=discover_curseforge('example','1.21.1',{'loader':'neoforge'},'mod',api_key='secret',requester=requester)
  self.assertEqual(rows[0]['content_id'],'curseforge:123');self.assertNotIn('secret',str(rows));self.assertTrue(any('modLoaderType=6' in url for url,_ in seen))
 def test_customer_view_hides_bundle_children_and_uses_agent_verdict(self):
  with tempfile.TemporaryDirectory() as tmp:
   backend=create_backend(DatabaseConfig(driver='sqlite',database=str(Path(tmp)/'db.sqlite')));backend.initialize()
   with backend.transaction() as c:
    c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",('ctrl-node','Controller','controller'));c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",('agent-node','Agent','agent'));c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",('ctrl','ctrl-node','Controller'));c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",('agent','ctrl','agent-node','Agent','active'));customer=c.execute("INSERT INTO customers(controller_id,name) VALUES (?,?)",('ctrl','Customer'));cid=int(customer.lastrowid);c.execute("INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",('inst','agent-node','minecraft','Instance','stopped','ctrl','agent',cid))
   repo=ContentRepository(backend);parent=repo.put({'instance_id':'inst','content_id':'pack','content_type':'modpack','provider':'http','artifact':{'provider':'http','url':'https://example.invalid/pack.zip'},'metadata':{'bundle':{'parent_content_id':'pack'}}})['assignment'];child=repo.put({'instance_id':'inst','content_id':'child','content_type':'mod','provider':'http','artifact':{'provider':'http','url':'https://example.invalid/mod.jar'},'metadata':{'bundle':{'parent_content_id':'pack'}}})['assignment']
   repo.record_agent_state('agent',[{'instance_id':'inst','content_id':'pack','desired_revision':parent['revision'],'desired_checksum':parent['checksum'],'applied_revision':parent['revision'],'applied_checksum':parent['checksum'],'status':'applied','security_state':'clean'},{'instance_id':'inst','content_id':'child','desired_revision':child['revision'],'desired_checksum':child['checksum'],'status':'security_blocked','security_state':'blocked'}])
   view=repo.customer_view('inst');self.assertEqual(len(view),1);self.assertEqual(view[0]['content_id'],'pack');self.assertEqual(view[0]['effective_security_state'],'blocked');self.assertEqual(view[0]['bundle_summary']['child_count'],1);backend.close()
 def test_workshop_discovery_is_lookup_not_legacy_catalog_search(self):
  service=CustomerContentWorkspaceService.__new__(CustomerContentWorkspaceService)
  service.workspace=SimpleNamespace(root=ROOT,repo=SimpleNamespace(workspace_policy=lambda iid:{}),require=lambda user,iid,permission:{'id':iid,'game_id':'dayz','runtime_id':'dayz.stable','game_version':'current'},_contract_policy=lambda context,policy:({'providers':{'workshop':['steam-workshop']}},SimpleNamespace(workshop_allowed=True,plugins_allowed=False,mods_allowed=False,modpacks_allowed=False,datapacks_allowed=False,modifications_allowed=True)))
  service.workshop_resolver=lambda ref,expected_app_id:{'published_file_id':'123','metadata':{'title':'Workshop Item','creator':'42'}}
  rows=service.search({'username':'u'},'inst','steam-workshop','workshop','123')
  self.assertEqual(rows[0]['content_id'],'steam-workshop:123');self.assertEqual(rows[0]['name'],'Workshop Item')
 def test_v2_ui_uses_canonical_content_workspace(self):
  js=(ROOT/'dashboard/web/customer-instance-v2.js').read_text(encoding='utf-8');html=(ROOT/'dashboard/web/customer-instance.html').read_text(encoding='utf-8')
  for token in ('/content/search','/content/upload','effective_security_state','bundle_summary','content.install','content.remove','allowed.update','allowed.rollback','rollback_revision','Atualizar','Reverter'):self.assertIn(token,js)
  self.assertIn('allowed=item.actions&&typeof item.actions==="object"?item.actions:{}',js)
  self.assertNotIn('/api/catalog/install',js);self.assertNotIn('/api/catalog/remove',js);self.assertIn('class="content-layout"',html)
if __name__=='__main__':unittest.main()
