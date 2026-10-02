#!/usr/bin/env python3
"""Subprocess crash tests; ALL paths are isolated disposable temp directories."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"core"))
from minecraft_staged_migration_crash_rehearsal import (
    CrashRehearsalError, prepare, switch, recover, commit, disposable_lock,
)


class CrashJournalTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="capivara-journal-test-")
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/".capivara-disposable-migration-test").write_text("test only")
        (self.root/"active").mkdir()
        (self.root/"active"/"neoforge.txt").write_text("26.1.2.94")
        (self.root/"active"/"mod.jar").write_bytes(b"original mod content")
        (self.root/"stage").mkdir()
        (self.root/"stage"/"neoforge.txt").write_text("26.1.2.109")
        self.oldhash=hashlib.sha256(b"26.1.2.94").hexdigest()
        self.previous=os.environ.get("CAPIVARA_DISPOSABLE_MIGRATION_REHEARSAL")
        os.environ["CAPIVARA_DISPOSABLE_MIGRATION_REHEARSAL"]="YES"
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self.previous is None:
            os.environ.pop("CAPIVARA_DISPOSABLE_MIGRATION_REHEARSAL",None)
        else:
            os.environ["CAPIVARA_DISPOSABLE_MIGRATION_REHEARSAL"]=self.previous

    def _prepare(self):
        prepare(self.root,original_hash=self.oldhash,checkpoint_verified=True)

    def _crash(self,step):
        cmd=[sys.executable,"-c",
             "import sys; sys.path.insert(0,sys.argv[1]); "
             "from minecraft_staged_migration_crash_rehearsal import switch; "
             "switch(sys.argv[2],crash_at=sys.argv[3])",
             str(ROOT/"core"),str(self.root),step]
        return subprocess.run(cmd,env=dict(os.environ),capture_output=True,timeout=8).returncode

    def test_explicit_disposable_flag_required(self):
        os.environ.pop("CAPIVARA_DISPOSABLE_MIGRATION_REHEARSAL")
        with self.assertRaisesRegex(CrashRehearsalError,"opt-in"):
            prepare(self.root,original_hash=self.oldhash,checkpoint_verified=True)
        self.assertFalse((self.root/"migration-journal.json").exists())

    def test_checkpoint_is_required_before_first_rename(self):
        with self.assertRaisesRegex(CrashRehearsalError,"verified checkpoint"):
            prepare(self.root,original_hash=self.oldhash,checkpoint_verified=False)
        self.assertTrue((self.root/"active").exists())

    def test_crash_after_old_rename_restores_exact_original(self):
        self._prepare()
        self.assertEqual(self._crash("after_old_rename"),71)
        self.assertFalse((self.root/"active").exists())
        result=recover(self.root)
        self.assertEqual(result["status"],"recovered")
        self.assertEqual((self.root/"active"/"neoforge.txt").read_text(),"26.1.2.94")
        self.assertEqual(recover(self.root)["status"],"already_recovered")

    def test_crash_after_new_rename_quarantines_new_and_restores_old(self):
        self._prepare()
        self.assertEqual(self._crash("after_new_rename"),72)
        self.assertEqual((self.root/"active"/"neoforge.txt").read_text(),"26.1.2.109")
        self.assertTrue(recover(self.root)["quarantine_retained"])
        self.assertEqual((self.root/"active"/"neoforge.txt").read_text(),"26.1.2.94")
        self.assertEqual((self.root/"quarantine-new"/"neoforge.txt").read_text(),"26.1.2.109")

    def test_recovery_resumes_after_second_crash_during_restore(self):
        self._prepare()
        self.assertEqual(self._crash("after_new_rename"),72)
        # Simulate a process dying after persisting 'recovering' and moving
        # the new runtime to quarantine but before restoring the old runtime.
        journal=self.root/"migration-journal.json"
        entry=json.loads(journal.read_text());entry["phase"]="recovering"
        journal.write_text(json.dumps(entry))
        (self.root/"active").rename(self.root/"quarantine-new")
        self.assertEqual(recover(self.root)["status"],"recovered")
        self.assertEqual((self.root/"active"/"neoforge.txt").read_text(),"26.1.2.94")

    def test_corrupt_or_missing_original_refuses_recovery(self):
        self._prepare()
        self.assertEqual(self._crash("after_new_rename"),72)
        (self.root/"rollback-runtime"/"neoforge.txt").write_text("tampered")
        with self.assertRaisesRegex(CrashRehearsalError,"incorrect"):
            recover(self.root)
        self.assertEqual((self.root/"active"/"neoforge.txt").read_text(),"26.1.2.109")

    def test_tampered_mod_in_rollback_requires_manual_intervention(self):
        self._prepare()
        self.assertEqual(self._crash("after_new_rename"),72)
        (self.root/"rollback-runtime"/"mod.jar").write_bytes(b"tampered content")
        with self.assertRaisesRegex(CrashRehearsalError,"incorrect"):
            recover(self.root)
        self.assertEqual((self.root/"active"/"neoforge.txt").read_text(),"26.1.2.109")

    def test_corrupt_journal_never_modifies_runtime(self):
        self._prepare()
        self.assertEqual(self._crash("after_new_rename"),72)
        (self.root/"migration-journal.json").write_text("not-json")
        with self.assertRaisesRegex(CrashRehearsalError,"manual intervention"):
            recover(self.root)
        self.assertEqual((self.root/"active"/"neoforge.txt").read_text(),"26.1.2.109")

    def test_recovery_preserves_entire_old_tree(self):
        self._prepare()
        self.assertEqual(self._crash("after_new_rename"),72)
        result=recover(self.root)
        self.assertEqual(result["status"],"recovered")
        self.assertEqual((self.root/"active"/"mod.jar").read_bytes(),b"original mod content")

    def test_changed_staged_mod_blocks_switch_before_first_rename(self):
        self._prepare()
        (self.root/"stage"/"mod.jar").write_bytes(b"injected staged mod")
        with self.assertRaisesRegex(CrashRehearsalError,"changed after checkpoint"):
            switch(self.root)
        self.assertTrue((self.root/"active").exists())
        self.assertFalse((self.root/"rollback-runtime").exists())

    def test_changed_current_mod_blocks_switch_before_first_rename(self):
        self._prepare()
        (self.root/"active"/"mod.jar").write_bytes(b"changed while waiting")
        with self.assertRaisesRegex(CrashRehearsalError,"changed after checkpoint"):
            switch(self.root)
        self.assertTrue((self.root/"active").exists())
        self.assertFalse((self.root/"rollback-runtime").exists())

    def test_exclusive_lock_rejects_competing_subprocess(self):
        script = ("import sys;sys.path.insert(0,sys.argv[1]);"
                  "from minecraft_staged_migration_crash_rehearsal import prepare;"
                  "prepare(sys.argv[2], original_hash=sys.argv[3], checkpoint_verified=True)")
        with disposable_lock(self.root):
            process = subprocess.run(
                [sys.executable, "-c", script, str(ROOT/"core"),
                 str(self.root), self.oldhash],
                env=dict(os.environ), capture_output=True, text=True, timeout=8)
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("already locked", process.stderr)
            self.assertFalse((self.root/"migration-journal.json").exists())
        self._prepare()

    def test_orphan_temporary_journal_blocks_forward_prepare_without_durable_journal(self):
        orphan=self.root/".migration-journal.tmp"
        orphan.write_text("{incomplete")
        with self.assertRaisesRegex(CrashRehearsalError,"orphan"):
            self._prepare()
        with self.assertRaisesRegex(CrashRehearsalError,"journal is absent"):
            recover(self.root)
        self.assertEqual(orphan.read_text(),"{incomplete")
        self.assertTrue((self.root/"active").is_dir())

    def test_fsynchronized_temp_crash_requires_explicit_verified_recovery(self):
        self._prepare()
        self.assertEqual(self._crash("after_journal_temp_fsync"),73)
        orphan=self.root/".migration-journal.tmp"
        self.assertTrue(orphan.is_file())
        self.assertEqual(json.loads((self.root/"migration-journal.json").read_text())["phase"],"prepared")
        self.assertEqual(json.loads(orphan.read_text())["phase"],"swapping")
        with self.assertRaisesRegex(CrashRehearsalError,"orphan"):
            switch(self.root)
        with self.assertRaisesRegex(CrashRehearsalError,"orphan"):
            commit(self.root,readiness_passed=True)
        self.assertEqual(recover(self.root)["status"],"recovered")
        self.assertFalse(orphan.exists())
        self.assertEqual((self.root/"active"/"mod.jar").read_bytes(),b"original mod content")

    def test_orphan_temp_is_retained_if_original_checksum_fails(self):
        self._prepare()
        self.assertEqual(self._crash("after_journal_temp_fsync"),73)
        orphan=self.root/".migration-journal.tmp"
        (self.root/"active"/"mod.jar").write_bytes(b"tamper")
        with self.assertRaisesRegex(CrashRehearsalError,"retain orphan"):
            recover(self.root)
        self.assertTrue(orphan.is_file())
        self.assertEqual((self.root/"active"/"mod.jar").read_bytes(),b"tamper")

    def test_unsafe_symlink_temporary_journal_is_rejected(self):
        outside = self.root/"outside-marker"
        outside.write_text("do not touch")
        (self.root/".migration-journal.tmp").symlink_to(outside)
        with self.assertRaisesRegex(CrashRehearsalError,"symlink paths are prohibited"):
            self._prepare()
        self.assertEqual(outside.read_text(),"do not touch")
        self.assertFalse((self.root/"migration-journal.json").exists())

    def test_commit_keeps_rollback_snapshot(self):
        self._prepare()
        switch(self.root)
        commit(self.root,readiness_passed=True)
        self.assertEqual((self.root/"rollback-runtime"/"neoforge.txt").read_text(),"26.1.2.94")
        with self.assertRaisesRegex(CrashRehearsalError,"committed"):
            recover(self.root)


if __name__=="__main__":
    unittest.main()
