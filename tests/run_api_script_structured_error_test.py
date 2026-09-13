#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "dashboard", ROOT / "database", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import server


class RunApiScriptStructuredErrorTest(unittest.TestCase):
    def setUp(self):
        self.original_api_dir = server.API_DIR
        self.temp = tempfile.TemporaryDirectory()
        server.API_DIR = Path(self.temp.name)

    def tearDown(self):
        server.API_DIR = self.original_api_dir
        self.temp.cleanup()

    def _script(self, name: str, body: str) -> None:
        (server.API_DIR / name).write_text(body, encoding="utf-8")

    def test_nonzero_json_stderr_preserves_structured_error(self):
        self._script(
            "conflict.sh",
            "#!/usr/bin/env bash\n"
            "printf '%s\n' '{\"error\":\"lifecycle_operation_in_progress\",\"command_id\":\"instance-cmd-test\",\"active_action\":\"restart\"}' >&2\n"
            "exit 3\n",
        )
        success, result = server.run_api_script("conflict.sh")
        self.assertFalse(success)
        self.assertEqual(result["error"], "lifecycle_operation_in_progress")
        self.assertEqual(result["command_id"], "instance-cmd-test")
        self.assertEqual(result["active_action"], "restart")
        self.assertEqual(result["exit_code"], 3)

    def test_nonzero_plain_stderr_keeps_legacy_wrapper(self):
        self._script("plain.sh", "#!/usr/bin/env bash\nprintf 'plain failure\n' >&2\nexit 7\n")
        success, result = server.run_api_script("plain.sh")
        self.assertFalse(success)
        self.assertEqual(result, {"error": "plain failure", "exit_code": 7})


if __name__ == "__main__":
    unittest.main()
