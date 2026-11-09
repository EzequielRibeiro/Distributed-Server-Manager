"""Real authenticated heartbeat → event → Controller projection on disposable SQLite."""
from __future__ import annotations
from datetime import datetime,timezone
import sys
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/'dashboard',ROOT/'database',ROOT/'core'):
    if str(path) not in sys.path:sys.path.insert(0,str(path))
from tests import minecraft_serverpack_pending_publication_atomic_test as _fixtures
from agent_heartbeat_api import record_agent_heartbeat
from universal_event_repository import UniversalEventRepository

class RemoteServerpackSQLiteIntegrationTest(unittest.TestCase):
    setUp=_fixtures.AtomicPendingPublicationTest.setUp
    tearDown=_fixtures.AtomicPendingPublicationTest.tearDown

    def test_remote_heartbeat_event_is_current_owned_and_never_healthy(self):
        bundle=self.content._bundle_row('pr855-controller-atomic','atm11')
        report={'instance_id':'pr855-controller-atomic','content_id':'atm11',
                'bundle_revision':bundle['revision'],
                'manifest_sha256':bundle['manifest_sha256'],
                'status':'physical_runtime_verified','reason':'boot_not_observed',
                'boot_verified':False,'ready_for_release':False}
        payload={'agent_id':'pr839-isolated-agent',
                 'minecraft_serverpack_observations':{
                    'observed_at':datetime.now(timezone.utc).isoformat(),
                    'observations':[report]}}
        result=record_agent_heartbeat('pr839-isolated-agent',payload,backend=self.backend)
        self.assertEqual(result['serverpack_observations_accepted'],1)
        self.assertEqual(result['serverpack_observations_created'],1)
        events=UniversalEventRepository(self.backend).list_events(
            event_type='MINECRAFT_SERVERPACK_RUNTIME_OBSERVED',
            instance_id='pr855-controller-atomic',limit=10)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['source'],'controller.authenticated_agent_serverpack_observer')
        summary=self.content.customer_view('pr855-controller-atomic')[0]['bundle_summary']
        self.assertEqual(summary['current_physical_observation'],'verified')
        self.assertEqual(summary['health_gate'],'blocked')
        self.assertEqual(summary['convergence_status'],'pending')
        payload['minecraft_serverpack_observations']['observations']=[
            {**report,'bundle_revision':report['bundle_revision']+1}]
        second=record_agent_heartbeat('pr839-isolated-agent',payload,backend=self.backend)
        self.assertEqual(second['serverpack_observations_accepted'],0)
        self.assertEqual(len(UniversalEventRepository(self.backend).list_events(
            event_type='MINECRAFT_SERVERPACK_RUNTIME_OBSERVED',
            instance_id='pr855-controller-atomic',limit=10)),1)

if __name__=='__main__':unittest.main()