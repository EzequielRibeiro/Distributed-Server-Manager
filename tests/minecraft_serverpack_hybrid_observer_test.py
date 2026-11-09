"""Hybrid Server Pack observation is bounded, read-only and ownership-scoped."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/'dashboard',ROOT/'dashboard/workers',ROOT/'database'):
    if str(p) not in sys.path:sys.path.insert(0,str(p))
from minecraft_serverpack_hybrid_observer import collect_hybrid_serverpack_observations
import hybrid_agent_worker

PARENT={'instance_id':'inst','content_id':'pack','content_type':'modpack','provider':'local',
        'artifact':{'ephemeral_upload':True}}
ROW={'revision':2,'manifest_sha256':'a'*64,'manifest_kind':'serverpack-local-v1',
     'provider':'local','provider_project_id':'p','provider_version_id':'v',
     'minecraft_version':'26.1.2','loader_id':'neoforge','loader_version':'26.1.2.109'}
HISTORY={'manifest_sha256':'a'*64,'manifest_json':json.dumps({'members':[]}),
         'override_roots_json':'[]'}
RECORD={'instance_id':'inst','agent_id':'agent','runtime_id':'minecraft.java.neoforge',
        'working_directory':'/tmp/disposable-runtime'}

class HybridObservationTests(unittest.TestCase):
    def setup_mock_repo(self):
        stack=patch('minecraft_serverpack_hybrid_observer.ContentRepository')
        repo=stack.start().return_value
        self.addCleanup(stack.stop)
        repo.list.return_value=[PARENT]
        repo._bundle_row.return_value=ROW
        repo._bundle_revision.return_value=HISTORY
        return repo

    def test_owned_runtime_and_controller_manifest_are_required(self):
        self.setup_mock_repo()
        with patch('minecraft_serverpack_hybrid_observer.observe_runtime',
                   return_value={'status':'physical_runtime_verified','reason':'boot_not_observed','manifest_sha256':'a'*64}) as probe:
            results=collect_hybrid_serverpack_observations(object(),agent_id='agent',
                                                            read_instance=lambda _:RECORD)
        self.assertEqual(len(results),1)
        self.assertEqual(results[0]['status'],'physical_runtime_verified')
        self.assertFalse(results[0]['boot_verified'])
        self.assertFalse(results[0]['ready_for_release'])
        probe.assert_called_once()

    def test_observed_hash_drift_cannot_be_promoted(self):
        self.setup_mock_repo()
        with patch('minecraft_serverpack_hybrid_observer.observe_runtime',
                   return_value={'status':'physical_runtime_verified',
                                 'manifest_sha256':'f'*64,'reason':'boot_not_observed'}):
            results=collect_hybrid_serverpack_observations(object(),agent_id='agent',
                                                            read_instance=lambda _:RECORD)
        self.assertEqual(results[0]['status'],'unverified')
        self.assertEqual(results[0]['reason'],'published_manifest_mismatch')

    def test_other_agent_never_reads_runtime(self):
        self.setup_mock_repo()
        with patch('minecraft_serverpack_hybrid_observer.observe_runtime') as probe:
            results=collect_hybrid_serverpack_observations(object(),agent_id='agent',
                read_instance=lambda _:{**RECORD,'agent_id':'another-agent'})
        self.assertEqual(results,[])
        probe.assert_not_called()

    def test_manifest_revision_drift_fails_before_probe(self):
        repo=self.setup_mock_repo()
        repo._bundle_revision.return_value={**HISTORY,'manifest_sha256':'f'*64}
        with patch('minecraft_serverpack_hybrid_observer.observe_runtime') as probe:
            results=collect_hybrid_serverpack_observations(object(),agent_id='agent',
                                                            read_instance=lambda _:RECORD)
        self.assertEqual(results,[])
        probe.assert_not_called()

    def test_hybrid_cycle_throttles_disk_scan_and_never_reports_boot(self):
        hybrid_agent_worker._SERVERPACK_OBSERVATION_LAST_RUN=0.0
        self.addCleanup(setattr,hybrid_agent_worker,'_SERVERPACK_OBSERVATION_LAST_RUN',0.0)
        with patch('hybrid_agent_worker._instance_runtime_module',return_value=type('R',(),{'get_instance':lambda self,_:RECORD})()),\
             patch('minecraft_serverpack_hybrid_observer.collect_hybrid_serverpack_observations',
                   return_value=[{'status':'physical_runtime_verified','reason':'boot_not_observed'}]) as probe,\
             patch('minecraft_serverpack_observation_events.persist_serverpack_runtime_observations',
                   return_value={'accepted':1,'created':1}):
            first=hybrid_agent_worker.process_hybrid_serverpack_observation_cycle(object(),ROOT,'agent')
            second=hybrid_agent_worker.process_hybrid_serverpack_observation_cycle(object(),ROOT,'agent')
        self.assertEqual(first['status'],'observed')
        self.assertEqual(first['verified'],1)
        self.assertEqual(second['status'],'throttled')
        self.assertEqual(probe.call_count,1)

if __name__=='__main__':unittest.main()