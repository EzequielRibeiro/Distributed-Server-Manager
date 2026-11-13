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

    def test_controller_returns_current_manifest_for_only_owned_serverpack(self):
        from core.content_bundle import normalize_bundle
        response=record_agent_heartbeat('pr839-isolated-agent',
            {'agent_id':'pr839-isolated-agent'},backend=self.backend)
        requests=response['serverpack_observation_requests']
        self.assertEqual(len(requests),1)
        request=requests[0]
        self.assertEqual(request['instance_id'],'pr855-controller-atomic')
        self.assertEqual(request['content_id'],'atm11')
        canonical=normalize_bundle({**request['bundle'],
            'instance_id':request['instance_id'],
            'parent_content_id':request['content_id']})
        self.assertEqual(request['manifest_sha256'],canonical['manifest_sha256'])
        current=self.content._bundle_row('pr855-controller-atomic','atm11')
        self.assertEqual(request['bundle_revision'],current['revision'])
        self.assertEqual(request['manifest_sha256'],current['manifest_sha256'])
        with self.backend.transaction() as connection:
            connection.execute('UPDATE content_bundles SET manifest_sha256=? WHERE bundle_id=?',
                ('f'*64,current['bundle_id']))
        self.assertEqual(record_agent_heartbeat('pr839-isolated-agent',
            {'agent_id':'pr839-isolated-agent'},backend=self.backend)
            ['serverpack_observation_requests'],[])

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
        # A DB manifest change invalidates an otherwise successful, still
        # fresh physical report for the same numeric revision.
        with self.backend.transaction() as connection:
            connection.execute('UPDATE content_bundles SET manifest_sha256=? WHERE bundle_id=?',
                               ('f'*64,bundle['bundle_id']))
        self.assertEqual(self.content.customer_view('pr855-controller-atomic')[0]
                         ['bundle_summary']['current_physical_observation'],'missing')
        with self.backend.transaction() as connection:
            connection.execute('UPDATE content_bundles SET manifest_sha256=? WHERE bundle_id=?',
                               (bundle['manifest_sha256'],bundle['bundle_id']))
        payload['minecraft_serverpack_observations']['observations']=[
            {**report,'bundle_revision':report['bundle_revision']+1}]
        second=record_agent_heartbeat('pr839-isolated-agent',payload,backend=self.backend)
        self.assertEqual(second['serverpack_observations_accepted'],0)
        self.assertEqual(len(UniversalEventRepository(self.backend).list_events(
            event_type='MINECRAFT_SERVERPACK_RUNTIME_OBSERVED',
            instance_id='pr855-controller-atomic',limit=10)),1)

    def test_authenticated_functional_boot_evidence_is_scoped_and_non_authorizing(self):
        from datetime import timedelta
        bundle=self.content._bundle_row('pr855-controller-atomic','atm11')
        now=datetime.now(timezone.utc)
        evidence={
            'status':'functional_boot_attested',
            'proof_scope':'owned_jvm_and_live_minecraft_status',
            'instance_id':'pr855-controller-atomic',
            'bundle_revision':bundle['revision'],
            'manifest_sha256':bundle['manifest_sha256'],
            'java_pid':43210,'game_port':25582,
            'java_started_at':(now-timedelta(minutes=3)).isoformat(),
            'done_at':(now-timedelta(minutes=1)).isoformat(),
            'boot_verified':True,'ready_for_release':False,
        }
        report={
            'instance_id':evidence['instance_id'],'content_id':'atm11',
            'bundle_revision':bundle['revision'],
            'manifest_sha256':bundle['manifest_sha256'],
            'status':'physical_runtime_verified','reason':'boot_not_observed',
            'boot_verified':False,'ready_for_release':False,
            'operational_attestation':evidence,
            'boot_observation':{
                'status':'boot_process_observed',
                'proof_scope':'advisory_current_process_log',
                'reason':'current_java_and_done_log_bound',
                'java_pid':evidence['java_pid'],
                'java_started_at':evidence['java_started_at'],
                'done_at':evidence['done_at'],
                'boot_verified':False,'ready_for_release':False},
        }
        payload={'agent_id':'pr839-isolated-agent',
                 'minecraft_serverpack_observations':{
                     'observed_at':now.isoformat(),'observations':[report]}}
        outcome=record_agent_heartbeat('pr839-isolated-agent',payload,backend=self.backend)
        self.assertEqual(outcome['serverpack_observations_created'],1)
        events=UniversalEventRepository(self.backend).list_events(
            event_type='MINECRAFT_SERVERPACK_RUNTIME_OBSERVED',
            instance_id='pr855-controller-atomic',limit=10)
        self.assertEqual(events[0]['data']['operational_attestation']['game_port'],25582)
        self.assertFalse(events[0]['data']['release_authorized'])
        summary=self.content.customer_view('pr855-controller-atomic')[0]['bundle_summary']
        self.assertEqual(summary['current_operational_attestation'],'observed')
        self.assertEqual(summary['health_gate'],'blocked')
        # A newer negative observation invalidates the positive, not vice versa.
        payload['minecraft_serverpack_observations']['observed_at']=(now+timedelta(seconds=1)).isoformat()
        payload['minecraft_serverpack_observations']['observations']=[
            {**report,'status':'unverified','reason':'physical_or_loader_mismatch',
             'operational_attestation':None}]
        self.assertEqual(record_agent_heartbeat('pr839-isolated-agent',payload,
            backend=self.backend)['serverpack_observations_created'],1)
        self.assertEqual(self.content.customer_view('pr855-controller-atomic')[0]
                         ['bundle_summary']['current_operational_attestation'],'missing')
        self.assertEqual(self.content.customer_view('pr855-controller-atomic')[0]
                         ['bundle_summary']['health_gate'],'blocked')

    def test_boot_witness_is_scoped_to_current_manifest_and_never_grants_health(self):
        from datetime import timedelta
        bundle=self.content._bundle_row('pr855-controller-atomic','atm11')
        now=datetime.now(timezone.utc)
        observed_at=now.isoformat()
        proof={
            'status':'boot_process_observed',
            'reason':'current_java_and_done_log_bound',
            'proof_scope':'advisory_current_process_log',
            'java_pid':12345,
            'java_started_at':(now-timedelta(minutes=3)).isoformat(),
            'done_at':(now-timedelta(minutes=1)).isoformat(),
            'boot_verified':False,
            'ready_for_release':False,
        }
        report={
            'instance_id':'pr855-controller-atomic','content_id':'atm11',
            'bundle_revision':bundle['revision'],
            'manifest_sha256':bundle['manifest_sha256'],
            'status':'physical_runtime_verified','reason':'boot_not_observed',
            'boot_verified':False,'ready_for_release':False,
            'boot_observation':proof,
        }
        payload={'agent_id':'pr839-isolated-agent',
                 'minecraft_serverpack_observations':{
                     'observed_at':observed_at,'observations':[report]}}
        result=record_agent_heartbeat('pr839-isolated-agent',payload,backend=self.backend)
        self.assertEqual(result['serverpack_observations_created'],1)
        summary=self.content.customer_view('pr855-controller-atomic')[0]['bundle_summary']
        self.assertEqual(summary['current_boot_witness'],'observed')
        self.assertEqual(summary['health_gate'],'blocked')
        self.assertEqual(summary['convergence_status'],'pending')
        # Replaced bundle digest supersedes a previously valid boot witness.
        with self.backend.transaction() as c:
            c.execute('UPDATE content_bundles SET manifest_sha256=? WHERE bundle_id=?',
                      ('f'*64,bundle['bundle_id']))
        self.assertEqual(self.content.customer_view('pr855-controller-atomic')[0]
                         ['bundle_summary']['current_boot_witness'],'missing')
        with self.backend.transaction() as c:
            c.execute('UPDATE content_bundles SET manifest_sha256=? WHERE bundle_id=?',
                      (bundle['manifest_sha256'],bundle['bundle_id']))
        # Newer unverified observation supersedes a previous positive one.
        payload['minecraft_serverpack_observations']['observed_at']=(now+timedelta(seconds=1)).isoformat()
        payload['minecraft_serverpack_observations']['observations']=[
            {**report,'status':'unverified','reason':'physical_manifest_mismatch'}]
        result=record_agent_heartbeat('pr839-isolated-agent',payload,backend=self.backend)
        self.assertEqual(result['serverpack_observations_created'],1)
        self.assertEqual(self.content.customer_view('pr855-controller-atomic')[0]
                         ['bundle_summary']['current_boot_witness'],'missing')
        self.assertEqual(self.content.customer_view('pr855-controller-atomic')[0]
                         ['bundle_summary']['health_gate'],'blocked')

if __name__=='__main__':unittest.main()