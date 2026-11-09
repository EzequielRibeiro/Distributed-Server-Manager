"""Linux Agent sends a read-only observation on the next authenticated heartbeat."""
from __future__ import annotations
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
for folder in (ROOT/'agents/linux/runtime',ROOT/'dashboard',ROOT/'database'):
    if str(folder) not in sys.path:sys.path.insert(0,str(folder))
import agent


class RemoteHeartbeatCycleTest(unittest.TestCase):
    def setUp(self):
        self.config={'controller_url':'https://controller.invalid',
            'agent_id':'agent','credential_id':'cred','credential_secret':'secret',
            'fingerprint':'fingerprint'}
        agent._SERVERPACK_LAST_SCANNED=0.0
        agent._SERVERPACK_OBSERVATION_PENDING=None
        self.addCleanup(setattr,agent,'_SERVERPACK_LAST_SCANNED',0.0)
        self.addCleanup(setattr,agent,'_SERVERPACK_OBSERVATION_PENDING',None)

    def test_next_heartbeat_delivers_proof_without_rescanning_every_30_seconds(self):
        request={'instance_id':'i','content_id':'pack','bundle_revision':2,
                 'manifest_sha256':'a'*64,'bundle':{}}
        proof={'observed_at':'2026-11-09T12:00:00Z',
               'observations':[{'instance_id':'i','content_id':'pack',
                   'bundle_revision':2,'manifest_sha256':'a'*64,
                   'status':'physical_runtime_verified','reason':'boot_not_observed',
                   'boot_verified':False,'ready_for_release':False}]}
        delivered=[]
        def transmit(_url,payload,headers=None):
            delivered.append(payload)
            return {'serverpack_observation_requests':[request]}
        with patch.object(agent,'_post',side_effect=transmit), \
             patch.object(agent,'_inventory',side_effect=lambda _: {'agent_id':'agent',**(
                 {'minecraft_serverpack_observations':agent._SERVERPACK_OBSERVATION_PENDING}
                 if agent._SERVERPACK_OBSERVATION_PENDING else {})}), \
             patch.object(agent,'observe_remote_requests',return_value=proof) as scan:
            agent.heartbeat(self.config)
            agent.heartbeat(self.config)
            agent.heartbeat(self.config)
        self.assertEqual(scan.call_count,1)
        self.assertNotIn('minecraft_serverpack_observations',delivered[0])
        self.assertEqual(delivered[1]['minecraft_serverpack_observations'],proof)
        self.assertNotIn('minecraft_serverpack_observations',delivered[2])

    def test_failed_upload_keeps_pending_evidence(self):
        report={'observed_at':'2026-11-09T12:00:00Z','observations':[]}
        agent._SERVERPACK_OBSERVATION_PENDING=report
        with patch.object(agent,'_inventory',return_value={'minecraft_serverpack_observations':report}), \
             patch.object(agent,'_post',side_effect=RuntimeError('network offline')):
            with self.assertRaises(RuntimeError):agent.heartbeat(self.config)
        self.assertIs(agent._SERVERPACK_OBSERVATION_PENDING,report)

if __name__=='__main__':unittest.main()