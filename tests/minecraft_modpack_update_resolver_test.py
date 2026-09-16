#!/usr/bin/env python3
from __future__ import annotations
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/'core',):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from minecraft_modpack_update_resolver import resolve_curseforge_modpack_update,resolve_minecraft_modpack_update,resolve_modrinth_modpack_update


class MinecraftModpackUpdateResolverTest(unittest.TestCase):
 def test_modrinth_resolves_only_latest_compatible_revision_identity(self):
  calls=[]
  def requester(url,headers):
   calls.append(url)
   if '/project/pack/version?' in url:return [{'id':'old','project_id':'project-1','version_type':'release','date_published':'2026-01-01','game_versions':['1.21.1'],'loaders':['fabric']},{'id':'new','project_id':'project-1','version_type':'release','date_published':'2026-09-01','game_versions':['1.21.1'],'loaders':['fabric']}]
   if '/project/pack' in url:return {'id':'project-1','project_type':'modpack','status':'approved'}
   raise AssertionError(url)
  result=resolve_modrinth_modpack_update('pack','1.21.1',{'loader':'fabric'},requester=requester)
  self.assertEqual(result['package_id'],'project-1:new');self.assertEqual(result['revision'],'new');self.assertEqual(len(calls),2);self.assertFalse(any('download' in url for url in calls))
 def test_curseforge_resolves_latest_zip_identity_without_archive_download(self):
  calls=[]
  def requester(url,headers):
   calls.append(url)
   if '/categories?' in url:return {'data':[{'id':4471,'isClass':True,'slug':'modpacks','name':'Modpacks'}]}
   if url.endswith('/mods/123'):return {'data':{'id':123,'gameId':432,'classId':4471}}
   if '/mods/123/files?' in url:return {'data':[{'id':10,'isAvailable':True,'gameVersions':['1.21.1'],'fileName':'old.zip','releaseType':1,'fileDate':'2026-01-01'},{'id':11,'isAvailable':True,'gameVersions':['1.21.1'],'fileName':'new.zip','releaseType':1,'fileDate':'2026-09-01'}]}
   raise AssertionError(url)
  result=resolve_curseforge_modpack_update('123','1.21.1',{'loader':'forge'},api_key='secret',requester=requester)
  self.assertEqual(result['package_id'],'123:11');self.assertEqual(result['revision'],'11');self.assertEqual(len(calls),3);self.assertFalse(any('download-url' in url for url in calls))
 def test_generic_dispatches_supported_provider(self):
  def requester(url,headers):
   if '/project/pack/version?' in url:return [{'id':'v2','project_id':'p','version_type':'release','date_published':'2026-09-01','game_versions':['1.21.1'],'loaders':['fabric']}]
   return {'id':'p','project_type':'modpack','status':'approved'}
  result=resolve_minecraft_modpack_update('modrinth','pack','1.21.1',{'loader':'fabric'},requester=requester);self.assertEqual(result['revision'],'v2')


if __name__=='__main__':unittest.main()
