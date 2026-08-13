#!/usr/bin/env python3
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT / "database"
USERS_PATH = DATABASE_DIR / "users.py"
sys.path.insert(0, str(DATABASE_DIR))
SPEC = importlib.util.spec_from_file_location("database_users", USERS_PATH)
USERS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = USERS
SPEC.loader.exec_module(USERS)


class UsersCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *arguments, passwords):
        stdout = io.StringIO()
        stderr = io.StringIO()
        argv = [str(USERS_PATH), "--root", str(self.root), *arguments]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(USERS.getpass, "getpass", side_effect=passwords),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = USERS.main()
        return result, stdout.getvalue(), stderr.getvalue()

    def test_short_password_shows_requirements_without_traceback(self):
        result, stdout, stderr = self.run_cli(
            "create", "admin", "--role", "admin", passwords=["short", "short"]
        )

        self.assertEqual(result, 2)
        self.assertIn("Requisitos da senha: no mínimo 8 caracteres.", stdout)
        self.assertEqual(stderr, "Erro: a senha deve ter no mínimo 8 caracteres.\n")
        self.assertNotIn("Traceback", stdout + stderr)

    def test_confirmation_mismatch_is_a_friendly_error(self):
        result, stdout, stderr = self.run_cli(
            "create", "admin", "--role", "admin",
            passwords=["password-one", "password-two"],
        )

        self.assertEqual(result, 2)
        self.assertIn("Requisitos da senha: no mínimo 8 caracteres.", stdout)
        self.assertEqual(stderr, "Erro: a confirmação da senha não corresponde.\n")
        self.assertNotIn("Traceback", stdout + stderr)

    def test_customer_without_scope_is_rejected_before_password_prompt(self):
        result = subprocess.run(
            ["bash", str(ROOT / "core" / "user_manager.sh"), "add", "aurora", "customer"],
            env={"DSM_ROOT": str(ROOT)},
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("papel customer exigem o identificador do scope", result.stderr)
        self.assertIn("dsm user add <usuario> customer <scope>", result.stderr)
        self.assertNotIn("Password:", result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
