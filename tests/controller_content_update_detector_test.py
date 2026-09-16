#!/usr/bin/env python3
from __future__ import annotations
import sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/'core',ROOT/'database',ROOT/'dashboard'):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from content_update_detector import ControllerContentUpdateDetector,_artifact_revision,_project_reference


class _Content:
 def __init__(self,items):self.items=list(items)
 def initialize(self):return None
 def list(self,**kwargs):return list(self.items)


class _Instances:
 def __init__(self,contexts):self.contexts=dict(contexts)
 def initialize(self):return None
 def instance_context(self,instance_id):return dict(self.contexts[instance_id])


class _State:
 def __init__(self):self.calls=[]
 def initialize(self):return None
 def record_content_update_inventory(self,agent_id,payload):self.calls.append((agent_id,payload));return {'accepted':len(payload.get('content') or []),'rejected':0}


def _item(package='project:old',**extra):
 value={'agent_id':'agent-1','instance_id':'instance-1','content_id':'mod-a','game_id':'minecraft','content_type':'mod','desired_state':'installed','provider':'modrinth','artifact':{'provider':'modrinth','package_id':package},'provenance':{'minecraft_provider':{'project_id':'project'}},'metadata':{}}
 value.update(extra);return value


class ControllerContentUpdateDetectorTest(unittest.TestCase):
 def detector(self,items,resolver,modpack_resolver=None):
  contexts={'instance-1':{'id':'instance-1','agent_id':'agent-1','game_id':'minecraft','runtime_id':'fabric','game_version':'1.21.1'}};state=_State();detector=ControllerContentUpdateDetector(None,ROOT,content=_Content(items),instances=_Instances(contexts),state=state,resolver=resolver,modpack_resolver=modpack_resolver or (lambda *args,**kwargs:{'package_id':'unused:unused'}),interval_seconds=900);return detector,state
 def test_artifact_revision_uses_immutable_provider_id(self):
  self.assertEqual(_artifact_revision({'package_id':'project:version-id'}),'version-id');self.assertEqual(_artifact_revision({'package_id':'bad'}),'')
 def test_modrinth_new_package_revision_becomes_update_available(self):
  resolver=lambda provider,project,game_version,runtime,ctype:{'version':'same-human-name','artifact':{'provider':'modrinth','package_id':'project:new-id'}}
  detector,state=self.detector([_item()],resolver)
  with patch('content_update_detector.runtime_definition',return_value={'loader':'fabric'}):result=detector.scan(force=True)
  self.assertEqual(result['checked'],1);self.assertEqual(result['available'],1);self.assertEqual(len(state.calls),1)
  report=state.calls[0][1]['content'][0];self.assertEqual(report['state'],'update_available');self.assertEqual(report['installed_revision'],'old');self.assertEqual(report['available_revision'],'new-id')
 def test_same_package_revision_is_up_to_date(self):
  resolver=lambda *args,**kwargs:{'version':'v','artifact':{'provider':'modrinth','package_id':'project:old'}};detector,state=self.detector([_item()],resolver)
  with patch('content_update_detector.runtime_definition',return_value={'loader':'fabric'}):result=detector.scan(force=True)
  self.assertEqual(result['current'],1);self.assertEqual(state.calls[0][1]['content'][0]['state'],'up_to_date')
 def test_modpack_uses_lightweight_identity_resolver_and_parent_project(self):
  pack=_item(content_id='pack-a',content_type='modpack',artifact={'provider':'modrinth','package_id':'pack-project:old-pack'},provenance={'minecraft_modpack':{'project_id':'pack-project'}},metadata={'minecraft_modpack':{'provider_project_id':'pack-project'}});calls=[]
  def modpack_resolver(provider,project,game_version,runtime):calls.append((provider,project,game_version));return {'provider':provider,'package_id':'pack-project:new-pack','revision':'new-pack'}
  detector,state=self.detector([pack],lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError('individual resolver must not run')),modpack_resolver)
  with patch('content_update_detector.runtime_definition',return_value={'loader':'fabric'}):result=detector.scan(force=True)
  self.assertEqual(result['available'],1);self.assertEqual(calls,[('modrinth','pack-project','1.21.1')]);report=state.calls[0][1]['content'][0];self.assertEqual(report['content_type'],'modpack');self.assertEqual(report['available_revision'],'new-pack');self.assertEqual(_project_reference(pack),'pack-project')
 def test_bundle_child_is_not_updated_independently(self):
  child=_item(metadata={'bundle':{'parent_content_id':'pack-a'}});called=[]
  def resolver(*args,**kwargs):called.append(True);return {}
  detector,state=self.detector([child],resolver)
  result=detector.scan(force=True);self.assertEqual(result['skipped'],1);self.assertEqual(result['checked'],0);self.assertEqual(called,[]);self.assertEqual(state.calls,[])
 def test_resolver_failure_is_persisted_as_probe_failed(self):
  def resolver(*args,**kwargs):raise RuntimeError('provider unavailable')
  detector,state=self.detector([_item(provider='curseforge',artifact={'provider':'curseforge','package_id':'123:456'},provenance={'minecraft_provider':{'project_id':'123'}})],resolver)
  with patch('content_update_detector.runtime_definition',return_value={'loader':'forge'}):result=detector.scan(force=True)
  self.assertEqual(result['failed'],1);report=state.calls[0][1]['content'][0];self.assertEqual(report['state'],'probe_failed');self.assertIn('provider unavailable',report['error'])
 def test_detection_interval_prevents_hot_loop(self):
  resolver=lambda *args,**kwargs:{'artifact':{'provider':'modrinth','package_id':'project:new'}};detector,state=self.detector([_item()],resolver)
  with patch('content_update_detector.runtime_definition',return_value={'loader':'fabric'}):
   first=detector.scan(force=True);second=detector.scan()
  self.assertEqual(first['checked'],1);self.assertEqual(second['checked'],0);self.assertEqual(len(state.calls),1)


if __name__=='__main__':unittest.main()
