#!/usr/bin/env python3
from __future__ import annotations
import ast
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DASHBOARD=ROOT/"dashboard"

class CustomerWorkspaceArchitectureBoundaryTest(unittest.TestCase):
 def test_workspace_uses_agent_owned_operation_repositories(self):
  text=(DASHBOARD/"customer_instance_workspace_service.py").read_text(encoding="utf-8")
  self.assertIn("InstanceFileRepository",text)
  self.assertIn("BackupRepository",text)
  self.assertIn("enqueue_console",text)
  self.assertNotIn("subprocess.",text)
  self.assertNotIn("os.system",text)
  self.assertNotIn("shutil.rmtree",text)

 def test_customer_http_layers_do_not_mutate_instance_filesystem(self):
  paths=[
   DASHBOARD/"customer_instance_workspace_http.py",
   DASHBOARD/"customer_instance_workspace_service.py",
   DASHBOARD/"customer_instance_team_http.py",
   DASHBOARD/"customer_instance_activity_http.py",
   DASHBOARD/"deleted_backup_vault_http.py",
   DASHBOARD/"backup_clone_http.py",
   DASHBOARD/"contract_upgrade_http.py",
  ]
  forbidden={"unlink","rmdir","mkdir","write_text","write_bytes","rename","replace"}
  for path in paths:
   tree=ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
   bad=[]
   for node in ast.walk(tree):
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in forbidden:
     bad.append(node.func.attr)
   self.assertEqual(bad,[],f"{path.name} performs direct filesystem mutation: {bad}")

 def test_binary_spool_is_explicit_controller_artifact_plane(self):
  transfer=(DASHBOARD/"artifact_transfer_http.py").read_text(encoding="utf-8")
  vault=(ROOT/"database"/"deleted_backup_vault_repository.py").read_text(encoding="utf-8")
  self.assertIn("ArtifactTransferRepository",transfer)
  self.assertIn("agent_to_controller",transfer)
  self.assertIn("controller_to_agent",transfer)
  self.assertIn("relative_to(self.artifacts.spool)",vault)

 def test_deletion_remains_agent_owned(self):
  text=(ROOT/"database"/"deleted_backup_vault_repository.py").read_text(encoding="utf-8")
  self.assertIn('action="remove"',text)
  self.assertNotIn("shutil.rmtree",text)
  self.assertIn("ArtifactTransferRepository",text)

 def test_resource_upgrade_is_commanded_to_agent(self):
  text=(ROOT/"database"/"instance_resource_repository.py").read_text(encoding="utf-8")
  self.assertIn("instance_resource_commands",text)
  self.assertIn("agent_id",text)

if __name__=="__main__":unittest.main()
