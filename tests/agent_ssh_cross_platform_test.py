#!/usr/bin/env python3
from __future__ import annotations
import os,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT,ROOT/"core",ROOT/"database"):
    if str(path) not in sys.path:sys.path.insert(0,str(path))
from agent_connection_test_cli import build_parser as build_test_parser
from agent_deploy_cli import build_parser as build_deploy_parser
from agent_ssh_deploy import AgentDeployError,SSHDeployOptions,SSHResult,_powershell_encoded_command,_windows_bootstrap_stdin,bootstrap_windows_agent_ssh,build_ssh_argv,preflight_windows_ssh,validate_password_file

class AgentSSHCrossPlatformTest(unittest.TestCase):
    def test_deploy_cli_supports_windows_and_password_file(self):
        args=build_deploy_parser().parse_args(["win-node01","--platform","windows","--ssh-user","Administrator","--password-file","/tmp/node.secret"])
        self.assertEqual(args.platform,"windows");self.assertEqual(args.password_file,"/tmp/node.secret")

    def test_connection_test_cli_is_explicitly_non_installing(self):
        args=build_test_parser().parse_args(["node01","--platform","linux","--ssh-user","root"])
        self.assertEqual(args.platform,"linux")

    def test_password_file_must_be_private_and_secret_never_enters_argv(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"node.secret";path.write_text("SuperSecret!\n",encoding="utf-8");os.chmod(path,0o600)
            self.assertEqual(validate_password_file(str(path)),path.resolve())
            argv=build_ssh_argv(SSHDeployOptions(host="node01",ssh_user="root",password_file=str(path)),"true")
            self.assertEqual(argv[:2],["sshpass","-f"]);self.assertIn(str(path.resolve()),argv);self.assertNotIn("SuperSecret!"," ".join(argv))
            os.chmod(path,0o644)
            with self.assertRaises(AgentDeployError):validate_password_file(str(path))

    def test_windows_preflight_requires_administrator_marker(self):
        observed={}
        def runner(argv,stdin_text,timeout):
            observed["argv"]=list(argv);return SSHResult(0,"CAPIVARA_WINDOWS_PREFLIGHT_OK\nAMD64\n","")
        result=preflight_windows_ssh(SSHDeployOptions(host="win-node01",ssh_user="Administrator"),runner=runner)
        self.assertEqual(result["platform"],"windows");self.assertEqual(result["architecture"],"AMD64");self.assertIn("powershell.exe",observed["argv"][-1])

    def test_windows_pairing_token_travels_on_stdin_only(self):
        observed={};secret="pairing-WINDOWS-SECRET"
        def runner(argv,stdin_text,timeout):
            observed["argv"]=list(argv);observed["stdin"]=stdin_text;return SSHResult(0,"","")
        bootstrap_windows_agent_ssh(SSHDeployOptions(host="win-node01",ssh_user="Administrator"),controller_url="https://controller.example",pairing_token=secret,runner=runner)
        self.assertNotIn(secret," ".join(observed["argv"]));self.assertIn(secret,observed["stdin"]);self.assertEqual(observed["argv"][-1],"powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command -")

    def test_windows_encoded_powershell_forces_utf8_output(self):
        import base64
        command=_powershell_encoded_command("Write-Output 'CAPIVARA_TEST'")
        encoded=command.rsplit(" ",1)[-1]
        script=base64.b64decode(encoded).decode("utf-16le")
        self.assertIn("System.Text.UTF8Encoding($false)",script)
        self.assertIn("[Console]::OutputEncoding = $utf8",script)
        self.assertIn("$OutputEncoding = $utf8",script)
        self.assertLess(
            script.index("[Console]::OutputEncoding = $utf8"),
            script.index("Write-Output 'CAPIVARA_TEST'"),
        )

    def test_windows_bootstrap_stdin_forces_utf8_output(self):
        script=_windows_bootstrap_stdin(
            "https://controller.example:9443",
            "cap_pair_test-token",
            "v2.0.15",
        )
        self.assertIn("System.Text.UTF8Encoding($false)",script)
        self.assertIn("[Console]::OutputEncoding = $utf8",script)
        self.assertIn("$OutputEncoding = $utf8",script)
        self.assertIn("/agent/install.ps1",script)
        self.assertIn("-ReleaseTag $payload.release_tag",script)

    def test_cap_help_exposes_new_agent_commands(self):
        cap=(ROOT/"bin/cap").read_text(encoding="utf-8")
        self.assertIn("cap agent test-connection HOST",cap);self.assertIn("cap agent secret create|delete NAME",cap);self.assertIn("--platform linux|windows",cap)

if __name__=="__main__":unittest.main()
