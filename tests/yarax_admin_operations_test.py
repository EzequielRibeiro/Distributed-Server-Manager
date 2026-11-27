#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
from datetime import datetime, timezone, timedelta
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"dashboard",ROOT/"database"):
    if str(path) not in sys.path:sys.path.insert(0,str(path))

from yarax_admin_operation_repository import ACTIONS, YaraXAdminOperationRepository
from yarax_admin_operation_api import create_operation


def load(platform,name,module_name):
    runtime=ROOT/"agents"/platform/"runtime"
    old=list(sys.path);sys.path.insert(0,str(runtime))
    try:
        spec=importlib.util.spec_from_file_location(module_name,runtime/name)
        mod=importlib.util.module_from_spec(spec);assert spec.loader;spec.loader.exec_module(mod);return mod
    finally:sys.path[:]=old


class YaraXAdminOperationsTest(unittest.TestCase):
    def test_lost_delivery_review_is_fail_closed(self):
        spec = importlib.util.spec_from_file_location(
            "reconcile_test", ROOT/"update-manager/game-uptime-yarax-reconcile.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=10)).isoformat()
        row = dict(operation_id="yarax-" + "a"*32, agent_id="a1",
                   action="install_engine", status="delivered",
                   created_at=old, delivered_at=old, updated_at=old,
                   completed_at=None, no_result=True, no_error=True)
        report = dict(hybrid=1, credentials=0, rows=[row])
        self.assertEqual(module.eligible(report, "a1", [row["operation_id"]], now), [row])
        for change in ({"status":"running"}, {"no_result":False},
                       {"updated_at":now.isoformat()}, {"agent_id":"a2"},
                       {"delivered_at":now.isoformat(),"updated_at":now.isoformat()}):
            with self.assertRaises(RuntimeError):
                module.eligible(dict(report, rows=[dict(row, **change)]),
                                "a1", [row["operation_id"]], now)
        with self.assertRaises(RuntimeError):
            module.eligible(dict(report, credentials=1), "a1", [row["operation_id"]], now)

    def test_terminal_result_cannot_reopen_operation(self):
        repo = YaraXAdminOperationRepository(type("Backend", (), {"name":"sqlite"})())
        with patch.object(repo, "get", return_value={
            "operation_id":"op1", "agent_id":"a1",
            "action":"install_engine","status":"failed",
            "result":{"outcome":"unconfirmed"},
        }):
            actual = repo.apply_result("a1", {"operation_id":"op1","status":"running"})
            self.assertEqual(actual["status"], "failed")
            self.assertEqual(actual["result"]["outcome"], "unconfirmed")
            with self.assertRaises(PermissionError):
                repo.apply_result("a2", {"operation_id":"op1","status":"completed"})

    def test_allowlist_is_closed(self):
        self.assertEqual(ACTIONS,{"install_engine","install_rules","test_scan","rescan_content","rollback_rules"})
        for source in (
            ROOT/"agents/linux/runtime/yarax_admin_client.py",
            ROOT/"agents/windows/runtime/yarax_admin_client.py",
        ):
            text=source.read_text(encoding="utf-8")
            self.assertNotIn("shell=True",text)
            self.assertNotIn("subprocess.Popen",text)
            self.assertNotIn("command.get(\"path\")",text)
            self.assertNotIn("command.get(\"url\")",text)

    def test_agent_executor_is_idempotent_and_allowlisted(self):
        module=load("linux","yarax_admin_client.py","y6_linux_client")
        with tempfile.TemporaryDirectory() as td:
            module.STATE_DIR=Path(td);module.RESULT_PATH=Path(td)/"result.json"
            with patch.object(module,"install_engine",return_value={"state":"ready"}),patch.object(module,"engine_status",return_value={"state":"ready"}),patch.object(module,"rules_status",return_value={"state":"ready"}):
                result=module.handle_command({"operation_id":"op1","action":"install_engine"})
                self.assertEqual(result["status"],"completed")
                again=module.handle_command({"operation_id":"op1","action":"install_engine"})
                self.assertEqual(again,result)
            with self.assertRaises(ValueError):
                module.handle_command({"operation_id":"op2","action":"run_shell"})

    def test_rescan_resolves_managed_path_from_local_state(self):
        module=load("linux","yarax_admin_client.py","y6_linux_rescan")
        with tempfile.TemporaryDirectory() as td:
            managed=Path(td)/"managed";managed.mkdir()
            record={"instance_id":"i1","content_id":"c1","managed_path":str(managed),"provider":"local","game_id":"dayz"}
            with patch.object(module,"content_state",return_value=[record]),patch.object(module,"scan_content",return_value={"security_state":"clean"}) as scan:
                result=module._rescan({"agent_id":"a1","instance_id":"i1","content_id":"c1","path":"/attacker"})
            self.assertEqual(result["verdict"]["security_state"],"clean")
            self.assertEqual(scan.call_args.args[0],managed)

    def test_self_test_requires_eicar_block(self):
        module=load("linux","yarax_admin_client.py","y6_linux_test")
        with tempfile.TemporaryDirectory() as td:
            module.STATE_DIR=Path(td)
            with patch.object(module,"scan_content",return_value={"security_state":"blocked"}):
                result=module._test_scan({"agent_id":"a1"})
                self.assertEqual(result["self_test"],"passed")
            with patch.object(module,"scan_content",return_value={"security_state":"clean"}):
                with self.assertRaises(RuntimeError):module._test_scan({"agent_id":"a1"})

    def test_ruleset_rollback_contract_is_trusted_only(self):
        for platform in ("linux","windows"):
            source=(ROOT/f"agents/{platform}/runtime/security_yarax_rules.py").read_text(encoding="utf-8")
            self.assertIn("TRUSTED_RULESETS",source)
            self.assertIn("previous YARA-X ruleset version is not trusted",source)
            self.assertIn("previous YARA-X ruleset file checksum is invalid",source)
            self.assertIn('"rollback"',source)

    def test_controller_operation_api_records_semantic_audit(self):
        class Backend:
            name="sqlite"
            def connect(self):
                class C:
                    def __enter__(self):
                        class Conn:
                            def execute(self,*args):
                                return type("Cursor",(),{"fetchone":lambda self:{"id":"a1","controller_id":"ctrl"}})()
                        return Conn()
                    def __exit__(self,*args):return False
                return C()
        user={"role":"admin","username":"root"}
        with patch("yarax_admin_operation_api.YaraXAdminOperationRepository") as repo_cls,patch("yarax_admin_operation_api.ActivityAuditRepository") as audit_cls:
            repo_cls.return_value.create.return_value={"operation_id":"yarax-1","agent_id":"a1","action":"test_scan","instance_id":None,"content_id":None}
            result=create_operation(user=user,backend=Backend(),payload={"agent_id":"a1","action":"test_scan"})
            self.assertEqual(result["operation_id"],"yarax-1")
            audit_cls.return_value.record_action.assert_called_once()
            self.assertEqual(audit_cls.return_value.record_action.call_args.kwargs["category"],"security")

    def test_customers_cannot_administer_yarax(self):
        class Backend:pass
        with self.assertRaises(PermissionError):
            create_operation(user={"role":"customer"},backend=Backend(),payload={"agent_id":"a1","action":"test_scan"})

    def test_heartbeat_and_hybrid_transport_contracts(self):
        linux=(ROOT/"agents/linux/runtime/agent.py").read_text(encoding="utf-8")
        windows=(ROOT/"agents/windows/runtime/agent.py").read_text(encoding="utf-8")
        controller=(ROOT/"dashboard/agent_heartbeat_api.py").read_text(encoding="utf-8")
        hybrid=(ROOT/"dashboard/workers/hybrid_agent_worker.py").read_text(encoding="utf-8")
        for source in (linux,windows):
            self.assertIn("yarax_admin_command",source);self.assertIn("yarax_admin_result",source)
        self.assertIn("_yarax_admin_exchange",controller)
        self.assertIn('"yarax_admin_command":yarax_admin_command',controller)
        self.assertIn("process_hybrid_yarax_admin_cycle",hybrid)

    def test_schema_and_ui_contract(self):
        for name in ("sqlite.sql","postgresql.sql","mysql.sql","mariadb.sql"):
            schema=(ROOT/"database/schemas"/name).read_text(encoding="utf-8")
            self.assertIn("042_yarax_admin_operations.sql",schema)
            self.assertIn("yarax_admin_operations",schema)
        part=(ROOT/"dashboard/server_part21.py").read_text(encoding="utf-8")
        js=(ROOT/"dashboard/web/admin-security-yarax.js").read_text(encoding="utf-8")
        self.assertIn("install_yarax_admin_operations_http",part)
        for action in ("install_engine","install_rules","test_scan","rollback_rules","rescan_content"):
            self.assertIn(action,js)
        self.assertIn("/api/admin/security/yara-x/operations",js)


if __name__=="__main__":unittest.main()
