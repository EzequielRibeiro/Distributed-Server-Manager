#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import customer_instance_creation as integration


class _FakeProvisioningRepository:
    calls = []

    def __init__(self, backend):
        self.backend = backend

    def initialize(self):
        return None

    def enqueue(self, **kwargs):
        self.__class__.calls.append(dict(kwargs))
        return {
            "provisioning_id": f"provision-{len(self.__class__.calls)}",
            "instance_id": kwargs["instance_id"],
            "agent_id": kwargs["agent_id"],
            "status": "queued",
            "current_step": "queued",
            "progress": 0,
        }


class _FakeDashboardRepository:
    def __init__(self, root: Path):
        self.root = root
        self.backend = types.SimpleNamespace(name="sqlite")
        self.deleted = []
        self.status_updates = []
        self.retry_status = "pending_steam_auth"

    def create_customer_instance(self, **kwargs):
        instance_id = "aurora-dayz-001"
        node_id = "remote-node"
        instance_path = self.root / "instances" / node_id / "dayz" / instance_id
        metadata = {
            "instance_id": instance_id,
            "controller_id": "controller-test",
            "agent_id": kwargs["selected_agent_id"],
            "node_id": node_id,
            "game_id": "dayz",
            "customer": {"id": kwargs["customer_id"]},
        }
        return {
            "instance_id": instance_id,
            "name": "Aurora DayZ",
            "instance_path": instance_path,
            "metadata_path": instance_path / ".dsm" / "instance-metadata.json",
            "metadata": metadata,
            "agent_id": kwargs["selected_agent_id"],
            "node_id": node_id,
            "contract_id": kwargs.get("contract_id"),
        }

    def delete_instance(self, instance_id):
        self.deleted.append(instance_id)

    def reserve_retry(self, instance_id, node_id, game):
        self.status_updates.append((instance_id, "queued"))
        return {
            "runtime_id": "dayz.stable",
            "edition": "default",
            "game_version": "current",
            "build_id": "steam-current",
            "agent_id": "agent-remote",
            "status": self.retry_status,
        }

    def update_instance_status(self, instance_id, status):
        self.status_updates.append((instance_id, status))


class CustomerDistributedProvisioningTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        runtime_dir = self.root / "catalog" / "v2" / "games" / "dayz" / "runtimes"
        runtime_dir.mkdir(parents=True)
        (runtime_dir / "stable.json").write_text(
            json.dumps(
                {
                    "id": "dayz.stable",
                    "game": "dayz",
                    "edition": "default",
                    "variant": "stable",
                    "version": {"strategy": "static", "value": "current", "build": "steam-current"},
                    "artifact": {"provider": "steam", "auth": "required", "package_id": "223350"},
                    "network": {"allocation": "block", "block_size": 10},
                }
            ),
            encoding="utf-8",
        )
        self.repository = _FakeDashboardRepository(self.root)

        class FakeDashboardHandler:
            def do_POST(self):
                return None

        self.legacy = types.SimpleNamespace(
            DashboardHandler=FakeDashboardHandler,
            DSM_ROOT=self.root,
            DATABASE_FILE=self.root / "capivara.db",
            INSTANCE_ROOT=self.root / "instances",
            dashboard_repository=lambda _path: self.repository,
            resolve_instance_placement=lambda _user, _payload, _repo: {
                "agent_id": "agent-remote",
                "region_id": "br-sudeste",
                "datacenter_id": "dc01",
                "score": 100,
                "reason": "eligible",
            },
            start_instance_provisioning=Mock(side_effect=AssertionError("legacy local provisioner must not run")),
            catalog_instance_path=lambda value: str(Path(value).resolve()),
            audit=Mock(),
        )
        _FakeProvisioningRepository.calls = []
        integration.install_customer_instance_creation(self.legacy)

    def tearDown(self):
        self.temp.cleanup()

    def _payload(self):
        return {
            "game": "dayz",
            "runtime_id": "dayz.stable",
            "edition": "default",
            "version": "current",
            "build": "steam-current",
            "contract_id": "contract-dayz",
        }

    def _projection(self, _backend, state, *, root):
        return {
            "status": "queued",
            "stage": "queued",
            "progress": 5,
            "message": "Instalação aguardando o Agent…",
            "provisioning_id": state["provisioning_id"],
            "distributed": True,
        }

    def test_customer_creation_queues_b10_and_never_runs_controller_installer(self):
        with (
            patch.object(integration, "occupied_ports_provider_for_backend", return_value=lambda *args: set()),
            patch.object(
                integration,
                "resolve_catalog_provisioning",
                return_value=(
                    {"game": "dayz", "provider": "steam", "version": "current", "install": {"package_id": "223350"}},
                    {"catalog_runtime_id": "dayz.stable", "catalog_game_id": "dayz"},
                ),
            ) as resolver,
            patch.object(integration, "AgentInstanceProvisioningRepository", _FakeProvisioningRepository),
            patch.object(integration, "project_agent_provisioning", side_effect=self._projection),
        ):
            result = self.legacy.create_customer_instance(
                {"role": "customer", "scope_id": "customer-aurora", "username": "aurora"},
                self._payload(),
            )

        self.assertTrue(result["created"])
        self.assertTrue(result["provision"]["distributed"])
        self.assertEqual(result["provision"]["status"], "queued")
        self.legacy.start_instance_provisioning.assert_not_called()
        self.assertEqual(len(_FakeProvisioningRepository.calls), 1)
        queued = _FakeProvisioningRepository.calls[0]
        self.assertEqual(queued["agent_id"], "agent-remote")
        self.assertEqual(queued["instance_id"], "aurora-dayz-001")
        self.assertEqual(queued["environment_id"], "dayz.stable")
        self.assertEqual(queued["desired_state"], "stopped")
        self.assertEqual(queued["requested_by"], "aurora")
        resolver.assert_called_once()

        instance_path = self.root / "instances" / "remote-node" / "dayz" / "aurora-dayz-001"
        self.assertTrue((instance_path / ".dsm" / "instance-metadata.json").is_file())
        self.assertFalse((instance_path / "serverfiles").exists())
        self.assertFalse((self.root / "game-data").exists())

    def test_retry_of_legacy_pending_steam_auth_is_requeued_to_remote_agent(self):
        instance = self.root / "instances" / "remote-node" / "dayz" / "aurora-dayz-001"
        instance.mkdir(parents=True)
        with (
            patch.object(
                integration,
                "resolve_catalog_provisioning",
                return_value=(
                    {"game": "dayz", "provider": "steam", "version": "current", "install": {"package_id": "223350"}},
                    {"catalog_runtime_id": "dayz.stable", "catalog_game_id": "dayz"},
                ),
            ),
            patch.object(integration, "AgentInstanceProvisioningRepository", _FakeProvisioningRepository),
            patch.object(integration, "project_agent_provisioning", side_effect=self._projection),
        ):
            result = self.legacy.retry_instance_provisioning(
                {"role": "customer", "scope_id": "customer-aurora", "username": "aurora"},
                instance,
            )

        self.assertTrue(result["retried"])
        self.assertEqual(result["provision"]["status"], "queued")
        self.assertEqual(_FakeProvisioningRepository.calls[-1]["agent_id"], "agent-remote")
        self.legacy.start_instance_provisioning.assert_not_called()
        self.legacy.audit.assert_called_once()


    def test_customer_creation_grants_manager_access_before_enqueue(self):
        events = []

        class FakeTeamRepository:
            def __init__(self, backend):
                self.backend = backend

            def set_instance_access(
                self,
                customer_reference,
                username,
                instance_id,
                permission_profile,
            ):
                events.append(
                    (
                        "access",
                        customer_reference,
                        username,
                        instance_id,
                        permission_profile,
                    )
                )

        class OrderedProvisioningRepository(_FakeProvisioningRepository):
            def enqueue(self, **kwargs):
                events.append(("enqueue", kwargs["instance_id"]))
                return super().enqueue(**kwargs)

        with (
            patch.object(
                integration,
                "occupied_ports_provider_for_backend",
                return_value=lambda *args: set(),
            ),
            patch.object(
                integration,
                "require_port_pool_preflight",
                return_value=None,
            ),
            patch.object(
                integration,
                "resolve_catalog_resource_policy",
                return_value=(
                    "low",
                    {},
                    {
                        "cpu_cores": 2,
                        "memory_mb": 6144,
                        "storage_mb": 30720,
                    },
                ),
            ),
            patch.object(
                integration,
                "normalize_resource_policy",
                return_value=types.SimpleNamespace(
                    placement_resources=lambda: {}
                ),
            ),
            patch.object(
                integration,
                "resolve_catalog_provisioning",
                return_value=(
                    {
                        "game": "dayz",
                        "provider": "steam",
                        "version": "current",
                        "install": {"package_id": "223350"},
                    },
                    {
                        "catalog_runtime_id": "dayz.stable",
                        "catalog_game_id": "dayz",
                    },
                ),
            ),
            patch.object(
                integration,
                "CustomerTeamRepository",
                FakeTeamRepository,
            ),
            patch.object(
                integration,
                "AgentInstanceProvisioningRepository",
                OrderedProvisioningRepository,
            ),
            patch.object(
                integration,
                "project_agent_provisioning",
                side_effect=self._projection,
            ),
        ):
            result = self.legacy.create_customer_instance(
                {
                    "role": "customer",
                    "scope_id": 1,
                    "username": "aurora",
                },
                self._payload(),
            )

        self.assertTrue(result["created"])
        self.assertEqual(events[0], (
            "access",
            1,
            "aurora",
            "aurora-dayz-001",
            "manager",
        ))
        self.assertEqual(
            events[1],
            ("enqueue", "aurora-dayz-001"),
        )

    def test_customer_creation_rolls_back_when_enqueue_fails(self):
        events = []

        class FakeTeamRepository:
            def __init__(self, backend):
                self.backend = backend

            def set_instance_access(
                self,
                customer_reference,
                username,
                instance_id,
                permission_profile,
            ):
                events.append(("access", instance_id))

        class FailingProvisioningRepository:
            def __init__(self, backend):
                self.backend = backend

            def initialize(self):
                return None

            def enqueue(self, **kwargs):
                events.append(("enqueue", kwargs["instance_id"]))
                raise RuntimeError("forced enqueue failure")

        with (
            patch.object(
                integration,
                "occupied_ports_provider_for_backend",
                return_value=lambda *args: set(),
            ),
            patch.object(
                integration,
                "require_port_pool_preflight",
                return_value=None,
            ),
            patch.object(
                integration,
                "resolve_catalog_resource_policy",
                return_value=(
                    "low",
                    {},
                    {
                        "cpu_cores": 2,
                        "memory_mb": 6144,
                        "storage_mb": 30720,
                    },
                ),
            ),
            patch.object(
                integration,
                "normalize_resource_policy",
                return_value=types.SimpleNamespace(
                    placement_resources=lambda: {}
                ),
            ),
            patch.object(
                integration,
                "resolve_catalog_provisioning",
                return_value=(
                    {
                        "game": "dayz",
                        "provider": "steam",
                        "version": "current",
                        "install": {"package_id": "223350"},
                    },
                    {
                        "catalog_runtime_id": "dayz.stable",
                        "catalog_game_id": "dayz",
                    },
                ),
            ),
            patch.object(
                integration,
                "CustomerTeamRepository",
                FakeTeamRepository,
            ),
            patch.object(
                integration,
                "AgentInstanceProvisioningRepository",
                FailingProvisioningRepository,
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "forced enqueue failure",
            ):
                self.legacy.create_customer_instance(
                    {
                        "role": "customer",
                        "scope_id": 1,
                        "username": "aurora",
                    },
                    self._payload(),
                )

        self.assertEqual(events, [
            ("access", "aurora-dayz-001"),
            ("enqueue", "aurora-dayz-001"),
        ])
        self.assertEqual(
            self.repository.deleted,
            ["aurora-dayz-001"],
        )


if __name__ == "__main__":
    unittest.main()
