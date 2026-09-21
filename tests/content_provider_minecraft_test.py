#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/'core',ROOT/'database',ROOT/'dashboard'):
 if str(path) not in sys.path:sys.path.insert(0,str(path))

from core.minecraft_content_resolver import MinecraftContentResolverError,discover_modrinth,provider_loaders,resolve_curseforge,resolve_modrinth
from dashboard.customer_content_workspace import CustomerContentWorkspaceService

class _Workspace:
 def __init__(self,context,policy):self.root=ROOT;self.context=context;self.policy=policy;self.repo=SimpleNamespace(workspace_policy=lambda iid:{})
 def require(self,user,iid,permission):return dict(self.context)
 def _contract_policy(self,context,policy):return {},self.policy

class _Content:
 def __init__(self):self.puts=[]
 def put(self,payload,requested_by=None):self.puts.append((dict(payload),requested_by));return {'changed':True,'assignment':dict(payload,revision=1)}
 def get(self,iid,cid):return None
 def list(self,**kwargs):return []

def _policy():return SimpleNamespace(modifications_allowed=True,mods_allowed=True,plugins_allowed=True,modpacks_allowed=True,datapacks_allowed=True,workshop_allowed=True,external_upload_allowed=True,custom_runtime_allowed=False)

def _service(context,resolver):
 service=CustomerContentWorkspaceService.__new__(CustomerContentWorkspaceService);service.workspace=_Workspace(context,_policy());service.content=_Content();service.minecraft_resolver=resolver;return service

def _load_content_client(platform):
 stubs={
  'instance_runtime':types.ModuleType('instance_runtime'),
  'content_provider':types.ModuleType('content_provider'),
  'content_provider_steam_workshop':types.ModuleType('content_provider_steam_workshop'),
  'content_activation_projection':types.ModuleType('content_activation_projection'),
  'content_activation_apply':types.ModuleType('content_activation_apply'),
  'content_security':types.ModuleType('content_security'),
 }
 stubs['content_provider'].resolve_source=lambda *args:None
 stubs['content_activation_projection'].synchronize_activation_state=lambda *args:[]
 stubs['content_activation_apply'].ContentActivationApplyError=type('ContentActivationApplyError',(RuntimeError,),{})
 stubs['content_activation_apply'].ContentActivationRollbackError=type('ContentActivationRollbackError',(stubs['content_activation_apply'].ContentActivationApplyError,),{})
 stubs['content_activation_apply'].apply_activation_snapshots=lambda *args:None
 stubs['content_security'].ContentSecurityRejected=type('ContentSecurityRejected',(ValueError,),{})
 stubs['content_security'].require_clean=lambda *args,**kwargs:{'security_state':'clean'}
 path=ROOT/f'agents/{platform}/runtime/content_client.py';spec=importlib.util.spec_from_file_location(f'{platform}_minecraft_hash_test',path);module=importlib.util.module_from_spec(spec)
 with patch.dict(sys.modules,stubs):spec.loader.exec_module(module)
 return module

class MinecraftProviderResolverTest(unittest.TestCase):
 def test_runtime_loader_mapping_is_fail_closed(self):
  self.assertEqual(provider_loaders({'loader':'fabric'},'mod'),('fabric',))
  self.assertEqual(provider_loaders({'loader':'youer'},'mod'),('neoforge',))
  self.assertEqual(provider_loaders({'loader':'paper'},'plugin'),('paper','bukkit','spigot'))
  with self.assertRaises(MinecraftContentResolverError):provider_loaders({'loader':'paper'},'mod')
  with self.assertRaises(MinecraftContentResolverError):provider_loaders({'loader':'neoforge'},'plugin')

 def test_modrinth_resolves_server_owned_url_version_and_hashes(self):
  def requester(url,headers):
   self.assertFalse(headers)
   if url.endswith('/project/sodium'):return {'id':'proj','project_type':'mod','status':'approved'}
   self.assertIn('/project/sodium/version?',url)
   return [
    {'id':'beta','project_id':'proj','version_number':'2.0-beta','version_type':'beta','date_published':'2026-09-12','status':'listed','game_versions':['1.21.1'],'loaders':['fabric'],'files':[{'primary':True,'url':'https://cdn.modrinth.com/data/proj/versions/beta/mod.jar','filename':'mod.jar','size':4,'hashes':{'sha512':'b'*128,'sha1':'c'*40}}]},
    {'id':'release','project_id':'proj','version_number':'1.9.0','version_type':'release','date_published':'2026-09-10','status':'listed','game_versions':['1.21.1'],'loaders':['fabric'],'files':[{'primary':True,'url':'https://cdn.modrinth.com/data/proj/versions/release/mod.jar','filename':'mod.jar','size':4,'hashes':{'sha512':'a'*128,'sha1':'d'*40}}]},
   ]
  result=resolve_modrinth('sodium','1.21.1',('fabric',),requester=requester)
  self.assertEqual(result['version'],'1.9.0');self.assertEqual(result['artifact']['package_id'],'proj:release');self.assertEqual(result['artifact']['sha512'],'a'*128);self.assertEqual(result['artifact']['sha1'],'d'*40);self.assertNotIn('token',json.dumps(result).lower())


 def test_modrinth_plugin_discovery_uses_plugin_project_type_for_youer(self):
  seen=[]
  def requester(url,headers):
   seen.append(url)
   return {'hits':[{'project_id':'vote-me','slug':'voteme','title':'VoteMe','description':'Voting plugin','author':'Herza','downloads':425,'icon_url':'https://cdn.modrinth.com/icon.png','project_type':'plugin'}]}
  runtime={'loader':'youer'}
  result=discover_modrinth('voteme','1.21.1',runtime,'plugin',requester=requester)
  self.assertEqual(1,len(result))
  self.assertEqual('voteme',result[0]['project_ref'])
  self.assertEqual('plugin',result[0]['project_type'])
  self.assertTrue(any('project_type%3Aplugin' in url or 'project_type%3Aplugin' in url.replace('%22','') for url in seen))
  self.assertTrue(any('categories%3Abukkit' in url or 'categories%3Aspigot' in url for url in seen))

 def test_modrinth_plugin_resolution_accepts_plugin_project(self):
  def requester(url,headers):
   if '/project/voteme/version?' not in url:
    return {'id':'vote-me','project_type':'plugin','status':'approved'}
   return [{'id':'v1','project_id':'vote-me','version_number':'1.0.2','version_type':'release','date_published':'2026-03-05','status':'listed','game_versions':['1.21.1'],'loaders':['bukkit','paper','purpur','spigot'],'files':[{'primary':True,'url':'https://cdn.modrinth.com/data/vote-me/versions/v1/VoteMe.jar','filename':'VoteMe.jar','size':4,'hashes':{'sha512':'a'*128,'sha1':'b'*40}}]}]
  result=resolve_modrinth('voteme','1.21.1',('bukkit','spigot'),'plugin',requester=requester)
  self.assertEqual('1.0.2',result['version'])
  self.assertEqual('vote-me:v1',result['artifact']['package_id'])

 def test_curseforge_key_is_controller_only_and_sha1_is_required(self):
  seen=[]
  def requester(url,headers):
   seen.append((url,dict(headers)));self.assertEqual(headers.get('x-api-key'),'secret-key')
   if '/categories?' in url:return {'data':[{'id':6,'gameId':432,'name':'Mods','slug':'mc-mods','isClass':True}]}
   if url.endswith('/mods/1234'):return {'data':{'id':1234,'gameId':432,'classId':6,'name':'Example Mod'}}
   return {'data':[{'id':77,'isAvailable':True,'displayName':'Build 77','releaseType':1,'fileDate':'2026-09-12T00:00:00Z','fileName':'mod.jar','fileLength':5,'downloadUrl':'https://mediafilez.forgecdn.net/files/0/77/mod.jar','gameVersions':['1.21.1'],'hashes':[{'algo':1,'value':'e'*40},{'algo':2,'value':'f'*32}],'dependencies':[]}]}
  result=resolve_curseforge('1234','1.21.1',('neoforge',),api_key='secret-key',requester=requester)
  self.assertEqual(result['artifact']['package_id'],'1234:77');self.assertEqual(result['artifact']['sha1'],'e'*40);self.assertNotIn('secret-key',json.dumps(result));self.assertTrue(any('modLoaderType=6' in url for url,_ in seen))

 def test_provider_project_type_rejects_modpack_disguised_as_mod(self):
  def modrinth(url,headers):
   return {'id':'pack','project_type':'modpack','status':'approved'}
  with self.assertRaisesRegex(MinecraftContentResolverError,'not an individual'):
   resolve_modrinth('pack','1.21.1',('fabric',),requester=modrinth)
  def curseforge(url,headers):
   if '/categories?' in url:return {'data':[{'id':6,'gameId':432,'name':'Mods','slug':'mc-mods','isClass':True},{'id':4471,'gameId':432,'name':'Modpacks','slug':'modpacks','isClass':True}]}
   return {'data':{'id':99,'gameId':432,'classId':4471,'name':'A Pack'}}
  with self.assertRaisesRegex(MinecraftContentResolverError,'not an individual'):
   resolve_curseforge('99','1.21.1',('forge',),api_key='secret-key',requester=curseforge)

 def test_customer_provider_payload_is_replaced_by_authoritative_resolution(self):
  context={'id':'i1','game_id':'minecraft','runtime_id':'minecraft.java.fabric','game_version':'1.21.1','agent_id':'agent-1'};calls=[]
  def resolver(provider,project,game_version,runtime,ctype):
   calls.append((provider,project,game_version,runtime.get('loader'),ctype));return {'provider':provider,'version':'resolved-1','artifact':{'provider':provider,'package_id':'project:version','url':'https://cdn.modrinth.com/data/project/version/mod.jar','filename':'mod.jar','sha512':'a'*128},'provenance':{'project_id':'project','version_id':'version'},'metadata':{'version_type':'release'}}
  service=_service(context,resolver)
  service.install({'username':'alice'},'i1',{'content_id':'sodium','content_type':'mod','provider':'modrinth','version':'client-forged','artifact':{'package_id':'sodium','url':'https://evil.invalid/payload.jar','sha512':'0'*128,'api_key':'must-not-survive'},'provenance':{'spoofed':True}})
  payload,_=service.content.puts[-1]
  self.assertEqual(calls,[('modrinth','sodium','1.21.1','fabric','mod')]);self.assertEqual(payload['version'],'resolved-1');self.assertEqual(payload['artifact']['url'],'https://cdn.modrinth.com/data/project/version/mod.jar');self.assertNotIn('api_key',payload['artifact']);self.assertNotIn('spoofed',payload['provenance'])

 def test_minecraft_provider_cannot_be_used_on_non_minecraft_instance(self):
  context={'id':'i1','game_id':'dayz','runtime_id':'dayz.stable','game_version':'1','agent_id':'agent-1'}
  with self.assertRaises(PermissionError):_service(context,lambda *a,**k:{}).install({'username':'alice'},'i1',{'content_id':'x','content_type':'mod','provider':'modrinth','artifact':{'package_id':'x'}})

 def test_multi_hash_verification_has_linux_windows_parity(self):
  data=b'capivara-minecraft-provider'
  expected={'size_bytes':len(data),'sha512':hashlib.sha512(data).hexdigest(),'sha256':hashlib.sha256(data).hexdigest(),'sha1':hashlib.sha1(data).hexdigest()}
  for platform in ('linux','windows'):
   with self.subTest(platform=platform),tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/'artifact.jar';path.write_bytes(data);module=_load_content_client(platform);module._verify_artifact(path,expected)
    with self.assertRaisesRegex(ValueError,'sha512 mismatch'):module._verify_artifact(path,{**expected,'sha512':'0'*128})
    with self.assertRaisesRegex(ValueError,'size mismatch'):module._verify_artifact(path,{**expected,'size_bytes':len(data)+1})

if __name__=='__main__':unittest.main()
