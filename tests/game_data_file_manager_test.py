from __future__ import annotations

import base64
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "agents" / "linux" / "runtime" / "game_data_files.py"
spec = importlib.util.spec_from_file_location("game_data_files", MODULE)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
execute = module.execute_file_operation


class GameDataFileManagerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / "cfg").mkdir()
        (self.root / "cfg" / "server.cfg").write_text("name=demo\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_list_read_write_create_rename_delete(self):
        listing = execute(self.root, {"action": "list", "path": "cfg"})
        self.assertEqual(listing["entries"][0]["name"], "server.cfg")
        read = execute(self.root, {"action": "read", "path": "cfg/server.cfg"})
        self.assertIn("name=demo", read["content"])
        execute(self.root, {"action": "write", "path": "cfg/server.cfg", "content": "name=changed\n"})
        self.assertEqual((self.root / "cfg/server.cfg").read_text(), "name=changed\n")
        execute(self.root, {"action": "create", "path": "cfg/new.txt", "content": "new"})
        execute(self.root, {"action": "rename", "path": "cfg/new.txt", "destination": "cfg/renamed.txt"})
        self.assertTrue((self.root / "cfg/renamed.txt").is_file())
        execute(self.root, {"action": "delete", "path": "cfg/renamed.txt"})
        self.assertFalse((self.root / "cfg/renamed.txt").exists())

    def test_upload_and_mkdir(self):
        execute(self.root, {"action": "mkdir", "path": "mods"})
        execute(self.root, {"action": "upload", "path": "mods/blob.bin", "content_base64": base64.b64encode(b"abc").decode()})
        self.assertEqual((self.root / "mods/blob.bin").read_bytes(), b"abc")

    def test_rejects_traversal_and_absolute_paths(self):
        for bad in ("../secret", "/etc/passwd", "cfg/../../secret"):
            with self.assertRaises(ValueError):
                execute(self.root, {"action": "read", "path": bad})

    def test_rejects_symlink_escape(self):
        outside = self.root.parent / "outside-capivara-test"
        outside.mkdir(exist_ok=True)
        try:
            (outside / "secret.txt").write_text("secret", encoding="utf-8")
            (self.root / "escape").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                execute(self.root, {"action": "read", "path": "escape/secret.txt"})
        finally:
            if (self.root / "escape").is_symlink():
                (self.root / "escape").unlink()
            try:
                (outside / "secret.txt").unlink()
                outside.rmdir()
            except OSError:
                pass

    def test_nonempty_directory_requires_recursive_delete(self):
        with self.assertRaises(ValueError):
            execute(self.root, {"action": "delete", "path": "cfg"})


if __name__ == "__main__":
    unittest.main()
