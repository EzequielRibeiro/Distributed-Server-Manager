"""#928: synthetic heartbeat + SHA pinned supervisor evidence before /tmp updater.

No production credentials, Controller/Agent process or systemd operations.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
import tempfile
import unittest

from update_game_uptime_isolated_compose_test import (
    IsolatedCompositionTests, UNIT, DAYZ, load,
)

ROOT = Path(__file__).resolve().parents[1]
observed = load(
    "update-manager/game-uptime-evidence-rehearsal.py",
    "dsm928_observed_evidence_tests",
)
stage = load(
    "update-manager/game-uptime-supervisor-stage.py",
    "dsm928_evidence_stage_tests",
)


class ObservedEvidenceFixtureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = IsolatedCompositionTests(methodName="test_success_composes_real_updater_functions_and_fake_reload")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        f.set_fixture_supervisors(installed="old", candidate="new")
        self.versions = f.root / "immutable-versions"
        self.versions.mkdir(mode=0o700)
        source = f.root / "observed-supervisor.py"
        source.write_text("print('fixture pinned')\n")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        self.pin = stage.stage_supervisor(source, self.versions, expected_sha256=digest)
        self.digest = digest
        self.minecraft_unit = "capivara-instance-dsm928-minecraft-fixture.service"
        self.probe = observed._AGENT.build_probe("fixture-agent")
        self.offer = observed._CONTROLLER.assess_authenticated_probe(
            self.probe, authenticated_agent_id="fixture-agent",
        )
        self.override_pinned = None

    def pin_observation(self, unit):
        self.assertEqual(unit, self.minecraft_unit)
        f = self.fixture
        values = {
            "main_pid": f.states[UNIT]["pid"],
            "start_stamp": f.states[UNIT]["started"],
            "exec": (
                "path=/usr/bin/python3 ; argv[]=/usr/bin/python3 "
                + self.pin["path"]
                + " --socket /tmp/fixture.sock -- /usr/bin/sleep 180 ;"
            ),
            "fragment": "/etc/systemd/system/" + unit,
        }
        if self.override_pinned:
            values.update(self.override_pinned)
        return values

    def execute(self, **overrides):
        f = self.fixture
        values = {
            "heartbeat_probe": self.probe,
            "heartbeat_offer": self.offer,
            "authenticated_agent_id": "fixture-agent",
            "minecraft_unit": UNIT,
            "observed_minecraft_unit": self.minecraft_unit,
            "versions_dir": self.versions,
            "supervisor_sha256": self.digest,
            "inspect_pinned": self.pin_observation,
            "inspect": f.inspect,
            "prepare_files": lambda: f.updater("prepare"),
            "apply_files": lambda: f.updater("apply"),
            "rollback_files": lambda: f.updater("rollback"),
            "apply_unit": f.swap_unit,
            "rollback_unit": f.restore_unit,
            "verify": f.verify,
        }
        values.update(overrides)
        return observed.execute_observed_fixture(f.root, [UNIT, DAYZ], **values)

    def assert_no_mutation(self):
        f = self.fixture
        self.assertFalse((f.root / "backups").exists())
        self.assertFalse((f.root / "dsm928-composite-journal").exists())
        self.assertEqual(f.installed.read_bytes(), f.old)
        self.assertEqual((f.root / "installed/version").read_text(),
                         "2.0.998-fixture")

    def test_matching_observation_composes_transaction_but_never_authorizes(self):
        result = self.execute()
        self.assertEqual(result["status"], "verified")
        self.assertTrue(result["heartbeat_envelope_compatible"])
        self.assertTrue(result["pinned_supervisor_observed"])
        self.assertFalse(result["live_no_drain_authorized"])
        self.assertEqual(
            result["evidence_source"],
            "injected_authenticated_heartbeat_and_mock_systemd",
        )
        self.assertEqual(self.fixture.states[UNIT]["pid"], 22001)
        self.assertEqual(self.fixture.states[DAYZ]["pid"], 22002)
        self.assertEqual((self.fixture.root / "installed/version").read_text(),
                         "2.0.999-fixture")
        self.fixture.restore_unit()
        self.fixture.updater("rollback")

    def test_replayed_heartbeat_offer_blocked_before_any_backup(self):
        another = observed._AGENT.build_probe("fixture-agent")
        with self.assertRaisesRegex(observed.EvidenceSafetyError,
                                    "heartbeat fixture evidence invalid"):
            self.execute(heartbeat_probe=another)
        self.assert_no_mutation()

    def test_spoofed_authenticated_identity_blocked(self):
        with self.assertRaisesRegex(observed.EvidenceSafetyError,
                                    "heartbeat fixture evidence invalid"):
            self.execute(authenticated_agent_id="fixture-other-agent")
        self.assert_no_mutation()

    def test_extra_command_or_authorization_in_offer_blocked(self):
        for changes in (
            {"game_commands": [{"action": "restart"}]},
            {"live_no_drain_authorized": True},
            {"status": "blocked"},
        ):
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(observed.EvidenceSafetyError, "heartbeat"):
                    self.execute(heartbeat_offer={**self.offer, **changes})
                self.assert_no_mutation()

    def test_real_service_name_and_external_versions_path_never_reach_callbacks(self):
        scenarios = (
            {"observed_minecraft_unit": "capivara-instance-cli-000001-minecraft-005.service"},
            {"versions_dir": Path("/opt/dsm/runtime")},
            {"authenticated_agent_id": "real-agent"},
        )
        for overrides in scenarios:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(observed.EvidenceSafetyError,
                                            "non-disposable|private disposable"):
                    self.execute(**overrides)
                self.assert_no_mutation()

    def test_mismatched_pid_blocks_before_backup(self):
        self.override_pinned = {"main_pid": 99999}
        with self.assertRaisesRegex(observed.EvidenceSafetyError, "process identity differs"):
            self.execute()
        self.assert_no_mutation()

    def test_unpinned_systemd_command_blocks_before_backup(self):
        self.override_pinned = {
            "exec": "path=/usr/bin/python3 ; argv[]=/usr/bin/python3 "
                    "/opt/dsm/agents/linux/runtime/console_supervisor.py "
                    "--socket /tmp/test.sock -- /usr/bin/sleep 180 ;"
        }
        with self.assertRaisesRegex(observed.EvidenceSafetyError, "pinned supervisor"):
            self.execute()
        self.assert_no_mutation()

    def test_corrupt_pinned_sha_blocks_before_backup(self):
        path = Path(self.pin["path"])
        path.chmod(0o644)
        path.write_text("changed")
        with self.assertRaisesRegex(observed.EvidenceSafetyError, "pinned supervisor"):
            self.execute()
        self.assert_no_mutation()

    def test_process_identity_change_during_apply_never_succeeds(self):
        f = self.fixture

        def apply_with_pid_change():
            f.swap_unit()
            f.states[UNIT]["pid"] += 1

        with self.assertRaisesRegex(
            observed._COMPOSE._TRANSACTION.TransactionSafetyError,
            "rollback completed|manual review|required|changed",
        ):
            self.execute(apply_unit=apply_with_pid_change)
        self.assertFalse(
            (f.root / "dsm928-composite-journal/game-uptime-transaction.json").is_symlink()
        )
        self.assertNotEqual(
            (f.root / "dsm928-composite-journal/game-uptime-transaction.json").read_text().find('"status"'),
            -1,
        )


if __name__ == "__main__":
    unittest.main()
