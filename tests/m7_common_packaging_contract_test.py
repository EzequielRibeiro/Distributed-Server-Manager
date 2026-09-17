#!/usr/bin/env python3

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class M7CommonPackagingContractTest(unittest.TestCase):

    def test_linux_package_includes_all_common_python_modules(self):
        text = (
            ROOT / "release/build_agent_package.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'ls-tree -r --name-only "${REF}" -- agents/common',
            text,
        )
        self.assertIn(
            '"agent/common/${relative}"',
            text,
        )

    def test_windows_package_includes_common_tree(self):
        text = (
            ROOT / "release/build_windows_agent_package.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            '_tree_sources(ref,"agents/common","agent/common",(".py",))',
            text,
        )

    def test_linux_installer_installs_all_common_modules(self):
        text = (
            ROOT / "agents/linux/installer/install-agent.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'find "${PACKAGE_DIR}/agent/common"',
            text,
        )
        self.assertIn(
            '"${INSTALL_ROOT}/common/${file}"',
            text,
        )

    def test_windows_installer_installs_all_common_modules(self):
        text = (
            ROOT / "agents/windows/installer/install-agent.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn(
            r'agent\common\*.py',
            text,
        )

    def test_native_maintenance_supports_source_and_installed_layouts(self):
        for relative in (
            "agents/linux/runtime/native_maintenance.py",
            "agents/windows/runtime/native_maintenance.py",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")

            self.assertIn(
                '_HERE.parents[2] / "common"',
                text,
            )
            self.assertIn(
                '_HERE.parents[1] / "common"',
                text,
            )


if __name__ == "__main__":
    unittest.main()
