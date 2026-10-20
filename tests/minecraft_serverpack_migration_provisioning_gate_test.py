#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/"agents/linux/runtime"
COMMON=ROOT/"agents/common"
CORE=ROOT/"core"
for path in (ROOT,RUNTIME,COMMON,CORE):
    if str(path) not in sys.path:
        sys.path.insert(0,str(path))

import minecraft_serverpack_migration_provisioning as module


class HomologationGateTest(unittest.TestCase):
    def request(self,instance_id="pr855-lab",agent_id="pr839-isolated-agent"):
        return {"instance_id":instance_id,"agent_id":agent_id}

    def test_gate_requires_explicit_env_lab_prefix_and_isolated_agent(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertFalse(module.enabled_for(self.request()))
        with patch.dict(os.environ,{
            "CAPIVARA_ENABLE_SERVERPACK_MIGRATION_HOMOLOGATION":"YES",
        },clear=False):
            self.assertTrue(module.enabled_for(self.request()))
            self.assertFalse(module.enabled_for(self.request(instance_id="cli-000001-minecraft-005")))
            self.assertFalse(module.enabled_for(self.request(agent_id="agent-5d320c393c9dc0f8e36e")))
            self.assertFalse(module.enabled_for(self.request(instance_id="minecraft-005",agent_id="pr839-isolated-agent")))

    def test_production_gate_requires_request_mode_binding_and_exact_allowlists(self):
        request={
            "instance_id":"cli-production-test",
            "agent_id":"agent-production-test",
            "configuration":{"minecraft_serverpack_execution_mode":"production"},
        }
        env={
            "CAPIVARA_SERVERPACK_MIGRATION_MODE":"production",
            "CAPIVARA_SERVERPACK_MIGRATION_PRODUCTION_ACK":"AUTHORIZED",
            "CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_INSTANCES":"cli-production-test",
            "CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_AGENTS":"agent-production-test",
        }
        with patch.dict(os.environ,env,clear=True):
            self.assertTrue(module.enabled_for(request))
            self.assertFalse(module.enabled_for({
                **request,
                "configuration":{},
            }))
            self.assertFalse(module.enabled_for({
                **request,
                "instance_id":"cli-production-test-other",
            }))
            self.assertFalse(module.enabled_for({
                **request,
                "agent_id":"agent-production-test-other",
            }))

    def test_hybrid_customer_flow_is_scoped_to_minecraft_005(self):
        env={
            "CAPIVARA_SERVERPACK_MIGRATION_MODE":"production",
            "CAPIVARA_SERVERPACK_MIGRATION_PRODUCTION_ACK":"AUTHORIZED",
            "CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_INSTANCES":"cli-000001-minecraft-005",
            "CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_AGENTS":"agent-horizon-server",
        }
        request={
            "instance_id":"cli-000001-minecraft-005",
            "agent_id":"agent-horizon-server",
            "configuration":{"minecraft_serverpack_execution_mode":"production"},
        }
        with patch.dict(os.environ,env,clear=True):
            self.assertTrue(module.enabled_for(request))
            self.assertFalse(module.enabled_for({**request,"instance_id":"cli-000001-minecraft-003"}))
            self.assertFalse(module.enabled_for({**request,"agent_id":"agent-node1"}))
            self.assertFalse(module.enabled_for({**request,"configuration":{}}))

    def test_production_agent_stays_disabled_without_exact_ack(self):
        request={
            "instance_id":"cli-production-test",
            "agent_id":"agent-production-test",
            "configuration":{"minecraft_serverpack_execution_mode":"production"},
        }
        env={
            "CAPIVARA_SERVERPACK_MIGRATION_MODE":"production",
            "CAPIVARA_SERVERPACK_MIGRATION_PRODUCTION_ACK":"YES",
            "CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_INSTANCES":"cli-production-test",
            "CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_AGENTS":"agent-production-test",
        }
        with patch.dict(os.environ,env,clear=True):
            self.assertFalse(module.enabled_for(request))

    def test_non_yes_values_do_not_enable_gate(self):
        for value in ("","1","true","on","enabled"):
            with self.subTest(value=value),patch.dict(os.environ,{
                "CAPIVARA_ENABLE_SERVERPACK_MIGRATION_HOMOLOGATION":value,
            },clear=False):
                self.assertFalse(module.enabled_for(self.request()))


class AutomaticRestartTest(unittest.TestCase):
    def test_running_instance_restarts_and_waits_for_fresh_readiness(self):
        from unittest.mock import Mock
        adapter=Mock()
        record={"instance_id":"lab"}
        with patch.object(module,"_readiness_log_baseline",return_value=(42,100)), \
             patch.object(module,"_wait_for_done",return_value=True) as wait:
            observed=module._restore_initial_running_state(
                record,adapter,"active",working=Path("/tmp/pr916-test-runtime"))
        self.assertEqual(observed,"running")
        adapter.start.assert_called_once_with(record)
        wait.assert_called_once_with(record,adapter,baseline=(42,100))

    def test_previously_stopped_instance_stays_stopped(self):
        from unittest.mock import Mock
        adapter=Mock()
        with patch.object(module,"_wait_for_done") as wait:
            observed=module._restore_initial_running_state(
                {},adapter,"inactive",working=Path("/tmp/pr916-test-runtime"))
        self.assertEqual(observed,"stopped")
        adapter.start.assert_not_called()
        wait.assert_not_called()

    def test_activating_instance_restores_running_state(self):
        from unittest.mock import Mock
        adapter=Mock()
        with patch.object(module,"_readiness_log_baseline",return_value=None), \
             patch.object(module,"_wait_for_done",return_value=True):
            observed=module._restore_initial_running_state(
                {},adapter,"activating",working=Path("/tmp/pr916-test-runtime"))
        self.assertEqual(observed,"running")
        adapter.start.assert_called_once()

    def test_failed_restart_prevents_commit(self):
        from unittest.mock import Mock
        adapter=Mock()
        with patch.object(module,"_readiness_log_baseline",return_value=None), \
             patch.object(module,"_wait_for_done",return_value=False):
            with self.assertRaisesRegex(module.MinecraftServerPackProvisioningHomologationError,
                                        "did not become ready"):
                module._restore_initial_running_state(
                    {},adapter,"active",working=Path("/tmp/pr916-test-runtime"))
        adapter.start.assert_called_once()


if __name__=="__main__":
    unittest.main()
