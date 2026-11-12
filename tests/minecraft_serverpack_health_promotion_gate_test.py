"""Customer health only turns ready for an independently corroborated live revision.

Runs on temporary SQLite, no production runtime or Controller is touched.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / 'dashboard', ROOT / 'database', ROOT / 'core'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from tests import minecraft_serverpack_pending_publication_atomic_test as fixtures
from core.content_bundle import normalize_bundle
from agent_instance_runtime_health_repository import AgentInstanceRuntimeHealthRepository
from agent_heartbeat_api import record_agent_heartbeat


class ServerpackHealthPromotionGateTest(unittest.TestCase):
    setUp = fixtures.AtomicPendingPublicationTest.setUp
    tearDown = fixtures.AtomicPendingPublicationTest.tearDown
    pending = fixtures.AtomicPendingPublicationTest.pending
    enqueue = fixtures.AtomicPendingPublicationTest.enqueue
    completed = fixtures.AtomicPendingPublicationTest.completed

    def seed_committed_bundle(self):
        pending = self.pending()
        repo, state = self.enqueue(pending, production=True)
        canonical = normalize_bundle({**pending['bundle'],
                                      'instance_id':pending['instance_id'],
                                      'parent_content_id':pending['content_id']})
        result = self.completed(state, pending)
        result['minecraft_serverpack_migration']['physical_manifest'] = {
            'status':'physical_mods_verified',
            'manifest_sha256':canonical['manifest_sha256'],
            'mod_count':len(canonical['manifest']['members']),
        }
        self.assertEqual(repo.apply_result('pr839-isolated-agent',result)['status'], 'completed')
        parent = self.content.get('pr855-controller-atomic', 'atm11')
        child = self.content.get('pr855-controller-atomic', 'mod-a')
        self.content.record_agent_state('pr839-isolated-agent', [
            {'instance_id':'pr855-controller-atomic',
             'content_id':item['content_id'],
             'desired_revision':item['revision'],
             'desired_checksum':item['checksum'],
             'applied_revision':item['revision'],
             'applied_checksum':item['checksum'],
             'installed_version':item['version'],
             'status':'applied','security_state':'clean'}
            for item in (parent, child)
        ])
        current = self.content._bundle_row('pr855-controller-atomic', 'atm11')
        return current

    def publish_live_heartbeat(self, current):
        now = datetime.now(timezone.utc)
        start, done = now-timedelta(minutes=3), now-timedelta(minutes=1)
        boot = {
            'status':'boot_process_observed',
            'reason':'current_java_and_done_log_bound',
            'proof_scope':'advisory_current_process_log',
            'java_pid':45123,
            'java_started_at':start.isoformat(),
            'done_at':done.isoformat(),
            'boot_verified':False,'ready_for_release':False,
        }
        evidence = {
            'status':'functional_boot_attested',
            'proof_scope':'owned_jvm_and_live_minecraft_status',
            'instance_id':'pr855-controller-atomic',
            'bundle_revision':current['revision'],
            'manifest_sha256':current['manifest_sha256'],
            'java_pid':45123,'game_port':25582,
            'java_started_at':start.isoformat(),
            'done_at':done.isoformat(),
            'boot_verified':True,'ready_for_release':False,
        }
        self.health = {
            'instance_id':'pr855-controller-atomic',
            'desired_state':'running', 'observed_state':'running',
            'reconcile_status':'healthy','health':'healthy',
            'operation_status':'idle','generated_at':now.isoformat(),
        }
        self.report = {
            'instance_id':'pr855-controller-atomic', 'content_id':'atm11',
            'bundle_revision':current['revision'],
            'manifest_sha256':current['manifest_sha256'],
            'status':'physical_runtime_verified','reason':'boot_not_observed',
            'boot_verified':False,'ready_for_release':False,
            'boot_observation':boot,'operational_attestation':evidence,
        }
        self.body = {
            'agent_id':'pr839-isolated-agent',
            'instance_runtime_health':[self.health],
            'minecraft_serverpack_observations':{
                'observed_at':now.isoformat(),
                'observations':[self.report],
            },
        }
        response = record_agent_heartbeat('pr839-isolated-agent', self.body,
                                          backend=self.backend)
        self.assertEqual(response['serverpack_observations_created'], 1)

    def summary(self, enabled):
        with patch.dict(os.environ, {'DSM_SERVERPACK_HEALTH_PROMOTION_ENABLED':
                                      '1' if enabled else '0'}):
            return self.content.customer_view('pr855-controller-atomic')[0]['bundle_summary']

    def test_fresh_corroborated_revision_transitions_ready_only_under_opt_in(self):
        current = self.seed_committed_bundle()
        self.publish_live_heartbeat(current)
        summary = self.summary(False)
        self.assertEqual(summary['health_gate'], 'blocked')
        self.assertEqual(summary['convergence_status'], 'pending')
        self.assertEqual(summary['health_reason'], 'health_promotion_disabled')
        with patch.dict(os.environ, {'DSM_CONTENT_HOLD_INSTANCE_IDS':'pr855-controller-atomic'}):
            self.assertEqual(self.summary(True)['health_gate'],'blocked')
            self.assertEqual(self.summary(True)['health_reason'],'activation_hold_active')
        summary = self.summary(True)
        for key,value in (
            ('metadata_convergence','aligned'),
            ('manifest_alignment','metadata_aligned'),
            ('physical_attestation','verified'),
            ('current_physical_observation','verified'),
            ('current_boot_witness','observed'),
            ('current_operational_attestation','observed'),
            ('runtime_process_observation','reported_running'),
            ('health_gate','ready'),
            ('convergence_status','ready'),
            ('health_reason','runtime_functionally_attested')):
            self.assertEqual(summary[key],value, key)

        # The same timestamp may no longer be used to mask a newer stopped state.
        AgentInstanceRuntimeHealthRepository(self.backend).apply_inventory(
            'pr839-isolated-agent',[{**self.health,'observed_state':'stopped'}])
        self.assertEqual(self.summary(True)['health_gate'],'blocked')
        self.assertEqual(self.summary(True)['convergence_status'],'pending')
        AgentInstanceRuntimeHealthRepository(self.backend).apply_inventory(
            'pr839-isolated-agent',[self.health])
        self.assertEqual(self.summary(True)['health_gate'],'ready')

        # Any new failed physical observation revokes the positive read model.
        self.body['minecraft_serverpack_observations']['observed_at'] = (
            datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat()
        self.body['minecraft_serverpack_observations']['observations'] = [{
            **self.report,'status':'unverified','reason':'physical_or_loader_mismatch',
            'operational_attestation':None,'boot_observation':None}]
        self.assertEqual(record_agent_heartbeat('pr839-isolated-agent',self.body,
            backend=self.backend)['serverpack_observations_created'],1)
        self.assertEqual(self.summary(True)['health_gate'],'blocked')

    def test_expired_or_mismatched_evidence_never_becomes_healthy(self):
        current = self.seed_committed_bundle()
        self.publish_live_heartbeat(current)
        for signal, state in (
            ('_serverpack_recent_operational_attestation','stale'),
            ('_serverpack_recent_boot_witness','missing'),
            ('_serverpack_recent_physical_observation','unverified'),
            ('_serverpack_runtime_process_observation','stale')):
            with self.subTest(signal=signal), patch.object(self.content,signal,
                                                            return_value=state):
                self.assertEqual(self.summary(True)['health_gate'],'blocked')
        with self.backend.transaction() as connection:
            connection.execute('UPDATE content_bundles SET manifest_sha256=? WHERE bundle_id=?',
                               ('f'*64,current['bundle_id']))
        self.assertEqual(self.summary(True)['health_gate'],'blocked')


    def test_controller_game_port_change_revokes_attested_jvm_health(self):
        current=self.seed_committed_bundle()
        self.publish_live_heartbeat(current)
        self.assertEqual(self.summary(True)['health_gate'],'ready')
        with self.backend.transaction() as connection:
            connection.execute('UPDATE instance_ports SET port=? WHERE instance_id=? AND name=?',
                               (25583,'pr855-controller-atomic','game'))
        self.assertEqual(self.summary(True)['current_operational_attestation'],'missing')
        self.assertEqual(self.summary(True)['health_gate'],'blocked')
        with self.backend.transaction() as connection:
            connection.execute('UPDATE instance_ports SET port=? WHERE instance_id=? AND name=?',
                               (25582,'pr855-controller-atomic','game'))
        self.assertEqual(self.summary(True)['health_gate'],'ready')


if __name__=='__main__':
    unittest.main()
