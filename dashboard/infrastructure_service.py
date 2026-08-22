#!/usr/bin/env python3
"""Compose dashboard infrastructure topology from persistence records."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT_DIR / "database"
for path in (ROOT_DIR, DATABASE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from core.placement_readiness import readiness_snapshot
from infrastructure_repository import InfrastructureRepository


class InfrastructureService:
    """Build Region -> Datacenter -> Agent views for one Controller.

    Persistence remains in InfrastructureRepository. This service owns tree
    composition, derived readiness and keeps unplaced Agents visible without
    inventing a fake geographic location.
    """

    def __init__(self, repository: InfrastructureRepository):
        self.repository = repository

    @staticmethod
    def _location_record(agent: dict[str, Any]) -> dict[str, Any] | None:
        if (
            agent.get("datacenter_id") is None
            and agent.get("location_status") is None
        ):
            return None

        return {
            "datacenter_id": agent.get("datacenter_id"),
            "status": agent.get("location_status"),
        }

    @classmethod
    def _agent_node(
        cls,
        controller: dict[str, Any],
        agent: dict[str, Any],
        datacenter: dict[str, Any] | None,
        region: dict[str, Any] | None,
        instance_count: int,
    ) -> dict[str, Any]:
        readiness = readiness_snapshot(
            controller,
            agent,
            cls._location_record(agent),
            datacenter,
            region,
        )

        return {
            "type": "agent",
            "id": agent["id"],
            "name": agent["name"],
            "node_id": agent["node_id"],
            "status": agent["status"],
            "location_status": agent.get("location_status"),
            "public_host": agent.get("public_host"),
            "topology_state": readiness["topology_state"],
            "placement_ready": readiness["placement_ready"],
            "children_count": instance_count,
        }

    @staticmethod
    def _datacenter_node(datacenter: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "datacenter",
            "id": datacenter["id"],
            "region_id": datacenter["region_id"],
            "name": datacenter["name"],
            "status": datacenter["status"],
            "provider": datacenter.get("provider"),
            "city": datacenter.get("city"),
            "country_code": datacenter.get("country_code"),
            "latitude": datacenter.get("latitude"),
            "longitude": datacenter.get("longitude"),
            "children": [],
        }

    @staticmethod
    def _region_node(region: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "region",
            "id": region["id"],
            "name": region["name"],
            "status": region["status"],
            "country_code": region.get("country_code"),
            "continent_code": region.get("continent_code"),
            "latitude": region.get("latitude"),
            "longitude": region.get("longitude"),
            "children": [],
        }

    def controller_tree(
        self,
        controller_id: str,
        *,
        active_only: bool = False,
    ) -> dict[str, Any] | None:
        """Return the geographic infrastructure tree for one Controller."""
        controller = self.repository.controller(controller_id)
        if controller is None:
            return None
        if active_only and controller["status"] != "active":
            return None

        regions = self.repository.regions(active_only=active_only)
        datacenters = self.repository.datacenters(active_only=active_only)
        agents = self.repository.agents(
            controller_id=controller_id,
            active_only=active_only,
        )
        counts = self.repository.instance_counts_by_agent(
            controller_id=controller_id,
        )

        region_records = {
            region["id"]: region
            for region in regions
        }
        datacenter_records = {
            datacenter["id"]: datacenter
            for datacenter in datacenters
        }
        region_nodes = {
            region["id"]: self._region_node(region)
            for region in regions
        }
        datacenter_nodes = {
            datacenter["id"]: self._datacenter_node(datacenter)
            for datacenter in datacenters
            if datacenter["region_id"] in region_nodes
        }

        for datacenter in datacenters:
            node = datacenter_nodes.get(datacenter["id"])
            region = region_nodes.get(datacenter["region_id"])
            if node is not None and region is not None:
                region["children"].append(node)

        unplaced: list[dict[str, Any]] = []
        for agent in agents:
            datacenter_id = agent.get("datacenter_id")
            datacenter_record = datacenter_records.get(datacenter_id)
            region_record = None
            if datacenter_record is not None:
                region_record = region_records.get(datacenter_record["region_id"])

            node = self._agent_node(
                controller,
                agent,
                datacenter_record,
                region_record,
                counts.get(str(agent["id"]), 0),
            )
            datacenter = datacenter_nodes.get(datacenter_id)
            if datacenter is None:
                unplaced.append(node)
            else:
                datacenter["children"].append(node)

        for datacenter in datacenter_nodes.values():
            datacenter["children_count"] = len(datacenter["children"])
        for region in region_nodes.values():
            region["children_count"] = len(region["children"])

        tree = {
            "type": "controller",
            "id": controller["id"],
            "name": controller["name"],
            "status": controller["status"],
            "children": list(region_nodes.values()),
            "unplaced_agents": unplaced,
        }
        tree["children_count"] = len(tree["children"])
        tree["unplaced_agent_count"] = len(unplaced)
        return tree
