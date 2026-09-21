#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "dashboard", ROOT / "database", ROOT / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import server


USER = {"role": "customer", "scope_id": "CLI-000001", "username": "customer"}


class CustomerRuntimeContractGateTest(unittest.TestCase):
    @staticmethod
    def _contract(*, mode: str, allowed: list[str], available: bool = True) -> dict:
        return {
            "id": "contract-cli-000001-minecraft-test",
            "game_id": "minecraft",
            "status": "active",
            "available": available,
            "content_mode": mode,
            "product_variant": mode,
            "allowed_runtime_ids": allowed,
        }

    def test_standard_contract_allows_vanilla(self):
        contract = self._contract(
            mode="standard",
            allowed=["minecraft.java.vanilla", "minecraft.bedrock.vanilla"],
        )
        with patch.object(server, "customer_contracts", return_value=[contract]):
            resolved = server.customer_contract_for_runtime(
                USER,
                "minecraft",
                "minecraft.java.vanilla",
                contract["id"],
            )
        self.assertEqual(resolved["id"], contract["id"])

    def test_standard_contract_rejects_modified_runtimes(self):
        contract = self._contract(
            mode="standard",
            allowed=["minecraft.java.vanilla", "minecraft.bedrock.vanilla"],
        )
        with patch.object(server, "customer_contracts", return_value=[contract]):
            for runtime_id in (
                "minecraft.java.fabric",
                "minecraft.java.forge",
                "minecraft.java.neoforge",
                "minecraft.java.paper",
                "minecraft.java.youer",
            ):
                with self.subTest(runtime_id=runtime_id):
                    with self.assertRaisesRegex(
                        PermissionError,
                        "Minecraft Padrão",
                    ):
                        server.customer_contract_for_runtime(
                            USER,
                            "minecraft",
                            runtime_id,
                            contract["id"],
                        )

    def test_modified_contract_allows_neoforge(self):
        contract = self._contract(
            mode="modified",
            allowed=[
                "minecraft.java.vanilla",
                "minecraft.java.neoforge",
                "minecraft.java.fabric",
            ],
        )
        with patch.object(server, "customer_contracts", return_value=[contract]):
            resolved = server.customer_contract_for_runtime(
                USER,
                "minecraft",
                "minecraft.java.neoforge",
                contract["id"],
            )
        self.assertEqual(resolved["product_variant"], "modified")

    def test_unavailable_contract_is_rejected_before_provisioning(self):
        contract = self._contract(
            mode="modified",
            allowed=["minecraft.java.neoforge"],
            available=False,
        )
        with patch.object(server, "customer_contracts", return_value=[contract]):
            with self.assertRaisesRegex(PermissionError, "unavailable"):
                server.customer_contract_for_runtime(
                    USER,
                    "minecraft",
                    "minecraft.java.neoforge",
                    contract["id"],
                )


if __name__ == "__main__":
    unittest.main()
