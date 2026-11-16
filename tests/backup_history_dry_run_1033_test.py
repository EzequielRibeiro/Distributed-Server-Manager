"""#1033: non-destructive history reconciliation and Linux/Windows retention."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT / "database", ROOT / "agents/windows/runtime"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
from backup_history_projection import annotate_backup_jobs

spec = importlib.util.spec_from_file_location(
    "dsm1033_dryrun", ROOT / "tools/backup_history_dry_run.py")
dryrun = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dryrun)


def make_tar(path, *, manifest_only=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as archive:
        items = [(".capivara-backup-manifest.json", b'{"kind":"CapivaraInstanceBackup"}')]
        if not manifest_only:
            items.append(("world.dat", b"world data"))
        for name, payload in items:
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))


class BackupHistoryDryRun1033Test(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="dsm1033-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.backups = self.root / "backups"
        self.results = self.root / "backup-results"
        self.backups.mkdir()
        self.results.mkdir()
        self.iid = "cli-000001-minecraft-005"
        self.inst = self.backups / self.iid
        self.inst.mkdir()

    def report(self, bid, *, status="completed", digest="a"*64,
               size=None, ts="2026-11-09T07:10:00Z"):
        path = self.inst / (bid + ".tar.gz")
        payload = {
            "command_id": bid, "instance_id": self.iid, "backup_id": bid,
            "action": "create", "status": status, "sha256": digest,
            "size_bytes": path.stat().st_size if size is None else size,
            "artifact_path": str(path), "completed_at": ts,
        }
        (self.results / (bid + ".json")).write_text(json.dumps(payload))
        return payload

    def test_operational_and_history_are_record_only_not_verified(self):
        latest, old = "backup-new", "backup-old"
        make_tar(self.inst / (latest + ".tar.gz"))
        make_tar(self.inst / (old + ".tar.gz"))
        newest = self.report(latest)
        previous = self.report(old, ts="2026-11-08T07:10:00Z")
        values = annotate_backup_jobs([newest, previous])
        self.assertEqual(values[0]["history_role"], "operational_reference")
        self.assertEqual(values[1]["history_role"], "historical_record")
        self.assertEqual(values[0]["physical_verification"], "not_checked")
        self.assertEqual(values[1]["retention_protection"], "preserve")

    def test_failed_replacement_cannot_promote_or_prune_last_record(self):
        make_tar(self.inst / "existing.tar.gz")
        old = self.report("existing")
        failed = {"instance_id":self.iid, "action":"create", "status":"failed",
                  "backup_id":"replacement", "sha256":None}
        report = annotate_backup_jobs([failed, old])
        self.assertEqual(report[0]["history_role"], "operation_not_completed")
        self.assertEqual(report[1]["history_role"], "operational_reference")

    def test_duplicate_or_missing_checksum_never_becomes_operational(self):
        make_tar(self.inst / "same.tar.gz")
        row = self.report("same")
        cases = annotate_backup_jobs([row,dict(row),dict(row,backup_id="incomplete",sha256=None)])
        self.assertEqual(cases[0]["history_role"], "ambiguous_record")
        self.assertEqual(cases[1]["history_role"], "ambiguous_record")
        self.assertEqual(cases[2]["history_role"], "incomplete_record")
        self.assertFalse(any(r.get("history_role")=="operational_reference" for r in cases))

    def test_existing_orphan_manifest_invalid_and_partial_are_preserved(self):
        make_tar(self.inst / "latest.tar.gz")
        self.report("latest")
        make_tar(self.inst / "old-manifest-only.tar.gz",manifest_only=True)
        (self.inst / "partial.tar.gz").write_bytes(b"truncated")
        (self.inst / "copy.inprogress").write_bytes(b"incomplete")
        initial = {p.name:p.read_bytes() for p in self.inst.iterdir()}
        report = dryrun.reconcile(self.backups,self.results,self.iid)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["proposed_actions"],[])
        self.assertEqual(report["proposed_delete_count"],0)
        self.assertEqual(report["physical_file_count"],4)
        self.assertEqual(report["classifications"]["manifest_only"],1)
        self.assertEqual(report["classifications"]["invalid_archive"],1)
        self.assertEqual(report["unmatched_local_result_count"],3)
        self.assertTrue(all(item["disposition"]=="preserve" for item in report["physical_files"]))
        self.assertFalse(report["physical_integrity_verified"])
        self.assertEqual(initial,{p.name:p.read_bytes() for p in self.inst.iterdir()})

    def test_missing_recorded_file_reported_without_delete(self):
        self.report_missing("not-on-disk")
        result = dryrun.reconcile(self.backups,self.results,self.iid)
        self.assertEqual(result["missing_registered_backup_ids"],["not-on-disk"])
        self.assertEqual(result["proposed_delete_count"],0)

    def report_missing(self,bid):
        row={"command_id":bid,"instance_id":self.iid,"backup_id":bid,
             "action":"create","status":"completed","sha256":"a"*64,
             "size_bytes":1200,"artifact_path":str(self.inst/(bid+".tar.gz"))}
        (self.results / (bid+".json")).write_text(json.dumps(row))

    def test_cross_instance_historic_files_not_included(self):
        make_tar(self.inst / "for-this.tar.gz")
        other = self.backups / "other-client-dayz"
        make_tar(other / "for-other.tar.gz")
        report = dryrun.reconcile(self.backups,self.results,self.iid)
        self.assertEqual(report["physical_file_count"],1)
        self.assertEqual(report["physical_files"][0]["filename"],"for-this.tar.gz")

    def test_symlinks_and_unsafe_identifiers_fail_closed(self):
        (self.inst/"redirect.tar.gz").symlink_to(self.results)
        with self.assertRaisesRegex(OSError,"unsafe"):
            dryrun.reconcile(self.backups,self.results,self.iid)
        for iid in ("/etc","../escape","bad/name","", ".", ".."):
            with self.subTest(iid=iid),self.assertRaises(ValueError):
                dryrun.reconcile(self.backups,self.results,iid)


class WindowsRetentionParity1033Test(unittest.TestCase):
    def test_windows_create_never_prunes_even_without_single_policy(self):
        win_path=ROOT/"agents/windows/runtime/backup_client.py"
        source=win_path.read_text()
        self.assertNotIn("def _retention(",source)
        self.assertNotIn("_retention(idir,",source)

    def test_windows_legacy_and_scheduled_deletes_refused_without_opt_in(self):
        import types
        runtime_stub=types.ModuleType("instance_runtime")
        runtime_stub.get_instance=lambda iid:None
        runtime_stub.lifecycle=lambda *args,**kwargs:None
        runtime_stub.status=lambda *args,**kwargs:{"observed_state":"stopped"}
        prior=sys.modules.get("instance_runtime")
        try:
            sys.modules["instance_runtime"]=runtime_stub
            spec=importlib.util.spec_from_file_location(
                "dsm1033_winbackup",ROOT/"agents/windows/runtime/backup_client.py")
            module=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            if prior is None:sys.modules.pop("instance_runtime",None)
            else:sys.modules["instance_runtime"]=prior
        with patch.dict(os.environ,{"DSM_BACKUP_ALLOW_AUTOMATIC_DELETION":""}), \
             patch.object(module,"_owned") as owned, \
             patch.object(module,"_artifact") as artifact:
            for reason in (None,"age_retention","operational_retention"):
                with self.subTest(reason=reason),self.assertRaisesRegex(ValueError,"automatic backup deletion"):
                    module._delete({"agent_id":"test"},
                                   {"instance_id":"test","backup_id":"old","reason":reason})
            owned.assert_not_called()
            artifact.assert_not_called()


if __name__ == "__main__":
    unittest.main()
