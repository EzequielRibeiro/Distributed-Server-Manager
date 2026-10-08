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


if __name__=="__main__":
    unittest.main()
