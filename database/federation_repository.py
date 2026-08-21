#!/usr/bin/env python3
"""Backend-neutral persistence for E1 Multi-Datacenter Federation."""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from alert_repository import AlertSession
from federation import (
    FederationController,
    FederationPlacementRequest,
    FederationRoute,
    aggregate_inventory,
    build_event_batch,
    build_handoff,
    issue_federation_secret,
    select_controller,
    snapshot_checksum,
    split_federation_secret,
    utc_now,
    validate_event_batch,
    validate_inventory_snapshot,
    validate_nonce,
    validate_request_freshness,
    verify_federation_secret,
)


class FederationRepository:
    """Federation registry, inventory, routing, handoffs and peer authentication."""

    def __init__(self, backend):
        self.backend = backend

    def initialize(self):
        return self.backend.initialize()

    @property
    def ph(self) -> str:
        return "?" if self.backend.name == "sqlite" else "%s"

    def _row(self, row):
        if row is None:
            return None
        value = dict(row)
        for source, target, default in (
            ("capabilities_json", "capabilities", {}),
            ("metadata_json", "metadata", {}),
            ("payload_json", "payload", {}),
            ("result_json", "result", None),
        ):
            if source in value:
                raw = value.pop(source)
                if raw is None:
                    value[target] = default
                else:
                    try:
                        parsed = json.loads(str(raw))
                        value[target] = parsed
                    except Exception:
                        value[target] = default
        if "enabled" in value:
            value["enabled"] = bool(value["enabled"])
        value.pop("secret_hash", None)
        return value

    def upsert_controller(self, controller: FederationController, *, capabilities: Mapping[str, Any] | None = None):
        controller.validate()
        now = utc_now()
        existing = self.get_controller(controller.controller_id)
        payload = json.dumps(dict(capabilities or {}), sort_keys=True, separators=(",", ":"))
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                if existing is None:
                    session.execute(
                        f"INSERT INTO federation_controllers(controller_id,region_id,datacenter_id,endpoint,role,status,priority,capabilities_json,last_seen_at,created_at,updated_at) VALUES ({','.join([self.ph]*11)})",
                        (controller.controller_id, controller.region_id, controller.datacenter_id, controller.endpoint.rstrip("/"), controller.role, controller.status, int(controller.priority), payload, None, now, now),
                    )
                else:
                    session.execute(
                        f"UPDATE federation_controllers SET region_id={self.ph},datacenter_id={self.ph},endpoint={self.ph},role={self.ph},status={self.ph},priority={self.ph},capabilities_json={self.ph},updated_at={self.ph} WHERE controller_id={self.ph}",
                        (controller.region_id, controller.datacenter_id, controller.endpoint.rstrip("/"), controller.role, controller.status, int(controller.priority), payload, now, controller.controller_id),
                    )
            finally:
                session.close()
        return self.get_controller(controller.controller_id)

    def get_controller(self, controller_id: str):
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(f"SELECT * FROM federation_controllers WHERE controller_id={self.ph}", (str(controller_id),)).fetchone()
            finally:
                session.close()
        return self._row(row)

    def list_controllers(self, *, include_disabled: bool = False):
        sql = "SELECT * FROM federation_controllers"
        params: tuple[Any, ...] = ()
        if not include_disabled:
            sql += f" WHERE status<>{self.ph}"
            params = ("disabled",)
        sql += " ORDER BY priority,controller_id"
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute(sql, params).fetchall()
            finally:
                session.close()
        return [self._row(row) for row in rows]

    def set_controller_status(self, controller_id: str, status: str):
        if status not in {"unknown", "pending", "online", "degraded", "offline", "disabled"}:
            raise ValueError("unsupported federation controller status")
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                session.execute(f"UPDATE federation_controllers SET status={self.ph},updated_at={self.ph} WHERE controller_id={self.ph}", (status, utc_now(), controller_id))
            finally:
                session.close()
        return self.get_controller(controller_id)

    def issue_credential(self, controller_id: str, *, expires_at: str | None = None):
        if self.get_controller(controller_id) is None:
            raise ValueError("unknown federation controller")
        if expires_at:
            try:
                parsed = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if parsed <= datetime.now(timezone.utc):
                    raise ValueError
            except Exception as exc:
                raise ValueError("expires_at must be a future ISO-8601 timestamp") from exc
        prefix, presented, digest = issue_federation_secret(controller_id)
        credential_id = "fedcred-" + uuid.uuid4().hex
        now = utc_now()
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                session.execute(
                    f"INSERT INTO federation_credentials(credential_id,controller_id,token_prefix,secret_hash,status,expires_at,last_used_at,created_at,revoked_at) VALUES ({','.join([self.ph]*9)})",
                    (credential_id, controller_id, prefix, digest, "active", expires_at, None, now, None),
                )
            finally:
                session.close()
        return {"credential_id": credential_id, "controller_id": controller_id, "token_prefix": prefix, "token": presented, "status": "active", "expires_at": expires_at, "created_at": now}

    def list_credentials(self, controller_id: str | None = None):
        sql = "SELECT credential_id,controller_id,token_prefix,status,expires_at,last_used_at,created_at,revoked_at FROM federation_credentials"
        params: tuple[Any, ...] = ()
        if controller_id:
            sql += f" WHERE controller_id={self.ph}"
            params = (controller_id,)
        sql += " ORDER BY created_at DESC"
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute(sql, params).fetchall()
            finally:
                session.close()
        return [dict(row) for row in rows]

    def revoke_credential(self, credential_id: str):
        now = utc_now()
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                session.execute(f"UPDATE federation_credentials SET status='revoked',revoked_at={self.ph} WHERE credential_id={self.ph} AND status='active'", (now, credential_id))
            finally:
                session.close()
        rows = [row for row in self.list_credentials() if row["credential_id"] == credential_id]
        return rows[0] if rows else None

    def authenticate_peer(self, presented_token: str, *, request_timestamp: str, nonce: str):
        prefix, secret = split_federation_secret(presented_token)
        validate_request_freshness(request_timestamp)
        nonce = validate_nonce(nonce)
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT fc.*,fcr.credential_id,fcr.secret_hash,fcr.status AS credential_status,fcr.expires_at FROM federation_credentials fcr JOIN federation_controllers fc ON fc.controller_id=fcr.controller_id WHERE fcr.token_prefix={self.ph}",
                    (prefix,),
                ).fetchone()
            finally:
                session.close()
        if row is None:
            raise PermissionError("invalid federation credential")
        raw = dict(row)
        if raw.get("credential_status") != "active" or raw.get("status") == "disabled" or not verify_federation_secret(secret, raw.get("secret_hash")):
            raise PermissionError("invalid federation credential")
        if raw.get("expires_at"):
            try:
                expires = datetime.fromisoformat(str(raw["expires_at"]).replace("Z", "+00:00"))
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires <= datetime.now(timezone.utc):
                    raise PermissionError("federation credential expired")
            except PermissionError:
                raise
            except Exception as exc:
                raise PermissionError("federation credential expired") from exc
        now = utc_now()
        try:
            with self.backend.transaction() as connection:
                session = AlertSession(self.backend, connection)
                try:
                    session.execute(
                        f"INSERT INTO federation_request_nonces(controller_id,nonce,request_timestamp,received_at) VALUES ({','.join([self.ph]*4)})",
                        (raw["controller_id"], nonce, request_timestamp, now),
                    )
                    session.execute(f"UPDATE federation_credentials SET last_used_at={self.ph} WHERE credential_id={self.ph}", (now, raw["credential_id"]))
                finally:
                    session.close()
        except Exception as exc:
            raise PermissionError("replayed federation request") from exc
        raw.pop("secret_hash", None); raw.pop("credential_status", None)
        raw["principal_type"] = "federation_controller"
        return self._row(raw)

    def store_snapshot(self, authenticated_controller_id: str, snapshot: Mapping[str, Any]):
        payload = validate_inventory_snapshot(snapshot, authenticated_controller_id)
        sequence = int(payload["sequence"])
        controller_id = str(authenticated_controller_id)
        latest = self.latest_snapshot(controller_id)
        if latest is not None:
            previous = int(latest["payload"]["sequence"])
            if sequence < previous:
                raise ValueError("out-of-order federation snapshot")
            if sequence == previous:
                if str(latest["checksum"]) == str(snapshot["checksum"]):
                    return {"snapshot": latest, "created": False}
                raise ValueError("conflicting federation snapshot replay")
        now = utc_now()
        values = (str(snapshot["snapshot_id"]), controller_id, payload["generated_at"], sequence, str(snapshot["checksum"]), json.dumps(payload, sort_keys=True, separators=(",", ":")), now)
        try:
            with self.backend.transaction() as connection:
                session = AlertSession(self.backend, connection)
                try:
                    session.execute(f"INSERT INTO federation_snapshots(snapshot_id,controller_id,generated_at,sequence,checksum,payload_json,received_at) VALUES ({','.join([self.ph]*7)})", values)
                    session.execute(f"UPDATE federation_controllers SET status='online',last_seen_at={self.ph},updated_at={self.ph} WHERE controller_id={self.ph}", (now, now, controller_id))
                finally:
                    session.close()
        except Exception:
            existing = self.snapshot_by_sequence(controller_id, sequence)
            if existing and existing["checksum"] == str(snapshot["checksum"]):
                return {"snapshot": existing, "created": False}
            raise
        return {"snapshot": self.snapshot_by_sequence(controller_id, sequence), "created": True}

    def snapshot_by_sequence(self, controller_id: str, sequence: int):
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(f"SELECT * FROM federation_snapshots WHERE controller_id={self.ph} AND sequence={self.ph}", (controller_id, int(sequence))).fetchone()
            finally:
                session.close()
        return self._row(row)

    def latest_snapshot(self, controller_id: str):
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(f"SELECT * FROM federation_snapshots WHERE controller_id={self.ph} ORDER BY sequence DESC LIMIT 1", (controller_id,)).fetchone()
            finally:
                session.close()
        return self._row(row)

    def latest_snapshots(self):
        result = []
        for controller in self.list_controllers(include_disabled=False):
            item = self.latest_snapshot(controller["controller_id"])
            if item is not None:
                result.append({"snapshot_id": item["snapshot_id"], "checksum": item["checksum"], "payload": item["payload"]})
        return result

    def global_inventory(self):
        snapshots = self.latest_snapshots()
        inventory = aggregate_inventory(snapshots) if snapshots else {"controllers": [], "regions": {}, "datacenters": {}, "agents": {}, "instances": {}, "capacity": {}, "generated_at": utc_now()}
        inventory["registry"] = self.list_controllers(include_disabled=True)
        return inventory

    def upsert_route(self, route: FederationRoute, *, metadata: Mapping[str, Any] | None = None):
        route.validate()
        if self.get_controller(route.controller_id) is None:
            raise ValueError("unknown federation route controller")
        route_id = f"fedroute-{uuid.uuid5(uuid.NAMESPACE_URL, f'{route.scope_type}:{route.scope_id}:{route.controller_id}') }"
        now = utc_now(); payload = json.dumps(dict(metadata or {}), sort_keys=True, separators=(",", ":"))
        existing = [row for row in self.list_routes() if row["scope_type"] == route.scope_type and row["scope_id"] == route.scope_id and row["controller_id"] == route.controller_id]
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                if existing:
                    session.execute(f"UPDATE federation_routes SET priority={self.ph},enabled={self.ph},metadata_json={self.ph},updated_at={self.ph} WHERE route_id={self.ph}", (int(route.priority), 1 if route.enabled else 0, payload, now, existing[0]["route_id"]))
                    route_id = existing[0]["route_id"]
                else:
                    session.execute(f"INSERT INTO federation_routes(route_id,scope_type,scope_id,controller_id,priority,enabled,metadata_json,created_at,updated_at) VALUES ({','.join([self.ph]*9)})", (route_id, route.scope_type, route.scope_id, route.controller_id, int(route.priority), 1 if route.enabled else 0, payload, now, now))
            finally:
                session.close()
        return [row for row in self.list_routes() if row["route_id"] == route_id][0]

    def list_routes(self):
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute("SELECT * FROM federation_routes ORDER BY scope_type,scope_id,priority,controller_id").fetchall()
            finally:
                session.close()
        return [self._row(row) for row in rows]

    def select_for_placement(self, request: FederationPlacementRequest):
        request.validate()
        controllers = [FederationController(controller_id=row["controller_id"], endpoint=row["endpoint"], region_id=row.get("region_id"), datacenter_id=row.get("datacenter_id"), role=row.get("role") or "datacenter", status=row.get("status") or "unknown", priority=int(row.get("priority") or 100)) for row in self.list_controllers()]
        routes = [FederationRoute(scope_type=row["scope_type"], scope_id=row["scope_id"], controller_id=row["controller_id"], priority=int(row.get("priority") or 100), enabled=bool(row.get("enabled"))) for row in self.list_routes()]
        return select_controller(controllers, routes, region_id=request.region_id, datacenter_id=request.datacenter_id, customer_id=request.customer_id, game_id=request.game_id, mode=request.mode, cross_region_fallback=request.cross_region_fallback)

    def create_handoff(self, request: FederationPlacementRequest, *, source_controller_id: str | None = None):
        target = self.select_for_placement(request)
        if target is None:
            raise LookupError("no eligible federation controller")
        existing = self.handoff_by_request(request.request_id)
        if existing is not None:
            return existing
        handoff = build_handoff(request, target); now = utc_now()
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                session.execute(f"INSERT INTO federation_handoffs(handoff_id,request_id,source_controller_id,target_controller_id,instance_id,status,checksum,payload_json,result_json,created_at,updated_at) VALUES ({','.join([self.ph]*11)})", (handoff["handoff_id"], request.request_id, source_controller_id, target.controller_id, request.instance_id, "pending", handoff["checksum"], json.dumps(handoff, sort_keys=True, separators=(",", ":")), None, now, now))
            finally:
                session.close()
        return self.handoff_by_request(request.request_id)

    def handoff_by_request(self, request_id: str):
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(f"SELECT * FROM federation_handoffs WHERE request_id={self.ph}", (request_id,)).fetchone()
            finally:
                session.close()
        return self._row(row)

    def complete_handoff(self, handoff_id: str, *, status: str, result: Mapping[str, Any] | None = None):
        if status not in {"accepted", "rejected", "completed", "failed"}:
            raise ValueError("invalid federation handoff result status")
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                session.execute(f"UPDATE federation_handoffs SET status={self.ph},result_json={self.ph},updated_at={self.ph} WHERE handoff_id={self.ph}", (status, json.dumps(dict(result or {}), sort_keys=True, separators=(",", ":")), utc_now(), handoff_id))
            finally:
                session.close()
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(f"SELECT * FROM federation_handoffs WHERE handoff_id={self.ph}", (handoff_id,)).fetchone()
            finally:
                session.close()
        return self._row(row)

    def list_handoffs(self, *, limit: int = 200):
        bounded = max(1, min(int(limit), 1000))
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute(f"SELECT * FROM federation_handoffs ORDER BY created_at DESC LIMIT {self.ph}", (bounded,)).fetchall()
            finally:
                session.close()
        return [self._row(row) for row in rows]

    def event_cursor(self, controller_id: str) -> int:
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(f"SELECT last_sequence FROM federation_event_cursors WHERE controller_id={self.ph}", (controller_id,)).fetchone()
            finally:
                session.close()
        return int(dict(row).get("last_sequence", -1)) if row is not None else -1

    def ingest_event_batch(self, authenticated_controller_id: str, batch: Mapping[str, Any], event_repository):
        payload = validate_event_batch(batch, authenticated_controller_id)
        sequence = int(payload["sequence"]); current = self.event_cursor(authenticated_controller_id)
        if sequence < current:
            raise ValueError("out-of-order federation event batch")
        accepted = 0; created = 0
        for raw in payload["events"]:
            event_id = str(raw.get("event_id") or "").strip()
            if not event_id:
                raise ValueError("federated event_id is required")
            checksum = snapshot_checksum(dict(raw))
            with self.backend.connect() as connection:
                session = AlertSession(self.backend, connection)
                try:
                    receipt = session.execute(f"SELECT checksum FROM federation_event_receipts WHERE controller_id={self.ph} AND event_id={self.ph}", (authenticated_controller_id, event_id)).fetchone()
                finally:
                    session.close()
            if receipt is not None:
                if str(dict(receipt)["checksum"]) != checksum:
                    raise ValueError("conflicting federated event replay")
                accepted += 1; continue
            result = event_repository.publish(raw)
            with self.backend.transaction() as connection:
                session = AlertSession(self.backend, connection)
                try:
                    session.execute(f"INSERT INTO federation_event_receipts(controller_id,event_id,checksum,received_at) VALUES ({','.join([self.ph]*4)})", (authenticated_controller_id, event_id, checksum, utc_now()))
                finally:
                    session.close()
            accepted += 1
            if result.get("created"):
                created += 1
        if sequence > current:
            now = utc_now()
            with self.backend.transaction() as connection:
                session = AlertSession(self.backend, connection)
                try:
                    existing = session.execute(f"SELECT controller_id FROM federation_event_cursors WHERE controller_id={self.ph}", (authenticated_controller_id,)).fetchone()
                    last_event_id = str(payload["events"][-1].get("event_id")) if payload["events"] else None
                    if existing is None:
                        session.execute(f"INSERT INTO federation_event_cursors(controller_id,last_sequence,last_event_id,updated_at) VALUES ({','.join([self.ph]*4)})", (authenticated_controller_id, sequence, last_event_id, now))
                    else:
                        session.execute(f"UPDATE federation_event_cursors SET last_sequence={self.ph},last_event_id={self.ph},updated_at={self.ph} WHERE controller_id={self.ph}", (sequence, last_event_id, now, authenticated_controller_id))
                finally:
                    session.close()
        return {"controller_id": authenticated_controller_id, "sequence": sequence, "accepted": accepted, "created": created}

    def build_event_batch_from_store(self, controller_id: str, event_repository, *, sequence: int, limit: int = 200):
        events = list(reversed(event_repository.list_events(limit=max(1, min(int(limit), 500)))))
        return build_event_batch(controller_id, int(sequence), events)

    def refresh_health(self, *, degraded_after_seconds: int = 90, offline_after_seconds: int = 300):
        now = datetime.now(timezone.utc); changed = []
        for controller in self.list_controllers(include_disabled=True):
            if controller["status"] in {"disabled", "pending", "unknown"} or not controller.get("last_seen_at"):
                continue
            try:
                seen = datetime.fromisoformat(str(controller["last_seen_at"]).replace("Z", "+00:00")); seen = seen if seen.tzinfo else seen.replace(tzinfo=timezone.utc)
                age = (now - seen.astimezone(timezone.utc)).total_seconds()
            except Exception:
                age = float("inf")
            desired = "offline" if age >= max(degraded_after_seconds, offline_after_seconds) else ("degraded" if age >= degraded_after_seconds else "online")
            if desired != controller["status"]:
                self.set_controller_status(controller["controller_id"], desired); changed.append({"controller_id": controller["controller_id"], "status": desired})
        return changed


__all__ = ["FederationRepository"]
