import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "agents/linux/runtime/minecraft_serverpack_finalization_coordinator.py"
spec = importlib.util.spec_from_file_location("coordinator", path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
OP = {"agent_id": "agent-test", "instance_id": "instance-test",
      "operation": "minecraft_serverpack_migration", "status": "finalization_pending",
      "migration_plan_sha256": "a" * 64}
BASE = {"provisioning_id": "provision-test", "instance_id": "instance-test",
        "status": "running", "current_step": "minecraft_serverpack_finalization",
        "finalization_state": "pending",
        "minecraft_serverpack_migration": {"migration_plan_sha256": "a" * 64}}
COMPLETE = {"status": "completed", "trace": ["committed", "finalized"],
            "finalization": {"status": "archived", "observed_state": "inactive"},
            "migration_plan_sha256": "a" * 64}


class CoordinatorTest(unittest.TestCase):
    def scenario(self, *, op=None, result=None, fail=None):
        events = []
        def done_op(_):
            events.append("operation")
            if fail == "operation":
                raise RuntimeError("crash after publication")
        def recover():
            events.append("recovery")
            return {"status": "finalized", "instance_id": "instance-test",
                    "migration_plan_sha256": "a" * 64}
        def done_result(_):
            events.append("provisioning")
            if fail == "provisioning":
                raise RuntimeError("crash before publication")
        value = m.reconcile_finalization(
            operation=OP if op is None else op,
            result=BASE if result is None else result,
            instance_id="instance-test", agent_id="agent-test",
            complete_operation=done_op, run_recovery=recover,
            complete_provisioning=done_result)
        return value, events

    def test_completion_order(self):
        value, events = self.scenario()
        self.assertEqual(value["status"], "completed")
        self.assertEqual(events, ["recovery", "provisioning", "operation"])

    def test_crash_before_provisioning_does_not_release_barrier(self):
        with self.assertRaisesRegex(RuntimeError, "before publication"):
            self.scenario(fail="provisioning")

    def test_crash_after_publication_reconciles_only_operation(self):
        result = {**BASE, "status": "completed", "minecraft_serverpack_migration": COMPLETE}
        value, events = self.scenario(result=result)
        self.assertEqual(value["status"], "operation_reconciled")
        self.assertEqual(events, ["operation"])

    def test_repeated_completion_no_mutations(self):
        result = {**BASE, "status": "completed", "minecraft_serverpack_migration": COMPLETE}
        value, events = self.scenario(result=result, op={**OP, "status": "completed"})
        self.assertEqual(value["status"], "already_completed")
        self.assertEqual(events, [])

    def test_unverified_controller_completion_rejected(self):
        with self.assertRaisesRegex(m.FinalizationReconciliationError, "unverified"):
            self.scenario(result={**BASE, "status": "completed"})

    def test_wrong_agent_rejected(self):
        with self.assertRaisesRegex(m.FinalizationReconciliationError, "identity"):
            self.scenario(op={**OP, "agent_id": "foreign"})

    def test_wrong_instance_rejected(self):
        with self.assertRaisesRegex(m.FinalizationReconciliationError, "identity"):
            self.scenario(result={**BASE, "instance_id": "other"})

    def test_unsafe_operation_state_rejected(self):
        with self.assertRaisesRegex(m.FinalizationReconciliationError, "no eligible"):
            self.scenario(op={**OP, "status": "failed"})

    def test_unrelated_running_result_rejected(self):
        with self.assertRaisesRegex(m.FinalizationReconciliationError, "not pending"):
            self.scenario(result={**BASE, "current_step": "other"})

    def test_recovery_failure_does_not_publish(self):
        events = []
        with self.assertRaisesRegex(m.FinalizationReconciliationError, "no verified"):
            m.reconcile_finalization(
                operation=OP, result=BASE, instance_id="instance-test",
                agent_id="agent-test",
                complete_operation=lambda _: events.append("operation"),
                complete_provisioning=lambda _: events.append("provisioning"),
                run_recovery=lambda: {"status": "unknown"})
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
