"""Authenticated remote Server Pack transport is ownership/revision scoped."""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest import TestCase
from unittest.mock import patch, MagicMock

ROOT=Path(__file__).resolve().parents[1]
for folder in ('dashboard','database'):
    path=str(ROOT/folder)
    if path not in sys.path:sys.path.insert(0,path)
from minecraft_serverpack_observation_events import (
    record_authenticated_serverpack_observations,classify_recent_serverpack_observation,
)

class RemoteHeartbeatObservationTest(TestCase):
    def setUp(self):
        self.timestamp=(datetime.now(timezone.utc)-timedelta(seconds=2)).isoformat()
        self.manifest='a'*64
        self.item={'instance_id':'inst','content_id':'pack',
                   'bundle_revision':3,'manifest_sha256':self.manifest,
                   'status':'physical_runtime_verified','reason':'boot_not_observed',
                   'boot_verified':False,'ready_for_release':False}
        self.payload={'observed_at':self.timestamp,'observations':[self.item]}

    def setup_repo(self):
        self.backend=MagicMock()
        patched=patch('content_repository.ContentRepository')
        repo=patched.start().return_value
        self.addCleanup(patched.stop)
        repo._instance.return_value={'agent_id':'agent','runtime_id':'minecraft.java.neoforge'}
        stack2=patch('alert_repository.AlertSession')
        session=stack2.start().return_value
        self.addCleanup(stack2.stop)
        session.execute.return_value.fetchone.return_value={'agent_id':'agent','runtime_id':'minecraft.java.neoforge'}
        self.db_session=session
        repo._bundle_row.return_value={'manifest_kind':'serverpack-local-v1',
            'revision':3,'manifest_sha256':self.manifest}
        return repo

    def test_accepts_only_authenticated_owners_current_revision_and_sha(self):
        repo=self.setup_repo()
        with patch('minecraft_serverpack_observation_events.persist_serverpack_runtime_observations',
                   return_value={'accepted':1,'created':1}) as write:
            result=record_authenticated_serverpack_observations(
                self.backend,agent_id='agent',payload=self.payload)
            self.assertEqual(result,{'accepted':1,'created':1})
            self.assertEqual(write.call_args.kwargs['source'],
                'controller.authenticated_agent_serverpack_observer')
            self.assertEqual(write.call_args.kwargs['observations'],[self.item])
            repo._bundle_row.return_value['revision']=4
            self.assertEqual(record_authenticated_serverpack_observations(
                self.backend,agent_id='agent',payload=self.payload)['accepted'],0)
            repo._bundle_row.return_value['revision']=3
            self.db_session.execute.return_value.fetchone.return_value['agent_id']='another'
            self.assertEqual(record_authenticated_serverpack_observations(
                self.backend,agent_id='agent',payload=self.payload)['accepted'],0)
            self.assertEqual(write.call_count,1)

    def test_rejects_invalid_time_loader_digest_and_sender_health_claim(self):
        repo=self.setup_repo()
        self.db_session.execute.return_value.fetchone.return_value['runtime_id']='minecraft.java.fabric'
        with patch('minecraft_serverpack_observation_events.persist_serverpack_runtime_observations',
                   return_value={'accepted':0,'created':0}) as write:
            self.assertEqual(record_authenticated_serverpack_observations(
                self.backend,agent_id='agent',payload=self.payload)['accepted'],0)
            self.db_session.execute.return_value.fetchone.return_value['runtime_id']='minecraft.java.neoforge'
            self.assertEqual(record_authenticated_serverpack_observations(
                self.backend,agent_id='agent',payload={**self.payload,'observed_at':'2026-01-01T00:00:00Z'})['accepted'],0)
            self.assertEqual(record_authenticated_serverpack_observations(
                self.backend,agent_id='agent',payload={**self.payload,'observations':[{**self.item,'manifest_sha256':'b'*64}]})['accepted'],0)
            write.assert_not_called()

    def test_authenticated_remote_source_is_read_only_and_scope_restricted(self):
        now=datetime.now(timezone.utc)
        event={'event_type':'MINECRAFT_SERVERPACK_RUNTIME_OBSERVED',
            'agent_id':'agent','instance_id':'inst',
            'source':'controller.authenticated_agent_serverpack_observer',
            'source_id':'agent','occurred_at':self.timestamp,
            'data':{'content_id':'pack','bundle_revision':3,
                    'observation_status':'physical_runtime_verified',
                    'proof_scope':'current_filesystem_only',
                    'boot_verified':False,'release_authorized':False}}
        self.assertEqual(classify_recent_serverpack_observation(event,
            agent_id='agent',instance_id='inst',content_id='pack',bundle_revision=3,now=now),'verified')
        self.assertEqual(classify_recent_serverpack_observation({**event,'source_id':'wrong'},
            agent_id='agent',instance_id='inst',content_id='pack',bundle_revision=3,now=now),'missing')
        self.assertEqual(classify_recent_serverpack_observation(event,
            agent_id='agent',instance_id='inst',content_id='pack',bundle_revision=4,now=now),'missing')