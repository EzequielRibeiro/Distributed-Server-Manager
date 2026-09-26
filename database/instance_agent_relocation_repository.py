#!/usr/bin/env python3
"""Fail-closed, durable, offline relocation of an instance between Agents.

The source runtime and its ports are retained until an administrator separately
decommissions it. No Agent gets a second running copy during relocation.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import tarfile
import uuid

from alert_repository import AlertSession, dialect_for_backend
from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from agent_runtime_repository import AgentRuntimeRepository
from agent_instance_runtime_repository import AgentInstanceRuntimeRepository
from artifact_transfer_repository import ArtifactTransferRepository
from backup_repository import BackupRepository
from catalog_provisioning_resolver import resolve_catalog_provisioning, resolve_catalog_resource_policy
from core.network.port_allocator import PortRange, allocate_port_profile
from core.network.port_profile import PortProfile
from core.placement_requirements import requirements_for_instance
from instance_network import occupied_ports_provider_for_backend
from placement_eligibility import evaluate_agent_for_placement
from agent_runtime_repository import AgentRuntimeRepository
from agent_instance_runtime_repository import AgentInstanceRuntimeRepository as RuntimeCommands
from universal_event_repository import UniversalEventRepository

ACTIVE = frozenset({
    "queued", "stopping", "backing_up", "exporting", "cutting_over",
    "provisioning", "importing", "restoring", "starting", "verifying",
    "rolling_back", "manual_recovery",
})
TERMINAL = frozenset({"completed", "failed"})
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,190}$")
SHA = re.compile(r"^[0-9a-f]{64}$")


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value):
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _token(value, field):
    value = str(value or "").strip()
    if not TOKEN.fullmatch(value):
        raise ValueError(f"invalid {field}")
    return value


def _ports(raw):
    return [dict(item) for item in json.loads(raw or "[]")]


class RelocationConflict(RuntimeError):
    pass


class InstanceAgentRelocationRepository:
    def __init__(self, backend, root):
        self.backend, self.root = backend, Path(root).resolve()
        self.dialect = dialect_for_backend(backend)
        self.backups = BackupRepository(backend)
        self.transfers = ArtifactTransferRepository(backend, self.root)
        self.lifecycle = RuntimeCommands(backend)
        self.provisioning = AgentInstanceProvisioningRepository(backend)

    @property
    def ph(self):
        return self.dialect.placeholder

    @contextmanager
    def session(self, transaction=False):
        with (self.backend.transaction() if transaction else self.backend.connect()) as connection:
            session = AlertSession(self.backend, connection)
            try:
                yield session
            finally:
                session.close()

    def initialize(self):
        return self.backend.initialize()

    def get(self, relocation_id):
        with self.session() as session:
            row = session.execute(
                f"SELECT * FROM instance_agent_relocations WHERE relocation_id={self.ph}",
                (_token(relocation_id, "relocation_id"),),
            ).fetchone()
        if row is None:
            raise KeyError(relocation_id)
        item = dict(row)
        item["source_ports"] = _ports(item.pop("source_ports_json"))
        item["target_ports"] = _ports(item.pop("target_ports_json"))
        item["source_running"] = bool(item["source_running"])
        return item

    def list_for_instance(self, instance_id, limit=20):
        with self.session() as session:
            rows = session.execute(
                f"SELECT relocation_id FROM instance_agent_relocations WHERE instance_id={self.ph} "
                f"ORDER BY created_at DESC LIMIT {self.ph}",
                (_token(instance_id, "instance_id"), min(100, max(1, int(limit)))),
            ).fetchall()
        return [self.get(row["relocation_id"]) for row in rows]

    def _set(self, relocation_id, **changes):
        if not changes:
            return self.get(relocation_id)
        changes["updated_at"] = _now()
        keys = tuple(changes)
        with self.session(transaction=True) as session:
            session.execute(
                "UPDATE instance_agent_relocations SET " +
                ",".join(f"{key}={self.ph}" for key in keys) +
                f" WHERE relocation_id={self.ph}",
                tuple(changes[key] for key in keys) + (relocation_id,),
            )
        return self.get(relocation_id)

    def _instance_and_agents(self, instance_id, target_agent_id):
        with self.session() as session:
            item = session.execute(
                f"SELECT * FROM instances WHERE id={self.ph}",
                (instance_id,),
            ).fetchone()
            target = session.execute(
                f"SELECT * FROM agents WHERE id={self.ph}",
                (target_agent_id,),
            ).fetchone()
            source = session.execute(
                f"SELECT * FROM agents WHERE id={self.ph}",
                (item["agent_id"],),
            ).fetchone() if item else None
            ports = session.execute(
                f"SELECT name,protocol,port,bind_address FROM instance_ports WHERE instance_id={self.ph} "
                "ORDER BY name,protocol,port",
                (instance_id,),
            ).fetchall() if item else []
        if item is None:
            raise LookupError("instance not found")
        if not source or not target:
            raise LookupError("source or target Agent not found")
        item, source, target = dict(item), dict(source), dict(target)
        if source["id"] == target["id"] or source["node_id"] == target["node_id"]:
            raise ValueError("source and destination must be different hosts")
        if item["controller_id"] != target["controller_id"]:
            raise PermissionError("cross-Controller relocation is not permitted")
        if str(source["status"]).lower() != "active" or str(target["status"]).lower() != "active":
            raise ValueError("both Agents must be active")
        if not ports:
            raise ValueError("instance has no managed port reservations")
        with self.session() as session:
            fingerprints = session.execute(
                f"SELECT agent_id,fingerprint FROM agent_runtime_inventory "
                f"WHERE agent_id IN ({self.ph},{self.ph})",
                (source["id"], target["id"]),
            ).fetchall()
        identities = {str(row["agent_id"]): str(row["fingerprint"] or "").strip()
                      for row in fingerprints}
        if (identities.get(source["id"]) and
                identities[source["id"]] == identities.get(target["id"])):
            raise ValueError("Agents share the same host fingerprint")
        source_host = _json(source["metadata_json"]).get("capivara_host_identity_v1")
        target_host = _json(target["metadata_json"]).get("capivara_host_identity_v1")
        if source_host and target_host and source_host == target_host:
            raise ValueError("Agents belong to the same physical host")
        return item, source, target, [dict(p) for p in ports]

    def _network_plan(self, session, target, profile):
        if profile is None:
            raise ValueError("runtime has no managed network profile")
        ph = self.ph
        if self.dialect.name in {"postgresql", "mysql"}:
            row = session.execute(
                f"SELECT id FROM nodes WHERE id={ph} FOR UPDATE", (target["node_id"],)
            ).fetchone()
            if row is None:
                raise LookupError("destination node is missing")
        rows = session.execute(
            f"SELECT protocol,start_port,end_port FROM agent_port_ranges "
            f"WHERE agent_id={ph} AND status='active'",
            (target["id"],),
        ).fetchall()
        ranges = [PortRange(str(row["protocol"]), int(row["start_port"]), int(row["end_port"])) for row in rows]
        rows = session.execute(
            f"SELECT protocol,port FROM instance_ports WHERE node_id={ph} UNION ALL "
            f"SELECT protocol,port FROM instance_agent_relocation_port_holds WHERE node_id={ph}",
            (target["node_id"], target["node_id"]),
        ).fetchall()
        reserved = {"tcp": set(), "udp": set()}
        for row in rows:
            reserved[row["protocol"]].add(int(row["port"]))
        occupied = {"tcp": set(), "udp": set()}
        provider = occupied_ports_provider_for_backend(self.backend)
        for port_range in ranges:
            occupied[port_range.protocol].update(
                provider(target["id"], target["node_id"], port_range.protocol,
                         port_range.start_port, port_range.end_port)
            )
        allocation = allocate_port_profile(profile, ranges, reserved=reserved, occupied=occupied)
        by_name = {p.name: p for p in profile.ports}
        return [
            {"name": name, "protocol": by_name[name].protocol, "port": port,
             "bind_address": by_name[name].bind_address}
            for name, port in allocation.ports.items()
        ]

    def preflight(self, instance_id, target_agent_id):
        self.initialize()
        instance_id = _token(instance_id, "instance_id")
        target_agent_id = _token(target_agent_id, "target_agent_id")
        item, source, target, source_ports = self._instance_and_agents(instance_id, target_agent_id)
        if str(item["status"]).lower() not in {"online", "stopped"}:
            raise ValueError("instance must be online or stopped before moving")
        with self.session() as session:
            for table, condition in (
                ("instance_agent_relocations", "status NOT IN ('completed','failed')"),
                ("agent_instance_commands", "status IN ('queued','delivered')"),
                ("agent_instance_provisioning", "status IN ('queued','delivered','running')"),
                ("backup_jobs", "status IN ('pending','running')"),
            ):
                existing = session.execute(
                    f"SELECT 1 FROM {table} WHERE instance_id={self.ph} AND {condition} LIMIT 1",
                    (instance_id,),
                ).fetchone()
                if existing:
                    raise RelocationConflict("instance already has an active operation: " + table)
        metadata = _json(item.get("metadata_json"))
        profile_id = str(metadata.get("resource_profile_id") or "").strip() or None
        resource_policy = {}
        if profile_id:
            _, _, policy = resolve_catalog_resource_policy(
                root=self.root, game_id=item["game_id"], resource_profile_id=profile_id,
            )
            from core.effective_resource_policy import normalize_resource_policy
            resource_policy = normalize_resource_policy(policy).placement_resources()
        requirements = requirements_for_instance(
            game_id=item["game_id"], runtime_id=item["runtime_id"],
            resources=resource_policy, catalog_root=self.root,
        )
        eligibility = evaluate_agent_for_placement(
            self.backend, agent_id=target_agent_id, requirements=requirements,
        )
        if not eligibility.eligible:
            raise ValueError("destination Agent is not eligible: " + ",".join(eligibility.reasons))
        source_health = AgentRuntimeRepository(self.backend).snapshot(source["id"])
        if str(source_health.get("health_status") or "").lower() != "online":
            raise ValueError("source Agent must be online")
        source_features = source_health.get("capabilities")
        if not isinstance(source_features, dict) or source_features.get("instance_relocation_fence_v1") is not True:
            raise ValueError("source Agent must be updated to support durable relocation fencing")
        from core.placement_requirements import load_runtime_definition
        runtime = load_runtime_definition(item["runtime_id"], catalog_root=self.root)
        if not runtime:
            raise ValueError("runtime definition not found")
        network = PortProfile.from_mapping(runtime.get("network"))
        with self.session(transaction=True) as session:
            target_ports = self._network_plan(session, target, network)
        manifest_path = str(item.get("manifest_path") or "").strip()
        source_manifest, target_manifest = None, None
        if manifest_path:
            anchor = (self.root / "instances" / source["node_id"]).resolve()
            relative = Path(manifest_path).resolve().relative_to(anchor)
            source_manifest = manifest_path
            target_manifest = str(self.root / "instances" / target["node_id"] / relative)
        return {
            "instance_id": instance_id, "source_agent_id": source["id"],
            "source_node_id": source["node_id"], "target_agent_id": target["id"],
            "target_node_id": target["node_id"], "source_ports": source_ports,
            "target_ports": target_ports, "source_running": item["status"].lower() == "online",
            "game_id": item["game_id"], "runtime_id": item["runtime_id"],
            "game_version": item.get("game_version"), "build_id": item.get("build_id"),
            "resource_profile_id": profile_id, "source_manifest_path": source_manifest,
            "target_manifest_path": target_manifest, "estimated_downtime": "offline transfer and provisioning",
            "source_retained": True,
        }

    def enqueue(self, instance_id, target_agent_id, *, requested_by, confirmation):
        if str(confirmation or "") != str(instance_id):
            raise ValueError("confirmation must exactly match the instance ID")
        plan = self.preflight(instance_id, target_agent_id)
        relocation_id = "relocation-" + uuid.uuid4().hex
        now = _now()
        with self.session(transaction=True) as session:
            current = session.execute(
                f"SELECT agent_id,node_id FROM instances WHERE id={self.ph}" +
                (" FOR UPDATE" if self.dialect.name in {"postgresql", "mysql"} else ""),
                (plan["instance_id"],),
            ).fetchone()
            if current is None or current["agent_id"] != plan["source_agent_id"]:
                raise RelocationConflict("instance ownership changed")
            existing = session.execute(
                f"SELECT 1 FROM instance_agent_relocations WHERE instance_id={self.ph} "
                "AND status NOT IN ('completed','failed') LIMIT 1",
                (plan["instance_id"],),
            ).fetchone()
            if existing:
                raise RelocationConflict("instance relocation already in progress")
            target = session.execute(
                f"SELECT id,node_id FROM agents WHERE id={self.ph}",
                (plan["target_agent_id"],),
            ).fetchone()
            if not target:
                raise ValueError("target Agent disappeared")
            from core.placement_requirements import load_runtime_definition
            definition = load_runtime_definition(plan["runtime_id"], catalog_root=self.root)
            refreshed = self._network_plan(session, dict(target), PortProfile.from_mapping(definition["network"]))
            cols = (
                "relocation_id", "instance_id", "source_agent_id", "source_node_id",
                "target_agent_id", "target_node_id", "source_ports_json", "target_ports_json",
                "source_running", "source_manifest_path", "source_metadata_json", "target_manifest_path",
                "status", "requested_by", "created_at", "updated_at",
            )
            values = (
                relocation_id, plan["instance_id"], plan["source_agent_id"], plan["source_node_id"],
                plan["target_agent_id"], plan["target_node_id"],
                json.dumps(plan["source_ports"], sort_keys=True), json.dumps(refreshed, sort_keys=True),
                1 if plan["source_running"] else 0,
                plan["source_manifest_path"], json.dumps(_json(self._instance_and_agents(plan["instance_id"], plan["target_agent_id"])[0]["metadata_json"]), sort_keys=True), plan["target_manifest_path"],
                "queued", str(requested_by or "admin").strip()[:191], now, now,
            )
            session.execute(
                "INSERT INTO instance_agent_relocations(" + ",".join(cols) + ") VALUES (" +
                self.dialect.parameters(len(cols)) + ")", values,
            )
            for port in refreshed:
                session.execute(
                    "INSERT INTO instance_agent_relocation_port_holds "
                    f"(relocation_id,node_id,protocol,port) VALUES ({self.dialect.parameters(4)})",
                    (relocation_id, plan["target_node_id"], port["protocol"], port["port"]),
                )
        item = self.get(relocation_id)
        self._event(item, "INSTANCE_AGENT_RELOCATION_QUEUED", "Administrator authorized offline Agent relocation")
        return item

    def _ownership(self, item):
        with self.session() as session:
            row = session.execute(
                f"SELECT agent_id,status,metadata_json,game_id,runtime_id,game_version,build_id,customer_id "
                f"FROM instances WHERE id={self.ph}", (item["instance_id"],)
            ).fetchone()
        if row is None:
            raise LookupError("relocating instance disappeared")
        return dict(row)

    def _hold_release(self, relocation_id):
        with self.session(transaction=True) as session:
            session.execute(
                f"DELETE FROM instance_agent_relocation_port_holds WHERE relocation_id={self.ph}",
                (relocation_id,),
            )

    def _event(self, item, kind, message):
        try:
            UniversalEventRepository(self.backend).publish({
                "event_id": f'{item["relocation_id"]}:{kind}',
                "event_type": kind, "source": "controller.instance-agent-relocation",
                "source_id": item["relocation_id"], "severity": "critical" if "FAILED" in kind else "info",
                "agent_id": item["target_agent_id"], "instance_id": item["instance_id"],
                "correlation_id": item["relocation_id"],
                "actor_type": "user", "actor_id": item["requested_by"],
                "data": {"message": str(message)[:500], "source_agent_id": item["source_agent_id"],
                         "target_agent_id": item["target_agent_id"]},
            })
        except Exception:
            pass  # operational event failure cannot bypass migration safety

    @staticmethod
    def _observed(command):
        envelope = command.get("result") if isinstance(command.get("result"), dict) else {}
        # Real Agent reports are stored as the complete command envelope:
        # {"status":"completed","result":{"observed_state":"stopped",...}}.
        # Old tests and local transports may store the inner payload directly.
        result = envelope.get("result") if isinstance(envelope.get("result"), dict) else envelope
        return str(result.get("observed_state") or result.get("state") or "").lower()

    @staticmethod
    def _lifecycle_operation(item, action, agent_id):
        if agent_id == item["source_agent_id"]:
            names = {
                "fence": ("stop", "source-fence"),
                "unfence": ("stop", "source-unfence"),
                "start": ("start", "source-start"),
            }
        elif agent_id == item["target_agent_id"]:
            names = {"stop": ("stop", "target-stop"), "start": ("start", "target-start")}
        else:
            raise PermissionError("Agent is not participating in relocation")
        if action not in names:
            raise ValueError("unsupported relocation phase")
        verb, phase = names[action]
        return verb, "relocation:" + item["relocation_id"] + ":" + phase

    def _existing_lifecycle(self, item, action, agent_id):
        verb, actor = self._lifecycle_operation(item, action, agent_id)
        with self.session() as session:
            row = session.execute(
                f"SELECT command_id FROM agent_instance_commands WHERE agent_id={self.ph} "
                f"AND instance_id={self.ph} AND action={self.ph} AND requested_by={self.ph} "
                "ORDER BY created_at DESC LIMIT 1",
                (agent_id, item["instance_id"], verb, actor),
            ).fetchone()
        return self.lifecycle.snapshot(str(row["command_id"])) if row else None

    def _lifecycle(self, item, action, agent_id):
        verb, actor = self._lifecycle_operation(item, action, agent_id)
        prior = self._existing_lifecycle(item, action, agent_id)
        if prior:
            return prior
        command = self.lifecycle.enqueue(
            agent_id=agent_id, instance_id=item["instance_id"], action=verb,
            requested_by=actor,
        )
        if command.get("requested_by") != actor:
            raise RelocationConflict("another lifecycle operation was already queued")
        return command

    def _existing_transfer(self, item, direction):
        with self.session() as session:
            row = session.execute(
                f"SELECT transfer_id FROM artifact_transfers WHERE requested_by={self.ph} "
                f"AND instance_id={self.ph} AND agent_id={self.ph} AND direction={self.ph} "
                "ORDER BY created_at DESC LIMIT 1",
                ("relocation:" + item["relocation_id"], item["instance_id"],
                 item["source_agent_id"] if direction == "agent_to_controller" else item["target_agent_id"],
                 direction),
            ).fetchone()
        return self.transfers.get(row["transfer_id"]) if row else None

    @staticmethod
    def _validate_artifact(path, item):
        # Do not trust Agent-provided paths or manifests. A copied archive must
        # match both the job checksum and the transfer checksum before cutover.
        expected = str(item.get("backup_sha256") or "").lower()
        if not SHA.fullmatch(expected):
            raise ValueError("missing authenticated backup digest")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for part in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(part)
        if digest.hexdigest() != expected:
            raise ValueError("relocation backup digest mismatch")
        with tarfile.open(path, "r:*") as archive:
            members = archive.getmembers()
            if not members or len(members) > 250000:
                raise ValueError("backup archive is empty or exceeds entry limit")
            manifest_members = [m for m in members if m.name == ".capivara-backup-manifest.json"]
            if len(manifest_members) != 1:
                raise ValueError("backup archive manifest missing or duplicated")
            for member in members:
                member_name = Path(member.name)
                if member.issym() or member.islnk() or member.isdev() or (
                    member_name.is_absolute() or ".." in member_name.parts
                ):
                    raise ValueError("backup contains unsafe archive members")
                if not (member.isfile() or member.isdir()):
                    raise ValueError("backup contains unsupported archive member")
            manifest = json.load(archive.extractfile(manifest_members[0]))
        if (manifest.get("kind") != "CapivaraInstanceBackup" or
                manifest.get("backup_format") != "capivara-instance" or
                str(manifest.get("source_instance") or "") != item["instance_id"] or
                str(manifest.get("backup_id") or "") != item["backup_id"] or
                str(manifest.get("game_id") or "") != item["game_id"] or
                str(manifest.get("runtime_id") or "") != item["runtime_id"]):
            raise ValueError("backup manifest does not match the source instance")

    def _cutover(self, item):
        owner = self._ownership(item)
        if owner["agent_id"] != item["source_agent_id"]:
            if owner["agent_id"] == item["target_agent_id"]:
                # Previous process committed the handoff before losing response.
                return self.get(item["relocation_id"])
            raise RelocationConflict("instance Agent changed unexpectedly")
        expected = {(p["name"], p["protocol"], int(p["port"])) for p in item["source_ports"]}
        # Verify the destination still has an up-to-date inventory without
        # taking a transaction lock around a health refresh.
        target = AgentRuntimeRepository(self.backend).snapshot(item["target_agent_id"])
        if target.get("health_status") != "online":
            raise ValueError("destination Agent is no longer online")
        with self.session() as session:
            agent = session.execute(
                f"SELECT status FROM agents WHERE id={self.ph}", (item["target_agent_id"],)
            ).fetchone()
        if not agent or agent["status"] != "active":
            raise ValueError("destination Agent must remain active")
        provider = occupied_ports_provider_for_backend(self.backend)
        checked = {}
        for port in item["target_ports"]:
            key = port["protocol"], int(port["port"])
            if key not in checked:
                checked[key] = provider(item["target_agent_id"], item["target_node_id"], key[0], key[1], key[1])
            if key[1] in checked[key]:
                raise RelocationConflict(f'destination {key[0]} port {key[1]} became occupied')
        original = _json(item["source_metadata_json"])
        updated = dict(original)
        updated["agent_id"] = item["target_agent_id"]
        network = dict(updated.get("network") or {})
        network["ports"] = {p["name"]: int(p["port"]) for p in item["target_ports"]}
        updated["network"] = network
        with self.session(transaction=True) as session:
            current = session.execute(
                f"SELECT agent_id,node_id FROM instances WHERE id={self.ph}" +
                (" FOR UPDATE" if self.dialect.name in {"postgresql", "mysql"} else ""),
                (item["instance_id"],),
            ).fetchone()
            if not current or current["agent_id"] != item["source_agent_id"]:
                raise RelocationConflict("instance was moved by another operation")
            ports = session.execute(
                f"SELECT name,protocol,port FROM instance_ports WHERE instance_id={self.ph}",
                (item["instance_id"],),
            ).fetchall()
            if {(p["name"], p["protocol"], int(p["port"])) for p in ports} != expected:
                raise RelocationConflict("source port reservations changed")
            held = session.execute(
                f"SELECT protocol,port FROM instance_agent_relocation_port_holds "
                f"WHERE relocation_id={self.ph} AND node_id={self.ph}",
                (item["relocation_id"], item["target_node_id"]),
            ).fetchall()
            if {(p["protocol"], int(p["port"])) for p in held} != {
                (p["protocol"], int(p["port"])) for p in item["target_ports"]
            }:
                raise RelocationConflict("destination port reservation was lost")
            for source in item["source_ports"]:
                session.execute(
                    "INSERT INTO instance_agent_relocation_port_holds "
                    f"(relocation_id,node_id,protocol,port) VALUES ({self.dialect.parameters(4)})",
                    (item["relocation_id"], item["source_node_id"], source["protocol"], source["port"]),
                )
            destination = {(p["name"], p["protocol"]): p for p in item["target_ports"]}
            for source in item["source_ports"]:
                dest = destination[(source["name"], source["protocol"])]
                session.execute(
                    f"UPDATE instance_ports SET node_id={self.ph},port={self.ph},bind_address={self.ph} "
                    f"WHERE instance_id={self.ph} AND name={self.ph} AND protocol={self.ph}",
                    (item["target_node_id"], dest["port"], dest["bind_address"],
                     item["instance_id"], source["name"], source["protocol"]),
                )
            session.execute(
                f"UPDATE instances SET agent_id={self.ph},node_id={self.ph},status='stopped',"
                f"metadata_json={self.ph},manifest_path={self.ph} WHERE id={self.ph}",
                (item["target_agent_id"], item["target_node_id"], json.dumps(updated, sort_keys=True),
                 item["target_manifest_path"], item["instance_id"]),
            )
            session.execute(
                f"UPDATE backup_policies SET agent_id={self.ph} WHERE instance_id={self.ph}",
                (item["target_agent_id"], item["instance_id"]),
            )
            session.execute(
                f"DELETE FROM instance_agent_relocation_port_holds "
                f"WHERE relocation_id={self.ph} AND node_id={self.ph}",
                (item["relocation_id"], item["target_node_id"]),
            )
            session.execute(
                f"UPDATE instance_agent_relocations SET status='provisioning',updated_at={self.ph} "
                f"WHERE relocation_id={self.ph} AND status='cutting_over'",
                (_now(), item["relocation_id"]),
            )
        self._event(item, "INSTANCE_AGENT_RELOCATION_CUTOVER", "Controller switched instance to destination Agent")
        return self.get(item["relocation_id"])

    def _undo_cutover(self, item):
        original = _json(item["source_metadata_json"])
        with self.session(transaction=True) as session:
            current = session.execute(
                f"SELECT agent_id FROM instances WHERE id={self.ph}" +
                (" FOR UPDATE" if self.dialect.name in {"postgresql", "mysql"} else ""),
                (item["instance_id"],),
            ).fetchone()
            if not current or current["agent_id"] != item["target_agent_id"]:
                raise RelocationConflict("rollback requires exclusive ownership by destination")
            holds = session.execute(
                f"SELECT protocol,port FROM instance_agent_relocation_port_holds "
                f"WHERE relocation_id={self.ph} AND node_id={self.ph}",
                (item["relocation_id"], item["source_node_id"]),
            ).fetchall()
            if {(p["protocol"], int(p["port"])) for p in holds} != {
                (p["protocol"], int(p["port"])) for p in item["source_ports"]
            }:
                raise RelocationConflict("original source port hold was lost")
            old = {(p["name"], p["protocol"]): p for p in item["source_ports"]}
            for dest in item["target_ports"]:
                source = old[(dest["name"], dest["protocol"])]
                session.execute(
                    f"UPDATE instance_ports SET node_id={self.ph},port={self.ph},bind_address={self.ph} "
                    f"WHERE instance_id={self.ph} AND name={self.ph} AND protocol={self.ph}",
                    (item["source_node_id"], source["port"], source["bind_address"],
                     item["instance_id"], dest["name"], dest["protocol"]),
                )
            session.execute(
                f"UPDATE instances SET agent_id={self.ph},node_id={self.ph},"
                f"metadata_json={self.ph},manifest_path={self.ph},status='stopped' WHERE id={self.ph}",
                (item["source_agent_id"], item["source_node_id"], json.dumps(original, sort_keys=True),
                 item["source_manifest_path"], item["instance_id"]),
            )
            session.execute(
                f"UPDATE backup_policies SET agent_id={self.ph} WHERE instance_id={self.ph}",
                (item["source_agent_id"], item["instance_id"]),
            )
        self._event(item, "INSTANCE_AGENT_RELOCATION_REVERTED", "Ownership returned to original Agent")

    def _abort(self, item, reason):
        message = str(reason)[:1400]
        owner = self._ownership(item)["agent_id"]
        if owner not in {item["source_agent_id"], item["target_agent_id"]}:
            item = self._set(item["relocation_id"], status="manual_recovery", last_error=message)
        else:
            item = self._set(item["relocation_id"], status="rolling_back", last_error=message)
        self._event(item, "INSTANCE_AGENT_RELOCATION_FAILED", message)
        return item

    def _finish(self, item, status):
        self._hold_release(item["relocation_id"]) if status == "failed" else None
        state = self._set(item["relocation_id"], status=status, completed_at=_now())
        self._event(state, "INSTANCE_AGENT_RELOCATION_COMPLETED" if status == "completed"
                    else "INSTANCE_AGENT_RELOCATION_ROLLED_BACK", status)
        return state

    def _rollback(self, item):
        owner = self._ownership(item)
        if owner["agent_id"] == item["source_agent_id"]:
            prior_fence = self._existing_lifecycle(item, "fence", item["source_agent_id"])
            if not prior_fence:
                return self._finish(item, "failed")
            parked = prior_fence
            if parked["status"] == "failed" or (
                parked["status"] == "completed" and self._observed(parked) != "stopped"
            ):
                return self._set(item["relocation_id"], status="manual_recovery",
                                 last_error="original fence not confirmed; verify Agent state")
            if parked["status"] != "completed":
                return item
            unpark = self._lifecycle(item, "unfence", item["source_agent_id"])
            if not item.get("unfence_command_id"):
                item = self._set(item["relocation_id"], unfence_command_id=unpark["command_id"])
            if unpark["status"] == "failed" or (
                unpark["status"] == "completed" and self._observed(unpark) != "stopped"
            ):
                return self._set(item["relocation_id"], status="manual_recovery",
                                 last_error="source startup restoration not confirmed")
            if unpark["status"] != "completed":
                return item
            if item["source_running"]:
                start = self._lifecycle(item, "start", item["source_agent_id"])
                if start["status"] == "failed" or (
                    start["status"] == "completed" and self._observed(start) != "running"
                ):
                    return self._set(item["relocation_id"], status="manual_recovery",
                                     last_error="source restart not confirmed")
                if start["status"] != "completed":
                    return item
            return self._finish(item, "failed")
        if owner["agent_id"] != item["target_agent_id"]:
            return self._set(item["relocation_id"], status="manual_recovery",
                             last_error="relocation ownership changed unexpectedly")
        # Unknown provisioning failures can leave an untracked partial target
        # process. Refuse to bring up source until an operator proves target
        # inactive; never risk two active game servers.
        if not item.get("provisioning_id"):
            return self._set(item["relocation_id"], status="manual_recovery",
                             last_error="target provisioning untracked; inspect destination before recovery")
        provision = self.provisioning.snapshot(item["provisioning_id"])
        if provision.get("status") != "completed":
            return self._set(item["relocation_id"], status="manual_recovery",
                             last_error="target provisioning did not complete; verify target stopped manually")
        if item.get("start_command_id"):
            previous_start = self.lifecycle.snapshot(item["start_command_id"])
            if previous_start["status"] not in {"completed", "failed"}:
                return item
        command = self._lifecycle(item, "stop", item["target_agent_id"])
        if not item.get("rollback_command_id"):
            item = self._set(item["relocation_id"], rollback_command_id=command["command_id"])
        if command["status"] == "failed" or (
            command["status"] == "completed" and self._observed(command) != "stopped"
        ):
            return self._set(item["relocation_id"], status="manual_recovery",
                             last_error="target stop not confirmed; original must remain offline")
        if command["status"] != "completed":
            return item
        self._undo_cutover(item)
        # The next reconciliation cycle restores the source's original
        # boot policy, then restarts it only if it was originally running.
        return self.get(item["relocation_id"])

    def reconcile(self, relocation_id):
        item = self.get(relocation_id)
        if item["status"] in TERMINAL | {"manual_recovery"}:
            return item
        # Heartbeats and flush calls can overlap. Claim a durable, short-lived
        # lease before issuing any side-effect. Stale leases recover after
        # Controller interruption; individual phase operations are idempotent.
        token = uuid.uuid4().hex
        epoch = int(datetime.now(timezone.utc).timestamp())
        with self.session(transaction=True) as session:
            cursor = session.execute(
                f"UPDATE instance_agent_relocations SET lease_until={self.ph},"
                f"lease_token={self.ph} WHERE relocation_id={self.ph} AND lease_until<{self.ph} "
                "AND status NOT IN ('completed','failed','manual_recovery')",
                (epoch + 3600, token, relocation_id, epoch),
            )
            if getattr(cursor, "rowcount", 0) != 1:
                return item
        try:
            item = self.get(relocation_id)
            try:
                return self._step(item)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                return self._abort(item, exc)
        finally:
            with self.session(transaction=True) as session:
                session.execute(
                    f"UPDATE instance_agent_relocations SET lease_until=0,lease_token=NULL "
                    f"WHERE relocation_id={self.ph} AND lease_token={self.ph}",
                    (relocation_id, token),
                )

    def _step(self, item):
        rid, iid = item["relocation_id"], item["instance_id"]
        actor = "relocation:" + rid
        state = item["status"]
        if state == "rolling_back":
            return self._rollback(item)
        if state == "queued":
            command = self._lifecycle(item, "fence", item["source_agent_id"])
            return self._set(rid, status="stopping", stop_command_id=command["command_id"])
        if state == "stopping":
            command = self.lifecycle.snapshot(item["stop_command_id"])
            if command["status"] == "failed":
                return self._set(rid, status="manual_recovery",
                                 last_error=command.get("last_error") or "source fencing failed")
            if command["status"] != "completed":
                return item
            envelope = command.get("result") if isinstance(command.get("result"), dict) else {}
            proof = envelope.get("result") if isinstance(envelope.get("result"), dict) else envelope
            if self._observed(command) != "stopped" or proof.get("fenced") is not True:
                return self._set(rid, status="manual_recovery",
                                 last_error="source Agent did not prove durable fencing; no transfer allowed")
            job = next((
                job for job in self.backups.list_jobs(instance_id=iid, limit=300)
                if job.get("reason") == "agent_relocation:" + rid and job.get("action") == "create"
            ), None) or self.backups.request(
                iid, action="create", reason="agent_relocation:" + rid, requested_by=actor,
            )
            return self._set(rid, status="backing_up", backup_job_id=job["command_id"])
        if state == "backing_up":
            job = self.backups.get_job(item["backup_job_id"])
            if not job or job.get("status") == "failed":
                return self._abort(item, (job or {}).get("last_error") or "source backup failed")
            if job["status"] != "completed":
                return item
            backup_id, sha = str(job.get("backup_id") or ""), str(job.get("sha256") or "").lower()
            if not TOKEN.fullmatch(backup_id) or not SHA.fullmatch(sha) or int(job.get("size_bytes") or 0) <= 0:
                raise ValueError("source backup is not checksummed and nonempty")
            transfer = self._existing_transfer(item, "agent_to_controller")
            if transfer is None:
                filename = Path(str(job.get("artifact_path") or f"{backup_id}.tar.gz")).name
                if not filename.endswith((".tar", ".tar.gz", ".tgz")):
                    raise ValueError("source backup archive extension is unsupported")
                transfer = self.transfers.create(
                    agent_id=item["source_agent_id"], instance_id=iid,
                    customer_id=self._ownership(item).get("customer_id"),
                    direction="agent_to_controller", purpose="backup_export",
                    filename=filename, source_ref=backup_id,
                    requested_by=actor, ttl_hours=72,
                )
            return self._set(rid, status="exporting", backup_id=backup_id,
                             backup_sha256=sha, export_transfer_id=transfer["transfer_id"])
        if state == "exporting":
            transfer = self.transfers.get(item["export_transfer_id"])
            if transfer["status"] in {"failed", "cancelled", "expired"}:
                return self._abort(item, transfer.get("last_error") or "backup export failed")
            if transfer["status"] != "completed":
                return item
            job = self.backups.get_job(item["backup_job_id"])
            if (str(transfer.get("sha256") or "").lower() != item["backup_sha256"] or
                    int(transfer.get("size_bytes") or 0) != int(job.get("size_bytes") or 0)):
                raise ValueError("backup export checksum or length mismatch")
            path, _ = self.transfers.controller_artifact(item["export_transfer_id"])
            self._validate_artifact(path, {**item, "game_id": self._ownership(item)["game_id"],
                                           "runtime_id": self._ownership(item)["runtime_id"]})
            return self._set(rid, status="cutting_over")
        if state == "cutting_over":
            # Revalidate durable fencing even if the Controller restarted after
            # backup verification. An old Agent that merely stopped is unsafe.
            fence = self._existing_lifecycle(item, "fence", item["source_agent_id"])
            if not fence or fence["status"] != "completed":
                raise RelocationConflict("durable source fence command missing")
            envelope = fence.get("result") if isinstance(fence.get("result"), dict) else {}
            proof = envelope.get("result") if isinstance(envelope.get("result"), dict) else envelope
            if self._observed(fence) != "stopped" or proof.get("fenced") is not True:
                raise RelocationConflict("durable source fencing acknowledgement missing")
            return self._cutover(item)
        if state == "provisioning":
            owner = self._ownership(item)
            if owner["agent_id"] != item["target_agent_id"]:
                raise RelocationConflict("destination no longer owns the instance")
            if not item.get("provisioning_id"):
                from core.placement_requirements import load_runtime_definition
                from customer_instance_creation import _selector
                definition = load_runtime_definition(owner["runtime_id"], catalog_root=self.root)
                if not definition:
                    raise ValueError("selected runtime definition unavailable")
                selector = _selector(definition, owner.get("game_version"), owner.get("build_id"))
                selection, configuration = resolve_catalog_provisioning(
                    environment_id=owner["runtime_id"], selector=selector, selection={},
                    configuration=({"resource_profile_id": _json(owner["metadata_json"])["resource_profile_id"]}
                                   if _json(owner["metadata_json"]).get("resource_profile_id") else {}),
                    root=self.root,
                )
                with self.session() as session:
                    pending = session.execute(
                        f"SELECT provisioning_id FROM agent_instance_provisioning "
                        f"WHERE instance_id={self.ph} AND agent_id={self.ph} AND requested_by={self.ph} "
                        "ORDER BY created_at DESC LIMIT 1",
                        (iid, item["target_agent_id"], actor),
                    ).fetchone()
                if pending:
                    job = self.provisioning.snapshot(pending["provisioning_id"])
                else:
                    job = self.provisioning.enqueue(
                        agent_id=item["target_agent_id"], instance_id=iid,
                        environment_id=owner["runtime_id"], selector=selector,
                        selection=selection, configuration=configuration,
                        desired_state="stopped", requested_by=actor,
                    )
                item = self._set(rid, provisioning_id=job["provisioning_id"])
            job = self.provisioning.snapshot(item["provisioning_id"])
            if job.get("status") == "failed":
                return self._abort(item, job.get("last_error") or "destination provisioning failed")
            if job.get("status") != "completed":
                return item
            return self._set(rid, status="importing")
        if state == "importing":
            source = self.transfers.get(item["export_transfer_id"])
            path, _ = self.transfers.controller_artifact(item["export_transfer_id"])
            self._validate_artifact(path, {**item, "game_id": self._ownership(item)["game_id"],
                                           "runtime_id": self._ownership(item)["runtime_id"]})
            imported = item.get("imported_backup_id") or "reloc-" + rid.removeprefix("relocation-")
            transfer = self._existing_transfer(item, "controller_to_agent")
            if transfer is None:
                transfer = self.transfers.create(
                    agent_id=item["target_agent_id"], instance_id=iid,
                    customer_id=self._ownership(item).get("customer_id"),
                    direction="controller_to_agent", purpose="backup_clone",
                    filename=source["filename"], destination_ref=imported,
                    requested_by=actor, ttl_hours=72,
                )
            if transfer["status"] == "staging":
                with path.open("rb") as stream:
                    transfer = self.transfers.stage_from_controller(
                        transfer["transfer_id"], stream, path.stat().st_size,
                    )
            item = self._set(rid, imported_backup_id=imported, import_transfer_id=transfer["transfer_id"])
            if transfer.get("status") in {"failed", "cancelled", "expired"}:
                return self._abort(item, transfer.get("last_error") or "target transfer failed")
            if transfer["status"] != "completed":
                return item
            if (transfer.get("sha256") != item["backup_sha256"] or
                    int(transfer.get("size_bytes") or 0) != path.stat().st_size):
                raise ValueError("destination transfer acknowledgement digest mismatch")
            existing = next((
                job for job in self.backups.list_jobs(instance_id=iid, limit=300)
                if job.get("reason") == actor and job.get("action") == "restore"
                and job.get("backup_id") == imported
            ), None)
            restore = existing or self.backups.request(
                iid, action="restore", backup_id=imported, reason=actor, requested_by=actor,
            )
            return self._set(rid, status="restoring", restore_job_id=restore["command_id"])
        if state == "restoring":
            job = self.backups.get_job(item["restore_job_id"])
            if not job or job.get("status") == "failed":
                return self._abort(item, (job or {}).get("last_error") or "destination restore failed")
            if job.get("status") != "completed":
                return item
            if not item["source_running"]:
                return self._finish(item, "completed")
            return self._set(rid, status="starting")
        if state == "starting":
            if not item.get("start_command_id"):
                command = self._lifecycle(item, "start", item["target_agent_id"])
                item = self._set(rid, start_command_id=command["command_id"])
            command = self.lifecycle.snapshot(item["start_command_id"])
            if command["status"] == "failed":
                return self._abort(item, command.get("last_error") or "destination failed to start")
            if command["status"] != "completed":
                return item
            if self._observed(command) != "running":
                return self._abort(item, "destination start did not confirm running")
            return self._set(rid, status="verifying")
        if state == "verifying":
            with self.session() as session:
                row = session.execute(
                    f"SELECT agent_id,observed_state,health FROM agent_instance_runtime_health "
                    f"WHERE instance_id={self.ph}", (iid,),
                ).fetchone()
            if not row or row["agent_id"] != item["target_agent_id"] or str(row["observed_state"] or "").lower() != "running":
                updated = item.get("updated_at")
                if isinstance(updated, datetime):
                    since = updated
                else:
                    since = datetime.fromisoformat(str(updated or _now()).replace("Z", "+00:00"))
                if since.tzinfo is None:
                    since = since.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - since > timedelta(minutes=5):
                    return self._abort(item, "destination did not report healthy running state")
                return item
            if str(row["health"] or "").lower() == "healthy":
                return self._finish(item, "completed")
            # Do not leave the customer suspended forever if the destination
            # never stabilizes. Roll back only after a confirmed target stop.
            updated = item.get("updated_at")
            if isinstance(updated, datetime):
                since = updated
            else:
                since = datetime.fromisoformat(str(updated or _now()).replace("Z", "+00:00"))
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - since > timedelta(minutes=5):
                return self._abort(item, "destination health did not stabilize")
            return item
        raise ValueError("unsupported migration state")

    def reconcile_for_agent(self, agent_id):
        self.initialize()
        with self.session() as session:
            rows = session.execute(
                f"SELECT relocation_id FROM instance_agent_relocations "
                f"WHERE (source_agent_id={self.ph} OR target_agent_id={self.ph}) "
                "AND status NOT IN ('completed','failed','manual_recovery') "
                "ORDER BY created_at LIMIT 30", (agent_id, agent_id),
            ).fetchall()
        output = []
        for row in rows:
            item = self.get(row["relocation_id"])
            owner = self._ownership(item)["agent_id"]
            if owner != agent_id:
                continue
            output.append(self.reconcile(item["relocation_id"]))
        return output


__all__ = ["ACTIVE", "TERMINAL", "RelocationConflict", "InstanceAgentRelocationRepository"]
