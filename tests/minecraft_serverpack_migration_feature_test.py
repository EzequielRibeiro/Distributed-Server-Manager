#!/usr/bin/env python3
from __future__ import annotations

import unittest

from core.minecraft_serverpack_migration_feature import migration_feature_decision


class ServerPackMigrationFeaturePolicyTest(unittest.TestCase):
    def decision(self,env,instance_id="cli-000001-minecraft-005",agent_id="agent-prod"):
        return migration_feature_decision(
            instance_id=instance_id,
            agent_id=agent_id,
            environ=env,
        )

    def test_default_is_disabled(self):
        result=self.decision({})
        self.assertFalse(result["allowed"])
        self.assertEqual(result["mode"],"disabled")

    def test_legacy_homologation_switch_keeps_only_pr855_lab_identity(self):
        env={"CAPIVARA_ENABLE_SERVERPACK_MIGRATION_HOMOLOGATION":"YES"}
        self.assertTrue(self.decision(
            env,instance_id="pr855-lab",agent_id="pr839-isolated-agent"
        )["allowed"])
        self.assertFalse(self.decision(
            env,instance_id="cli-000001-minecraft-005",agent_id="pr839-isolated-agent"
        )["allowed"])
        self.assertFalse(self.decision(
            env,instance_id="pr855-lab",agent_id="agent-prod"
        )["allowed"])

    def test_explicit_disabled_mode_overrides_legacy_switch(self):
        result=self.decision({
            "CAPIVARA_SERVERPACK_MIGRATION_MODE":"disabled",
            "CAPIVARA_ENABLE_SERVERPACK_MIGRATION_HOMOLOGATION":"YES",
        },instance_id="pr855-lab",agent_id="pr839-isolated-agent")
        self.assertFalse(result["allowed"])
        self.assertEqual(result["mode"],"disabled")

    def test_production_requires_exact_ack_and_both_allowlists(self):
        base={
            "CAPIVARA_SERVERPACK_MIGRATION_MODE":"production",
            "CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_INSTANCES":"cli-000001-minecraft-005",
            "CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_AGENTS":"agent-prod",
        }
        for ack in ("","yes","AUTHORIZED "):
            with self.subTest(ack=ack):
                result=self.decision({**base,"CAPIVARA_SERVERPACK_MIGRATION_PRODUCTION_ACK":ack})
                self.assertFalse(result["allowed"])
        self.assertTrue(self.decision({
            **base,
            "CAPIVARA_SERVERPACK_MIGRATION_PRODUCTION_ACK":"AUTHORIZED",
        })["allowed"])

    def test_production_allowlists_are_exact_not_prefix_or_substring(self):
        env={
            "CAPIVARA_SERVERPACK_MIGRATION_MODE":"production",
            "CAPIVARA_SERVERPACK_MIGRATION_PRODUCTION_ACK":"AUTHORIZED",
            "CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_INSTANCES":"cli-000001-minecraft-005,cli-test",
            "CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_AGENTS":"agent-prod,agent-other",
        }
        self.assertTrue(self.decision(env)["allowed"])
        self.assertFalse(self.decision(
            env,instance_id="cli-000001-minecraft-005-extra",agent_id="agent-prod"
        )["allowed"])
        self.assertFalse(self.decision(
            env,instance_id="cli-000001-minecraft-005",agent_id="agent"
        )["allowed"])

    def test_empty_allowlist_side_fails_closed(self):
        common={
            "CAPIVARA_SERVERPACK_MIGRATION_MODE":"production",
            "CAPIVARA_SERVERPACK_MIGRATION_PRODUCTION_ACK":"AUTHORIZED",
        }
        for env in (
            {**common,
             "CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_INSTANCES":"cli-000001-minecraft-005",
             "CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_AGENTS":""},
            {**common,
             "CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_INSTANCES":"",
             "CAPIVARA_SERVERPACK_MIGRATION_ALLOWED_AGENTS":"agent-prod"},
        ):
            with self.subTest(env=env):
                self.assertFalse(self.decision(env)["allowed"])

    def test_invalid_mode_fails_closed(self):
        result=self.decision({"CAPIVARA_SERVERPACK_MIGRATION_MODE":"prod"})
        self.assertFalse(result["allowed"])
        self.assertEqual(result["mode"],"invalid")


if __name__=="__main__":
    unittest.main()
