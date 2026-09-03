#!/usr/bin/env python3
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LINUX = ROOT / "agents" / "linux" / "installer" / "install-agent.sh"
WINDOWS = ROOT / "agents" / "windows" / "installer" / "install-agent.ps1"


class AgentInstallerPairingTokenValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.linux = LINUX.read_text(encoding="utf-8")
        cls.windows = WINDOWS.read_text(encoding="utf-8")

    def test_linux_rejects_noncanonical_pairing_token(self):
        self.assertIn(
            '[[ "${PAIRING_TOKEN}" =~ ^cap_pair_[A-Za-z0-9_-]{32,}$ ]]',
            self.linux,
        )
        self.assertIn("pairing token inválido", self.linux)

    def test_linux_trims_transport_whitespace_before_validation(self):
        self.assertIn("PAIRING_TOKEN=\"${PAIRING_TOKEN//$'\\r'/}\"", self.linux)
        self.assertIn("PAIRING_TOKEN=\"${PAIRING_TOKEN//$'\\n'/}\"", self.linux)

    def test_windows_rejects_noncanonical_pairing_token(self):
        self.assertIn(
            "if ($PairingToken -notmatch '^cap_pair_[A-Za-z0-9_-]{32,}$')",
            self.windows,
        )
        self.assertIn("PairingToken inválido", self.windows)

    def test_windows_trims_pairing_token_before_validation(self):
        self.assertIn("$PairingToken = $PairingToken.Trim()", self.windows)


if __name__ == "__main__":
    unittest.main()
