import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "agents" / "windows" / "service" / "run-agent.ps1"


class WindowsAgentLauncherContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = LAUNCHER.read_text(encoding="utf-8")

    def test_launcher_setup_remains_strict(self):
        self.assertIn("$ErrorActionPreference = 'Stop'", self.text)

    def test_native_python_runtime_uses_powershell_redirection(self):
        self.assertIn("& $PythonExe $scriptToRun *>> $logPath", self.text)
        self.assertNotIn("$env:ComSpec /d /s /c", self.text)

    def test_native_python_runtime_uses_continue(self):
        child = self.text.index("& $PythonExe $scriptToRun *>> $logPath")
        before = self.text[:child]
        self.assertIn("$ErrorActionPreference = 'Continue'", before)

    def test_exit_code_is_captured_before_preference_restore(self):
        child = self.text.index("& $PythonExe $scriptToRun *>> $logPath")
        capture = self.text.index("$pythonExitCode = $LASTEXITCODE", child)
        restore = self.text.index(
            "$ErrorActionPreference = $previousErrorActionPreference", capture
        )
        self.assertLess(capture, restore)

    def test_launcher_restores_error_action_preference(self):
        self.assertIn(
            "$previousErrorActionPreference = $ErrorActionPreference", self.text
        )
        self.assertIn(
            "$ErrorActionPreference = $previousErrorActionPreference", self.text
        )

    def test_launcher_exits_with_captured_python_code(self):
        self.assertIn("exit $pythonExitCode", self.text)
        self.assertNotIn("exit $LASTEXITCODE", self.text)

    def test_missing_native_exit_code_defaults_to_failure(self):
        self.assertIn("if ($null -eq $pythonExitCode)", self.text)
        self.assertIn("$pythonExitCode = 1", self.text)


if __name__ == "__main__":
    unittest.main()
