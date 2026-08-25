#!/usr/bin/env python3
from __future__ import annotations
import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"database",ROOT/"dashboard",ROOT/"core"):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from backend import DatabaseConfig
from backend_factory import create_backend
from instance_activity_repository import InstanceActivityRepository
from instance_workspace_policy import INSTANCE_PERMISSIONS,PERMISSION_PRESETS

class CustomerInstanceActivityTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.backend=create_backend(DatabaseConfig(driver="sqlite",database=str(Path(self.temp.name)/"capivara.db")));self.backend.initialize();self.repo=InstanceActivityRepository(self.backend)
 def tearDown(self):self.backend.close();self.temp.cleanup()
 def test_activity_read_is_a_real_instance_permission(self):
  self.assertIn("activity.read",INSTANCE_PERMISSIONS);self.assertIn("activity.read",PERMISSION_PRESETS["viewer"]);self.assertIn("activity.read",PERMISSION_PRESETS["operator"]);self.assertIn("activity.read",PERMISSION_PRESETS["manager"])
 def test_timeline_is_strictly_isolated_by_instance(self):
  self.repo.record(instance_id="server-a",customer_id=1,username="ronaldo",role="customer",activity="INSTANCE_STOPPED",category="server")
  self.repo.record(instance_id="server-b",customer_id=2,username="marcos",role="customer",activity="FILE_EDIT_REQUESTED",category="files",target_type="file",target_name="config.conf")
  a=self.repo.search(instance_id="server-a");b=self.repo.search(instance_id="server-b")
  self.assertEqual(len(a),1);self.assertEqual(a[0]["username"],"ronaldo");self.assertEqual(a[0]["target_id"],"server-a")
  self.assertEqual(len(b),1);self.assertEqual(b[0]["username"],"marcos");self.assertEqual(b[0]["details"]["resource_name"],"config.conf")
 def test_filters_are_instance_scoped(self):
  self.repo.record(instance_id="server-a",customer_id=1,username="ronaldo",role="customer",activity="BACKUP_CREATE_REQUESTED",category="backup",result="accepted")
  self.repo.record(instance_id="server-a",customer_id=1,username="joao",role="customer",activity="INSTANCE_STARTED",category="server",result="success")
  rows=self.repo.search(instance_id="server-a",username="ronaldo",category="backup",result="accepted")
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]["activity"],"BACKUP_CREATE_REQUESTED")
 def test_customer_ui_and_api_contract(self):
  html=(ROOT/"dashboard/web/customer-instance.html").read_text(encoding="utf-8");js=(ROOT/"dashboard/web/customer-instance-activity.js").read_text(encoding="utf-8");http=(ROOT/"dashboard/customer_instance_activity_http.py").read_text(encoding="utf-8")
  self.assertIn('data-view="activity"',html);self.assertIn("Atividade da instância",html);self.assertIn("customer-instance-activity.js",html)
  self.assertIn("activity.read",js);self.assertIn("/api/customer/instance/activity",js);self.assertIn("activity.read",http);self.assertIn("InstanceActivityRepository",http)
 def test_sensitive_console_text_is_not_persisted_by_workspace_activity(self):
  source=(ROOT/"dashboard/customer_instance_workspace_http.py").read_text(encoding="utf-8")
  self.assertIn('"CONSOLE_COMMAND_REQUESTED"',source)
  self.assertNotIn('details={"command":body.get("command")}',source)

if __name__=="__main__":unittest.main()
