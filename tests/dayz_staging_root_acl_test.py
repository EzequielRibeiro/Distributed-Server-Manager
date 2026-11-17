"""DayZ staging-root ACL regression tests."""
import sys
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"agents/linux/runtime"))
from server_update_agent import _ensure_dayz_staging_root_access, ServerUpdateError

class StagingAclTest(unittest.TestCase):
    def test_dayz_root_acl_not_recursive(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"serverfiles";root.mkdir()
            child=root/"dta";child.mkdir()
            _ensure_dayz_staging_root_access(root,"dayz")
            acl=subprocess.check_output(["getfacl","-cp",str(root)],text=True)
            child_acl=subprocess.check_output(["getfacl","-cp",str(child)],text=True)
            self.assertIn("user:capivara-instance:rwx",acl)
            self.assertNotIn("user:capivara-instance:rwx",child_acl)
    def test_other_games_unchanged(self):
        with patch("server_update_agent.subprocess.run") as run:
            _ensure_dayz_staging_root_access(Path("/missing"),"minecraft")
            run.assert_not_called()
    def test_failure_rejects_activation(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("server_update_agent.subprocess.run",side_effect=OSError("no ACL")):
                with self.assertRaises(ServerUpdateError):
                    _ensure_dayz_staging_root_access(Path(td),"dayz")
    def test_symlink_target_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            a=Path(td)/"a";a.mkdir();link=Path(td)/"link";link.symlink_to(a)
            with self.assertRaises(ServerUpdateError):
                _ensure_dayz_staging_root_access(link,"dayz")
if __name__ == "__main__":
    unittest.main()
