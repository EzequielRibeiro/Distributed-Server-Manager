#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from queue_observability import collect_queue_observability


class AgentQueueObservabilityTest(unittest.TestCase):
    def test_reports_depth_age_retry_and_stale_without_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "instance-results" / "result-1.json"
            target.parent.mkdir(parents=True)
            target.write_text(
                json.dumps({
                    "status": "retrying",
                    "retry_count": 4,
                    "credential_secret": "must-not-leak",
                    "error": "contains internal sensitive detail",
                }),
                encoding="utf-8",
            )
            # Use the real file mtime as the deterministic reference instead of
            # monkey-patching pathlib.Path.stat. Patching Path.stat globally also
            # affects pathlib's directory traversal internals on Python 3.12 and
            # can make glob() receive a non-integer st_mode.
            mtime = target.stat().st_mtime
            report = collect_queue_observability(
                root,
                now=mtime + 400,
                stale_after_seconds=300,
            )

            queue = report["instance_results"]
            self.assertEqual(queue["depth"], 1)
            self.assertEqual(queue["oldest_age_seconds"], 400)
            self.assertEqual(queue["max_retry_count"], 4)
            self.assertTrue(queue["stale"])
            self.assertEqual(queue["statuses"], {"retrying": 1})
            serialized = json.dumps(report)
            self.assertNotIn("must-not-leak", serialized)
            self.assertNotIn("sensitive detail", serialized)

    def test_empty_queues_are_not_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            report = collect_queue_observability(Path(temp), now=1000, stale_after_seconds=30)
        self.assertTrue(report)
        for queue in report.values():
            self.assertEqual(queue["depth"], 0)
            self.assertEqual(queue["oldest_age_seconds"], 0)
            self.assertFalse(queue["stale"])

    def test_unknown_status_is_not_exposed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "backup-results" / "result.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({"status": "secret-status-value"}), encoding="utf-8")
            report = collect_queue_observability(root, now=target.stat().st_mtime, stale_after_seconds=30)
        self.assertEqual(report["backup_results"]["statuses"], {})


if __name__ == "__main__":
    unittest.main()
