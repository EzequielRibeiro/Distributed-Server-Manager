#!/usr/bin/env python3

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_LIVE = ROOT / "dashboard" / "web" / "customer-instance-runtime-live.js"


class CustomerConsoleRefreshControlsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = RUNTIME_LIVE.read_text(encoding="utf-8")

    def test_console_controls_start_hidden_until_capability_is_known(self) -> None:
        self.assertIn(
            'initialConsoleWrap.hidden=true',
            self.source,
        )

    def test_runtime_capability_and_permission_are_authoritative(self) -> None:
        self.assertIn(
            'setConsoleInteractive(!!overview?.console?.supported&&p.has("console.execute"))',
            self.source,
        )
        self.assertIn('consoleWrap.hidden=!interactive', self.source)
        self.assertIn(
            'consoleWrap.classList.toggle("hidden",!interactive)',
            self.source,
        )

    def test_log_refresh_does_not_change_command_control_visibility(self) -> None:
        refresh_console = self.source.split(
            "async function refreshConsole(){", 1
        )[1].split("\nif(!iid)return;", 1)[0]
        self.assertNotIn("console-command-wrap", refresh_console)
        self.assertNotIn("setConsoleInteractive", refresh_console)


if __name__ == "__main__":
    unittest.main()
