"""Root-only local CLI recovery dispatch, without live instance mutations."""
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"agents/linux/runtime"))
import local_cli


class ServerPackRecoveryCLITest(unittest.TestCase):
    def setUp(self):
        self.spec={"instance_id":"fixture01","agent_id":"agent-test",
                   "game_id":"minecraft","environment_id":"minecraft.java.neoforge",
                   "instance_state_root":"/tmp/fixture01"}
        self.config={"agent_id":"agent-test"}
        self.cfg=patch.object(local_cli,"_read_config",return_value=self.config)
        self.owner=patch("instance_runtime._owned",return_value=self.spec)
        self.rec=patch("minecraft_serverpack_migration_recovery.recover_minecraft_serverpack_migration",
                       return_value={"status":"recovered","filesystem":{"pre_swap_only":True}})
        self.cfg.start();self.owner_mock=self.owner.start();self.rec_mock=self.rec.start()
        self.addCleanup(self.cfg.stop);self.addCleanup(self.owner.stop);self.addCleanup(self.rec.stop)

    def run_cli(self,args,uid):
        with patch.object(local_cli.os,"geteuid",return_value=uid):
            with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                return local_cli.main(["instance","recover-serverpack","fixture01",*args])

    def test_nonroot_denied(self):
        self.assertEqual(self.run_cli(["--confirm","fixture01"],1000),3)
        self.rec_mock.assert_not_called()

    def test_confirmation_must_match(self):
        self.assertEqual(self.run_cli(["--confirm","other"],0),2)
        self.rec_mock.assert_not_called()

    def test_root_uses_registered_instance_only(self):
        self.assertEqual(self.run_cli(["--confirm","fixture01","--json"],0),0)
        self.rec_mock.assert_called_once_with(self.config,"fixture01",
                                               instance_state_root=Path("/tmp/fixture01"))

    def test_wrong_game_denied(self):
        self.spec["game_id"]="dayz"
        self.assertEqual(self.run_cli(["--confirm","fixture01"],0),2)
        self.rec_mock.assert_not_called()

    def test_relative_root_denied(self):
        self.spec["instance_state_root"]="relative"
        self.assertEqual(self.run_cli(["--confirm","fixture01"],0),2)
        self.rec_mock.assert_not_called()

if __name__=="__main__":unittest.main()
