#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "agents/linux/installer/install-agent.sh"


class AgentInstallerAccountTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.installer = INSTALLER.read_text(encoding="utf-8")
        match = re.search(
            r"ensure_agent_account\(\)\{\n(?P<body>.*?)\n\}\n",
            cls.installer,
            flags=re.DOTALL,
        )
        if match is None:
            raise AssertionError("ensure_agent_account() not found in install-agent.sh")
        cls.function_source = "ensure_agent_account(){\n" + match.group("body") + "\n}\n"

    def run_account_scenario(self, *, group_exists: bool, user_exists: bool) -> list[str]:
        script = f"""\
set -Eeuo pipefail
AGENT_USER=capivara-agent
AGENT_GROUP=capivara-agent
STATE_DIR=/var/lib/capivara-agent
GROUP_EXISTS={int(group_exists)}
USER_EXISTS={int(user_exists)}
EVENTS=()
getent() {{
  [[ "$1" == "group" && "$2" == "$AGENT_GROUP" && "$GROUP_EXISTS" == "1" ]]
}}
groupadd() {{
  EVENTS+=("groupadd:$*")
  GROUP_EXISTS=1
}}
id() {{
  [[ "$1" == "$AGENT_USER" && "$USER_EXISTS" == "1" ]]
}}
useradd() {{
  EVENTS+=("useradd:$*")
  USER_EXISTS=1
}}
{self.function_source}
ensure_agent_account
printf '%s\n' "${{EVENTS[@]}}"
"""
        completed = subprocess.run(
            ["bash"],
            input=script,
            text=True,
            capture_output=True,
            check=True,
        )
        return [line for line in completed.stdout.splitlines() if line]

    def test_clean_install_creates_group_before_user_with_explicit_gid(self):
        events = self.run_account_scenario(group_exists=False, user_exists=False)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0], "groupadd:--system capivara-agent")
        self.assertEqual(
            events[1],
            "useradd:--system --gid capivara-agent --home /var/lib/capivara-agent "
            "--create-home --shell /usr/sbin/nologin capivara-agent",
        )

    def test_partial_install_reuses_existing_group_and_creates_user(self):
        events = self.run_account_scenario(group_exists=True, user_exists=False)
        self.assertEqual(
            events,
            [
                "useradd:--system --gid capivara-agent --home /var/lib/capivara-agent "
                "--create-home --shell /usr/sbin/nologin capivara-agent"
            ],
        )

    def test_rerun_reuses_existing_group_and_user(self):
        events = self.run_account_scenario(group_exists=True, user_exists=True)
        self.assertEqual(events, [])

    def test_installer_invokes_account_reconciliation_and_checks_dependencies(self):
        self.assertIn(
            "for cmd in python3 install systemctl getent groupadd useradd id; do",
            self.installer,
        )
        self.assertIn("ensure_agent_account\ninstall -d", self.installer)
        self.assertNotIn(
            "id capivara-agent >/dev/null 2>&1 || useradd",
            self.installer,
        )


if __name__ == "__main__":
    unittest.main()
