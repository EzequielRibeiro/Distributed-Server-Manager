#!/usr/bin/env python3
"""Fail-closed upload retention: never remove an active writer or unrelated data."""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "database"), str(ROOT / "dashboard" / "workers")]
from content_upload_retention_worker import sweep
from artifact_transfer_repository import _copy_artifact_stream


class Repository:
    def __init__(self, root, now, *, status="staging"):
        self.spool = root / "runtime" / "artifact-transfers"
        self.spool.mkdir(parents=True)
        self.dialect = SimpleNamespace(placeholder="?")
        self.item = {
            "transfer_id": "transfer-unit-1", "purpose": "content_upload",
            "direction": "controller_to_agent", "status": status,
            "filename": "pack.zip", "updated_at": (now - timedelta(hours=3)).isoformat(),
        }
        self.item["controller_path"] = str(self.spool / "transfer-unit-1" / "pack.zip")
        self.failed = []

    @staticmethod
    def _token(text, label):
        if not text or "/" in text or "\\" in text or text in {".", ".."}:
            raise ValueError(label)
        return text

    def session(self):
        repo = self
        class Context:
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def execute(self, sql):
                assert "purpose='content_upload'" in sql
                return self
            def fetchall(self): return [dict(repo.item)]
        return Context()

    def get(self, transfer_id): return dict(self.item)

    def fail_staging_upload(self, transfer_id, reason):
        self.failed.append(reason)
        self.item["status"] = "failed"
        return dict(self.item)


class UploadRetentionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime.now(timezone.utc)
        self.repo = Repository(Path(self.temp.name), self.now)
        self.directory = self.repo.spool / "transfer-unit-1"
        self.directory.mkdir()
        self.partial = self.directory / "pack.zip.part"

    def old_partial(self):
        self.partial.write_bytes(b"incomplete test bytes")
        old = (self.now - timedelta(hours=2)).timestamp()
        os.utime(self.partial, (old, old))

    def test_free_space_reserve_stops_stream_before_writing(self):
        file_path = Path(self.temp.name) / "scratch.bin"
        with file_path.open("wb") as output, \\
             patch("artifact_transfer_repository.shutil.disk_usage",
                   return_value=SimpleNamespace(free=5)):
            with self.assertRaisesRegex(OSError, "Espaço livre insuficiente"):
                _copy_artifact_stream(io.BytesIO(b"1234"), output, 4, reserve_free_bytes=4)
        self.assertEqual(file_path.stat().st_size, 0)

    def test_abandoned_closed_partial_fails_and_removes_only_partial(self):
        self.old_partial()
        unrelated = self.repo.spool / "other-ongoing-upload"
        unrelated.mkdir()
        (unrelated / "untouched.part").write_text("preserve")
        with patch("content_upload_retention_worker.shutil.which", return_value="/usr/bin/fuser"), \
             patch("content_upload_retention_worker.subprocess.run", return_value=SimpleNamespace(returncode=1)):
            result = sweep(self.repo, now=self.now)
        self.assertEqual(result["marked_failed"], 1)
        self.assertEqual(result["files_removed"], 1)
        self.assertFalse(self.partial.exists())
        self.assertEqual(self.repo.item["status"], "failed")
        self.assertTrue((unrelated / "untouched.part").exists())

    def test_open_writer_is_never_marked_failed_or_deleted(self):
        self.old_partial()
        with patch("content_upload_retention_worker.shutil.which", return_value="/usr/bin/fuser"), \
             patch("content_upload_retention_worker.subprocess.run", return_value=SimpleNamespace(returncode=0)):
            result = sweep(self.repo, now=self.now)
        self.assertEqual(result["marked_failed"], 0)
        self.assertTrue(self.partial.exists())
        self.assertEqual(self.repo.item["status"], "staging")

    def test_missing_fuser_refuses_partial_deletion(self):
        self.old_partial()
        with patch("content_upload_retention_worker.shutil.which", return_value=None):
            result = sweep(self.repo, now=self.now)
        self.assertEqual(result["marked_failed"], 0)
        self.assertTrue(self.partial.exists())

    def test_missing_partial_marks_abandoned_record(self):
        result = sweep(self.repo, now=self.now)
        self.assertEqual(result["marked_failed"], 1)
        self.assertEqual(result["files_removed"], 0)

    def test_recent_partial_is_not_touchable(self):
        self.partial.write_bytes(b"still uploading")
        result = sweep(self.repo, now=self.now)
        self.assertEqual(result["marked_failed"], 0)
        self.assertTrue(self.partial.exists())

    def test_complete_archive_is_never_removed_while_staging(self):
        (self.directory / "pack.zip").write_bytes(b"complete")
        result = sweep(self.repo, now=self.now)
        self.assertEqual(result["marked_failed"], 0)
        self.assertTrue((self.directory / "pack.zip").exists())

    def test_symlinked_quarantine_directory_is_never_followed(self):
        self.directory.rmdir()
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "pack.zip.part").write_bytes(b"preserve")
        self.directory.symlink_to(outside, target_is_directory=True)
        result = sweep(self.repo, now=self.now)
        self.assertEqual(result["marked_failed"], 0)
        self.assertTrue((outside / "pack.zip.part").exists())

    def test_failed_partial_retention_reaps_when_no_writer(self):
        self.repo.item["status"] = "failed"
        self.old_partial()
        with patch("content_upload_retention_worker.shutil.which", return_value="/usr/bin/fuser"), \
             patch("content_upload_retention_worker.subprocess.run", return_value=SimpleNamespace(returncode=1)):
            result = sweep(self.repo, now=self.now)
        self.assertEqual(result["marked_failed"], 0)
        self.assertEqual(result["files_removed"], 1)
        self.assertFalse(self.partial.exists())


if __name__ == "__main__":
    unittest.main()
