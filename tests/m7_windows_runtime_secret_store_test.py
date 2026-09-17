#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_RUNTIME = ROOT / "agents" / "windows" / "runtime"

if str(WINDOWS_RUNTIME) not in sys.path:
    sys.path.insert(0, str(WINDOWS_RUNTIME))

import runtime_secret_store


class WindowsRuntimeSecretStoreTest(unittest.TestCase):

    def test_secret_is_instance_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get(
                "CAPIVARA_RUNTIME_SECRET_ROOT"
            )

            os.environ[
                "CAPIVARA_RUNTIME_SECRET_ROOT"
            ] = tmp

            try:
                result = runtime_secret_store.put_secret(
                    "instance/mc-001/minecraft_rcon_password",
                    "secret-value",
                    expected_instance_id="mc-001",
                )

                self.assertTrue(result["present"])

                path = runtime_secret_store.credential_path(
                    result["ref"],
                    expected_instance_id="mc-001",
                )

                self.assertEqual(
                    path.read_text(encoding="utf-8"),
                    "secret-value",
                )

                with self.assertRaises(
                    runtime_secret_store.RuntimeSecretError
                ):
                    runtime_secret_store.credential_path(
                        result["ref"],
                        expected_instance_id="mc-002",
                    )
            finally:
                if old is None:
                    os.environ.pop(
                        "CAPIVARA_RUNTIME_SECRET_ROOT",
                        None,
                    )
                else:
                    os.environ[
                        "CAPIVARA_RUNTIME_SECRET_ROOT"
                    ] = old

    def test_windows_acl_is_system_and_administrators_only(self):
        fake = type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "",
                "stderr": "",
            },
        )()

        with (
            patch.object(
                runtime_secret_store.os,
                "name",
                "nt",
            ),
            patch.object(
                runtime_secret_store.subprocess,
                "run",
                return_value=fake,
            ) as run,
        ):
            runtime_secret_store._secure_acl(
                Path(r"C:\ProgramData\CapivaraAgent\runtime-secrets\x")
            )

        commands = [
            call.args[0]
            for call in run.call_args_list
        ]

        self.assertTrue(
            any("/inheritance:r" in command for command in commands)
        )

        grants = [
            command
            for command in commands
            if "/grant:r" in command
        ]

        self.assertEqual(len(grants), 1)
        self.assertIn("SYSTEM:(F)", grants[0])
        self.assertIn("*S-1-5-32-544:(F)", grants[0])


if __name__ == "__main__":
    unittest.main()
