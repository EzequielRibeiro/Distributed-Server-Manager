"""Server Pack functional readiness is stronger than a log or arbitrary ping."""
from __future__ import annotations

from pathlib import Path
import os
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'agents/linux/runtime'
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))
import minecraft_serverpack_live_readiness as readiness


class FunctionalReadinessTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.runtime = Path(tmp.name)
        (self.runtime / 'server.properties').write_text('server-port=25597\n')
        self.before = {'status': 'boot_process_observed', 'java_pid': 35791,
                       'java_started_at': '2026-11-12T12:00:00+00:00',
                       'done_at': '2026-11-12T12:02:00+00:00',
                       'boot_verified': False, 'ready_for_release': False}
        self.args = {'instance_id': 'isolated-minecraft-1031',
                     'game_port': 25597, 'bundle_revision': 3,
                     'manifest_sha256': 'a' * 64}

    def probe(self, *, before=None, after=None, owned=True, status=None):
        if status is None:
            status = {'players_online': 0, 'players_max': 5}
        with (patch.object(readiness, 'observe_boot_witness',
                           side_effect=[before or self.before, after or self.before]),
              patch.object(readiness, '_owned_listener', return_value=owned),
              patch.object(readiness, 'query_java_status', return_value=status)):
            return readiness.attest_live_serverpack_readiness(self.runtime, **self.args)

    def test_live_tcp_socket_is_bound_to_current_process_fd(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            port=listener.getsockname()[1]
            self.assertTrue(readiness._owned_listener(os.getpid(),port))
            self.assertFalse(readiness._owned_listener(os.getpid(),port+1))

    def test_live_owned_process_ping_and_manifest_attests_without_release(self):
        result = self.probe()
        self.assertEqual(result['status'], 'functional_boot_attested')
        self.assertIs(result['boot_verified'], True)
        self.assertIs(result['ready_for_release'], False)
        self.assertEqual(result['java_pid'], 35791)
        self.assertEqual(result['bundle_revision'], 3)
        self.assertEqual(result['manifest_sha256'], 'a' * 64)

    def test_log_without_current_game_listener_is_not_attested(self):
        self.assertEqual(self.probe(owned=False)['reason'], 'listener_not_owned_by_java')

    def test_status_ping_failure_cannot_promote_done_log(self):
        self.assertEqual(self.probe(status={})['reason'], 'minecraft_status_not_ready')

    def test_restart_during_ping_invalidates_positive_observation(self):
        after = {**self.before, 'java_pid': 35792}
        self.assertEqual(self.probe(after=after)['reason'], 'process_changed_during_probe')

    def test_stale_boot_log_is_not_attested(self):
        self.assertEqual(self.probe(before={'status': 'boot_unverified'})['reason'],
                         'current_boot_witness_missing')

    def test_wrong_or_ambiguous_server_port_fails_closed(self):
        self.assertEqual(readiness.attest_live_serverpack_readiness(
            self.runtime, **{**self.args, 'game_port': 25598})['reason'],
            'port_not_bound_to_runtime')
        (self.runtime / 'server.properties').write_text('server-port=25597\nserver-port=25597\n')
        self.assertEqual(readiness.attest_live_serverpack_readiness(
            self.runtime, **self.args)['reason'], 'port_not_bound_to_runtime')

    def test_non_authoritative_revision_or_manifest_fails_closed(self):
        for extra in ({'bundle_revision': 0}, {'bundle_revision': True},
                      {'manifest_sha256': 'bad'}, {'game_port': True}):
            with self.subTest(extra=extra):
                result = readiness.attest_live_serverpack_readiness(
                    self.runtime, **{**self.args, **extra})
                self.assertEqual(result['status'], 'not_attested')


if __name__ == '__main__':
    unittest.main()
