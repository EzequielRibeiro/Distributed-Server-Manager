"""Fail-fast and dry policy contract for the local Server Pack test gate."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
FILE=ROOT/'scripts/minecraft_serverpack_release_gate.py'
spec=importlib.util.spec_from_file_location('pr1013_serverpack_release_gate',FILE)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReleaseGateTest(unittest.TestCase):
    def test_quick_is_subset_of_full_without_game_execution(self):
        quick=module.commands('quick')
        full=module.commands('full')
        self.assertEqual(quick[:3],full[:3])
        self.assertLess(len(quick[-1]),len(full[-1]))
        self.assertIn(['bash','tests/agent_package_test.sh'],full)
        self.assertNotIn(['bash','tests/agent_package_test.sh'],quick)
        self.assertIn('tests/minecraft_serverpack_finalization_subprocess_e2e_test.py',full[-1])
        self.assertIn('tests/minecraft_serverpack_remote_heartbeat_sqlite_test.py',full[-1])
        self.assertIn('tests/minecraft_serverpack_outbox_loopback_http_e2e_test.py',full[-1])
        self.assertIn('tests/minecraft_serverpack_content_convergence_test.py',full[-1])
        self.assertNotIn('tests/minecraft_serverpack_outbox_loopback_http_e2e_test.py',quick[-1])
        for command in full:
            self.assertNotIn('systemctl',command)
            self.assertNotIn('docker',command)
        with self.assertRaises(ValueError):
            module.commands('production')

    def test_failure_stops_before_running_python_tests(self):
        class Failure:
            returncode=3
        with patch.object(module.subprocess,'run',return_value=Failure()) as call:
            result=module.run('quick')
        self.assertEqual(call.call_count,1)
        self.assertEqual(result['status'],'tests_failed')
        self.assertFalse(result['release_authorized'])

    @staticmethod
    def _mock_run_with_junit(xml: str | None):
        class Success:
            returncode=0
        def runner(command, **_kwargs):
            for part in command:
                if str(part).startswith('--junitxml='):
                    if xml is not None:
                        Path(str(part).split('=',1)[1]).write_text(xml,encoding='utf-8')
            return Success()
        return runner

    def test_success_never_claims_release_authorization(self):
        xml='<testsuites><testsuite tests="2"><testcase classname="test.api" name="one"/><testcase classname="test.api" name="two"/></testsuite></testsuites>'
        with patch.object(module.subprocess,'run',side_effect=self._mock_run_with_junit(xml)) as call:
            result=module.run('full')
        self.assertEqual(call.call_count,len(module.commands('full')))
        self.assertEqual(result['status'],'tests_passed')
        self.assertEqual(result['coverage']['status'],'complete')
        self.assertEqual(result['coverage']['passed'],2)
        self.assertTrue(result['environment_test_coverage_complete'])
        self.assertFalse(result['restored_private_world_boot_verified'])
        self.assertFalse(result['backup_14_day_capacity_verified'])
        self.assertFalse(result['release_authorized'])

    def test_skips_are_reported_and_cannot_be_claimed_as_full_coverage(self):
        xml=(
            '<testsuites><testsuite tests="2" skipped="1">'
            '<testcase classname="tests.e2e" name="boot">'
            '<skipped message="requires explicit disposable CI opt-in"/>'
            '</testcase><testcase classname="tests.unit" name="atomic"/></testsuite></testsuites>'
        )
        with patch.object(module.subprocess,'run',side_effect=self._mock_run_with_junit(xml)):
            result=module.run('full')
        self.assertEqual(result['status'],'tests_passed')
        self.assertEqual(result['coverage']['status'],'partial')
        self.assertEqual(result['coverage']['skipped'],1)
        self.assertEqual(result['coverage']['passed'],1)
        self.assertIn('boot',result['coverage']['skipped_cases'][0]['test'])
        self.assertFalse(result['environment_test_coverage_complete'])
        self.assertFalse(result['release_authorized'])

    def test_missing_or_malformed_pytest_report_fails_closed(self):
        for xml in (None,'<not-junit/>','<testsuite/>','<testsuites><'):
            with self.subTest(xml=xml):
                with patch.object(module.subprocess,'run',side_effect=self._mock_run_with_junit(xml)):
                    result=module.run('quick')
                self.assertEqual(result['status'],'tests_failed')
                self.assertEqual(result['coverage']['status'],'unavailable')
                self.assertFalse(result['environment_test_coverage_complete'])
                self.assertFalse(result['release_authorized'])

    def test_junit_errors_cannot_be_hidden_by_green_pytest_exit(self):
        xml='<testsuite><testcase classname="tests.unit" name="broken"><failure message="f"/></testcase></testsuite>'
        with patch.object(module.subprocess,'run',side_effect=self._mock_run_with_junit(xml)):
            result=module.run('quick')
        self.assertEqual(result['status'],'tests_failed')
        self.assertEqual(result['coverage']['failed'],1)



if __name__=='__main__':unittest.main()
