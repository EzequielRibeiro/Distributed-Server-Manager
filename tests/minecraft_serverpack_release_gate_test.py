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

    def test_success_never_claims_release_authorization(self):
        class Success:
            returncode=0
        with patch.object(module.subprocess,'run',return_value=Success()) as call:
            result=module.run('full')
        self.assertEqual(call.call_count,len(module.commands('full')))
        self.assertEqual(result['status'],'tests_passed')
        self.assertFalse(result['release_authorized'])


if __name__=='__main__':unittest.main()