"""Remote Linux observer checks Controller manifest and local Agent runtime, read-only."""
from __future__ import annotations
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
for folder in (ROOT/'agents/linux/runtime',ROOT/'dashboard',ROOT/'database'):
    if str(folder) not in sys.path:sys.path.insert(0,str(folder))
from minecraft_serverpack_remote_observer import observe_remote_requests
from minecraft_serverpack_observation_requests import requests_for_agent
from core.content_bundle import normalize_bundle


class RemoteProducerTest(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='dsm-remote-observer-')
        self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)
        self.runtime=root/'runtime'
        self.runtime.mkdir()
        loader='26.1.2.109'
        arg=self.runtime/'libraries/net/neoforged/neoforge'/loader/'unix_args.txt'
        arg.parent.mkdir(parents=True)
        arg.write_text('--version '+loader+'\n')
        (self.runtime/'capivara-launch.args').write_bytes(arg.read_bytes())
        mods=self.runtime/'mods'
        mods.mkdir()
        self.jar=mods/'example.jar'
        self.jar.write_bytes(b'disposable-jar-fixture')
        self.bundle={'provider':'local','provider_project_id':'cf-1148445',
                     'provider_version_id':'test-1',
                     'minecraft_version':'26.1.2','loader_id':'neoforge',
                     'loader_version':loader,'manifest_kind':'serverpack-local-v1',
                     'override_roots':[],
                     'members':[{'content_id':'mod-a','path':'mods/example.jar',
                     'required':True,'artifact':{'provider':'local',
                       'bundle_member':'mods/example.jar','serverpack_child_v1':True,
                       'ephemeral_upload':True,'bundle_parent_content_id':'pack',
                       'serverpack_loader':'neoforge','serverpack_loader_version':loader,
                       'sha256':hashlib.sha256(self.jar.read_bytes()).hexdigest(),
                       'size_bytes':self.jar.stat().st_size}}]}
        self.normalized=normalize_bundle({**self.bundle,'instance_id':'inst','parent_content_id':'pack'})
        self.request={'instance_id':'inst','content_id':'pack','bundle_revision':3,
                      'manifest_sha256':self.normalized['manifest_sha256'],
                      'bundle':self.bundle}
        self.record={'instance_id':'inst','agent_id':'agent',
                     'runtime_id':'minecraft.java.neoforge',
                     'working_directory':str(self.runtime)}

    def collect(self,request=None,record=None):
        return observe_remote_requests([self.request if request is None else request],
                 agent_id='agent',read_instance=lambda _:self.record if record is None else record)

    def test_exact_physical_bytes_reported_without_writes_or_boot_claim(self):
        before={x.relative_to(self.runtime):x.read_bytes()
                for x in self.runtime.rglob('*') if x.is_file()}
        report=self.collect()
        self.assertEqual(len(report['observations']),1)
        observed=report['observations'][0]
        self.assertEqual(observed['status'],'physical_runtime_verified')
        self.assertEqual(observed['manifest_sha256'],self.normalized['manifest_sha256'])
        self.assertFalse(observed['boot_verified'])
        self.assertFalse(observed['ready_for_release'])
        after={x.relative_to(self.runtime):x.read_bytes()
               for x in self.runtime.rglob('*') if x.is_file()}
        self.assertEqual(before,after)

    def test_modified_jar_unexpected_jar_and_loader_mismatch_fail_closed(self):
        self.jar.write_bytes(b'x'*self.jar.stat().st_size)
        self.assertEqual(self.collect()['observations'][0]['status'],'unverified')
        self.jar.write_bytes(b'disposable-jar-fixture')
        (self.runtime/'mods/extra.jar').write_bytes(b'x')
        self.assertEqual(self.collect()['observations'][0]['status'],'unverified')
        (self.runtime/'mods/extra.jar').unlink()
        (self.runtime/'capivara-launch.args').write_text('--version 26.1.2.94\n')
        self.assertEqual(self.collect()['observations'][0]['status'],'unverified')

    def test_rejects_forged_manifest_and_other_agent(self):
        self.assertEqual(self.collect({**self.request,'manifest_sha256':'f'*64})['observations'],[])
        self.assertEqual(self.collect(record={**self.record,'agent_id':'other'})['observations'],[])
        self.assertEqual(observe_remote_requests([self.request,self.request],
            agent_id='agent',read_instance=lambda _:self.record)['observations'][0]['bundle_revision'],3)

    def test_controller_requests_derived_from_current_bundle_and_bounded(self):
        with patch('minecraft_serverpack_observation_requests.ContentRepository') as mocked:
            repo=mocked.return_value
            repo.list.return_value=[{'instance_id':'inst','content_id':'pack',
                'content_type':'modpack','provider':'local','artifact':{'ephemeral_upload':True}}]
            repo._bundle_row.return_value={
                'revision':3,'manifest_sha256':self.normalized['manifest_sha256'],
                'manifest_kind':'serverpack-local-v1',
                **{k:self.bundle[k] for k in ('provider','provider_project_id','provider_version_id',
                    'minecraft_version','loader_id','loader_version')}}
            repo._bundle_revision.return_value={'manifest_json':__import__('json').dumps(
                self.normalized['manifest']),'manifest_sha256':self.normalized['manifest_sha256'],
                'override_roots_json':'[]'}
            generated=requests_for_agent(object(),agent_id='agent')
            self.assertEqual(len(generated),1)
            self.assertEqual(generated[0]['manifest_sha256'],self.normalized['manifest_sha256'])
            self.assertEqual(self.collect(generated[0])['observations'][0]['status'],
                             'physical_runtime_verified')
            repo._bundle_row.return_value['manifest_sha256']='f'*64
            self.assertEqual(requests_for_agent(object(),agent_id='agent'),[])

if __name__=='__main__':unittest.main()